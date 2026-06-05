from __future__ import annotations

import json
from typing import Any

from core.ai_client import AIClient
from core.task_state import AgentPlan, AgentStep


ALLOWED_AGENT_ACTIONS = frozenset({
    "open_app",
    "focus_window",
    "wait_for_window",
    "notify_user",
    "sleep",
    "run_command",
})


class PlannerError(ValueError):
    pass


class LLMPlanner:
    def __init__(
        self,
        ai_client: AIClient,
        max_steps: int = 5,
        allowed_actions: frozenset[str] = ALLOWED_AGENT_ACTIONS,
    ) -> None:
        self.ai_client = ai_client
        self.max_steps = max(1, int(max_steps))
        self.allowed_actions = allowed_actions

    def plan(self, goal: str, context: str = "") -> AgentPlan:
        raw = self.ai_client.generate_json(self._build_prompt(goal, context))
        payload = json.loads(raw)
        return self._parse_plan(goal, payload)

    def _build_prompt(self, goal: str, context: str) -> str:
        payload = {
            "goal": goal,
            "context": context,
            "allowed_actions": sorted(self.allowed_actions),
            "max_steps": self.max_steps,
        }
        return (
            "You are Jarvis, a local-first Windows PC agent planner.\n"
            "Create a minimal, safe plan for the user goal.\n"
            "Return JSON only with: steps, stop_condition, reasoning.\n"
            "Each step must have action, target, reason, optional timeout.\n"
            "Do not invent destructive commands, private file paths, credentials, or admin actions.\n"
            "Prefer notify_user if the goal is ambiguous or needs user input.\n"
            f"Input:\n{json.dumps(payload, ensure_ascii=True, indent=2)}"
        )

    def _parse_plan(self, goal: str, payload: dict[str, Any]) -> AgentPlan:
        raw_steps = payload.get("steps")
        if not isinstance(raw_steps, list) or not raw_steps:
            raise PlannerError("plan.steps must be a non-empty list")
        steps = []
        for raw_step in raw_steps[: self.max_steps]:
            if not isinstance(raw_step, dict):
                raise PlannerError("each plan step must be an object")
            action = str(raw_step.get("action", "")).strip()
            target = str(raw_step.get("target", "")).strip()
            reason = str(raw_step.get("reason", "")).strip()
            if action not in self.allowed_actions:
                raise PlannerError(f"Unsupported planner action: {action}")
            if not target:
                raise PlannerError(f"Missing target for planner action: {action}")
            timeout = raw_step.get("timeout")
            steps.append(
                AgentStep(
                    action=action,
                    target=target,
                    reason=reason,
                    timeout=int(timeout) if isinstance(timeout, (int, float)) else None,
                )
            )
        return AgentPlan(
            goal=goal,
            steps=tuple(steps),
            stop_condition=str(payload.get("stop_condition", "")).strip() or "first step executed",
            reasoning=str(payload.get("reasoning", "")).strip(),
        )
