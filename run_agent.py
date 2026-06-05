from __future__ import annotations

import argparse
import logging
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(dotenv_path=Path(__file__).parent / ".env")

from core.agent_loop import AgentLoop
from core.ai_client import AIClientConfigurationError, build_ai_client
from core.planner import LLMPlanner
from data.database import Database


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run one bounded Jarvis agent step for a user goal.")
    parser.add_argument("goal", help="Goal for Jarvis to plan and execute.")
    parser.add_argument("--db-path", default="data/jarvis.db", help="Path to the SQLite database.")
    parser.add_argument("--provider", default=None, choices=["gemini", "groq"], help="AI provider da usare (default: auto)")
    parser.add_argument("--model", default=None, help="Nome del modello (default: auto in base al provider).")
    parser.add_argument("--max-plan-steps", type=int, default=5, help="Maximum steps the planner may return.")
    parser.add_argument("--log-level", default="INFO", help="Logging level.")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    logging.basicConfig(
        level=getattr(logging, str(args.log_level).upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    db = Database(args.db_path)
    try:
        ai_client = build_ai_client(provider=args.provider, model=args.model)
    except AIClientConfigurationError as exc:
        print(f"Configuration error: {exc}")
        db.conn.close()
        return 2

    planner = LLMPlanner(ai_client=ai_client, max_steps=args.max_plan_steps)
    loop = AgentLoop(db=db, planner=planner)
    try:
        result = loop.run_goal(args.goal)
    finally:
        db.conn.close()

    print("Agent task run")
    print(f"Task id: {result.task_id}")
    print(f"Status: {result.status.value}")
    if result.executed_step:
        print(f"Executed: {result.executed_step.action} -> {result.executed_step.target}")
    if result.message:
        print(f"Observation: {result.message}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())