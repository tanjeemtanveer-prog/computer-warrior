"""Crash-resistant JSON persistence with last-good backup recovery."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import APP_NAME, APP_VERSION, DAILY_HISTORY_DAYS, DEFAULT_DAILY_GOAL_XP, SCHEMA_VERSION
from .model import DailyHistoryEntry, MetricTotals, PersistedState


class PersistenceError(RuntimeError):
    """Raised when neither the primary file nor its backup can be loaded."""


@dataclass(frozen=True)
class LoadResult:
    state: PersistedState
    source: str
    warning: str | None = None


def default_stats_path() -> Path:
    local_app_data = os.getenv("LOCALAPPDATA")
    if local_app_data:
        directory = Path(local_app_data) / "ComputerWarrior"
    else:
        directory = Path.home() / ".computer_warrior"
    directory.mkdir(parents=True, exist_ok=True)
    return directory / "stats.json"


class AtomicJsonStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.backup_path = self.path.with_suffix(self.path.suffix + ".bak")
        self.temp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        self.backup_temp_path = self.backup_path.with_suffix(
            self.backup_path.suffix + ".tmp"
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _parse_payload(payload: dict[str, Any]) -> PersistedState:
        if int(payload.get("schema_version", -1)) != SCHEMA_VERSION:
            raise ValueError("Unsupported stats schema version")

        history_raw = payload.get("daily_history", [])
        if not isinstance(history_raw, list):
            raise ValueError("daily_history must be a list")
        history = [DailyHistoryEntry.from_mapping(value) for value in history_raw]
        history.sort(key=lambda entry: entry.day_local)

        state = PersistedState(
            day_local=str(payload["day_local"]),
            lifetime=MetricTotals.from_mapping(payload.get("lifetime")),
            daily=MetricTotals.from_mapping(payload.get("daily")),
            movement_remainder_pixels=max(
                0.0, float(payload.get("movement_remainder_pixels", 0.0))
            ),
            scroll_remainder_steps=max(
                0.0, float(payload.get("scroll_remainder_steps", 0.0))
            ),
            daily_goal_xp=int(payload.get("daily_goal_xp", DEFAULT_DAILY_GOAL_XP)),
            daily_history=history[-DAILY_HISTORY_DAYS:],
        )
        state.validate()
        return state

    @classmethod
    def _read_file(cls, path: Path) -> PersistedState:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        if not isinstance(payload, dict):
            raise ValueError("Stats JSON root must be an object")
        return cls._parse_payload(payload)

    def load(self, default_day: str) -> LoadResult:
        primary_error: Exception | None = None

        if self.path.exists():
            try:
                return LoadResult(self._read_file(self.path), source="primary")
            except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
                primary_error = exc

        if self.backup_path.exists():
            try:
                warning = None
                if primary_error is not None:
                    warning = (
                        "Primary stats file was unreadable; recovered the last-good "
                        f"backup ({primary_error})."
                    )
                return LoadResult(
                    self._read_file(self.backup_path),
                    source="backup",
                    warning=warning,
                )
            except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as backup_error:
                if primary_error is not None:
                    raise PersistenceError(
                        "Primary and backup stats files are unreadable: "
                        f"primary={primary_error}; backup={backup_error}"
                    ) from backup_error
                raise PersistenceError(
                    f"Backup stats file is unreadable: {backup_error}"
                ) from backup_error

        if primary_error is not None:
            raise PersistenceError(
                f"Stats file is unreadable and no backup exists: {primary_error}"
            ) from primary_error

        return LoadResult(
            PersistedState(
                day_local=default_day,
                lifetime=MetricTotals(),
                daily=MetricTotals(),
            ),
            source="new",
        )

    @staticmethod
    def _payload(state: PersistedState) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "application": APP_NAME,
            "app_version": APP_VERSION,
            "saved_at_utc": datetime.now(timezone.utc).isoformat(),
            "privacy": "aggregate_xp_only_no_key_or_cursor_content",
            "day_local": state.day_local,
            "lifetime": state.lifetime.to_dict(),
            "daily": state.daily.to_dict(),
            "movement_remainder_pixels": round(
                state.movement_remainder_pixels, 6
            ),
            "scroll_remainder_steps": round(state.scroll_remainder_steps, 6),
            "daily_goal_xp": state.daily_goal_xp,
            "daily_history": [entry.to_dict() for entry in state.daily_history],
        }

    @staticmethod
    def _write_json_fsynced(path: Path, payload: dict[str, Any]) -> None:
        with path.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())

    def save(self, state: PersistedState) -> None:
        state.validate()
        payload = self._payload(state)

        try:
            self._write_json_fsynced(self.temp_path, payload)
            # Verify the exact temporary file before replacing anything.
            self._read_file(self.temp_path)

            if self.path.exists():
                # Preserve only a valid primary as the next last-good backup.
                # A corrupt primary must never replace an already-valid backup.
                try:
                    self._read_file(self.path)
                except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
                    pass
                else:
                    with self.path.open("rb") as source, self.backup_temp_path.open("wb") as target:
                        while True:
                            chunk = source.read(1024 * 1024)
                            if not chunk:
                                break
                            target.write(chunk)
                        target.flush()
                        os.fsync(target.fileno())
                    self._read_file(self.backup_temp_path)
                    os.replace(self.backup_temp_path, self.backup_path)

            os.replace(self.temp_path, self.path)
        except Exception:
            for candidate in (self.temp_path, self.backup_temp_path):
                try:
                    candidate.unlink(missing_ok=True)
                except OSError:
                    pass
            raise
