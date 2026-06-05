from __future__ import annotations

import json
import logging
from typing import Any, Protocol

from core.planner import LLMPlanner
from core.task_state import AgentTaskResult, AgentTaskStatus
from data.database import Database


log = logging.getLogger("agent_loop")


class RoutineExecutor(Protocol):
    def run_routine(self, routine: dict[str, Any], on_step: Any = None) -> Any:
        ...


class AgentLoop:
    def __init__(
        self,
        db: Database,
        planner: LLMPlanner,
        executor: RoutineExecutor | None = None,
        max_steps_per_turn: int = 1,
    ) -> None:
        self.db = db
        self.planner = planner
        self.executor = executor
        self.max_steps_per_turn = max(1, int(max_steps_per_turn))

    def run_goal(self, goal: str) -> AgentTaskResult:
        context = self._retrieve_context(goal)
        plan = self.planner.plan(goal=goal, context=context)
        task_id = self.db.create_agent_task(
            goal=goal,
            status=AgentTaskStatus.PLANNED.value,
            plan_json=json.dumps(plan.to_dict(), ensure_ascii=True),
        )

        if not plan.steps:
            self.db.update_agent_task(task_id, AgentTaskStatus.BLOCKED.value)
            return AgentTaskResult(task_id, AgentTaskStatus.BLOCKED, message="planner returned no steps")

        step = plan.steps[0]
        self.db.update_agent_task(task_id, AgentTaskStatus.RUNNING.value)
        try:
            executor = self.executor or self._build_default_executor()
            routine_result = executor.run_routine(
                {
                    "name": f"Agent task {task_id}",
                    "steps": [step.to_executor_step()],
                }
            )
            observation = self._observe_result(routine_result)
            status = self._status_from_observation(observation, remaining_steps=len(plan.steps) - 1)
            self.db.update_agent_task(
                task_id,
                status.value,
                result_json=json.dumps(observation, ensure_ascii=True),
            )
            return AgentTaskResult(
                task_id=task_id,
                status=status,
                executed_step=step,
                observation=observation,
                message=observation.get("summary", ""),
            )
        except Exception as exc:
            observation = {"error": str(exc)}
            self.db.update_agent_task(
                task_id,
                AgentTaskStatus.FAILED.value,
                result_json=json.dumps(observation, ensure_ascii=True),
            )
            log.exception("Agent task %s failed", task_id)
            return AgentTaskResult(task_id, AgentTaskStatus.FAILED, executed_step=step, observation=observation, message=str(exc))

    def _retrieve_context(self, goal: str) -> str:
        goal_terms = {term for term in goal.lower().replace(",", " ").split() if len(term) >= 3}
        lines = []
        for row in self.db.fetch_memory_events(limit=10):
            summary = str(row[3])
            metadata = str(row[4] or "")
            haystack = f"{summary} {metadata}".lower()
            if not goal_terms or any(term in haystack for term in goal_terms):
                lines.append(f"- Memory: {summary}")
        for row in self.db.fetch_reflections(limit=5):
            insight = str(row[2])
            if not goal_terms or any(term in insight.lower() for term in goal_terms):
                lines.append(f"- Reflection: {insight}")
        return "\n".join(lines[:8]) or "No relevant local context found."

    def _observe_result(self, routine_result: Any) -> dict[str, Any]:
        steps = []
        for step in getattr(routine_result, "steps", []):
            status = getattr(getattr(step, "status", ""), "value", str(getattr(step, "status", "")))
            steps.append(
                {
                    "action": getattr(step, "action", ""),
                    "target": getattr(step, "target", ""),
                    "status": status,
                    "message": getattr(step, "message", ""),
                    "elapsed": getattr(step, "elapsed", 0.0),
                }
            )
        summary = routine_result.summary() if hasattr(routine_result, "summary") else str(routine_result)
        return {
            "routine_status": getattr(routine_result, "status", "unknown"),
            "steps": steps,
            "summary": summary,
        }

    def _status_from_observation(self, observation: dict[str, Any], remaining_steps: int) -> AgentTaskStatus:
        if observation.get("routine_status") == "success":
            return AgentTaskStatus.PARTIAL if remaining_steps > 0 else AgentTaskStatus.COMPLETED
        if observation.get("routine_status") == "partial":
            return AgentTaskStatus.PARTIAL
        return AgentTaskStatus.BLOCKED

    def _build_default_executor(self) -> RoutineExecutor:
        from core.executor import Executor

        return Executor()
