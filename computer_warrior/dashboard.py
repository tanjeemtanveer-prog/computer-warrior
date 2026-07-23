"""Live, privacy-safe console dashboard for aggregate Computer Warrior XP."""

from __future__ import annotations

import ctypes
import sys
from typing import Any, TextIO

from .config import APP_NAME, PIXELS_PER_CURSOR_XP, SCROLL_STEPS_PER_XP


METRIC_ROWS = (
    ("Keyboard", "keyboard"),
    ("Mouse clicks", "click"),
    ("Cursor movement", "cursor"),
    ("Scrolling", "scroll"),
)


def _scope(snapshot: dict[str, object], name: str) -> dict[str, Any]:
    value = snapshot.get(name)
    if not isinstance(value, dict):
        raise ValueError(f"Snapshot field {name!r} must be a dictionary")
    return value


def format_compact_summary(snapshot: dict[str, object]) -> str:
    """Return the original one-line summary for shutdown and log output."""
    session = _scope(snapshot, "session")
    daily = _scope(snapshot, "daily")
    lifetime = _scope(snapshot, "lifetime")
    state = "PAUSED" if snapshot.get("paused") else "RUNNING"
    return (
        f"[{state}] Session {int(session['total'])} XP | "
        f"Today {int(daily['total'])} XP | "
        f"Lifetime {int(lifetime['total'])} XP"
    )


def format_dashboard(snapshot: dict[str, object]) -> str:
    """Format category totals before the combined XP totals."""
    session = _scope(snapshot, "session")
    daily = _scope(snapshot, "daily")
    lifetime = _scope(snapshot, "lifetime")
    state = "PAUSED" if snapshot.get("paused") else "RUNNING"

    lines = [
        f"{APP_NAME} Activity Dashboard [{state}]",
        f"{'Activity XP':<18}{'Session':>12}{'Today':>12}{'Lifetime':>12}",
        "-" * 54,
    ]

    for label, key in METRIC_ROWS:
        lines.append(
            f"{label:<18}"
            f"{int(session[key]):>12,}"
            f"{int(daily[key]):>12,}"
            f"{int(lifetime[key]):>12,}"
        )

    lines.extend(
        [
            "-" * 54,
            f"{'TOTAL XP':<18}"
            f"{int(session['total']):>12,}"
            f"{int(daily['total']):>12,}"
            f"{int(lifetime['total']):>12,}",
            "",
            "Next cursor XP: "
            f"{float(snapshot.get('movement_remainder_pixels', 0.0)):,.1f} / "
            f"{PIXELS_PER_CURSOR_XP:,.0f} pixels",
            "Next scroll XP: "
            f"{float(snapshot.get('scroll_remainder_steps', 0.0)):,.1f} / "
            f"{SCROLL_STEPS_PER_XP:,.0f} steps",
            "F9 = pause/resume | F10 = save and exit",
        ]
    )
    return "\n".join(lines)


def _enable_windows_virtual_terminal(stream: TextIO) -> bool:
    """Enable ANSI cursor movement in a real Windows console when available."""
    try:
        if sys.platform != "win32" or not stream.isatty():
            return False

        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.GetStdHandle.argtypes = [wintypes.DWORD]
        kernel32.GetStdHandle.restype = wintypes.HANDLE
        kernel32.GetConsoleMode.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel32.GetConsoleMode.restype = wintypes.BOOL
        kernel32.SetConsoleMode.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel32.SetConsoleMode.restype = wintypes.BOOL

        std_output_handle = wintypes.DWORD(0xFFFFFFF5)  # STD_OUTPUT_HANDLE (-11)
        handle = kernel32.GetStdHandle(std_output_handle)
        mode = wintypes.DWORD()
        if not handle or not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return False

        enable_virtual_terminal_processing = 0x0004
        if mode.value & enable_virtual_terminal_processing:
            return True
        return bool(
            kernel32.SetConsoleMode(
                handle,
                wintypes.DWORD(mode.value | enable_virtual_terminal_processing),
            )
        )
    except (AttributeError, OSError, TypeError, ValueError):
        return False


class LiveDashboard:
    """Refresh a fixed-height dashboard without filling the console history."""

    def __init__(
        self,
        stream: TextIO | None = None,
        *,
        live: bool | None = None,
    ) -> None:
        self.stream = stream or sys.stdout
        self.live = (
            _enable_windows_virtual_terminal(self.stream) if live is None else live
        )
        self._rendered_lines = 0
        self._last_text: str | None = None

    def render(self, snapshot: dict[str, object]) -> None:
        text = format_dashboard(snapshot)
        if text == self._last_text:
            return

        lines = text.splitlines()
        if self.live and self._rendered_lines:
            self.stream.write(f"\x1b[{self._rendered_lines}F")
            for line in lines:
                self.stream.write("\x1b[2K" + line + "\n")
        else:
            if self._rendered_lines:
                self.stream.write("\n")
            self.stream.write(text + "\n")

        self.stream.flush()
        self._rendered_lines = len(lines)
        self._last_text = text

    def finish(self) -> None:
        self.stream.flush()
