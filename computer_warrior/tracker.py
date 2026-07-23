"""Anonymous input-activity-to-XP aggregation core."""

from __future__ import annotations

import math
import threading
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
    MAX_DAILY_GOAL_XP,
    MIN_DAILY_GOAL_XP,
)
from .model import DailyHistoryEntry, MetricTotals, PersistedState
from .persistence import AtomicJsonStore, LoadResult, PersistenceError


class ActivityTracker:
    """Counts only aggregate XP. It never stores key values or cursor coordinates."""

    def __init__(
        self,
        store: AtomicJsonStore,
        day_provider: Callable[[], date] = date.today,
    ) -> None:
        self.store = store
        self.day_provider = day_provider
        self.lock = threading.RLock()
        self.keys_currently_down: set[tuple[str, object]] = set()
        self.last_mouse_position: tuple[float, float] | None = None
        self.session = MetricTotals()
        self.paused = False
        self.shutdown_requested = threading.Event()
        self.last_load_warning: str | None = None
        self.recovered_from_backup = False

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
            }

    def save(self) -> None:
        with self.lock:
            self._roll_day_if_needed_locked()
            state_copy = PersistedState(
                day_local=self.state.day_local,
                lifetime=MetricTotals.from_mapping(self.state.lifetime.to_dict()),
                daily=MetricTotals.from_mapping(self.state.daily.to_dict()),
                movement_remainder_pixels=self.state.movement_remainder_pixels,
                scroll_remainder_steps=self.state.scroll_remainder_steps,
                daily_goal_xp=self.state.daily_goal_xp,
                daily_history=list(self.state.daily_history),
            )
        self.store.save(state_copy)
