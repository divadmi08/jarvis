from __future__ import annotations

import json
import sqlite3
import unittest
from dataclasses import dataclass
from pathlib import Path

from core.agent_loop import AgentLoop
from core.ai_client import AIClient
from core.planner import LLMPlanner
from core.task_state import AgentTaskStatus
from data.database import Database


class StubAIClient(AIClient):
    def __init__(self, response: dict) -> None:
        self.response = response
        self.prompts: list[str] = []

    def generate_text(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return json.dumps(self.response)


@dataclass
class FakeStepResult:
    action: str
    target: str
    status: object = "success"
    message: str = ""
    elapsed: float = 0.0


class FakeRoutineResult:
    def __init__(self, steps):
        self.steps = steps
        self.status = "success"

    def summary(self) -> str:
        return "fake routine success"


class FakeExecutor:
    def __init__(self) -> None:
        self.routines = []

    def run_routine(self, routine, on_step=None):
        self.routines.append(routine)
        step = routine["steps"][0]
        return FakeRoutineResult([FakeStepResult(action=step["action"], target=step["target"])])


class AgentLoopTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path("tests/.tmp")
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = str(self.temp_dir / f"{self._testMethodName}.db")
        db_file = Path(self.db_path)
        if db_file.exists():
            db_file.unlink()
        self.db = Database(self.db_path)

    def tearDown(self) -> None:
        self.db.conn.close()
        db_file = Path(self.db_path)
        if db_file.exists():
            db_file.unlink()

    def test_agent_loop_plans_executes_one_step_and_persists_task(self) -> None:
        self.db.save_memory_event("session", "1", "coding session using vscode", "{}", 0.5)
        ai_client = StubAIClient(
            {
                "steps": [
                    {
                        "action": "notify_user",
                        "target": "Starting coding setup",
                        "reason": "Tell the user the task is starting.",
                    },
                    {
                        "action": "open_app",
                        "target": "vscode",
                        "reason": "Open the editor.",
                    },
                ],
                "stop_condition": "user is notified",
                "reasoning": "Start with a safe notification.",
            }
        )
        executor = FakeExecutor()
        loop = AgentLoop(db=self.db, planner=LLMPlanner(ai_client), executor=executor)

        result = loop.run_goal("start coding")

        self.assertEqual(result.status, AgentTaskStatus.PARTIAL)
        self.assertEqual(result.executed_step.action, "notify_user")
        self.assertEqual(len(executor.routines), 1)

        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("SELECT goal, status, plan_json, result_json FROM agent_tasks")
        goal, status, plan_json, result_json = cur.fetchone()
        conn.close()

        self.assertEqual(goal, "start coding")
        self.assertEqual(status, "partial")
        self.assertIn("notify_user", plan_json)
        self.assertIn("fake routine success", result_json)


if __name__ == "__main__":
    unittest.main()
