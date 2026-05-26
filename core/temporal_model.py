from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import math

from core.pattern_types import TemporalContext


@dataclass(frozen=True)
class TemporalDecayConfig:
    half_life_days: float = 30.0
    floor: float = 0.08


class TemporalModel:
    def __init__(self, decay: TemporalDecayConfig | None = None):
        self.decay = decay or TemporalDecayConfig()

    def decay_weight(self, event_time: datetime, reference_time: datetime | None = None) -> float:
        now = reference_time or datetime.now(event_time.tzinfo)
        age_days = max((now - event_time).total_seconds() / 86400.0, 0.0)
        decay = math.exp(-math.log(2) * age_days / max(self.decay.half_life_days, 0.1))
        return max(self.decay.floor, min(1.0, decay))

    def infer_context(self, start: datetime, end: datetime) -> TemporalContext:
        hour = start.hour + (start.minute / 60.0)
        duration_minutes = max((end - start).total_seconds() / 60.0, 0.0)
        return TemporalContext(
            period=self._period_for_hour(hour),
            weekday=start.weekday() < 5,
            weekday_index=start.weekday(),
            workday_probability=self._workday_probability(start.weekday(), hour),
            duration_category=self._duration_category(duration_minutes),
            hour=hour,
        )

    @staticmethod
    def _period_for_hour(hour: float) -> str:
        if hour < 6:
            return "night"
        if hour < 9:
            return "early_morning"
        if hour < 12:
            return "morning"
        if hour < 15:
            return "late_morning" if hour < 13 else "afternoon"
        if hour < 19:
            return "afternoon"
        if hour < 22:
            return "evening"
        return "night"

    @staticmethod
    def _duration_category(duration_minutes: float) -> str:
        if duration_minutes < 15:
            return "short"
        if duration_minutes < 60:
            return "medium"
        if duration_minutes < 180:
            return "long"
        return "extended"

    @staticmethod
    def _workday_probability(weekday_index: int, hour: float) -> float:
        if weekday_index >= 5:
            return 0.2 if 9 <= hour <= 18 else 0.05
        if 8 <= hour <= 18:
            return 0.9
        if 6 <= hour < 8 or 18 < hour <= 21:
            return 0.55
        return 0.2
