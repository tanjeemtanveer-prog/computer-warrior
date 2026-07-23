"""Data model and validation for anonymous aggregate XP totals."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any, Mapping

from .config import METRIC_NAMES


@dataclass
class MetricTotals:
    keyboard: int = 0
    click: int = 0
    cursor: int = 0
    scroll: int = 0

    @property
    def total(self) -> int:
        return self.keyboard + self.click + self.cursor + self.scroll

    def add(self, metric: str, amount: int) -> None:
        if metric not in METRIC_NAMES:
            raise ValueError(f"Unknown metric: {metric}")
        if amount < 0:
            raise ValueError("XP amount cannot be negative")
        setattr(self, metric, getattr(self, metric) + int(amount))

    def to_dict(self) -> dict[str, int]:
        data = asdict(self)
        data["total"] = self.total
        return data

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | None) -> "MetricTotals":
        value = value or {}
        parsed: dict[str, int] = {}
        for name in METRIC_NAMES:
            raw = value.get(name, 0)
            parsed[name] = max(0, int(raw))
        return cls(**parsed)


@dataclass(frozen=True)
class DailyHistoryEntry:
    """One local date and one aggregate XP total; never raw input data."""

    day_local: str
    total_xp: int

    def validate(self) -> None:
        date.fromisoformat(self.day_local)
        if self.total_xp < 0:
            raise ValueError("daily history XP cannot be negative")

    def to_dict(self) -> dict[str, int | str]:
        return {"day_local": self.day_local, "total_xp": self.total_xp}

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "DailyHistoryEntry":
        entry = cls(day_local=str(value["day_local"]), total_xp=max(0, int(value.get("total_xp", 0))))
        entry.validate()
        return entry


@dataclass
class PersistedState:
    day_local: str
    lifetime: MetricTotals
    daily: MetricTotals
    movement_remainder_pixels: float = 0.0
    scroll_remainder_steps: float = 0.0
    daily_goal_xp: int = 500
    daily_history: list[DailyHistoryEntry] = field(default_factory=list)

    def validate(self) -> None:
        if not self.day_local or len(self.day_local) != 10:
            raise ValueError("day_local must be an ISO date")
        if self.movement_remainder_pixels < 0:
            raise ValueError("movement remainder cannot be negative")
        if self.scroll_remainder_steps < 0:
            raise ValueError("scroll remainder cannot be negative")
        if not 50 <= self.daily_goal_xp <= 50_000:
            raise ValueError("daily goal must be between 50 and 50000 XP")
        if len(self.daily_history) > 7:
            raise ValueError("daily history cannot contain more than seven days")
        days = [entry.day_local for entry in self.daily_history]
        if len(days) != len(set(days)) or days != sorted(days):
            raise ValueError("daily history dates must be unique and sorted")
        for entry in self.daily_history:
            entry.validate()
