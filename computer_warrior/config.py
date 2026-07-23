"""Configuration constants for Computer Warrior v0.0.6."""

from __future__ import annotations

APP_NAME = "Computer Warrior"
APP_VERSION = "0.0.6"
SCHEMA_VERSION = 1

KEYBOARD_XP_PER_PRESS = 1
CLICK_XP_PER_PRESS = 1
PIXELS_PER_CURSOR_XP = 1000.0
SCROLL_STEPS_PER_XP = 10.0
MAX_SINGLE_CURSOR_JUMP_PIXELS = 5000.0
SAVE_INTERVAL_SECONDS = 10.0
STATUS_INTERVAL_SECONDS = 1.0

# Local XP is captured frequently, but an online account receives one aggregate
# batch at most every five minutes. Manual Sync and a clean app exit flush it
# immediately. This keeps normal Cloudflare/D1 use practical on free tiers.
ONLINE_SYNC_INTERVAL_SECONDS = 300

# pynput 1.7.8 renamed an internal listener method that collided with
# threading.Thread._handle on Python 3.13. Version 1.8.2 also fixes duplicate
# Windows scroll events and exposes the injected-event flag consistently.
MINIMUM_PYNPUT_VERSION = (1, 8, 2)
RECOMMENDED_PYNPUT_VERSION = "1.8.2"

# F9 toggles pause/resume. F10 requests a clean shutdown.
PAUSE_TOGGLE_KEY_NAME = "f9"
QUIT_KEY_NAME = "f10"

# Deliberately retained from v0.0.1 so old and new versions cannot run together.
WINDOWS_MUTEX_NAME = r"Local\ComputerWarriorFunctionalCore_v0_0_1"
ERROR_ALREADY_EXISTS = 183

METRIC_NAMES = ("keyboard", "click", "cursor", "scroll")
