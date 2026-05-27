from __future__ import annotations

from dataclasses import dataclass
from typing import Any


ALLOWED_AI_PROPOSAL_ACTIONS = frozenset({
    "open_app",
    "focus_window",
    "wait_for_window",
    "notify_user",
    "sleep",
})

MAX_PROPOSAL_NAME_LENGTH = 80
MAX_PROPOSAL_DESCRIPTION_LENGTH = 280
MAX_PROPOSAL_REASONING_LENGTH = 280


class RoutineProposalValidationError(ValueError):
    pass


@dataclass(frozen=True)
class PatternSourceRef:
    type: str
    apps: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "apps": list(self.apps),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "PatternSourceRef":
        pattern_type = str(payload.get("type", "")).strip()
        apps = payload.get("apps")
        if not pattern_type:
            raise RoutineProposalValidationError("source_pattern.type is required")
        if not isinstance(apps, list) or not apps:
            raise RoutineProposalValidationError("source_pattern.apps must be a non-empty list")
        normalized_apps = tuple(str(app).strip() for app in apps if str(app).strip())
        if len(normalized_apps) != len(apps):
            raise RoutineProposalValidationError("source_pattern.apps contains empty values")
        return cls(type=pattern_type, apps=normalized_apps)


@dataclass(frozen=True)
class ProposedRoutineStep:
    action: str
    target: str

    def to_dict(self) -> dict[str, str]:
        return {
            "action": self.action,
            "target": self.target,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ProposedRoutineStep":
        action = str(payload.get("action", "")).strip()
        target = str(payload.get("target", "")).strip()
        if not action:
            raise RoutineProposalValidationError("step.action is required")
        if action not in ALLOWED_AI_PROPOSAL_ACTIONS:
            raise RoutineProposalValidationError(f"Unsupported action proposed: {action}")
        if not target:
            raise RoutineProposalValidationError(f"step.target is required for action {action}")
        return cls(action=action, target=target)


@dataclass(frozen=True)
class RoutineProposal:
    name: str
    description: str
    steps: tuple[ProposedRoutineStep, ...]
    confidence: float
    reasoning: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "steps": [step.to_dict() for step in self.steps],
            "confidence": self.confidence,
            "reasoning": self.reasoning,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "RoutineProposal":
        name = str(payload.get("name", "")).strip()
        description = str(payload.get("description", "")).strip()
        raw_steps = payload.get("steps")
        confidence = payload.get("confidence")
        reasoning = str(payload.get("reasoning", "")).strip()

        if not name:
            raise RoutineProposalValidationError("proposal.name is required")
        if len(name) > MAX_PROPOSAL_NAME_LENGTH:
            raise RoutineProposalValidationError("proposal.name is too long")
        if not description:
            raise RoutineProposalValidationError("proposal.description is required")
        if len(description) > MAX_PROPOSAL_DESCRIPTION_LENGTH:
            raise RoutineProposalValidationError("proposal.description is too long")
        if not isinstance(raw_steps, list) or not raw_steps:
            raise RoutineProposalValidationError("proposal.steps must be a non-empty list")
        if not isinstance(confidence, (int, float)):
            raise RoutineProposalValidationError("proposal.confidence must be numeric")
        confidence_value = float(confidence)
        if confidence_value < 0 or confidence_value > 1:
            raise RoutineProposalValidationError("proposal.confidence must be between 0 and 1")
        if not reasoning:
            raise RoutineProposalValidationError("proposal.reasoning is required")
        if len(reasoning) > MAX_PROPOSAL_REASONING_LENGTH:
            raise RoutineProposalValidationError("proposal.reasoning is too long")

        steps = tuple(ProposedRoutineStep.from_dict(step) for step in raw_steps)
        return cls(
            name=name,
            description=description,
            steps=steps,
            confidence=confidence_value,
            reasoning=reasoning,
        )


@dataclass(frozen=True)
class RoutineProposalDecision:
    should_propose: bool
    source_pattern: PatternSourceRef | None = None
    proposal: RoutineProposal | None = None
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "should_propose": self.should_propose,
        }
        if self.source_pattern is not None:
            payload["source_pattern"] = self.source_pattern.to_dict()
        if self.proposal is not None:
            payload["proposal"] = self.proposal.to_dict()
        if self.reason:
            payload["reason"] = self.reason
        return payload
