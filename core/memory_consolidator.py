from __future__ import annotations

import json
import logging

from core.memory_types import MemoryEvent
from core.pattern_types import SessionRepresentation, WorkflowPattern
from core.reflection_engine import ReflectionEngine
from data.database import Database


log = logging.getLogger("memory_consolidator")


class MemoryConsolidator:
    def __init__(self, db: Database, semantic_memory=None) -> None:
        self.db = db
        self.semantic_memory = semantic_memory
        self.reflection_engine = ReflectionEngine(db)

    def consolidate(
        self,
        sessions: list[SessionRepresentation],
        patterns: list[WorkflowPattern],
    ) -> None:
        for session in sessions:
            self.remember_session(session)
        for pattern in patterns:
            self.remember_pattern(pattern)
        self.reflection_engine.reflect(sessions, patterns)

    def remember_session(self, session: SessionRepresentation) -> int:
        apps = ", ".join(session.ordered_apps[:5])
        summary = f"{session.label or 'activity'} session using {apps}"
        event = MemoryEvent(
            event_type="session",
            source_id=str(session.session_id) if session.session_id is not None else None,
            summary=summary,
            metadata={
                "apps": list(session.ordered_apps),
                "label": session.label,
                "period": session.temporal_context.period,
                "duration_seconds": session.total_duration_seconds,
            },
            importance=min(1.0, session.total_duration_seconds / 7200.0),
        )
        event_id = self._save_event(event)
        if self.semantic_memory is not None:
            try:
                self.semantic_memory.store_session(session)
            except Exception as exc:
                log.warning("Could not store session in semantic memory: %s", exc)
        return event_id

    def remember_pattern(self, pattern: WorkflowPattern) -> int:
        apps = ", ".join(pattern.apps)
        intent = pattern.semantic_intent.intent if pattern.semantic_intent else pattern.pattern_type
        summary = f"{intent} workflow pattern involving {apps}"
        event = MemoryEvent(
            event_type="pattern",
            source_id=f"{pattern.pattern_type}:{'|'.join(pattern.apps)}",
            summary=summary,
            metadata={
                "apps": list(pattern.apps),
                "pattern_type": pattern.pattern_type,
                "frequency": pattern.frequency,
                "score": pattern.score.final_score,
                "intent": intent,
            },
            importance=min(1.0, pattern.score.final_score),
        )
        event_id = self._save_event(event)
        if self.semantic_memory is not None:
            try:
                self.semantic_memory.store_pattern(pattern)
            except Exception as exc:
                log.warning("Could not store pattern in semantic memory: %s", exc)
        return event_id

    def _save_event(self, event: MemoryEvent) -> int:
        return self.db.save_memory_event(
            event_type=event.event_type,
            source_id=event.source_id,
            summary=event.summary,
            metadata_json=json.dumps(event.metadata, ensure_ascii=True),
            importance=event.importance,
        )
