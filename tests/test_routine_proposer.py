from __future__ import annotations

import json
import sqlite3
import unittest
from pathlib import Path
from unittest.mock import patch

from core.ai_client import AIClient, GeminiAIClient
from core.app_registry import normalize_app_name
from core.routine_proposal_service import RoutineProposalService
from core.routine_proposal_types import RoutineProposalValidationError
from core.routine_proposer import RoutineProposer
from data.database import Database


class StubAIClient(AIClient):
    def __init__(self, responses: list[str]) -> None:
        self.responses = list(responses)
        self.prompts: list[str] = []

    def generate_text(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if not self.responses:
            raise AssertionError("No stub response configured")
        return self.responses.pop(0)


class RetryBackend:
    def __init__(self, responses: list[object]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, object]] = []

    def generate(self, api_key: str, model: str, prompt: str, timeout_seconds: float) -> str:
        self.calls.append(
            {
                "api_key": api_key,
                "model": model,
                "prompt": prompt,
                "timeout_seconds": timeout_seconds,
            }
        )
        result = self.responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return str(result)


class FakeGenAIModels:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)

        class Response:
            text = '{"ok": true}'

        return Response()


class FakeGenAIClient:
    def __init__(self, api_key: str) -> None:
        self.api_key = api_key
        self.models = FakeGenAIModels()


class FakeGenAIModule:
    def __init__(self) -> None:
        self.created_clients: list[FakeGenAIClient] = []

    def Client(self, api_key: str) -> FakeGenAIClient:
        client = FakeGenAIClient(api_key=api_key)
        self.created_clients.append(client)
        return client


class RoutineProposerTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path("tests/.tmp")
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = str(self.temp_dir / f"{self._testMethodName}.db")
        db_file = Path(self.db_path)
        if db_file.exists():
            db_file.unlink()
        self.db = Database(self.db_path)
        self._seed_patterns()

    def tearDown(self) -> None:
        self.db.conn.close()
        db_file = Path(self.db_path)
        if db_file.exists():
            db_file.unlink()

    def _seed_patterns(self) -> None:
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        metadata = json.dumps(
            {
                "ordered_steps": ["discord", "opera"],
                "recency": 0.8,
                "score": {"final_score": 0.91},
                "app_weights": {"discord": 0.5, "opera": 0.5},
            }
        )
        cur.execute(
            """
            INSERT INTO patterns
            (pattern_type, apps_sequence, occurrences, first_seen, last_seen, metadata,
             proposed, accepted, score, semantic_intent, pattern_version)
            VALUES (?, ?, ?, ?, ?, ?, 0, 0, ?, ?, ?)
            """,
            (
                "cooccurrence",
                json.dumps(["discord", "opera"]),
                6,
                "2026-05-20T09:00:00",
                "2026-05-26T09:00:00",
                metadata,
                0.91,
                "communication",
                2,
            ),
        )
        cur.execute(
            """
            INSERT INTO patterns
            (pattern_type, apps_sequence, occurrences, first_seen, last_seen, metadata,
             proposed, accepted, score, semantic_intent, pattern_version)
            VALUES (?, ?, ?, ?, ?, ?, 1, 0, ?, ?, ?)
            """,
            (
                "cooccurrence",
                json.dumps(["slack", "notion"]),
                4,
                "2026-05-20T09:00:00",
                "2026-05-26T09:00:00",
                metadata,
                0.72,
                "coordination",
                2,
            ),
        )
        conn.commit()
        conn.close()

    def _build_proposer(self, responses: list[str]) -> tuple[RoutineProposer, StubAIClient]:
        ai_client = StubAIClient(responses)
        return RoutineProposer(db=self.db, ai_client=ai_client), ai_client

    def test_parsing_and_validation_accepts_valid_json(self) -> None:
        proposer, _ = self._build_proposer(
            [
                json.dumps(
                    {
                        "should_propose": True,
                        "source_pattern": {"type": "cooccurrence", "apps": ["discord", "opera"]},
                        "proposal": {
                            "name": "Social Browsing Setup",
                            "description": "Open Discord and Opera for communication and light browsing.",
                            "steps": [
                                {"action": "open_app", "target": "discord"},
                                {"action": "open_app", "target": "opera.exe"},
                                {"action": "sleep", "target": "2"},
                                {"action": "focus_window", "target": "opera"},
                            ],
                            "confidence": 0.78,
                            "reasoning": "This pattern is frequent and recent.",
                        },
                    }
                )
            ]
        )
        candidate = proposer.find_candidate_patterns(limit=5)[0]

        decision = proposer.generate_proposal_for_pattern(candidate)

        self.assertTrue(decision.should_propose)
        assert decision.proposal is not None
        self.assertEqual(decision.proposal.name, "Social Browsing Setup")
        self.assertEqual([step.target for step in decision.proposal.steps[:2]], ["discord", "opera"])

    def test_normalize_app_name_accepts_exe_and_path_variants(self) -> None:
        self.assertEqual(normalize_app_name("discord.exe"), "discord")
        self.assertEqual(normalize_app_name("C:/Users/test/AppData/Local/Programs/Opera/opera.exe"), "opera")
        self.assertEqual(normalize_app_name("Code"), "visual studio code")

    def test_rejects_malformed_json(self) -> None:
        proposer, _ = self._build_proposer(['{"should_propose": true'])
        candidate = proposer.find_candidate_patterns(limit=5)[0]

        with self.assertRaises(RoutineProposalValidationError):
            proposer.generate_proposal_for_pattern(candidate)

    def test_rejects_non_allowlisted_action(self) -> None:
        proposer, _ = self._build_proposer(
            [
                json.dumps(
                    {
                        "should_propose": True,
                        "source_pattern": {"type": "cooccurrence", "apps": ["discord", "opera"]},
                        "proposal": {
                            "name": "Unsafe Proposal",
                            "description": "Should be rejected.",
                            "steps": [{"action": "run_command", "target": "dir"}],
                            "confidence": 0.6,
                            "reasoning": "Rejected by policy.",
                        },
                    }
                )
            ]
        )
        candidate = proposer.find_candidate_patterns(limit=5)[0]

        with self.assertRaises(RoutineProposalValidationError):
            proposer.generate_proposal_for_pattern(candidate)

    def test_rejects_confidence_out_of_range(self) -> None:
        proposer, _ = self._build_proposer(
            [
                json.dumps(
                    {
                        "should_propose": True,
                        "source_pattern": {"type": "cooccurrence", "apps": ["discord", "opera"]},
                        "proposal": {
                            "name": "Too Sure",
                            "description": "Confidence is invalid.",
                            "steps": [{"action": "open_app", "target": "discord"}],
                            "confidence": 1.2,
                            "reasoning": "Invalid confidence.",
                        },
                    }
                )
            ]
        )
        candidate = proposer.find_candidate_patterns(limit=5)[0]

        with self.assertRaises(RoutineProposalValidationError):
            proposer.generate_proposal_for_pattern(candidate)

    def test_saves_proposal_in_database(self) -> None:
        proposer, _ = self._build_proposer(
            [
                json.dumps(
                    {
                        "should_propose": True,
                        "source_pattern": {"type": "cooccurrence", "apps": ["discord", "opera"]},
                        "proposal": {
                            "name": "Social Browsing Setup",
                            "description": "Open Discord and Opera for communication and light browsing.",
                            "steps": [
                                {"action": "open_app", "target": "discord"},
                                {"action": "open_app", "target": "opera"},
                            ],
                            "confidence": 0.78,
                            "reasoning": "This pattern is frequent and recent.",
                        },
                    }
                )
            ]
        )
        service = RoutineProposalService(db=self.db, proposer=proposer)
        candidate = proposer.find_candidate_patterns(limit=5)[0]

        result = service.propose_for_pattern(candidate.pattern_id)

        self.assertEqual(result.status, "created")
        proposals = self.db.fetch_routine_proposals(candidate.pattern_id)
        self.assertEqual(len(proposals), 1)
        self.assertEqual(proposals[0][2], "Social Browsing Setup")
        pattern_row = self.db.get_pattern_by_id(candidate.pattern_id)
        assert pattern_row is not None
        self.assertEqual(pattern_row[7], 1)

    def test_skips_patterns_already_proposed(self) -> None:
        proposer, _ = self._build_proposer([])
        service = RoutineProposalService(db=self.db, proposer=proposer)

        candidates = service.find_candidate_patterns(limit=10)

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].apps, ("discord", "opera"))

    def test_handles_should_propose_false_without_saving(self) -> None:
        proposer, _ = self._build_proposer(
            [
                json.dumps(
                    {
                        "should_propose": False,
                        "reason": "Pattern too ambiguous.",
                    }
                )
            ]
        )
        service = RoutineProposalService(db=self.db, proposer=proposer)
        candidate = proposer.find_candidate_patterns(limit=5)[0]

        result = service.propose_for_pattern(candidate.pattern_id)

        self.assertEqual(result.status, "skipped")
        self.assertEqual(result.reason, "Pattern too ambiguous.")
        self.assertEqual(self.db.fetch_routine_proposals(candidate.pattern_id), [])

    def test_skips_unmanaged_apps_before_calling_model(self) -> None:
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        metadata = json.dumps(
            {
                "ordered_steps": ["valorant-win64-shipping", "discord"],
                "recency": 0.8,
                "score": {"final_score": 0.88},
            }
        )
        cur.execute(
            """
            INSERT INTO patterns
            (pattern_type, apps_sequence, occurrences, first_seen, last_seen, metadata,
             proposed, accepted, score, semantic_intent, pattern_version)
            VALUES (?, ?, ?, ?, ?, ?, 0, 0, ?, ?, ?)
            """,
            (
                "sequence",
                json.dumps(["valorant-win64-shipping", "discord"]),
                5,
                "2026-05-20T09:00:00",
                "2026-05-26T09:00:00",
                metadata,
                0.88,
                "gaming",
                2,
            ),
        )
        pattern_id = cur.lastrowid
        conn.commit()
        conn.close()

        proposer, ai_client = self._build_proposer(
            [
                json.dumps(
                    {
                        "should_propose": True,
                        "source_pattern": {
                            "type": "sequence",
                            "apps": ["valorant-win64-shipping", "discord"],
                        },
                        "proposal": {
                            "name": "Should Not Be Used",
                            "description": "Model should never be called for unmanaged apps.",
                            "steps": [{"action": "open_app", "target": "discord"}],
                            "confidence": 0.5,
                            "reasoning": "Not expected.",
                        },
                    }
                )
            ]
        )
        service = RoutineProposalService(db=self.db, proposer=proposer)

        result = service.propose_for_pattern(pattern_id)

        self.assertEqual(result.status, "skipped")
        self.assertIn("unmanaged app targets", result.reason or "")
        self.assertEqual(ai_client.prompts, [])

    def test_gemini_client_retries_transient_timeout(self) -> None:
        stub_backend = RetryBackend([TimeoutError("ssl handshake timed out"), '{"ok": true}'])
        with patch.object(GeminiAIClient, "_load_backend", return_value=stub_backend):
            client = GeminiAIClient(api_key="test-key", max_attempts=2, retry_delay_seconds=0)

        response = client.generate_text("hello")

        self.assertEqual(response, '{"ok": true}')
        assert isinstance(client._backend, RetryBackend)
        self.assertEqual(len(client._backend.calls), 2)

    def test_google_genai_backend_uses_timeout_milliseconds_via_module(self) -> None:
        from core.ai_client import _GoogleGenAIBackend

        fake_module = FakeGenAIModule()
        backend = _GoogleGenAIBackend(fake_module)

        response = backend.generate(
            api_key="test-key",
            model="gemini-2.5-flash-lite",
            prompt="hello",
            timeout_seconds=20.0,
        )

        self.assertEqual(response, '{"ok": true}')
        self.assertEqual(len(fake_module.created_clients), 1)
        generate_call = fake_module.created_clients[0].models.calls[0]
        self.assertEqual(generate_call["config"]["http_options"]["timeout"], 20000)


if __name__ == "__main__":
    unittest.main()
