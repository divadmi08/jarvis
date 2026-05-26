from __future__ import annotations

from core.pattern_types import WorkflowPattern


class PatternCompressor:
    def __init__(self, overlap_threshold: float = 0.9):
        self.overlap_threshold = overlap_threshold

    def compress(self, patterns: list[WorkflowPattern]) -> list[WorkflowPattern]:
        kept: list[WorkflowPattern] = []
        ordered = sorted(
            patterns,
            key=lambda pattern: (len(pattern.apps), pattern.score.final_score, pattern.frequency),
            reverse=True,
        )
        for candidate in ordered:
            if not self._is_redundant(candidate, kept):
                kept.append(candidate)
        kept.sort(key=lambda pattern: pattern.score.final_score, reverse=True)
        return kept

    def _is_redundant(self, candidate: WorkflowPattern, existing: list[WorkflowPattern]) -> bool:
        candidate_set = set(candidate.apps)
        for pattern in existing:
            if candidate.pattern_type != pattern.pattern_type:
                continue
            existing_set = set(pattern.apps)
            if not candidate_set.issubset(existing_set):
                continue
            overlap = len(candidate_set & existing_set) / max(len(candidate_set), 1)
            if overlap >= self.overlap_threshold and pattern.score.confidence >= candidate.score.confidence:
                if pattern.frequency >= candidate.frequency and pattern.score.final_score >= candidate.score.final_score:
                    return True
        return False
