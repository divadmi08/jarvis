from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class MemoryEvent:
    event_type: str
    source_id: str | None
    summary: str
    metadata: dict[str, Any] = field(default_factory=dict)
    importance: float = 0.0


@dataclass(frozen=True)
class Reflection:
    topic: str
    insight: str
    confidence: float
    evidence: dict[str, Any] = field(default_factory=dict)
