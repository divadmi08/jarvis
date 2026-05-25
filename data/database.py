import sqlite3

class Database:
    def __init__(self, db_path="data/jarvis.db"):
        self.conn = sqlite3.connect(db_path)
        self.cursor = self.conn.cursor()
        self._create_tables()

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