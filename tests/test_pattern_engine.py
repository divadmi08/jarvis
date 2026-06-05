from __future__ import annotations

import json
import sqlite3
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from core.intent_inference import IntentInferenceEngine
from core.pattern_compression import PatternCompressor
from core.pattern_engine import PatternEngine
from core.pattern_scoring import PatternScorer
from core.pattern_similarity import PatternSimilarity
from core.pattern_types import PatternEngineConfig, PatternScore, SessionRepresentation, TemporalContext, WorkflowPattern
from core.temporal_model import TemporalDecayConfig, TemporalModel


class PatternEngineTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path("tests/.tmp")
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = str(self.temp_dir / f"{self._testMethodName}.db")
        db_file = Path(self.db_path)
        if db_file.exists():
            db_file.unlink()
        self.engine = PatternEngine(
            db_path=self.db_path,
            config=PatternEngineConfig(
                lookback_days=120,
                sequence_window_seconds=900,
                max_patterns_per_type=50,
                sequence_similarity_threshold=0.65,
            ),
        )
        self._seed_data()

    def tearDown(self) -> None:
        self.engine.db.conn.close()
        db_file = Path(self.db_path)
        if db_file.exists():
            db_file.unlink()

    def _seed_data(self) -> None:
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        base = datetime(2026, 5, 26, 9, 0, 0)
        raw_sequences = [
            ("chrome.exe", "vscode", "terminal", "docker"),
            ("brave.exe", "cursor", "powershell.exe", "docker"),
            ("chrome.exe", "chatgpt", "docs", "notion"),
            ("slack", "gmail", "calendar"),
            ("chrome.exe", "vscode", "terminal"),
            ("chrome.exe", "vscode", "terminal", "docker"),
        ]
        for index, sequence in enumerate(raw_sequences):
            start = base - timedelta(days=index * 7)
            apps_used = json.dumps(list(sequence))
            cur.execute(
                "INSERT INTO sessions (start_time, end_time, apps_used, label) VALUES (?, ?, ?, ?)",
                (
                    start.isoformat(),
                    (start + timedelta(minutes=90)).isoformat(),
                    apps_used,
                    "coding",
                ),
            )
            for step_index, app in enumerate(sequence):
                event_start = start + timedelta(minutes=step_index * 5)
                cur.execute(
                    """
                    INSERT INTO activity_log (app_name, window_title, start_time, end_time, duration)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        app,
                        f"{app} window",
                        event_start.isoformat(),
                        (event_start + timedelta(minutes=20)).isoformat(),
                        1200,
                    ),
                )
        conn.commit()
        conn.close()

    def test_temporal_decay_prioritizes_recent_activity(self) -> None:
        model = TemporalModel(TemporalDecayConfig(half_life_days=30, floor=0.05))
        now = datetime(2026, 5, 26, 12, 0, 0)
        today = model.decay_weight(now, now)
        week_old = model.decay_weight(now - timedelta(days=7), now)
        month_old = model.decay_weight(now - timedelta(days=30), now)
        old = model.decay_weight(now - timedelta(days=120), now)
        self.assertGreater(today, week_old)
        self.assertGreater(week_old, month_old)
        self.assertGreaterEqual(old, 0.05)

    def test_sequence_similarity_handles_aliases(self) -> None:
        similarity = PatternSimilarity()
        score = similarity.sequence_similarity(
            ("chrome", "vscode", "terminal"),
            ("brave", "cursor", "powershell.exe"),
        )
        self.assertGreater(score, 0.8)

    def test_pattern_compression_drops_redundant_subset(self) -> None:
        context = TemporalContext("morning", True, 1, 0.9, "long", 9.0)
        larger = WorkflowPattern(
            "cooccurrence",
            ("chrome", "terminal", "vscode"),
            ("chrome", "vscode", "terminal"),
            context,
            None,
            PatternScore(0.5, 0.95, 1.8, 0.8, 0.9, 0.7, 0.88),
            6,
            0.8,
            datetime(2026, 5, 1),
            datetime(2026, 5, 26),
        )
        subset = WorkflowPattern(
            "cooccurrence",
            ("chrome", "vscode"),
            ("chrome", "vscode"),
            context,
            None,
            PatternScore(0.5, 0.7, 1.2, 0.8, 0.9, 0.7, 0.62),
            5,
            0.8,
            datetime(2026, 5, 1),
            datetime(2026, 5, 26),
        )
        compressed = PatternCompressor(0.9).compress([subset, larger])
        self.assertEqual([pattern.apps for pattern in compressed], [larger.apps])

    def test_intent_inference_detects_backend_development(self) -> None:
        context = TemporalContext("morning", True, 1, 0.9, "long", 9.0)
        intent = IntentInferenceEngine().infer(("vscode", "docker", "terminal"), context)
        self.assertIsNotNone(intent)
        assert intent is not None
        self.assertEqual(intent.intent, "backend_development")
        self.assertGreater(intent.confidence, 0.6)

    def test_scoring_system_returns_rankable_score(self) -> None:
        context = TemporalContext("morning", True, 1, 0.9, "long", 9.0)
        sessions = [
            SessionRepresentation(
                session_id=index,
                start=datetime(2026, 5, 1 + index, 9, 0),
                end=datetime(2026, 5, 1 + index, 10, 0),
                app_weights={"vscode": 1.0, "terminal": 0.8},
                app_durations={"vscode": 1800, "terminal": 1200},
                ordered_apps=("vscode", "terminal"),
                temporal_context=context,
                label="coding",
            )
            for index in range(3)
        ]
        scorer = PatternScorer(reference_time=datetime(2026, 5, 26, 12, 0))
        score = scorer.score_pattern(sessions, sessions, ("vscode", "terminal"))
        self.assertGreater(score.final_score, 0.4)
        self.assertGreater(score.lift, 0.9)

    def test_backward_compatibility_preserves_legacy_shape_and_migrates_schema(self) -> None:
        results = self.engine.run()
        self.assertIn("cooccurrence", results)
        self.assertTrue(results["cooccurrence"])
        pattern = results["cooccurrence"][0]
        self.assertIn("type", pattern)
        self.assertIn("apps", pattern)
        self.assertIn("occurrences", pattern)
        self.assertIn("metadata", pattern)
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("PRAGMA table_info(patterns)")
        columns = {row[1] for row in cur.fetchall()}
        self.assertIn("score", columns)
        self.assertIn("semantic_intent", columns)
        cur.execute("SELECT metadata, score FROM patterns LIMIT 1")
        metadata_json, score = cur.fetchone()
        metadata = json.loads(metadata_json)
        self.assertIn("score", metadata)
        self.assertGreaterEqual(score, 0.0)
        conn.close()

    def test_run_consolidates_memory_events_and_reflections(self) -> None:
        self.engine.run()

        memory_events = self.engine.db.fetch_memory_events(limit=10)
        reflections = self.engine.db.fetch_reflections(limit=10)

        self.assertTrue(memory_events)
        self.assertTrue(reflections)
        self.assertTrue(any(row[1] == "session" for row in memory_events))
        self.assertTrue(any(row[1] == "pattern" for row in memory_events))

    def test_llm_intent_fallback_runs_when_rules_are_uncertain(self) -> None:
        class FakeLLMIntentRecognizer:
            def __init__(self) -> None:
                self.calls = []

            def infer(self, apps, context):
                self.calls.append((apps, context))
                return IntentInferenceEngine().infer(("chrome", "notion"), context)

        recognizer = FakeLLMIntentRecognizer()
        engine = PatternEngine(
            db_path=self.db_path,
            config=PatternEngineConfig(),
            llm_intent_recognizer=recognizer,
        )
        context = TemporalContext("evening", True, 1, 0.5, "short", 20.0)

        intent = engine._infer_intent(("unknown_app", "another_app"), context)

        self.assertEqual(len(recognizer.calls), 1)
        self.assertIsNotNone(intent)


if __name__ == "__main__":
    unittest.main()
