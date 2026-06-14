from __future__ import annotations

import json
import logging
from typing import Any, Protocol

from core.app_registry import load_aliases
from core.memory import get_memory
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

            # Salva in memoria semantica se il task è andato a buon fine
            if status in (AgentTaskStatus.COMPLETED, AgentTaskStatus.PARTIAL):
                self._save_to_memory(task_id, goal, step, observation)

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

    def _save_to_memory(
        self,
        task_id: int,
        goal: str,
        step: Any,
        observation: dict[str, Any],
    ) -> None:
        """Salva il task completato nella memoria semantica ChromaDB."""
        try:
            memory = get_memory()
            memory.save_task(
                task_id=task_id,
                goal=goal,
                action=getattr(step, "action", ""),
                target=getattr(step, "target", ""),
                status=observation.get("routine_status", "unknown"),
            )
        except Exception as e:
            log.warning(f"Failed to save task to semantic memory: {e}")

    def _retrieve_context(self, goal: str) -> str:
        lines = []

        # 1. Memoria semantica — cerca per similarità al goal corrente
        try:
            memory = get_memory()
            semantic_context = memory.format_for_prompt(goal, n_results=4)
            if semantic_context:
                lines.append(semantic_context)
        except Exception as e:
            log.warning(f"Semantic memory retrieval failed: {e}")

        # 2. Alias manuali — mostrati per primi così il modello li usa
        try:
            aliases = load_aliases()
            if aliases:
                alias_lines = [f"{name} -> {path}" for name, path in aliases.items()]
                lines.append("Manual app aliases (use these exact paths when matching):\n" + "\n".join(alias_lines))
        except Exception as e:
            log.warning(f"App aliases load failed: {e}")

        return "\n\n".join(lines) if lines else "No relevant context found."

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