from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from core.ai_client import AIClient
from core.app_registry import app_target_for, normalize_app_name
from core.routine_proposal_types import (
    PatternSourceRef,
    ProposedRoutineStep,
    RoutineProposal,
    RoutineProposalDecision,
    RoutineProposalValidationError,
)
from data.database import Database


log = logging.getLogger("routine_proposer")


@dataclass(frozen=True)
class CandidatePattern:
    pattern_id: int
    pattern_type: str
    apps: tuple[str, ...]
    occurrences: int
    first_seen: str | None
    last_seen: str | None
    metadata: dict[str, Any]
    proposed: bool
    accepted: bool
    score: float
    semantic_intent: str | None
    pattern_version: int

    @property
    def source_ref(self) -> PatternSourceRef:
        return PatternSourceRef(type=self.pattern_type, apps=self.apps)


@dataclass(frozen=True)
class ProposalAttemptResult:
    pattern_id: int
    status: str
    proposal_id: int | None = None
    proposal: RoutineProposalDecision | None = None
    reason: str | None = None


class RoutineProposer:
    def __init__(self, db: Database, ai_client: AIClient) -> None:
        self.db = db
        self.ai_client = ai_client

    def find_candidate_patterns(self, limit: int = 10) -> list[CandidatePattern]:
        rows = self.db.fetch_candidate_patterns(limit=limit)
        candidates = [self._row_to_candidate(row) for row in rows]
        filtered = [candidate for candidate in candidates if self._is_proposable(candidate)]
        log.info("Routine proposer found %s candidate patterns", len(filtered))
        return filtered

    def generate_proposal_for_pattern(self, pattern: CandidatePattern) -> RoutineProposalDecision:
        unsupported_apps = self._unsupported_apps(pattern.apps)
        if unsupported_apps:
            apps_text = ", ".join(unsupported_apps)
            return RoutineProposalDecision(
                should_propose=False,
                reason=f"Pattern contains unmanaged app targets: {apps_text}",
            )
        prompt = self.build_prompt(pattern)
        raw_response = self.ai_client.generate_json(prompt)
        return self.parse_ai_response(raw_response, pattern)

    def build_prompt(self, pattern: CandidatePattern) -> str:
        payload = {
            "pattern_id": pattern.pattern_id,
            "pattern_type": pattern.pattern_type,
            "apps": list(pattern.apps),
            "occurrences": pattern.occurrences,
            "score": round(pattern.score, 4),
            "semantic_intent": pattern.semantic_intent,
            "first_seen": pattern.first_seen,
            "last_seen": pattern.last_seen,
            "metadata": self._compact_metadata(pattern.metadata),
            "allowed_actions": [
                "open_app",
                "focus_window",
                "wait_for_window",
                "notify_user",
                "sleep",
            ],
            "app_targets": {
                app: app_target_for(app)
                for app in pattern.apps
                if app_target_for(app) is not None
            },
        }
        return (
            "You are a desktop automation routine designer for a local-first Windows agent.\n"
            "Your task is to convert one strong behavioral pattern into a safe routine proposal.\n"
            "Policy:\n"
            "- Return JSON only. No markdown, no prose outside JSON.\n"
            "- If the pattern is weak, ambiguous, incomplete, or unsafe, return "
            '{"should_propose": false, "reason": "..."}.\n'
            "- Never invent shell commands, scripts, file paths, URLs, or destructive actions.\n"
            "- Allowed actions only: open_app, focus_window, wait_for_window, notify_user, sleep.\n"
            "- Do not use run_command, type_text, click, or any other action.\n"
            "- Use app names from the provided pattern only. Do not add unrelated apps.\n"
            "- Keep the reasoning short and concrete.\n"
            "- Confidence must be a float between 0 and 1.\n"
            "Expected JSON shape when proposing:\n"
            '{'
            '"should_propose": true,'
            '"source_pattern": {"type": "...", "apps": ["..."]},'
            '"proposal": {'
            '"name": "...",'
            '"description": "...",'
            '"steps": [{"action": "open_app", "target": "discord"}],'
            '"confidence": 0.0,'
            '"reasoning": "..."'
            "}"
            "}\n"
            f"Pattern input:\n{json.dumps(payload, ensure_ascii=True, indent=2)}"
        )

    def parse_ai_response(self, raw_response: str, pattern: CandidatePattern) -> RoutineProposalDecision:
        payload = self._load_json_object(raw_response)
        should_propose = payload.get("should_propose")
        if should_propose is False:
            reason = str(payload.get("reason", "")).strip() or "model declined to propose"
            return RoutineProposalDecision(should_propose=False, reason=reason)
        if should_propose is not True:
            raise RoutineProposalValidationError("Missing boolean should_propose field")

        source_pattern_payload = payload.get("source_pattern")
        proposal_payload = payload.get("proposal")
        if not isinstance(source_pattern_payload, dict):
            raise RoutineProposalValidationError("source_pattern object is required")
        if not isinstance(proposal_payload, dict):
            raise RoutineProposalValidationError("proposal object is required")

        source_pattern = PatternSourceRef.from_dict(source_pattern_payload)
        if source_pattern.type != pattern.pattern_type or source_pattern.apps != pattern.apps:
            raise RoutineProposalValidationError("source_pattern does not match the candidate pattern")

        proposal = RoutineProposal.from_dict(proposal_payload)
        normalized_steps = tuple(self._normalize_step(step) for step in proposal.steps)
        normalized_proposal = RoutineProposal(
            name=proposal.name,
            description=proposal.description,
            steps=normalized_steps,
            confidence=proposal.confidence,
            reasoning=proposal.reasoning,
        )
        return RoutineProposalDecision(
            should_propose=True,
            source_pattern=source_pattern,
            proposal=normalized_proposal,
        )

    def _normalize_step(self, step: ProposedRoutineStep) -> ProposedRoutineStep:
        if step.action in {"open_app", "focus_window", "wait_for_window"}:
            normalized_app = normalize_app_name(step.target)
            if normalized_app is None:
                raise RoutineProposalValidationError(
                    f"Unknown or unmanaged app target for action {step.action}: {step.target}"
                )
            controlled_target = app_target_for(normalized_app)
            if controlled_target is None:
                raise RoutineProposalValidationError(f"Missing controlled target for app {normalized_app}")
            return ProposedRoutineStep(action=step.action, target=controlled_target)

        if step.action == "sleep":
            try:
                seconds = float(step.target)
            except ValueError as exc:
                raise RoutineProposalValidationError("sleep target must be numeric seconds") from exc
            if seconds <= 0 or seconds > 30:
                raise RoutineProposalValidationError("sleep target must be between 0 and 30 seconds")
            return ProposedRoutineStep(action=step.action, target=str(seconds).rstrip("0").rstrip("."))

        if step.action == "notify_user" and len(step.target) > 140:
            raise RoutineProposalValidationError("notify_user target is too long")

        return step

    def _is_proposable(self, pattern: CandidatePattern) -> bool:
        if pattern.accepted or pattern.proposed:
            return False
        if len(pattern.apps) < 2:
            return False
        if pattern.pattern_type not in {"cooccurrence", "sequence"}:
            return False
        return bool(pattern.metadata)

    def _row_to_candidate(self, row: tuple[Any, ...]) -> CandidatePattern:
        metadata = {}
        if row[6]:
            try:
                metadata = json.loads(row[6])
            except json.JSONDecodeError:
                metadata = {}
        apps = tuple(json.loads(row[2]))
        return CandidatePattern(
            pattern_id=int(row[0]),
            pattern_type=str(row[1]),
            apps=apps,
            occurrences=int(row[3] or 0),
            first_seen=row[4],
            last_seen=row[5],
            metadata=metadata,
            proposed=bool(row[7]),
            accepted=bool(row[8]),
            score=float(row[9] or 0.0),
            semantic_intent=row[10],
            pattern_version=int(row[11] or 1),
        )

    def _compact_metadata(self, metadata: dict[str, Any]) -> dict[str, Any]:
        allowed_keys = {
            "score",
            "recency",
            "ordered_steps",
            "temporal_context",
            "intent",
            "duration_seconds",
            "app_weights",
            "examples",
            "cluster_size",
        }
        return {key: value for key, value in metadata.items() if key in allowed_keys}

    def _unsupported_apps(self, apps: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(app for app in apps if app_target_for(app) is None)

    def _load_json_object(self, raw_response: str) -> dict[str, Any]:
        text = raw_response.strip()
        if text.startswith("```"):
            lines = [line for line in text.splitlines() if not line.strip().startswith("```")]
            text = "\n".join(lines).strip()
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise RoutineProposalValidationError(f"AI response is not valid JSON: {exc}") from exc
        if not isinstance(payload, dict):
            raise RoutineProposalValidationError("AI response root must be an object")
        return payload
