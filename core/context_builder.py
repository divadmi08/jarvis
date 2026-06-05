# core/context_builder.py

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from core.routine_proposer import CandidatePattern
from core.semantic_memory import ActivityContext, SemanticMemory
from data.database import Database


@dataclass
class EnrichedContext:
    pattern: CandidatePattern
    activity_context: ActivityContext
    past_proposal_outcomes: list[dict[str, Any]]
    memory_events: list[dict[str, Any]]
    reflections: list[dict[str, Any]]

    def to_prompt_section(self) -> str:
        """Serializza il contesto in testo leggibile per il prompt di Gemini."""
        ctx = self.activity_context
        lines = [
            f"Historical context for this workflow pattern:",
            f"- Typical session duration: {ctx.typical_duration_minutes:.0f} minutes",
            f"- Common apps in similar sessions: {', '.join(ctx.common_followup_apps) or 'none'}",
            f"- Based on {len(ctx.similar_sessions)} similar past sessions",
        ]
        if ctx.dominant_intent:
            lines.append(f"- Dominant past session focus: {ctx.dominant_intent}")
        if self.past_proposal_outcomes:
            accepted = sum(
                1 for p in self.past_proposal_outcomes if p.get("status") == "accepted"
            )
            lines.append(
                f"- Past proposals for similar patterns: "
                f"{accepted}/{len(self.past_proposal_outcomes)} accepted"
            )
        if self.memory_events:
            lines.append("- Relevant memories:")
            for event in self.memory_events[:3]:
                lines.append(f"  - {event.get('summary', '')}")
        if self.reflections:
            lines.append("- Recent reflections:")
            for reflection in self.reflections[:2]:
                lines.append(f"  - {reflection.get('insight', '')}")
        return "\n".join(lines)


class ContextBuilder:
    def __init__(self, memory: SemanticMemory, db: Database) -> None:
        self.memory = memory
        self.db = db

    def build_for_pattern(self, pattern: CandidatePattern) -> EnrichedContext:
        temporal_context = pattern.metadata.get("temporal_context", {})
        period = temporal_context.get("period", "morning")

        activity_context = self.memory.get_activity_context(
            apps=list(pattern.apps),
            period=period,
            n=5,
        )

        # recupera proposals passate per pattern simili
        past_proposals = self._fetch_past_proposals(pattern)
        memory_events = self._fetch_relevant_memory_events(pattern)
        reflections = self._fetch_relevant_reflections(pattern)

        return EnrichedContext(
            pattern=pattern,
            activity_context=activity_context,
            past_proposal_outcomes=past_proposals,
            memory_events=memory_events,
            reflections=reflections,
        )

    def _fetch_past_proposals(
        self, pattern: CandidatePattern
    ) -> list[dict[str, Any]]:
        rows = self.db.fetch_routine_proposals()
        outcomes = []
        pattern_apps = set(pattern.apps)
        for row in rows[:10]:  # ultimi 10
            try:
                source = json.loads(row[7])  # source_pattern_json
                source_apps = set(source.get("apps", []))
                if source_apps & pattern_apps:
                    outcomes.append({"status": row[8], "name": row[2]})
            except (json.JSONDecodeError, IndexError):
                continue
        return outcomes

    def _fetch_relevant_memory_events(self, pattern: CandidatePattern) -> list[dict[str, Any]]:
        pattern_apps = set(pattern.apps)
        events = []
        for row in self.db.fetch_memory_events(limit=25):
            try:
                metadata = json.loads(row[4]) if row[4] else {}
            except json.JSONDecodeError:
                metadata = {}
            apps = set(metadata.get("apps", []))
            if apps and not apps & pattern_apps:
                continue
            events.append(
                {
                    "event_type": row[1],
                    "summary": row[3],
                    "importance": row[5],
                    "metadata": metadata,
                }
            )
            if len(events) >= 5:
                break
        return events

    def _fetch_relevant_reflections(self, pattern: CandidatePattern) -> list[dict[str, Any]]:
        pattern_apps = set(pattern.apps)
        reflections = []
        for row in self.db.fetch_reflections(limit=20):
            try:
                evidence = json.loads(row[4]) if row[4] else {}
            except json.JSONDecodeError:
                evidence = {}
            apps = set(evidence.get("apps", []))
            if apps and not apps & pattern_apps:
                continue
            reflections.append(
                {
                    "topic": row[1],
                    "insight": row[2],
                    "confidence": row[3],
                    "evidence": evidence,
                }
            )
            if len(reflections) >= 3:
                break
        return reflections
