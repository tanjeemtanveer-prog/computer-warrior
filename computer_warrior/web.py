"""Loopback-only dashboard server for anonymous Computer Warrior totals."""

from __future__ import annotations

import json
import threading
from datetime import date, datetime, timedelta, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from .config import PIXELS_PER_CURSOR_XP, SCROLL_STEPS_PER_XP
from .tracker import ActivityTracker
from .online import OnlineSyncError, OnlineSyncManager


DEFAULT_WEB_HOST = "127.0.0.1"
DEFAULT_WEB_PORT = 8765


def make_dashboard_payload(snapshot: dict[str, object], saved_at: str | None) -> dict[str, object]:
    """Return only the aggregate values the dashboard is allowed to show."""
    lifetime = dict(snapshot["lifetime"])
    total = int(lifetime["total"])
    level = total // 1000 + 1
    level_start = (level - 1) * 1000
    level_progress = total - level_start
    day_local = str(snapshot["day_local"])
    daily = dict(snapshot["daily"])
    daily_total = int(daily.get("total", 0))
    goal_xp = int(snapshot.get("daily_goal_xp", 500))
    history = [entry for entry in snapshot.get("daily_history", []) if isinstance(entry, dict)]
    history_by_day = {str(entry.get("day_local")): max(0, int(entry.get("total_xp", 0))) for entry in history}
    history_by_day[day_local] = daily_total
    today = date.fromisoformat(day_local)
    week = []
    for offset in range(6, -1, -1):
        item_day = today - timedelta(days=offset)
        iso_day = item_day.isoformat()
        week.append(
            {
                "day_local": iso_day,
                "total_xp": history_by_day.get(iso_day, 0),
                # Distinguish an absent local history record from a day that
                # has a recorded aggregate total. The browser uses this only
                # to avoid drawing invented activity bars.
                "has_data": iso_day in history_by_day,
            }
        )
    streak = 0
    streak_day = today if daily_total >= goal_xp else today - timedelta(days=1)
    while history_by_day.get(streak_day.isoformat(), 0) >= goal_xp:
        streak += 1
        streak_day -= timedelta(days=1)
    achievements = []
    if total >= 100:
        achievements.append("FIRST SPARK")
    if daily_total >= goal_xp:
        achievements.append("GOAL CLEARED")
    if streak >= 3:
        achievements.append("MOMENTUM")
    if total >= 10_000:
        achievements.append("FIVE FIGURES")
    focus = dict(snapshot.get("focus", {}))
    focus["history"] = [
        dict(entry) for entry in focus.get("history", []) if isinstance(entry, dict)
    ]
    if int(focus.get("completed_today", 0)):
        achievements.append("FOCUS COMPLETE")

    return {
        "paused": bool(snapshot["paused"]),
        "day_local": day_local,
        "session": dict(snapshot["session"]),
        "daily": daily,
        "lifetime": lifetime,
        "progress": {
            "cursor_pixels": float(snapshot["movement_remainder_pixels"]),
            "cursor_target": PIXELS_PER_CURSOR_XP,
            "scroll_steps": float(snapshot["scroll_remainder_steps"]),
            "scroll_target": SCROLL_STEPS_PER_XP,
        },
        "level": {
            "number": level,
            "progress_xp": level_progress,
            "target_xp": 1000,
            "remaining_xp": 1000 - level_progress,
        },
        "momentum": {
            "goal_xp": goal_xp,
            "progress_xp": daily_total,
            "remaining_xp": max(0, goal_xp - daily_total),
            "complete": daily_total >= goal_xp,
            "streak_days": streak,
            "history": week,
            "achievements": achievements,
        },
        "focus": focus,
        "last_saved_at": saved_at,
    }


class LocalDashboardServer:
    """Serves the static dashboard and JSON endpoint on localhost only."""

    def __init__(
        self,
        tracker: ActivityTracker,
        page_path: Path,
        port: int,
        online_sync: OnlineSyncManager,
    ) -> None:
        self._tracker = tracker
        self._page_path = page_path
        self._saved_at: str | None = None
        self._saved_at_lock = threading.Lock()
        self._online_sync = online_sync
        self._server = ThreadingHTTPServer((DEFAULT_WEB_HOST, port), self._handler())
        self._server.daemon_threads = True
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="ComputerWarriorLocalDashboard",
            daemon=True,
        )

    @property
    def url(self) -> str:
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}/"

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=2)

    def mark_saved(self) -> None:
        value = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self._saved_at_lock:
            self._saved_at = value

    def _payload(self) -> dict[str, object]:
        with self._saved_at_lock:
            saved_at = self._saved_at
        return make_dashboard_payload(self._tracker.snapshot(), saved_at)

    def _online_payload(self) -> dict[str, object]:
        return self._online_sync.summary()

    def _handler(self) -> type[BaseHTTPRequestHandler]:
        owner = self

        class DashboardHandler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: object) -> None:
                # A dashboard refresh every half second should not flood the CLI.
                return

            def _json(self, status: HTTPStatus, payload: dict[str, object]) -> None:
                body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)

            def _body(self) -> dict[str, object]:
                length = int(self.headers.get("Content-Length", "0"))
                if length <= 0 or length > 16_384:
                    raise ValueError("A small JSON request body is required")
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                if not isinstance(payload, dict):
                    raise ValueError("JSON object required")
                return payload

            def _online_action(self, action: str) -> None:
                try:
                    payload = self._body()
                    snapshot = owner._tracker.snapshot()
                    username = str(payload.get("username", ""))
                    password = str(payload.get("password", ""))
                    invite_code = str(payload.get("invite_code", ""))
                    worker_url = str(payload.get("worker_url", "http://127.0.0.1:8787"))
                    label = str(payload.get("device_label", "")) or None
                    if action == "register":
                        result = owner._online_sync.register(username, password, snapshot, worker_url, label, invite_code)
                    elif action == "login":
                        result = owner._online_sync.login(username, password, snapshot, worker_url, label)
                    elif action == "sync":
                        owner._online_sync.capture(snapshot)
                        result = owner._online_sync.sync_pending()
                    elif action == "refresh":
                        result = owner._online_sync.refresh_leaderboard()
                    elif action == "leaderboard":
                        result = owner._online_sync.refresh_leaderboard(str(payload.get("period", "lifetime")))
                    elif action == "visibility":
                        result = owner._online_sync.set_leaderboard_visibility(payload.get("public_visible"))
                    elif action == "logout":
                        result = owner._online_sync.logout(snapshot)
                    else:
                        self.send_error(HTTPStatus.NOT_FOUND)
                        return
                    self._json(HTTPStatus.OK, result)
                except (ValueError, OnlineSyncError) as exc:
                    self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})

            def do_GET(self) -> None:  # noqa: N802 - stdlib handler name
                if self.path == "/api/stats":
                    self._json(HTTPStatus.OK, owner._payload())
                    return
                if self.path == "/api/health":
                    self._json(HTTPStatus.OK, {"ok": True})
                    return
                if self.path == "/api/online":
                    self._json(HTTPStatus.OK, owner._online_payload())
                    return
                if self.path in ("/", "/index.html"):
                    try:
                        body = owner._page_path.read_bytes()
                    except OSError:
                        self.send_error(HTTPStatus.NOT_FOUND, "Dashboard page is unavailable")
                        return
                    self.send_response(HTTPStatus.OK)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.send_header("Cache-Control", "no-store")
                    self.end_headers()
                    self.wfile.write(body)
                    return
                self.send_error(HTTPStatus.NOT_FOUND)

            def do_POST(self) -> None:  # noqa: N802 - stdlib handler name
                if self.path == "/api/control/pause":
                    owner._tracker.set_paused(True)
                elif self.path == "/api/control/resume":
                    owner._tracker.set_paused(False)
                elif self.path == "/api/control/exit":
                    owner._tracker.request_shutdown()
                elif self.path == "/api/goal":
                    try:
                        payload = self._body()
                        owner._tracker.set_daily_goal(int(payload.get("daily_goal_xp", 0)))
                        owner._tracker.save()
                        owner.mark_saved()
                    except ValueError as exc:
                        self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                        return
                elif self.path == "/api/focus/start":
                    try:
                        payload = self._body()
                        owner._tracker.start_focus_quest(int(payload.get("duration_minutes", 0)))
                    except ValueError as exc:
                        self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                        return
                elif self.path == "/api/focus/pause":
                    try:
                        owner._tracker.set_focus_quest_paused(True)
                    except ValueError as exc:
                        self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                        return
                elif self.path == "/api/focus/resume":
                    try:
                        owner._tracker.set_focus_quest_paused(False)
                    except ValueError as exc:
                        self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                        return
                elif self.path == "/api/focus/abandon":
                    try:
                        owner._tracker.abandon_focus_quest()
                    except ValueError as exc:
                        self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                        return
                elif self.path == "/api/online/register":
                    self._online_action("register")
                    return
                elif self.path == "/api/online/login":
                    self._online_action("login")
                    return
                elif self.path == "/api/online/sync":
                    self._online_action("sync")
                    return
                elif self.path == "/api/online/refresh":
                    self._online_action("refresh")
                    return
                elif self.path == "/api/online/leaderboard":
                    self._online_action("leaderboard")
                    return
                elif self.path == "/api/online/visibility":
                    self._online_action("visibility")
                    return
                elif self.path == "/api/online/logout":
                    self._online_action("logout")
                    return
                else:
                    self.send_error(HTTPStatus.NOT_FOUND)
                    return
                self._json(HTTPStatus.OK, owner._payload())

        return DashboardHandler
