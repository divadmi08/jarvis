from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class PatternScore:
    support: float
    confidence: float
    lift: float
    recency_score: float
    consistency_score: float
    duration_score: float
    final_score: float

    def as_metadata(self) -> dict[str, float]:
        return {
            "support": self.support,
            "confidence": self.confidence,
            "lift": self.lift,
            "recency_score": self.recency_score,
            "consistency_score": self.consistency_score,
            "duration_score": self.duration_score,
            "final_score": self.final_score,
        }


@dataclass(frozen=True)
class TemporalContext:
    period: str
    weekday: bool
    weekday_index: int
    workday_probability: float
    duration_category: str
    hour: float

    def as_metadata(self) -> dict[str, Any]:
        return {
            "period": self.period,
            "weekday": self.weekday,
            "weekday_index": self.weekday_index,
            "workday_probability": self.workday_probability,
            "duration_category": self.duration_category,
            "hour": self.hour,
        }


@dataclass(frozen=True)
class IntentPrediction:
    intent: str
    confidence: float
    context: dict[str, Any] = field(default_factory=dict)
    matched_rules: tuple[str, ...] = ()

    def as_metadata(self) -> dict[str, Any]:
        return {
            "intent": self.intent,
            "confidence": self.confidence,
            "context": self.context,
            "matched_rules": list(self.matched_rules),
        }


@dataclass(frozen=True)
class SessionRepresentation:
    session_id: int | None
    start: datetime
    end: datetime
    app_weights: dict[str, float]
    app_durations: dict[str, float]
    ordered_apps: tuple[str, ...]
    temporal_context: TemporalContext
    label: str | None = None

    @property
    def total_duration_seconds(self) -> float:
        return max((self.end - self.start).total_seconds(), 1.0)

    @property
    def dominant_apps(self) -> list[str]:
        return [app for app, weight in self.app_weights.items() if weight >= 0.2]


@dataclass(frozen=True)
class WorkflowPattern:
    pattern_type: str
    apps: tuple[str, ...]
    ordered_steps: tuple[str, ...]
    temporal_context: TemporalContext | None
    semantic_intent: IntentPrediction | None
    score: PatternScore
    frequency: int
    recency: float
    first_seen: datetime
    last_seen: datetime
    metadata: dict[str, Any] = field(default_factory=dict)

    def identity_key(self) -> tuple[str, tuple[str, ...]]:
        return self.pattern_type, self.apps

    def to_legacy_dict(self) -> dict[str, Any]:
        metadata = dict(self.metadata)
        metadata["score"] = self.score.as_metadata()
        metadata["recency"] = self.recency
        metadata["ordered_steps"] = list(self.ordered_steps)
        if self.temporal_context is not None:
            metadata["temporal_context"] = self.temporal_context.as_metadata()
        if self.semantic_intent is not None:
            metadata["intent"] = self.semantic_intent.as_metadata()
        return {
            "type": self.pattern_type,
            "apps": list(self.apps),
            "occurrences": self.frequency,
            "first_seen": self.first_seen.isoformat(),
            "last_seen": self.last_seen.isoformat(),
            "metadata": metadata,
            "score": self.score.final_score,
            "intent": self.semantic_intent.intent if self.semantic_intent else None,
        }


@dataclass(frozen=True)
class PatternEngineConfig:
    lookback_days: int = 90
    max_combo_size: int = 4
    sequence_window_seconds: int = 900
    min_meaningful_duration_seconds: int = 15
    decay_half_life_days: float = 30.0
    decay_floor: float = 0.08
    compression_overlap_threshold: float = 0.9
    sequence_similarity_threshold: float = 0.72
    min_app_weight: float = 0.12
    dominant_app_limit: int = 5
    max_patterns_per_type: int = 25
