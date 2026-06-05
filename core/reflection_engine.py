from __future__ import annotations

import json
from collections import Counter

from core.memory_types import Reflection
from core.pattern_types import SessionRepresentation, WorkflowPattern
from data.database import Database


class ReflectionEngine:
    def __init__(self, db: Database) -> None:
        self.db = db

    def reflect(
        self,
        sessions: list[SessionRepresentation],
        patterns: list[WorkflowPattern],
    ) -> list[Reflection]:
        reflections = []
        focus_reflection = self._reflect_dominant_focus(sessions)
        if focus_reflection:
            reflections.append(focus_reflection)
        workflow_reflection = self._reflect_strong_workflow(patterns)
        if workflow_reflection:
            reflections.append(workflow_reflection)

        for reflection in reflections:
            self.db.save_reflection(
                topic=reflection.topic,
                insight=reflection.insight,
                confidence=reflection.confidence,
                evidence_json=json.dumps(reflection.evidence, ensure_ascii=True),
            )
        return reflections

    def _reflect_dominant_focus(self, sessions: list[SessionRepresentation]) -> Reflection | None:
        labels = [session.label for session in sessions if session.label]
        if not labels:
            return None
        label, count = Counter(labels).most_common(1)[0]
        confidence = min(0.95, count / max(len(sessions), 1))
        return Reflection(
            topic="dominant_session_focus",
            insight=f"Recent sessions most often look like {label} work.",
            confidence=confidence,
            evidence={"label": label, "count": count, "total_sessions": len(sessions)},
        )

    def _reflect_strong_workflow(self, patterns: list[WorkflowPattern]) -> Reflection | None:
        if not patterns:
            return None
        strongest = max(patterns, key=lambda pattern: pattern.score.final_score)
        if strongest.score.final_score < 0.5:
            return None
        apps = ", ".join(strongest.apps)
        intent = strongest.semantic_intent.intent if strongest.semantic_intent else strongest.pattern_type
        return Reflection(
            topic="strong_workflow_pattern",
            insight=f"The strongest learned workflow is {intent} around {apps}.",
            confidence=min(0.95, strongest.score.final_score),
            evidence={
                "apps": list(strongest.apps),
                "pattern_type": strongest.pattern_type,
                "frequency": strongest.frequency,
                "score": strongest.score.final_score,
            },
        )
