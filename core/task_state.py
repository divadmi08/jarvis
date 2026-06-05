from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class AgentTaskStatus(str, Enum):
    PLANNED = "planned"
    RUNNING = "running"
    COMPLETED = "completed"
    PARTIAL = "partial"
    BLOCKED = "blocked"
    FAILED = "failed"


@dataclass(frozen=True)
class AgentStep:
    action: str
    target: str
    reason: str = ""
    timeout: int | None = None

    def to_executor_step(self) -> dict[str, Any]:
        step: dict[str, Any] = {
            "action": self.action,
            "target": self.target,
        }
        if self.timeout is not None:
            step["timeout"] = self.timeout
        return step

    def to_dict(self) -> dict[str, Any]:
        payload = self.to_executor_step()
        if self.reason:
            payload["reason"] = self.reason
        return payload


@dataclass(frozen=True)
class AgentPlan:
    goal: str
    steps: tuple[AgentStep, ...]
    stop_condition: str
    reasoning: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "goal": self.goal,
            "steps": [step.to_dict() for step in self.steps],
            "stop_condition": self.stop_condition,
            "reasoning": self.reasoning,
        }


@dataclass(frozen=True)
class AgentTaskResult:
    task_id: int
    status: AgentTaskStatus
    executed_step: AgentStep | None = None
    observation: dict[str, Any] = field(default_factory=dict)
    message: str = ""
