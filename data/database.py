import sqlite3
from pathlib import Path
from typing import Any


class Database:
    def __init__(self, db_path="data/jarvis.db"):
        db_file = Path(db_path)
        if db_file.parent:
            db_file.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(db_path, timeout=30)
        self.cursor = self.conn.cursor()
        self._configure_connection()
        self._create_tables()

    def _configure_connection(self):
        self.cursor.execute("PRAGMA journal_mode=WAL")
        self.cursor.execute("PRAGMA synchronous=NORMAL")

    def _create_tables(self):
        # Day 1–5 log
        self.cursor.execute("""
        CREATE TABLE IF NOT EXISTS activity_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            app_name TEXT,
            window_title TEXT,
            start_time TEXT,
            end_time TEXT,
            duration INTEGER
        )
        """)

        # Day 9+ sessions
        self.cursor.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            start_time TEXT,
            end_time TEXT,
            apps_used TEXT,
            label TEXT
        )
        """)

        self.cursor.execute("""
        CREATE TABLE IF NOT EXISTS patterns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pattern_type TEXT NOT NULL,
            apps_sequence TEXT NOT NULL,
            occurrences INTEGER DEFAULT 1,
            first_seen DATETIME,
            last_seen DATETIME,
            metadata TEXT,
            proposed INTEGER DEFAULT 0,
            accepted INTEGER DEFAULT 0,
            score REAL DEFAULT 0,
            semantic_intent TEXT,
            pattern_version INTEGER DEFAULT 1
        )
        """)

        self.cursor.execute("""
        CREATE TABLE IF NOT EXISTS system_state (
            key TEXT PRIMARY KEY,
            value TEXT
        )
        """)

        self.cursor.execute("""
        CREATE TABLE IF NOT EXISTS routine_proposals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pattern_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            description TEXT NOT NULL,
            steps_json TEXT NOT NULL,
            confidence REAL NOT NULL,
            reasoning TEXT NOT NULL,
            source_pattern_json TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(pattern_id) REFERENCES patterns(id)
        )
        """)

        existing_pattern_columns = {
            row[1]
            for row in self.cursor.execute("PRAGMA table_info(patterns)").fetchall()
        }
        for column, ddl in {
            "score": "ALTER TABLE patterns ADD COLUMN score REAL DEFAULT 0",
            "semantic_intent": "ALTER TABLE patterns ADD COLUMN semantic_intent TEXT",
            "pattern_version": "ALTER TABLE patterns ADD COLUMN pattern_version INTEGER DEFAULT 1",
        }.items():
            if column not in existing_pattern_columns:
                self.cursor.execute(ddl)

        self.cursor.execute("CREATE INDEX IF NOT EXISTS idx_activity_log_start_time ON activity_log(start_time)")
        self.cursor.execute("CREATE INDEX IF NOT EXISTS idx_activity_log_end_time ON activity_log(end_time)")
        self.cursor.execute("CREATE INDEX IF NOT EXISTS idx_sessions_start_time ON sessions(start_time)")
        self.cursor.execute("CREATE INDEX IF NOT EXISTS idx_patterns_type_score ON patterns(pattern_type, score DESC)")
        self.cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_patterns_identity ON patterns(pattern_type, apps_sequence)")
        self.cursor.execute("CREATE INDEX IF NOT EXISTS idx_routine_proposals_pattern_status ON routine_proposals(pattern_id, status)")

        self.conn.commit()

    # DAY 1–5
    def save_activity(self, app_name, window_title, start_time, end_time, duration):
        try:
            self.cursor.execute("""
            INSERT INTO activity_log
            (app_name, window_title, start_time, end_time, duration)
            VALUES (?, ?, ?, ?, ?)
            """, (
                app_name,
                window_title,
                start_time,
                end_time,
                int(duration)
            ))
            self.conn.commit()
        except Exception as e:
            print("DB ERROR:", e)

    # DAY 10+
    def save_session(self, start_time, end_time, apps_used, label):
        self.cursor.execute("""
        INSERT INTO sessions
        (start_time, end_time, apps_used, label)
        VALUES (?, ?, ?, ?)
        """, (
            start_time,
            end_time,
            str(apps_used),
            label
        ))
        self.conn.commit()

    def fetch_logs(self):
        self.cursor.execute("SELECT * FROM activity_log ORDER BY start_time")
        return self.cursor.fetchall()

    def get_state(self, key: str, default=None):
        self.cursor.execute("SELECT value FROM system_state WHERE key = ?", (key,))
        row = self.cursor.fetchone()
        return row[0] if row else default

    def set_state(self, key: str, value: str) -> None:
        self.cursor.execute(
            """
            INSERT INTO system_state (key, value)
            VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (key, value),
        )
        self.conn.commit()

    def get_pattern_by_id(self, pattern_id: int) -> tuple[Any, ...] | None:
        self.cursor.execute(
            """
            SELECT id, pattern_type, apps_sequence, occurrences, first_seen, last_seen,
                   metadata, proposed, accepted, score, semantic_intent, pattern_version
            FROM patterns
            WHERE id = ?
            """,
            (pattern_id,),
        )
        return self.cursor.fetchone()

    def fetch_candidate_patterns(
        self,
        limit: int = 10,
        allowed_types: tuple[str, ...] = ("cooccurrence", "sequence"),
        min_score: float = 0.3,
    ) -> list[tuple[Any, ...]]:
        placeholders = ",".join("?" for _ in allowed_types)
        params: list[Any] = [*allowed_types, min_score, limit]
        self.cursor.execute(
            f"""
            SELECT p.id, p.pattern_type, p.apps_sequence, p.occurrences, p.first_seen, p.last_seen,
                   p.metadata, p.proposed, p.accepted, p.score, p.semantic_intent, p.pattern_version
            FROM patterns p
            WHERE p.pattern_type IN ({placeholders})
              AND p.accepted = 0
              AND COALESCE(p.score, 0) >= ?
              AND NOT EXISTS (
                  SELECT 1
                  FROM routine_proposals rp
                  WHERE rp.pattern_id = p.id
                    AND rp.status IN ('pending', 'accepted')
              )
            ORDER BY COALESCE(p.score, 0) DESC, p.occurrences DESC, p.last_seen DESC
            LIMIT ?
            """,
            params,
        )
        return self.cursor.fetchall()

    def has_active_routine_proposal(self, pattern_id: int) -> bool:
        self.cursor.execute(
            """
            SELECT 1
            FROM routine_proposals
            WHERE pattern_id = ?
              AND status IN ('pending', 'accepted')
            LIMIT 1
            """,
            (pattern_id,),
        )
        return self.cursor.fetchone() is not None

    def save_routine_proposal(
        self,
        pattern_id: int,
        name: str,
        description: str,
        steps_json: str,
        confidence: float,
        reasoning: str,
        source_pattern_json: str,
        status: str = "pending",
    ) -> int:
        self.cursor.execute(
            """
            INSERT INTO routine_proposals
            (pattern_id, name, description, steps_json, confidence, reasoning, source_pattern_json, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """,
            (
                pattern_id,
                name,
                description,
                steps_json,
                confidence,
                reasoning,
                source_pattern_json,
                status,
            ),
        )
        self.cursor.execute(
            """
            UPDATE patterns
            SET proposed = 1
            WHERE id = ?
            """,
            (pattern_id,),
        )
        self.conn.commit()
        return int(self.cursor.lastrowid)

    def fetch_routine_proposals(self, pattern_id: int | None = None) -> list[tuple[Any, ...]]:
        if pattern_id is None:
            self.cursor.execute(
                """
                SELECT id, pattern_id, name, description, steps_json, confidence, reasoning,
                       source_pattern_json, status, created_at, updated_at
                FROM routine_proposals
                ORDER BY created_at DESC, id DESC
                """
            )
            return self.cursor.fetchall()
        self.cursor.execute(
            """
            SELECT id, pattern_id, name, description, steps_json, confidence, reasoning,
                   source_pattern_json, status, created_at, updated_at
            FROM routine_proposals
            WHERE pattern_id = ?
            ORDER BY created_at DESC, id DESC
            """,
            (pattern_id,),
        )
        return self.cursor.fetchall()
