from datetime import datetime
from data.database import Database

GAP_MINUTES = 10


# 🧹 APP DI RUMORE (Windows / system / inutili)
NOISE_APPS = {
    "explorer.exe",
    "searchhost.exe",
    "taskmgr.exe",
    "runtimebroker.exe",
    "shellexperiencehost.exe",
    "db browser for sqlite.exe"
}


class SessionBuilder:
    def __init__(self):
        self.db = Database("data/jarvis.db")
        self.cursor = self.db.cursor

    # -------------------------
    # LOAD LOGS
    # -------------------------
    def load_logs(self):
        self.cursor.execute("""
            SELECT app_name, start_time, end_time
            FROM activity_log
            ORDER BY start_time
        """)
        return self.cursor.fetchall()

    # -------------------------
    # CLEAN APP NAME
    # -------------------------
    def clean_app(self, app):
        if not app:
            return "unknown"

        app = app.lower().strip()

        if app in NOISE_APPS:
            return None  # 🔥 elimina completamente

        return app

    # -------------------------
    # BUILD SESSIONS
    # -------------------------
    def build_sessions(self):
        logs = self.load_logs()

        sessions = []
        current = None

        for app, start, end in logs:

            app = self.clean_app(app)
            if not app:
                continue  # skip noise

            start_dt = datetime.fromisoformat(start)
            end_dt = datetime.fromisoformat(end)
            duration = (end_dt - start_dt).total_seconds()

            if current is None:
                current = self._new_session(start_dt, end_dt, app, duration)
                continue

            gap = (start_dt - current["end"]).total_seconds() / 60

            # 🔥 nuova sessione
            if gap > GAP_MINUTES:
                sessions.append(current)
                current = self._new_session(start_dt, end_dt, app, duration)
                continue

            # 🧠 merge sessione
            current["end"] = max(current["end"], end_dt)

            current["apps"][app] = current["apps"].get(app, 0) + duration

        if current:
            sessions.append(current)

        return sessions

    # -------------------------
    # CREATE SESSION
    # -------------------------
    def _new_session(self, start, end, app, duration):
        return {
            "start": start,
            "end": end,
            "apps": {app: duration}
        }

    # -------------------------
    # FOCUS DETECTION
    # -------------------------
    def detect_focus(self, apps):
        apps_lower = [a.lower() for a in apps]

        score = {}

        # 🎮 gaming
        if any("valorant" in a or "steam" in a for a in apps_lower):
            score["gaming"] = 1

        # 💻 coding
        if any("code.exe" in a or "vscode" in a for a in apps_lower):
            score["coding"] = 1

        # 🌐 browsing
        if any("chrome" in a or "opera" in a for a in apps_lower):
            score["browsing"] = 1

        # 🧠 multitasking penalty
        score["multitask_penalty"] = len(apps)

        # 🎯 decide main focus
        focus = max(
            ["gaming", "coding", "browsing"],
            key=lambda k: score.get(k, 0)
        )

        return focus, score

    # -------------------------
    # SAVE
    # -------------------------
    def save_sessions(self, sessions):
        for s in sessions:

            apps_sorted = sorted(
                s["apps"].items(),
                key=lambda x: x[1],
                reverse=True
            )

            apps_used = [a[0] for a in apps_sorted]

            focus, score = self.detect_focus(apps_used)

            self.cursor.execute("""
                INSERT INTO sessions (start_time, end_time, apps_used, label)
                VALUES (?, ?, ?, ?)
            """, (
                s["start"].isoformat(),
                s["end"].isoformat(),
                str(apps_used),
                focus
            ))

        self.db.conn.commit()


# -------------------------
# RUN
# -------------------------
if __name__ == "__main__":
    sb = SessionBuilder()

    sessions = sb.build_sessions()

    sb.save_sessions(sessions)

    print(f"Sessions created: {len(sessions)}")