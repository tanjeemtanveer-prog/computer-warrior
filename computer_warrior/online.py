"""Offline-first aggregate XP synchronization owned by the local Python process."""

from __future__ import annotations

import json
import os
import socket
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .config import METRIC_NAMES, ONLINE_SYNC_INTERVAL_SECONDS, SAVE_INTERVAL_SECONDS
from .credentials import CredentialStore, CredentialStoreError, default_credential_store

DEFAULT_WORKER_URL = "http://127.0.0.1:8787"
# Cloudflare's Browser Integrity Check can reject urllib's default
# ``Python-urllib/<version>`` signature before the Worker sees a request.
# This is a stable, browser-compatible signature for the local dashboard's
# HTTPS API transport; it carries no user, device, or activity data.
WORKER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/150.0.0.0 Safari/537.36"
)
HttpRequest = Callable[[str, str, Mapping[str, Any] | None, str | None], Mapping[str, Any]]


class OnlineSyncError(RuntimeError):
    """A recoverable account or network error shown in the local dashboard."""


def default_online_path(stats_path: Path) -> Path:
    return Path(stats_path).with_name("online_sync.json")


def _zero_metrics() -> dict[str, int]:
    return {metric: 0 for metric in METRIC_NAMES}


def _metrics(value: Mapping[str, Any] | None) -> dict[str, int]:
    parsed = _zero_metrics()
    for metric in METRIC_NAMES:
        parsed[metric] = max(0, int((value or {}).get(metric, 0)))
    return parsed


def _default_state() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "worker_url": DEFAULT_WORKER_URL,
        "device_id": None,
        "device_label": None,
        "username": None,
        "credential_target": None,
        "next_sequence": 1,
        "baseline_lifetime": None,
        # This is a mutable local aggregate. It becomes an immutable queue entry
        # only when it is due, manually synced, or the tracker exits.
        "pending": None,
        "queue": [],
        "last_error": None,
        "last_synced_at": None,
        "last_auto_sync_attempt_at": None,
        "last_leaderboard_at": None,
        "account_totals": None,
        "leaderboard": [],
        "leaderboard_period": "lifetime",
        "leaderboard_day_utc": None,
        "leaderboard_me": None,
        "leaderboard_visible": False,
    }


class OnlineSyncManager:
    """Durable sync queue; it never stores input content or exposes a token to HTML."""

    def __init__(
        self,
        path: Path,
        http_request: HttpRequest | None = None,
        now: Callable[[], datetime] | None = None,
        credential_store: CredentialStore | None = None,
    ) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._http_request = http_request or self._request
        self._clock = now or (lambda: datetime.now(timezone.utc))
        self._credential_store = credential_store or default_credential_store()
        self._state_needs_save = False
        self._state = self._load()
        if self._state_needs_save:
            self._save()

    def _timestamp(self) -> str:
        return self._clock().astimezone(timezone.utc).isoformat(timespec="milliseconds")

    def _seconds_since(self, timestamp: object) -> float | None:
        if not isinstance(timestamp, str):
            return None
        try:
            moment = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            return max(0.0, (self._clock().astimezone(timezone.utc) - moment.astimezone(timezone.utc)).total_seconds())
        except ValueError:
            return None

    @staticmethod
    def _credential_target(device_id: object) -> str | None:
        if not isinstance(device_id, str):
            return None
        try:
            return f"ComputerWarrior.Session.{uuid.UUID(device_id)}"
        except ValueError:
            return None

    def _session_token_locked(self) -> str | None:
        target = self._state.get("credential_target")
        if not isinstance(target, str) or not target:
            return None
        try:
            return self._credential_store.read(target)
        except CredentialStoreError as exc:
            raise OnlineSyncError(str(exc)) from exc

    def _migrate_legacy_token(self, state: dict[str, Any]) -> None:
        legacy_token = state.pop("session_token", None)
        if not isinstance(legacy_token, str) or not legacy_token:
            return
        target = state.get("credential_target") or self._credential_target(state.get("device_id"))
        self._state_needs_save = True
        if not target:
            state["username"] = None
            state["last_error"] = "Previous local session was removed; please sign in again."
            return
        try:
            self._credential_store.write(target, legacy_token)
            state["credential_target"] = target
        except CredentialStoreError:
            state["username"] = None
            state["credential_target"] = None
            state["last_error"] = "Session could not be secured in Windows Credential Manager; please sign in again."

    def _load(self) -> dict[str, Any]:
        state = _default_state()
        if not self.path.exists():
            return state
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict) or raw.get("schema_version") != 1:
                raise ValueError("unsupported sync state")
            state.update(raw)
            state["next_sequence"] = max(1, int(state.get("next_sequence", 1)))
            state["queue"] = list(state.get("queue") or [])
            pending = state.get("pending")
            state["pending"] = pending if isinstance(pending, dict) else None
            self._migrate_legacy_token(state)
            return state
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            # Keep a corrupt file for inspection; start a safe unsigned-out state.
            return state

    def _save(self) -> None:
        temporary = self.path.with_suffix(".tmp")
        payload = dict(self._state)
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, self.path)

    @staticmethod
    def _request(method: str, url: str, payload: Mapping[str, Any] | None, token: str | None) -> Mapping[str, Any]:
        body = None if payload is None else json.dumps(payload, separators=(",", ":")).encode("utf-8")
        headers = {"Accept": "application/json", "User-Agent": WORKER_USER_AGENT}
        if body is not None:
            headers["Content-Type"] = "application/json"
        if token:
            headers["Authorization"] = f"Bearer {token}"
        request = Request(url, data=body, headers=headers, method=method)
        try:
            with urlopen(request, timeout=8) as response:
                parsed = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            try:
                message = json.loads(detail).get("error", {}).get("message", detail)
            except json.JSONDecodeError:
                message = detail
            raise OnlineSyncError(f"Worker returned {exc.code}: {message}") from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise OnlineSyncError(f"Worker unavailable: {exc}") from exc
        if not isinstance(parsed, dict):
            raise OnlineSyncError("Worker returned an invalid response")
        return parsed

    def _url(self, path: str) -> str:
        return str(self._state["worker_url"]).rstrip("/") + path

    def _summary_locked(self) -> dict[str, Any]:
        try:
            signed_in = bool(self._session_token_locked())
        except OnlineSyncError as exc:
            signed_in = False
            self._state["last_error"] = str(exc)
        pending = self._state.get("pending")
        pending_xp = sum(_metrics(pending.get("xp") if isinstance(pending, Mapping) else None).values())
        queued_xp = sum(
            sum(_metrics(entry.get("xp") if isinstance(entry, Mapping) else None).values())
            for entry in self._state["queue"]
        )
        return {
            "signed_in": signed_in,
            "username": self._state.get("username"),
            "worker_url": self._state.get("worker_url"),
            "device_id": self._state.get("device_id"),
            "device_label": self._state.get("device_label"),
            "pending_count": len(self._state["queue"]) + (1 if pending_xp else 0),
            "pending_xp": pending_xp + queued_xp,
            "last_error": self._state.get("last_error"),
            "last_synced_at": self._state.get("last_synced_at"),
            "last_leaderboard_at": self._state.get("last_leaderboard_at"),
            "account_totals": self._state.get("account_totals"),
            "leaderboard": self._state.get("leaderboard", []),
            "leaderboard_period": self._state.get("leaderboard_period", "lifetime"),
            "leaderboard_day_utc": self._state.get("leaderboard_day_utc"),
            "leaderboard_me": self._state.get("leaderboard_me"),
            "leaderboard_visible": bool(self._state.get("leaderboard_visible", False)),
        }

    def summary(self) -> dict[str, Any]:
        with self._lock:
            return self._summary_locked()

    def _set_account(self, response: Mapping[str, Any], worker_url: str, snapshot: Mapping[str, Any], label: str | None) -> dict[str, Any]:
        account = response.get("account")
        token = response.get("token")
        if not isinstance(account, Mapping) or not isinstance(account.get("username"), str) or not isinstance(token, str):
            raise OnlineSyncError("Worker registration response is incomplete")
        previous_user = self._state.get("username")
        previous_target = self._state.get("credential_target")
        self._state["worker_url"] = worker_url.rstrip("/")
        self._state["username"] = account["username"]
        self._state["last_error"] = None
        if previous_user != account["username"] or not self._state.get("device_id"):
            self._state["device_id"] = str(uuid.uuid4())
            self._state["device_label"] = label or f"{socket.gethostname()} — Computer Warrior"
            self._state["next_sequence"] = 1
            self._state["queue"] = []
            self._state["pending"] = None
            self._state["baseline_lifetime"] = _metrics(snapshot.get("lifetime"))
        target = self._credential_target(self._state.get("device_id"))
        if not target:
            raise OnlineSyncError("Could not create a secure local session identity")
        try:
            self._credential_store.write(target, token)
            if isinstance(previous_target, str) and previous_target != target:
                self._credential_store.delete(previous_target)
        except CredentialStoreError as exc:
            self._state["username"] = previous_user
            raise OnlineSyncError(str(exc)) from exc
        self._state["credential_target"] = target
        self._register_device_locked()
        self._save()
        return self._summary_locked()

    def register(
        self,
        username: str,
        password: str,
        snapshot: Mapping[str, Any],
        worker_url: str = DEFAULT_WORKER_URL,
        label: str | None = None,
        invite_code: str = "",
    ) -> dict[str, Any]:
        with self._lock:
            payload: dict[str, object] = {"username": username, "password": password}
            if invite_code.strip():
                payload["invite_code"] = invite_code.strip()
            response = self._http_request("POST", worker_url.rstrip("/") + "/api/auth/register", payload, None)
            return self._set_account(response, worker_url, snapshot, label)

    def login(self, username: str, password: str, snapshot: Mapping[str, Any], worker_url: str = DEFAULT_WORKER_URL, label: str | None = None) -> dict[str, Any]:
        with self._lock:
            response = self._http_request("POST", worker_url.rstrip("/") + "/api/auth/login", {"username": username, "password": password}, None)
            return self._set_account(response, worker_url, snapshot, label)

    def _register_device_locked(self) -> None:
        token = self._session_token_locked()
        if not token:
            raise OnlineSyncError("Sign in is required")
        self._http_request("POST", self._url("/api/devices"), {"device_id": self._state["device_id"], "label": self._state["device_label"]}, token)

    def logout(self, snapshot: Mapping[str, Any]) -> dict[str, Any]:
        with self._lock:
            credential_error: str | None = None
            target = self._state.get("credential_target")
            if isinstance(target, str):
                try:
                    self._credential_store.delete(target)
                except CredentialStoreError as exc:
                    credential_error = str(exc)
            self._state["credential_target"] = None
            self._state["username"] = None
            self._state["queue"] = []
            self._state["pending"] = None
            self._state["baseline_lifetime"] = _metrics(snapshot.get("lifetime"))
            self._state["last_error"] = credential_error
            self._save()
            return self._summary_locked()

    def capture(self, snapshot: Mapping[str, Any]) -> None:
        """Merge new aggregate XP locally; no raw events or typed content exist here."""
        with self._lock:
            if not self._session_token_locked():
                return
            lifetime = _metrics(snapshot.get("lifetime"))
            baseline = self._state.get("baseline_lifetime")
            if not isinstance(baseline, Mapping):
                self._state["baseline_lifetime"] = lifetime
                self._save()
                return
            previous = _metrics(baseline)
            delta = {metric: max(0, lifetime[metric] - previous[metric]) for metric in METRIC_NAMES}
            self._state["baseline_lifetime"] = lifetime
            if sum(delta.values()) == 0:
                self._save()
                return
            pending = self._state.get("pending")
            if not isinstance(pending, Mapping):
                self._state["pending"] = {
                    "started_at": self._timestamp(),
                    "xp": delta,
                }
            else:
                combined = _metrics(pending.get("xp"))
                self._state["pending"] = {
                    "started_at": pending.get("started_at") or self._timestamp(),
                    "xp": {metric: combined[metric] + delta[metric] for metric in METRIC_NAMES},
                }
            self._save()

    def _seal_pending_locked(self) -> bool:
        """Freeze the local aggregate before it is ever sent or retried."""
        pending = self._state.get("pending")
        if not isinstance(pending, Mapping):
            return False
        xp = _metrics(pending.get("xp"))
        if sum(xp.values()) == 0:
            self._state["pending"] = None
            return False
        elapsed = self._seconds_since(pending.get("started_at"))
        duration = max(1, int((elapsed or 0) + 0.999))
        self._state["queue"].append({
            "device_id": self._state["device_id"],
            "sequence": self._state["next_sequence"],
            "occurred_at": pending.get("started_at") or self._timestamp(),
            "duration_seconds": min(3600, max(int(SAVE_INTERVAL_SECONDS), duration)),
            "xp": xp,
        })
        self._state["next_sequence"] += 1
        self._state["pending"] = None
        return True

    def _automatic_sync_due_locked(self) -> bool:
        if not self._session_token_locked():
            return False
        last_attempt_age = self._seconds_since(self._state.get("last_auto_sync_attempt_at"))
        if last_attempt_age is not None and last_attempt_age < ONLINE_SYNC_INTERVAL_SECONDS:
            return False
        if self._state["queue"]:
            return True
        pending = self._state.get("pending")
        return isinstance(pending, Mapping) and (self._seconds_since(pending.get("started_at")) or 0) >= ONLINE_SYNC_INTERVAL_SECONDS

    def _sync_queued_locked(self, limit: int, refresh_leaderboard: bool) -> None:
        try:
            synced_any = False
            for _ in range(max(1, limit)):
                if not self._state["queue"]:
                    break
                entry = self._state["queue"][0]
                token = self._session_token_locked()
                if not token:
                    raise OnlineSyncError("Sign in is required")
                response = self._http_request("POST", self._url("/api/sync"), entry, token)
                if not response.get("accepted"):
                    raise OnlineSyncError("Worker did not accept the queued XP entry")
                self._state["queue"].pop(0)
                self._state["account_totals"] = response.get("totals")
                self._state["last_synced_at"] = self._timestamp()
                synced_any = True
            if refresh_leaderboard and (synced_any or not self._state.get("leaderboard")):
                self._refresh_leaderboard_locked()
            self._state["last_error"] = None
        except OnlineSyncError as exc:
            self._state["last_error"] = str(exc)

    def sync_due(self, limit: int = 10) -> dict[str, Any]:
        """Try at most once per five minutes during normal tracker operation."""
        with self._lock:
            if not self._automatic_sync_due_locked():
                return self._summary_locked()
            self._seal_pending_locked()
            self._state["last_auto_sync_attempt_at"] = self._timestamp()
            self._sync_queued_locked(limit, refresh_leaderboard=False)
            self._save()
            return self._summary_locked()

    def sync_pending(self, limit: int = 50, refresh_leaderboard: bool = True) -> dict[str, Any]:
        """Manual/exit flush: seal now, then send immutable entries in order."""
        with self._lock:
            if not self._session_token_locked():
                return self._summary_locked()
            self._seal_pending_locked()
            self._sync_queued_locked(limit, refresh_leaderboard)
            self._save()
            return self._summary_locked()

    def _refresh_leaderboard_locked(self, period: str = "lifetime") -> None:
        if period not in {"lifetime", "daily"}:
            raise OnlineSyncError("Leaderboard period must be lifetime or daily")
        token = self._session_token_locked()
        if not token:
            raise OnlineSyncError("Sign in is required")
        response = self._http_request("GET", self._url(f"/api/leaderboard/me?period={period}"), None, token)
        self._state["leaderboard"] = list(response.get("leaderboard") or [])[:25]
        self._state["leaderboard_period"] = str(response.get("period") or period)
        self._state["leaderboard_day_utc"] = response.get("day_utc")
        self._state["leaderboard_me"] = response.get("me") if isinstance(response.get("me"), Mapping) else None
        me = self._state["leaderboard_me"]
        self._state["leaderboard_visible"] = bool(me.get("visible")) if isinstance(me, Mapping) else False
        self._state["last_leaderboard_at"] = self._timestamp()

    def refresh_leaderboard(self, period: str = "lifetime") -> dict[str, Any]:
        """Fetch the selected global leaderboard only when the user asks for it."""
        with self._lock:
            if not self._session_token_locked():
                return self._summary_locked()
            try:
                self._refresh_leaderboard_locked(period)
                self._state["last_error"] = None
            except OnlineSyncError as exc:
                self._state["last_error"] = str(exc)
            self._save()
            return self._summary_locked()

    def set_leaderboard_visibility(self, public_visible: object) -> dict[str, Any]:
        """Opt in or out without exposing a device identifier to the board."""
        if not isinstance(public_visible, bool):
            raise OnlineSyncError("Leaderboard visibility must be true or false")
        with self._lock:
            token = self._session_token_locked()
            if not token:
                return self._summary_locked()
            try:
                response = self._http_request(
                    "POST",
                    self._url("/api/me/leaderboard-visibility"),
                    {"public_visible": public_visible},
                    token,
                )
                account = response.get("account")
                self._state["leaderboard_visible"] = bool(
                    account.get("leaderboard_visible") if isinstance(account, Mapping) else public_visible
                )
                self._refresh_leaderboard_locked(str(self._state.get("leaderboard_period") or "lifetime"))
                self._state["last_error"] = None
            except OnlineSyncError as exc:
                self._state["last_error"] = str(exc)
            self._save()
            return self._summary_locked()
