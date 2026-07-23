"""Data model and validation for anonymous aggregate XP totals."""

from __future__ import annotations

from dataclasses import asdict, dataclass
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


@dataclass
class PersistedState:
    day_local: str
    lifetime: MetricTotals
    daily: MetricTotals
    movement_remainder_pixels: float = 0.0
    scroll_remainder_steps: float = 0.0

    def validate(self) -> None:
        if not self.day_local or len(self.day_local) != 10:
            raise ValueError("day_local must be an ISO date")
        if self.movement_remainder_pixels < 0:
            raise ValueError("movement remainder cannot be negative")
        if self.scroll_remainder_steps < 0:
            raise ValueError("scroll remainder cannot be negative")
