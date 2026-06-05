from __future__ import annotations

import argparse
import logging

from core.ai_client import AIClientConfigurationError, GeminiAIClient
from core.routine_proposal_service import RoutineProposalService
from core.routine_proposer import RoutineProposer
from data.database import Database


def build_context_builder(db: Database):
    try:
        from core.context_builder import ContextBuilder
        from core.embedding_client import LocalEmbeddingClient
        from core.semantic_memory import SemanticMemory

        memory = SemanticMemory(LocalEmbeddingClient())
        return ContextBuilder(memory=memory, db=db)
    except Exception as exc:
        logging.getLogger("propose_routines").warning("Semantic context unavailable: %s", exc)
        return None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate safe routine proposals from mined patterns.")
    parser.add_argument("--db-path", default="data/jarvis.db", help="Path to the SQLite database.")
    parser.add_argument("--limit", type=int, default=5, help="Maximum number of candidate patterns to inspect.")
    parser.add_argument("--model", default="gemini-2.5-flash-lite", help="Gemini model name to use.")
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=20.0,
        help="Per-request Gemini timeout in seconds.",
    )
    parser.add_argument(
        "--max-attempts",
        type=int,
        default=2,
        help="How many times to retry each Gemini request per model on transient failures.",
    )
    parser.add_argument(
        "--retry-delay-seconds",
        type=float,
        default=1.0,
        help="Base delay between transient Gemini retries.",
    )
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
        ai_client = GeminiAIClient(
            model=args.model,
            timeout_seconds=args.timeout_seconds,
            max_attempts=args.max_attempts,
            retry_delay_seconds=args.retry_delay_seconds,
        )
    except AIClientConfigurationError as exc:
        print(f"Configuration error: {exc}")
        db.conn.close()
        return 2

    proposer = RoutineProposer(db=db, ai_client=ai_client, context_builder=build_context_builder(db))
    service = RoutineProposalService(db=db, proposer=proposer)

    try:
        summary = service.propose_top_patterns(limit=args.limit)
    finally:
        db.conn.close()

    print("Routine proposal run")
    print(f"Patterns examined: {summary.examined}")
    print(f"Proposals created: {summary.created}")
    print(f"Patterns skipped: {summary.skipped}")
    print(f"Errors: {summary.errors}")
    print("")
    for result in summary.results:
        line = f"- pattern {result.pattern_id}: {result.status}"
        if result.proposal_id is not None:
            line += f" (proposal_id={result.proposal_id})"
        if result.reason:
            line += f" - {result.reason}"
        if result.proposal and result.proposal.proposal:
            line += f" - {result.proposal.proposal.name}"
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
