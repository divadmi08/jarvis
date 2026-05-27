from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

from core.routine_proposal_types import RoutineProposalValidationError
from core.routine_proposer import CandidatePattern, ProposalAttemptResult, RoutineProposer
from data.database import Database


log = logging.getLogger("routine_proposal_service")


@dataclass(frozen=True)
class ProposalRunSummary:
    examined: int = 0
    created: int = 0
    skipped: int = 0
    errors: int = 0
    results: tuple[ProposalAttemptResult, ...] = field(default_factory=tuple)


class RoutineProposalService:
    def __init__(self, db: Database, proposer: RoutineProposer) -> None:
        self.db = db
        self.proposer = proposer

    def find_candidate_patterns(self, limit: int = 10) -> list[CandidatePattern]:
        return self.proposer.find_candidate_patterns(limit=limit)

    def propose_for_pattern(self, pattern_id: int) -> ProposalAttemptResult:
        row = self.db.get_pattern_by_id(pattern_id)
        if row is None:
            return ProposalAttemptResult(pattern_id=pattern_id, status="skipped", reason="pattern not found")

        candidate = self.proposer._row_to_candidate(row)
        if not self.proposer._is_proposable(candidate):
            return ProposalAttemptResult(pattern_id=pattern_id, status="skipped", reason="pattern not proposable")
        if self.db.has_active_routine_proposal(pattern_id):
            return ProposalAttemptResult(pattern_id=pattern_id, status="skipped", reason="active proposal already exists")

        try:
            decision = self.proposer.generate_proposal_for_pattern(candidate)
            if not decision.should_propose or decision.proposal is None or decision.source_pattern is None:
                return ProposalAttemptResult(
                    pattern_id=pattern_id,
                    status="skipped",
                    proposal=decision,
                    reason=decision.reason or "model declined to propose",
                )

            proposal_id = self.db.save_routine_proposal(
                pattern_id=pattern_id,
                name=decision.proposal.name,
                description=decision.proposal.description,
                steps_json=json.dumps(
                    [step.to_dict() for step in decision.proposal.steps],
                    ensure_ascii=True,
                ),
                confidence=decision.proposal.confidence,
                reasoning=decision.proposal.reasoning,
                source_pattern_json=json.dumps(decision.source_pattern.to_dict(), ensure_ascii=True),
            )
            log.info("Saved routine proposal %s for pattern %s", proposal_id, pattern_id)
            return ProposalAttemptResult(
                pattern_id=pattern_id,
                status="created",
                proposal_id=proposal_id,
                proposal=decision,
            )
        except RoutineProposalValidationError as exc:
            log.warning("Routine proposal rejected for pattern %s: %s", pattern_id, exc)
            return ProposalAttemptResult(pattern_id=pattern_id, status="error", reason=str(exc))
        except Exception as exc:
            log.exception("Routine proposal generation failed for pattern %s", pattern_id)
            return ProposalAttemptResult(pattern_id=pattern_id, status="error", reason=str(exc))

    def propose_top_patterns(self, limit: int = 5) -> ProposalRunSummary:
        candidates = self.find_candidate_patterns(limit=limit)
        results = tuple(self.propose_for_pattern(candidate.pattern_id) for candidate in candidates)
        created = sum(1 for result in results if result.status == "created")
        skipped = sum(1 for result in results if result.status == "skipped")
        errors = sum(1 for result in results if result.status == "error")
        log.info(
            "Routine proposal run completed: examined=%s created=%s skipped=%s errors=%s",
            len(candidates),
            created,
            skipped,
            errors,
        )
        return ProposalRunSummary(
            examined=len(candidates),
            created=created,
            skipped=skipped,
            errors=errors,
            results=results,
        )
