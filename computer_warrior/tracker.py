"""Anonymous input-activity-to-XP aggregation core."""

from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass
from datetime import date
from typing import Any, Callable

from .config import (
    CLICK_XP_PER_PRESS,
    KEYBOARD_XP_PER_PRESS,
    MAX_SINGLE_CURSOR_JUMP_PIXELS,
    PAUSE_TOGGLE_KEY_NAME,
    PIXELS_PER_CURSOR_XP,
    QUIT_KEY_NAME,
    SCROLL_STEPS_PER_XP,
    DAILY_HISTORY_DAYS,
    FOCUS_QUEST_HISTORY_LIMIT,
    MAX_FOCUS_QUEST_MINUTES,
    MAX_DAILY_GOAL_XP,
    MIN_FOCUS_QUEST_MINUTES,
    MIN_DAILY_GOAL_XP,
)
from .model import DailyHistoryEntry, FocusQuestRecord, MetricTotals, PersistedState
from .persistence import AtomicJsonStore, LoadResult, PersistenceError


class ActivityTracker:
    """Counts only aggregate XP. It never stores key values or cursor coordinates."""

    def __init__(
        self,
        store: AtomicJsonStore,
        day_provider: Callable[[], date] = date.today,
        monotonic_provider: Callable[[], float] = time.monotonic,
    ) -> None:
        self.store = store
        self.day_provider = day_provider
        self.monotonic_provider = monotonic_provider
        self.lock = threading.RLock()
        self.keys_currently_down: set[tuple[str, object]] = set()
        self.last_mouse_position: tuple[float, float] | None = None
        self.session = MetricTotals()
        self.paused = False
        self.shutdown_requested = threading.Event()
        self.last_load_warning: str | None = None
        self.recovered_from_backup = False
        self._focus_quest: _ActiveFocusQuest | None = None

        today = self._today_string()
        try:
            loaded = self.store.load(today)
        except PersistenceError as exc:
            # Preserve unreadable files for manual inspection and start safely at zero.
            self.last_load_warning = str(exc)
            loaded = LoadResult(
                state=PersistedState(
                    day_local=today,
                    lifetime=MetricTotals(),
                    daily=MetricTotals(),
                ),
                source="new",
                warning=str(exc),
            )

        self.state = loaded.state
        self.last_load_warning = loaded.warning or self.last_load_warning
        self.recovered_from_backup = loaded.source == "backup"
        self._roll_day_if_needed_locked()

    def _today_string(self) -> str:
        return self.day_provider().isoformat()

    def _roll_day_if_needed_locked(self) -> None:
        today = self._today_string()
        if self.state.day_local != today:
            self._record_daily_history_locked(self.state.day_local, self.state.daily.total)
            self.state.day_local = today
            self.state.daily = MetricTotals()

    def _record_daily_history_locked(self, day_local: str, total_xp: int) -> None:
        """Keep a short local-only history of daily aggregate totals."""
        entries = [entry for entry in self.state.daily_history if entry.day_local != day_local]
        entries.append(DailyHistoryEntry(day_local=day_local, total_xp=max(0, int(total_xp))))
        entries.sort(key=lambda entry: entry.day_local)
        self.state.daily_history = entries[-DAILY_HISTORY_DAYS:]

    def _focus_summary_locked(self) -> dict[str, object]:
        self._refresh_focus_quest_locked()
        records = self.state.focus_quest_history
        completed_today = sum(
            1 for record in records if record.completed_day_local == self.state.day_local
        )
        if self._focus_quest is None:
            return {
                "active": False,
                "paused": False,
                "duration_minutes": None,
                "remaining_seconds": 0,
                "earned_xp": 0,
                "completed_today": completed_today,
                "completed_total": len(records),
                "history": [record.to_dict() for record in records[-5:]][::-1],
            }
        now = self.monotonic_provider()
        quest = self._focus_quest
        elapsed = quest.elapsed_seconds(now)
        return {
            "active": True,
            "paused": quest.paused_since is not None,
            "duration_minutes": quest.duration_minutes,
            "remaining_seconds": max(0, int(round(quest.duration_seconds - elapsed))),
            "earned_xp": max(0, self.state.lifetime.total - quest.start_lifetime_total),
            "completed_today": completed_today,
            "completed_total": len(records),
            "history": [record.to_dict() for record in records[-5:]][::-1],
        }

    def _refresh_focus_quest_locked(self) -> None:
        quest = self._focus_quest
        if quest is None or quest.paused_since is not None:
            return
        if quest.elapsed_seconds(self.monotonic_provider()) < quest.duration_seconds:
            return
        earned_xp = max(0, self.state.lifetime.total - quest.start_lifetime_total)
        self.state.focus_quest_history.append(
            FocusQuestRecord(
                completed_day_local=self.state.day_local,
                duration_minutes=quest.duration_minutes,
                xp_earned=earned_xp,
            )
        )
        self.state.focus_quest_history = self.state.focus_quest_history[
            -FOCUS_QUEST_HISTORY_LIMIT:
        ]
        self._focus_quest = None

    def start_focus_quest(self, duration_minutes: int) -> dict[str, object]:
        with self.lock:
            self._roll_day_if_needed_locked()
            self._refresh_focus_quest_locked()
            duration = int(duration_minutes)
            if not MIN_FOCUS_QUEST_MINUTES <= duration <= MAX_FOCUS_QUEST_MINUTES:
                raise ValueError(
                    f"Focus quest must be between {MIN_FOCUS_QUEST_MINUTES} and "
                    f"{MAX_FOCUS_QUEST_MINUTES} minutes"
                )
            if self._focus_quest is not None:
                raise ValueError("Finish or abandon the active focus quest first")
            self._focus_quest = _ActiveFocusQuest(
                duration_minutes=duration,
                started_monotonic=self.monotonic_provider(),
                start_lifetime_total=self.state.lifetime.total,
            )
            return self._focus_summary_locked()

    def set_focus_quest_paused(self, paused: bool) -> dict[str, object]:
        with self.lock:
            self._roll_day_if_needed_locked()
            self._refresh_focus_quest_locked()
            quest = self._focus_quest
            if quest is None:
                raise ValueError("There is no active focus quest")
            now = self.monotonic_provider()
            if paused and quest.paused_since is None:
                quest.paused_since = now
            elif not paused and quest.paused_since is not None:
                quest.paused_seconds += max(0.0, now - quest.paused_since)
                quest.paused_since = None
            return self._focus_summary_locked()

    def abandon_focus_quest(self) -> dict[str, object]:
        with self.lock:
            self._roll_day_if_needed_locked()
            self._refresh_focus_quest_locked()
            if self._focus_quest is None:
                raise ValueError("There is no active focus quest")
            self._focus_quest = None
            return self._focus_summary_locked()

    def set_daily_goal(self, goal_xp: int) -> int:
        with self.lock:
            goal = int(goal_xp)
            if not MIN_DAILY_GOAL_XP <= goal <= MAX_DAILY_GOAL_XP:
                raise ValueError(
                    f"Daily goal must be between {MIN_DAILY_GOAL_XP} and {MAX_DAILY_GOAL_XP} XP"
                )
            self.state.daily_goal_xp = goal
            return goal

    @staticmethod
    def key_identifier(key: Any) -> tuple[str, object]:
        virtual_key = getattr(key, "vk", None)
        if virtual_key is not None:
            return ("vk", int(virtual_key))

        value = getattr(key, "value", None)
        nested_virtual_key = getattr(value, "vk", None)
        if nested_virtual_key is not None:
            return ("vk", int(nested_virtual_key))

        name = getattr(key, "name", None)
        if name is not None:
            return ("name", str(name).lower())

        # No key value is retained; this fallback identifies only the object type.
        return ("opaque", repr(type(key)))

    @staticmethod
    def _key_name(key: Any) -> str | None:
        name = getattr(key, "name", None)
        return str(name).lower() if name is not None else None

    def _award_locked(self, metric: str, amount: int) -> None:
        self._roll_day_if_needed_locked()
        self.session.add(metric, amount)
        self.state.daily.add(metric, amount)
        self.state.lifetime.add(metric, amount)

    def toggle_pause(self) -> bool:
        with self.lock:
            self.paused = not self.paused
            self.last_mouse_position = None
            return self.paused

    def set_paused(self, paused: bool) -> None:
        with self.lock:
            self.paused = bool(paused)
            self.last_mouse_position = None

    def request_shutdown(self) -> None:
        self.shutdown_requested.set()

    def on_key_press(self, key: Any, injected: bool = False) -> None:
        """Handle a physical key-down; synthetic/injected events award no XP."""
        if injected:
            return

        identifier = self.key_identifier(key)
        key_name = self._key_name(key)

        with self.lock:
            if identifier in self.keys_currently_down:
                return
            self.keys_currently_down.add(identifier)

            # Control keys are deliberately not awarded XP.
            if key_name == PAUSE_TOGGLE_KEY_NAME:
                self.paused = not self.paused
                self.last_mouse_position = None
                return
            if key_name == QUIT_KEY_NAME:
                self.shutdown_requested.set()
                return
            if self.paused:
                return
            self._award_locked("keyboard", KEYBOARD_XP_PER_PRESS)

    def on_key_release(self, key: Any, injected: bool = False) -> None:
        if injected:
            return
        with self.lock:
            self.keys_currently_down.discard(self.key_identifier(key))

    def on_mouse_click(
        self,
        x: float,
        y: float,
        button: Any,
        pressed: bool,
        injected: bool = False,
    ) -> None:
        del x, y, button
        if injected or not pressed:
            return
        with self.lock:
            if not self.paused:
                self._award_locked("click", CLICK_XP_PER_PRESS)

    def on_mouse_move(
        self,
        x: float,
        y: float,
        injected: bool = False,
    ) -> None:
        if injected:
            return

        current = (float(x), float(y))
        with self.lock:
            if self.paused:
                self.last_mouse_position = None
                return

            if self.last_mouse_position is None:
                self.last_mouse_position = current
                return

            previous = self.last_mouse_position
            self.last_mouse_position = current
            distance = math.hypot(current[0] - previous[0], current[1] - previous[1])
            if not math.isfinite(distance) or distance <= 0:
                return
            if distance > MAX_SINGLE_CURSOR_JUMP_PIXELS:
                return

            self.state.movement_remainder_pixels += distance
            earned = int(self.state.movement_remainder_pixels // PIXELS_PER_CURSOR_XP)
            if earned:
                self.state.movement_remainder_pixels -= earned * PIXELS_PER_CURSOR_XP
                self._award_locked("cursor", earned)

    def on_mouse_scroll(
        self,
        x: float,
        y: float,
        dx: float,
        dy: float,
        injected: bool = False,
    ) -> None:
        del x, y
        if injected:
            return

        steps = abs(float(dx)) + abs(float(dy))
        if not math.isfinite(steps) or steps <= 0:
            return

        with self.lock:
            if self.paused:
                return
            self.state.scroll_remainder_steps += steps
            earned = int(self.state.scroll_remainder_steps // SCROLL_STEPS_PER_XP)
            if earned:
                self.state.scroll_remainder_steps -= earned * SCROLL_STEPS_PER_XP
                self._award_locked("scroll", earned)

    def snapshot(self) -> dict[str, object]:
        with self.lock:
            self._roll_day_if_needed_locked()
            self._refresh_focus_quest_locked()
            return {
                "paused": self.paused,
                "day_local": self.state.day_local,
                "session": self.session.to_dict(),
                "daily": self.state.daily.to_dict(),
                "lifetime": self.state.lifetime.to_dict(),
                "movement_remainder_pixels": round(
                    self.state.movement_remainder_pixels, 4
                ),
                "scroll_remainder_steps": round(
                    self.state.scroll_remainder_steps, 4
                ),
                "daily_goal_xp": self.state.daily_goal_xp,
                "daily_history": [entry.to_dict() for entry in self.state.daily_history],
                "focus": self._focus_summary_locked(),
            }

    def save(self) -> None:
        with self.lock:
            self._roll_day_if_needed_locked()
            self._refresh_focus_quest_locked()
            state_copy = PersistedState(
                day_local=self.state.day_local,
                lifetime=MetricTotals.from_mapping(self.state.lifetime.to_dict()),
                daily=MetricTotals.from_mapping(self.state.daily.to_dict()),
                movement_remainder_pixels=self.state.movement_remainder_pixels,
                scroll_remainder_steps=self.state.scroll_remainder_steps,
                daily_goal_xp=self.state.daily_goal_xp,
                daily_history=list(self.state.daily_history),
                focus_quest_history=list(self.state.focus_quest_history),
            )
        self.store.save(state_copy)


@dataclass
class _ActiveFocusQuest:
    """Runtime-only timer state; no active timer data is written to disk."""

    duration_minutes: int
    started_monotonic: float
    start_lifetime_total: int
    paused_since: float | None = None
    paused_seconds: float = 0.0

    @property
    def duration_seconds(self) -> float:
        return float(self.duration_minutes * 60)

    def elapsed_seconds(self, now: float) -> float:
        paused = 0.0
        if self.paused_since is not None:
            paused = max(0.0, now - self.paused_since)
        return max(0.0, now - self.started_monotonic - self.paused_seconds - paused)
