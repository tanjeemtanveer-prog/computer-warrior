"""Console runtime for Computer Warrior v0.0.2."""

from __future__ import annotations

import argparse
import json
import re
import sys
import threading
import time
import webbrowser
from importlib.metadata import PackageNotFoundError, version as package_version
from pathlib import Path
from typing import Any, Sequence

from .config import (
    APP_NAME,
    APP_VERSION,
    MINIMUM_PYNPUT_VERSION,
    RECOMMENDED_PYNPUT_VERSION,
    SAVE_INTERVAL_SECONDS,
    STATUS_INTERVAL_SECONDS,
    WINDOWS_MUTEX_NAME,
)
from .dashboard import LiveDashboard, format_compact_summary
from .persistence import AtomicJsonStore, default_stats_path
from .online import OnlineSyncManager, default_online_path
from .single_instance import AlreadyRunningError, WindowsSingleInstance
from .tracker import ActivityTracker
from .web import DEFAULT_WEB_PORT, LocalDashboardServer


def _format_line(snapshot: dict[str, object]) -> str:
    return format_compact_summary(snapshot)


def _version_tuple(value: str) -> tuple[int, int, int]:
    """Extract a comparable three-part numeric version without extra packages."""
    parts = [int(part) for part in re.findall(r"\d+", value)[:3]]
    parts.extend([0] * (3 - len(parts)))
    return tuple(parts)  # type: ignore[return-value]


def _load_pynput_listeners() -> tuple[Any, Any, str]:
    try:
        installed_version = package_version("pynput")
    except PackageNotFoundError as exc:
        raise RuntimeError(
            "Missing dependency: pynput. Run install_dependencies.bat."
        ) from exc

    if _version_tuple(installed_version) < MINIMUM_PYNPUT_VERSION:
        minimum = ".".join(str(part) for part in MINIMUM_PYNPUT_VERSION)
        raise RuntimeError(
            f"Incompatible pynput {installed_version}. Computer Warrior requires "
            f"pynput {minimum} or newer for Python 3.13. "
            "Run install_dependencies.bat to replace the old package."
        )

    try:
        from pynput.keyboard import Listener as KeyboardListener
        from pynput.mouse import Listener as MouseListener
    except ImportError as exc:
        raise RuntimeError(
            "pynput could not load its Windows backend. "
            "Run install_dependencies.bat, then try again."
        ) from exc

    return KeyboardListener, MouseListener, installed_version


def _raise_if_listener_stopped(listener: Any, label: str) -> None:
    """Turn a silent listener-thread failure into a visible fatal runtime error."""
    if listener.is_alive():
        return

    try:
        # pynput re-raises callback exceptions from join().
        listener.join(timeout=0)
    except BaseException as exc:
        raise RuntimeError(f"{label} listener failed: {exc}") from exc

    raise RuntimeError(f"{label} listener stopped unexpectedly.")


def _stop_listener(listener: Any, label: str) -> None:
    if listener is None:
        return
    try:
        listener.stop()
    except BaseException as exc:
        print(f"\nWarning: could not stop {label} listener cleanly: {exc}")


def _join_listener(listener: Any, label: str) -> None:
    if listener is None:
        return
    try:
        listener.join(timeout=2)
    except BaseException as exc:
        print(f"\nWarning: {label} listener reported an error during shutdown: {exc}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Anonymous aggregate keyboard/mouse activity XP tracker"
    )
    parser.add_argument(
        "--stats-path",
        type=Path,
        default=default_stats_path(),
        help="Override the JSON stats file path",
    )
    parser.add_argument(
        "--print-json",
        action="store_true",
        help="Print a final JSON snapshot when the program exits",
    )
    parser.add_argument(
        "--web-port",
        type=int,
        default=DEFAULT_WEB_PORT,
        help="Serve the local dashboard on this loopback port (default: 8765)",
    )
    parser.add_argument(
        "--no-web",
        action="store_true",
        help="Run the CLI dashboard only; do not start the local web dashboard",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Start the local web dashboard without opening a browser window",
    )
    return parser


def run(argv: Sequence[str] | None = None) -> int:
    if sys.platform != "win32":
        print(f"{APP_NAME} v{APP_VERSION} runtime supports Windows only.")
        print("The built-in self-tests are cross-platform.")
        return 2

    args = build_parser().parse_args(argv)
    mutex: WindowsSingleInstance | None = None
    keyboard_listener = None
    mouse_listener = None
    tracker: ActivityTracker | None = None
    dashboard: LiveDashboard | None = None
    web_dashboard: LocalDashboardServer | None = None
    online_sync: OnlineSyncManager | None = None

    try:
        mutex = WindowsSingleInstance(WINDOWS_MUTEX_NAME)
    except AlreadyRunningError as exc:
        print(exc)
        return 3

    try:
        try:
            KeyboardListener, MouseListener, installed_version = (
                _load_pynput_listeners()
            )
        except RuntimeError as exc:
            print(exc)
            return 4

        tracker = ActivityTracker(AtomicJsonStore(args.stats_path))
        online_sync = OnlineSyncManager(default_online_path(args.stats_path))
        if tracker.last_load_warning:
            print(f"Warning: {tracker.last_load_warning}")
        if tracker.recovered_from_backup:
            print("Recovered from stats.json.bak; primary will be repaired on save.")

        keyboard_listener = KeyboardListener(
            on_press=tracker.on_key_press,
            on_release=tracker.on_key_release,
        )
        mouse_listener = MouseListener(
            on_move=tracker.on_mouse_move,
            on_click=tracker.on_mouse_click,
            on_scroll=tracker.on_mouse_scroll,
        )
        keyboard_listener.start()
        mouse_listener.start()

        if not args.no_web:
            page_path = Path(__file__).resolve().parent.parent / "web" / "index.html"
            try:
                web_dashboard = LocalDashboardServer(
                    tracker, page_path, args.web_port, online_sync
                )
                web_dashboard.mark_saved()
                web_dashboard.start()
                print(f"Web dashboard: {web_dashboard.url}")
                if not args.no_browser:
                    webbrowser.open(web_dashboard.url)
            except OSError as exc:
                print(f"Warning: web dashboard unavailable on 127.0.0.1:{args.web_port}: {exc}")

        print(f"{APP_NAME} v{APP_VERSION} is running.")
        print("Privacy: only anonymous aggregate XP totals are stored.")
        print("Injected/synthetic keyboard and mouse events are ignored.")
        print(f"Input backend: pynput {installed_version}")
        print(f"Stats: {args.stats_path}\n")

        dashboard = LiveDashboard()

        next_save = time.monotonic() + SAVE_INTERVAL_SECONDS
        next_status = time.monotonic()

        while not tracker.shutdown_requested.wait(0.05):
            _raise_if_listener_stopped(keyboard_listener, "Keyboard")
            _raise_if_listener_stopped(mouse_listener, "Mouse")

            now = time.monotonic()
            if now >= next_status:
                dashboard.render(tracker.snapshot())
                next_status = now + STATUS_INTERVAL_SECONDS
            if now >= next_save:
                tracker.save()
                online_sync.capture(tracker.snapshot())
                threading.Thread(
                    target=online_sync.sync_due,
                    name="ComputerWarriorOnlineSync",
                    daemon=True,
                ).start()
                if web_dashboard is not None:
                    web_dashboard.mark_saved()
                next_save = now + SAVE_INTERVAL_SECONDS

    except KeyboardInterrupt:
        print("\nShutdown requested from console.")
    except Exception as exc:
        print(f"\nFatal error: {exc}")
        print(
            f"Run install_dependencies.bat and confirm pynput "
            f"{RECOMMENDED_PYNPUT_VERSION} is installed."
        )
        return 5
    finally:
        _stop_listener(keyboard_listener, "keyboard")
        _stop_listener(mouse_listener, "mouse")

        if tracker is not None:
            try:
                tracker.save()
                if online_sync is not None:
                    online_sync.capture(tracker.snapshot())
                    online_sync.sync_pending(refresh_leaderboard=False)
                if web_dashboard is not None:
                    web_dashboard.mark_saved()
                final_snapshot = tracker.snapshot()
                if dashboard is not None:
                    dashboard.render(final_snapshot)
                    dashboard.finish()
                print("\nXP saved successfully.")
                print(_format_line(final_snapshot))
                if args.print_json:
                    print(json.dumps(final_snapshot, indent=2))
            except Exception as exc:
                print(f"\nWarning: final save failed: {exc}")

        _join_listener(keyboard_listener, "keyboard")
        _join_listener(mouse_listener, "mouse")
        if web_dashboard is not None:
            web_dashboard.stop()
        if mutex is not None:
            mutex.close()

    return 0
