from __future__ import annotations

import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from core.observer import Observer
from system.permissions import Level, PermissionSystem

try:
    from core.executor import StepStatus, action_run_command
except Exception:  # pragma: no cover - import guard for optional GUI deps
    StepStatus = None
    action_run_command = None


class FakeDatabase:
    def __init__(self) -> None:
        self.saved: list[tuple[str, str, str, str, float]] = []

    def save_activity(self, app_name, window_title, start_time, end_time, duration):
        self.saved.append((app_name, window_title, start_time, end_time, duration))


class ObserverTestCase(unittest.TestCase):
    def test_flush_current_activity_persists_last_window(self) -> None:
        db = FakeDatabase()
        start = datetime(2026, 5, 26, 10, 0, 0)
        end = start + timedelta(minutes=5)
        observer = Observer(db, clock=lambda: end, sleep_fn=lambda _: None)
        observer.current_app = "Code.exe"
        observer.current_title = "jarvis"
        observer.last_switch_time = start

        flushed = observer.flush_current_activity(end)

        self.assertTrue(flushed)
        self.assertEqual(len(db.saved), 1)
        app_name, window_title, start_time, end_time, duration = db.saved[0]
        self.assertEqual(app_name, "Code.exe")
        self.assertEqual(window_title, "jarvis")
        self.assertEqual(start_time, start.isoformat())
        self.assertEqual(end_time, end.isoformat())
        self.assertEqual(duration, 300.0)


class PermissionSystemTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path("tests/.tmp/runtime")
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.memory_path = str(self.temp_dir / f"{self._testMethodName}.json")
        memory_file = Path(self.memory_path)
        if memory_file.exists():
            memory_file.unlink()
        self.permissions = PermissionSystem(memory_path=self.memory_path)

    def tearDown(self) -> None:
        memory_file = Path(self.memory_path)
        if memory_file.exists():
            memory_file.unlink()

    def test_contextual_levels_harden_sensitive_actions(self) -> None:
        self.assertEqual(self.permissions.get_level("type_text", "hello"), Level.MEDIUM)
        self.assertEqual(self.permissions.get_level("click", "10,10"), Level.MEDIUM)
        self.assertEqual(self.permissions.get_level("open_app", "https://example.com"), Level.MEDIUM)
        self.assertEqual(
            self.permissions.get_level("run_command", "Remove-Item C:\\temp\\file.txt -Force"),
            Level.RISKY,
        )

    def test_medium_permission_is_cached_after_first_prompt(self) -> None:
        with patch.object(self.permissions, "_ask_user", return_value=True) as ask_user:
            first = self.permissions.check("type_text", "hello")
            second = self.permissions.check("type_text", "hello")

        self.assertTrue(first.granted)
        self.assertTrue(second.granted)
        self.assertEqual(ask_user.call_count, 1)


@unittest.skipIf(action_run_command is None or StepStatus is None, "executor dependencies unavailable")
class ExecutorCommandTestCase(unittest.TestCase):
    def test_run_command_uses_shell_false_for_simple_commands(self) -> None:
        completed = SimpleNamespace(returncode=0, stderr="", stdout="")
        with patch("core.executor.subprocess.run", return_value=completed) as run_mock:
            result = action_run_command("python -V")

        self.assertEqual(result.status, StepStatus.SUCCESS)
        self.assertFalse(run_mock.call_args.kwargs["shell"])
        self.assertEqual(run_mock.call_args.args[0], ["python", "-V"])

    def test_run_command_requires_explicit_shell_for_shell_operators(self) -> None:
        with patch("core.executor.subprocess.run") as run_mock:
            result = action_run_command("echo hi && echo bye")

        self.assertEqual(result.status, StepStatus.FAILED)
        self.assertIn("use_shell", result.message)
        run_mock.assert_not_called()

    def test_run_command_allows_explicit_shell_opt_in(self) -> None:
        completed = SimpleNamespace(returncode=0, stderr="", stdout="")
        with patch("core.executor.subprocess.run", return_value=completed) as run_mock:
            result = action_run_command("echo hi && echo bye", use_shell=True)

        self.assertEqual(result.status, StepStatus.SUCCESS)
        self.assertTrue(run_mock.call_args.kwargs["shell"])
        self.assertEqual(run_mock.call_args.args[0], "echo hi && echo bye")


if __name__ == "__main__":
    unittest.main()
