from __future__ import annotations

import json
import os
import sys
from collections import defaultdict
from dataclasses import asdict
from datetime import datetime, timedelta
from itertools import combinations
from typing import Any

if __package__ in {None, ""}:
    # Allow direct execution via `python core/pattern_engine.py`.
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.database import Database
from session_builder import MIN_APP_DURATION, categorize_app, is_noise

from core.intent_inference import IntentInferenceEngine
from core.pattern_compression import PatternCompressor
from core.pattern_scoring import PatternScorer
from core.pattern_similarity import PatternSimilarity
from core.pattern_types import PatternEngineConfig, SessionRepresentation, WorkflowPattern
from core.temporal_model import TemporalDecayConfig, TemporalModel
from core.workflow_embedding import build_workflow_embedding


class PatternEngine:
    def __init__(self, db_path: str = "data/jarvis.db", config: PatternEngineConfig | None = None):
        self.db = Database(db_path)
        self.cursor = self.db.cursor
        self.config = config or PatternEngineConfig(min_meaningful_duration_seconds=MIN_APP_DURATION)
        self.temporal_model = TemporalModel(
            TemporalDecayConfig(
                half_life_days=self.config.decay_half_life_days,
                floor=self.config.decay_floor,
            )
        )
        self.pattern_similarity = PatternSimilarity()
        self.intent_engine = IntentInferenceEngine()
        self.pattern_scorer = PatternScorer()
        self.compressor = PatternCompressor(self.config.compression_overlap_threshold)
        self._ensure_pattern_schema()

    def load_sessions(self, days: int | None = None) -> list[dict[str, Any]]:
        lookback_days = days or self.config.lookback_days
        since = (datetime.now() - timedelta(days=lookback_days)).isoformat()
        self.cursor.execute(
            """
            SELECT id, start_time, end_time, apps_used, label
            FROM sessions
            WHERE start_time >= ?
            ORDER BY start_time
            """,
            (since,),
        )
        sessions: list[dict[str, Any]] = []
        for row in self.cursor.fetchall():
            sid, start, end, apps_json, label = row
            apps = self._parse_apps_used(apps_json)
            sessions.append(
                {
                    "id": sid,
                    "start": datetime.fromisoformat(start),
                    "end": datetime.fromisoformat(end),
                    "apps": apps,
                    "label": label,
                }
            )
        return sessions

    def find_cooccurrence_patterns(self, sessions: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [pattern.to_legacy_dict() for pattern in self._build_cooccurrence_patterns(self._represent_sessions(sessions))]

    def find_temporal_patterns(self, sessions: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [pattern.to_legacy_dict() for pattern in self._build_temporal_patterns(self._represent_sessions(sessions))]

    def find_sequence_patterns(self, sessions: list[dict[str, Any]]) -> list[dict[str, Any]]:
        represented = self._represent_sessions(sessions)
        return [pattern.to_legacy_dict() for pattern in self._build_sequence_patterns(represented)]

    def save_patterns(self, patterns: list[dict[str, Any]]) -> int:
        saved = 0
        updated = 0
        for pattern in patterns:
            apps_json = json.dumps(pattern["apps"])
            metadata_json = json.dumps(pattern.get("metadata", {}))
            score = float(pattern.get("score") or pattern.get("metadata", {}).get("score", {}).get("final_score", 0.0))
            intent = pattern.get("intent")
            version = 2
            self.cursor.execute(
                """
                SELECT id, occurrences, proposed, accepted
                FROM patterns
                WHERE pattern_type = ? AND apps_sequence = ?
                """,
                (pattern["type"], apps_json),
            )
            existing = self.cursor.fetchone()
            if existing:
                pattern_id, old_occurrences, proposed, accepted = existing
                occurrences = max(old_occurrences, int(pattern["occurrences"]))
                self.cursor.execute(
                    """
                    UPDATE patterns
                    SET occurrences = ?, first_seen = ?, last_seen = ?, metadata = ?,
                        score = ?, semantic_intent = ?, pattern_version = ?,
                        proposed = ?, accepted = ?
                    WHERE id = ?
                    """,
                    (
                        occurrences,
                        pattern["first_seen"],
                        pattern["last_seen"],
                        metadata_json,
                        score,
                        intent,
                        version,
                        proposed,
                        accepted,
                        pattern_id,
                    ),
                )
                updated += 1
            else:
                self.cursor.execute(
                    """
                    INSERT INTO patterns
                    (pattern_type, apps_sequence, occurrences, first_seen, last_seen, metadata,
                     proposed, accepted, score, semantic_intent, pattern_version)
                    VALUES (?, ?, ?, ?, ?, ?, 0, 0, ?, ?, ?)
                    """,
                    (
                        pattern["type"],
                        apps_json,
                        int(pattern["occurrences"]),
                        pattern["first_seen"],
                        pattern["last_seen"],
                        metadata_json,
                        score,
                        intent,
                        version,
                    ),
                )
                saved += 1
        self.db.conn.commit()
        print(f"Pattern salvati: {saved} nuovi, {updated} aggiornati")
        return saved + updated

    def export_for_ai(self, top_n: int = 20) -> str:
        self.cursor.execute(
            """
            SELECT pattern_type, apps_sequence, occurrences, metadata, COALESCE(score, 0), semantic_intent
            FROM patterns
            WHERE accepted = 0
            ORDER BY COALESCE(score, 0) DESC, occurrences DESC
            LIMIT ?
            """,
            (top_n,),
        )
        rows = self.cursor.fetchall()
        if not rows:
            return "Nessun pattern identificato ancora."
        lines = ["## Pattern comportamentali dell'utente\n"]
        for pattern_type, apps_json, occurrences, metadata_json, score, intent in rows:
            apps = json.loads(apps_json)
            metadata = json.loads(metadata_json) if metadata_json else {}
            temporal = metadata.get("temporal_context", {})
            if pattern_type == "cooccurrence":
                lines.append(
                    f"- Routine app: {', '.join(apps)} | score={round(score, 2)} | occorrenze={occurrences}"
                )
            elif pattern_type == "temporal":
                lines.append(
                    f"- Pattern {temporal.get('period', '?')} "
                    f"({'weekday' if temporal.get('weekday') else 'weekend'}): {', '.join(apps)} "
                    f"| score={round(score, 2)}"
                )
            else:
                lines.append(
                    f"- Workflow: {' -> '.join(apps)} | score={round(score, 2)}"
                )
            if intent:
                lines.append(f"  intento: {intent}")
        return "\n".join(lines)

    def run(self) -> dict[str, list[dict[str, Any]]]:
        raw_sessions = self.load_sessions()
        print(f"Sessioni caricate: {len(raw_sessions)}")
        if not raw_sessions:
            print("Nessuna sessione trovata. Esegui prima session_builder.py")
            return {}
        represented = self._represent_sessions(raw_sessions)
        cooccurrence = [pattern.to_legacy_dict() for pattern in self._build_cooccurrence_patterns(represented)]
        temporal = [pattern.to_legacy_dict() for pattern in self._build_temporal_patterns(represented)]
        sequence = [pattern.to_legacy_dict() for pattern in self._build_sequence_patterns(represented)]
        all_patterns = cooccurrence + temporal + sequence
        print(f"Totale pattern candidati: {len(all_patterns)}")
        self.save_patterns(all_patterns)
        print(self.export_for_ai())
        return {
            "cooccurrence": cooccurrence,
            "temporal": temporal,
            "sequence": sequence,
        }

    def _build_cooccurrence_patterns(self, sessions: list[SessionRepresentation]) -> list[WorkflowPattern]:
        pattern_sessions: dict[tuple[str, ...], list[SessionRepresentation]] = defaultdict(list)
        for session in sessions:
            apps = list(session.app_weights)
            for size in range(2, min(len(apps), self.config.max_combo_size) + 1):
                for combo in combinations(apps, size):
                    pattern_sessions[tuple(sorted(combo))].append(session)
        patterns = [
            self._create_pattern("cooccurrence", apps, matches, sessions, ordered_steps=apps, temporal_context=None)
            for apps, matches in pattern_sessions.items()
        ]
        return self._rank_and_compress(patterns)

    def _build_temporal_patterns(self, sessions: list[SessionRepresentation]) -> list[WorkflowPattern]:
        grouped: dict[tuple[str, bool, tuple[str, ...]], list[SessionRepresentation]] = defaultdict(list)
        for session in sessions:
            apps = tuple(session.dominant_apps[: self.config.dominant_app_limit])
            if len(apps) < 2:
                continue
            key = (session.temporal_context.period, session.temporal_context.weekday, tuple(sorted(apps)))
            grouped[key].append(session)
        patterns = []
        for (period, weekday, apps), matches in grouped.items():
            context = matches[-1].temporal_context
            metadata = {
                "period_cluster": period,
                "weekday": weekday,
            }
            patterns.append(
                self._create_pattern(
                    "temporal",
                    apps,
                    matches,
                    sessions,
                    ordered_steps=apps,
                    temporal_context=context,
                    metadata=metadata,
                )
            )
        return self._rank_and_compress(patterns)

    def _build_sequence_patterns(self, sessions: list[SessionRepresentation]) -> list[WorkflowPattern]:
        raw_sequences = self._load_sequence_windows()
        if not raw_sequences:
            return []
        clusters: list[dict[str, Any]] = []
        for sequence in raw_sequences:
            canonical = self.pattern_similarity.normalize(sequence["apps"])
            matched_cluster = None
            for cluster in clusters:
                similarity = self.pattern_similarity.sequence_similarity(canonical, cluster["canonical"])
                if similarity >= self.config.sequence_similarity_threshold:
                    matched_cluster = cluster
                    break
            if matched_cluster is None:
                clusters.append(
                    {
                        "canonical": canonical,
                        "examples": [sequence],
                    }
                )
            else:
                matched_cluster["examples"].append(sequence)
        patterns = []
        for cluster in clusters:
            matches = self._match_sessions_for_sequence(cluster["canonical"], sessions)
            if not matches:
                continue
            context = matches[-1].temporal_context
            metadata = {
                "cluster_size": len(cluster["examples"]),
                "examples": [example["apps"] for example in cluster["examples"][:3]],
            }
            patterns.append(
                self._create_pattern(
                    "sequence",
                    cluster["canonical"],
                    matches,
                    sessions,
                    ordered_steps=cluster["canonical"],
                    temporal_context=context,
                    metadata=metadata,
                )
            )
        return self._rank_and_compress(patterns)

    def _represent_sessions(self, sessions: list[dict[str, Any]]) -> list[SessionRepresentation]:
        activity_durations = self._load_activity_durations()
        represented = []
        for session in sessions:
            start = session["start"]
            end = session["end"]
            app_durations = self._resolve_session_durations(session, activity_durations)
            app_weights = self._dominant_app_weights(app_durations)
            if len(app_weights) < 1:
                continue
            temporal_context = self.temporal_model.infer_context(start, end)
            ordered_apps = tuple(sorted(app_weights, key=app_weights.get, reverse=True))
            represented.append(
                SessionRepresentation(
                    session_id=session.get("id"),
                    start=start,
                    end=end,
                    app_weights=app_weights,
                    app_durations=app_durations,
                    ordered_apps=ordered_apps,
                    temporal_context=temporal_context,
                    label=session.get("label"),
                )
            )
        return represented

    def _load_activity_durations(self) -> list[dict[str, Any]]:
        self.cursor.execute(
            """
            SELECT app_name, start_time, end_time, duration
            FROM activity_log
            ORDER BY start_time
            """
        )
        entries = []
        for app_name, start_time, end_time, duration in self.cursor.fetchall():
            if is_noise(app_name, duration):
                continue
            entries.append(
                {
                    "app": self.pattern_similarity.synonyms.canonicalize(app_name),
                    "start": datetime.fromisoformat(start_time),
                    "end": datetime.fromisoformat(end_time) if end_time else datetime.fromisoformat(start_time),
                    "duration": float(duration),
                }
            )
        return entries

    def _resolve_session_durations(
        self,
        session: dict[str, Any],
        activity_durations: list[dict[str, Any]],
    ) -> dict[str, float]:
        session_apps = {self.pattern_similarity.synonyms.canonicalize(app) for app in session["apps"]}
        durations: dict[str, float] = defaultdict(float)
        for activity in activity_durations:
            if activity["app"] not in session_apps:
                continue
            if activity["start"] < session["start"] or activity["start"] > session["end"]:
                continue
            durations[activity["app"]] += activity["duration"]
        if durations:
            return dict(durations)
        fallback_weight = max((session["end"] - session["start"]).total_seconds() / max(len(session_apps), 1), 1.0)
        return {app: fallback_weight for app in session_apps}

    def _dominant_app_weights(self, app_durations: dict[str, float]) -> dict[str, float]:
        total = sum(app_durations.values()) or 1.0
        category_counts: dict[str, int] = defaultdict(int)
        for app in app_durations:
            category_counts[categorize_app(app)] += 1
        weighted: dict[str, float] = {}
        for app, duration in app_durations.items():
            share = duration / total
            category = categorize_app(app)
            centrality = 1.0 / max(category_counts[category], 1)
            score = (0.7 * share) + (0.3 * centrality)
            if share >= self.config.min_app_weight or duration >= self.config.min_meaningful_duration_seconds * 4:
                weighted[app] = round(min(score, 1.0), 6)
        ordered = sorted(weighted.items(), key=lambda item: item[1], reverse=True)[: self.config.dominant_app_limit]
        return dict(ordered)

    def _load_sequence_windows(self) -> list[dict[str, Any]]:
        self.cursor.execute(
            """
            SELECT app_name, start_time, duration
            FROM activity_log
            ORDER BY start_time
            """
        )
        logs = [
            (self.pattern_similarity.synonyms.canonicalize(app_name), datetime.fromisoformat(start_time), float(duration))
            for app_name, start_time, duration in self.cursor.fetchall()
            if not is_noise(app_name, duration)
        ]
        windows: list[dict[str, Any]] = []
        for index, (app_name, start_time, _) in enumerate(logs):
            steps = [app_name]
            for next_app, next_time, _ in logs[index + 1 :]:
                if (next_time - start_time).total_seconds() > self.config.sequence_window_seconds:
                    break
                if next_app != steps[-1]:
                    steps.append(next_app)
            canonical = tuple(dict.fromkeys(steps))
            if len(canonical) >= 2:
                windows.append({"apps": canonical, "start": start_time})
        return windows

    def _match_sessions_for_sequence(
        self,
        sequence: tuple[str, ...],
        sessions: list[SessionRepresentation],
    ) -> list[SessionRepresentation]:
        matches = []
        for session in sessions:
            similarity = self.pattern_similarity.sequence_similarity(sequence, session.ordered_apps)
            if similarity >= self.config.sequence_similarity_threshold:
                matches.append(session)
        return matches

    def _create_pattern(
        self,
        pattern_type: str,
        apps: tuple[str, ...],
        matching_sessions: list[SessionRepresentation],
        all_sessions: list[SessionRepresentation],
        ordered_steps: tuple[str, ...],
        temporal_context: Any,
        metadata: dict[str, Any] | None = None,
    ) -> WorkflowPattern:
        matches = sorted(matching_sessions, key=lambda session: session.start)
        score = self.pattern_scorer.score_pattern(matches, all_sessions, apps)
        intent = self.intent_engine.infer(apps, temporal_context)
        recency = self.temporal_model.decay_weight(matches[-1].end) if matches else 0.0
        workflow_metadata = dict(metadata or {})
        workflow_metadata["embedding"] = build_workflow_embedding({app: matches[-1].app_weights.get(app, 0.0) for app in apps})
        workflow_metadata["app_weights"] = matches[-1].app_weights if matches else {}
        workflow_metadata["duration_seconds"] = sum(matches[-1].app_durations.get(app, 0.0) for app in apps) if matches else 0.0
        return WorkflowPattern(
            pattern_type=pattern_type,
            apps=apps,
            ordered_steps=ordered_steps,
            temporal_context=temporal_context,
            semantic_intent=intent,
            score=score,
            frequency=len(matches),
            recency=recency,
            first_seen=matches[0].start,
            last_seen=matches[-1].end,
            metadata=workflow_metadata,
        )

    def _rank_and_compress(self, patterns: list[WorkflowPattern]) -> list[WorkflowPattern]:
        strong_patterns = [pattern for pattern in patterns if pattern.score.final_score > 0.18 and pattern.frequency >= 2]
        compressed = self.compressor.compress(strong_patterns)
        return sorted(compressed, key=lambda pattern: pattern.score.final_score, reverse=True)[: self.config.max_patterns_per_type]

    @staticmethod
    def _parse_apps_used(apps_used: str) -> list[str]:
        try:
            apps = json.loads(apps_used)
            if isinstance(apps, list):
                return apps
        except json.JSONDecodeError:
            pass
        legacy = apps_used.strip("[]")
        if not legacy:
            return []
        return [item.strip().strip("'\"") for item in legacy.split(",") if item.strip()]

    def _ensure_pattern_schema(self) -> None:
        self.cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS patterns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pattern_type TEXT NOT NULL,
                apps_sequence TEXT NOT NULL,
                occurrences INTEGER DEFAULT 1,
                first_seen DATETIME,
                last_seen DATETIME,
                metadata TEXT,
                proposed INTEGER DEFAULT 0,
                accepted INTEGER DEFAULT 0
            )
            """
        )
        existing_columns = {
            row[1]
            for row in self.cursor.execute("PRAGMA table_info(patterns)").fetchall()
        }
        migrations = {
            "score": "ALTER TABLE patterns ADD COLUMN score REAL DEFAULT 0",
            "semantic_intent": "ALTER TABLE patterns ADD COLUMN semantic_intent TEXT",
            "pattern_version": "ALTER TABLE patterns ADD COLUMN pattern_version INTEGER DEFAULT 1",
        }
        for column, sql in migrations.items():
            if column not in existing_columns:
                self.cursor.execute(sql)
        self.db.conn.commit()


if __name__ == "__main__":
    PatternEngine().run()
