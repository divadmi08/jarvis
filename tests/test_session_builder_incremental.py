from __future__ import annotations

import json
import sqlite3
import unittest
from datetime import datetime
from pathlib import Path

from data.database import Database
from session_builder import SESSION_BUILDER_STATE_KEY, SessionBuilder


class SessionBuilderIncrementalTestCase(unittest.TestCase):
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

    def _insert_activity(self, app: str, start: datetime, end: datetime) -> None:
        self.db.save_activity(
            app,
            f"{app} window",
            start.isoformat(),
            end.isoformat(),
            (end - start).total_seconds(),
        )

    def _fetch_sessions(self) -> list[tuple[str, str, str]]:
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("SELECT start_time, end_time, apps_used FROM sessions ORDER BY start_time")
        rows = cur.fetchall()
        conn.close()
        return rows

    def test_initial_sync_builds_all_sessions_and_state(self) -> None:
        self._insert_activity("code.exe", datetime(2026, 5, 26, 9, 0), datetime(2026, 5, 26, 9, 20))
        self._insert_activity("powershell.exe", datetime(2026, 5, 26, 9, 22), datetime(2026, 5, 26, 9, 40))
        self._insert_activity("chrome.exe", datetime(2026, 5, 26, 11, 0), datetime(2026, 5, 26, 11, 20))

        builder = SessionBuilder(self.db_path)
        saved = builder.sync_sessions_incremental()

        self.assertEqual(saved, 2)
        sessions = self._fetch_sessions()
        self.assertEqual(len(sessions), 2)
        self.assertEqual(
            builder.db.get_state(SESSION_BUILDER_STATE_KEY),
            datetime(2026, 5, 26, 11, 20).isoformat(),
        )
        builder.db.conn.close()

    def test_incremental_sync_rebuilds_only_tail_without_duplicates(self) -> None:
        self._insert_activity("code.exe", datetime(2026, 5, 26, 9, 0), datetime(2026, 5, 26, 9, 20))
        self._insert_activity("chrome.exe", datetime(2026, 5, 26, 11, 0), datetime(2026, 5, 26, 11, 20))

        builder = SessionBuilder(self.db_path)
        self.assertEqual(builder.sync_sessions_incremental(), 2)

        self._insert_activity("discord.exe", datetime(2026, 5, 26, 11, 25), datetime(2026, 5, 26, 11, 45))
        self._insert_activity("spotify.exe", datetime(2026, 5, 26, 13, 0), datetime(2026, 5, 26, 13, 20))

        saved = builder.sync_sessions_incremental()

        self.assertEqual(saved, 2)
        sessions = self._fetch_sessions()
        self.assertEqual(len(sessions), 3)
        self.assertEqual(sessions[0][0], datetime(2026, 5, 26, 9, 0).isoformat())

        second_apps = json.loads(sessions[1][2])
        self.assertIn("chrome.exe", second_apps)
        self.assertIn("discord.exe", second_apps)

        self.assertEqual(builder.sync_sessions_incremental(), 0)
        self.assertEqual(len(self._fetch_sessions()), 3)
        builder.db.conn.close()


if __name__ == "__main__":
    unittest.main()
