from __future__ import annotations

from collections import defaultdict
from datetime import datetime
import math

from core.pattern_types import PatternScore, SessionRepresentation


class PatternScorer:
    def __init__(self, reference_time: datetime | None = None):
        self.reference_time = reference_time or datetime.now()

    def score_pattern(
        self,
        matching_sessions: list[SessionRepresentation],
        all_sessions: list[SessionRepresentation],
        apps: tuple[str, ...],
        antecedent_apps: tuple[str, ...] | None = None,
    ) -> PatternScore:
        total_sessions = max(len(all_sessions), 1)
        support = len(matching_sessions) / total_sessions
        confidence = self._confidence(matching_sessions, all_sessions, antecedent_apps or apps[:-1] or apps)
        lift = self._lift(support, confidence, all_sessions, apps[-1] if apps else None)
        recency = self._recency_score(matching_sessions)
        consistency = self._consistency_score(matching_sessions)
        duration = self._duration_score(matching_sessions, apps)
        final_score = self._final_score(support, confidence, lift, recency, consistency, duration)
        return PatternScore(
            support=support,
            confidence=confidence,
            lift=lift,
            recency_score=recency,
            consistency_score=consistency,
            duration_score=duration,
            final_score=final_score,
        )

    def _confidence(
        self,
        matching_sessions: list[SessionRepresentation],
        all_sessions: list[SessionRepresentation],
        antecedent_apps: tuple[str, ...],
    ) -> float:
        antecedent_count = 0
        antecedent_set = set(antecedent_apps)
        for session in all_sessions:
            if antecedent_set.issubset(session.app_weights):
                antecedent_count += 1
        return len(matching_sessions) / max(antecedent_count, 1)

    def _lift(
        self,
        support: float,
        confidence: float,
        all_sessions: list[SessionRepresentation],
        consequent: str | None,
    ) -> float:
        if consequent is None:
            return 1.0
        consequent_count = sum(1 for session in all_sessions if consequent in session.app_weights)
        consequent_probability = consequent_count / max(len(all_sessions), 1)
        if consequent_probability <= 0:
            return 1.0
        return confidence / consequent_probability

    def _recency_score(self, matching_sessions: list[SessionRepresentation]) -> float:
        if not matching_sessions:
            return 0.0
        scores = []
        for session in matching_sessions:
            age_days = max((self.reference_time - session.end).total_seconds() / 86400.0, 0.0)
            scores.append(math.exp(-math.log(2) * age_days / 30.0))
        return sum(scores) / len(scores)

    def _consistency_score(self, matching_sessions: list[SessionRepresentation]) -> float:
        if len(matching_sessions) < 2:
            return 0.3 if matching_sessions else 0.0
        buckets: dict[tuple[int, int], int] = defaultdict(int)
        for session in matching_sessions:
            year, week, _ = session.start.isocalendar()
            buckets[(year, week)] += 1
        density = len(buckets) / len(matching_sessions)
        return max(0.0, min(1.0, density + 0.2))

    @staticmethod
    def _duration_score(matching_sessions: list[SessionRepresentation], apps: tuple[str, ...]) -> float:
        if not matching_sessions:
            return 0.0
        totals = []
        app_set = set(apps)
        for session in matching_sessions:
            weighted = sum(duration for app, duration in session.app_durations.items() if app in app_set)
            totals.append(min(weighted / max(session.total_duration_seconds, 1.0), 1.0))
        return sum(totals) / len(totals)

    @staticmethod
    def _final_score(
        support: float,
        confidence: float,
        lift: float,
        recency: float,
        consistency: float,
        duration: float,
    ) -> float:
        normalized_lift = max(0.0, min(lift / 3.0, 1.0))
        final = (
            0.2 * support
            + 0.2 * confidence
            + 0.15 * normalized_lift
            + 0.2 * recency
            + 0.15 * consistency
            + 0.1 * duration
        )
        return round(max(0.0, min(final, 1.0)), 6)
