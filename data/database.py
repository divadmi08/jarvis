import sqlite3
from pathlib import Path

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
