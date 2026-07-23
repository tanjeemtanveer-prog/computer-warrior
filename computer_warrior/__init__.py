"""Computer Warrior v0.0.2 functional core with live detailed statistics."""

from .config import APP_NAME, APP_VERSION
from .tracker import ActivityTracker

__all__ = ["APP_NAME", "APP_VERSION", "ActivityTracker"]
