"""
session_builder.py — Jarvis v2

Miglioramenti rispetto alla versione originale:
- Noise filtering basato su durata minima (non solo blacklist)
- Focus detection pesata sul tempo reale (non conteggio app)
- Categorie app estese: coding, gaming, browsing, communication, media, office, system
- Sessioni con metadati più ricchi (durata totale, app dominante, distribuzione categorie)
"""

import sys
import os
from datetime import datetime

# Aggiunge la root del progetto al path così "data.database" è trovabile
# sia lanciando da root che da sottocartelle
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from data.database import Database

# ── Configurazione ────────────────────────────────────────────────────────────

GAP_MINUTES = 10          # gap inattività → nuova sessione
MIN_APP_DURATION = 15     # secondi minimi per considerare un'app (filtra click accidentali)
MIN_SESSION_DURATION = 60 # secondi minimi per salvare una sessione (filtra sessioni fantasma)
MIN_APP_SHARE = 0.02      # % minima del tempo sessione per considerare un'app (filtra rumore)

# ── Mappa categoria → processi riconosciuti ───────────────────────────────────
# Ordine: più specifico prima. Match su sottostringa lowercase del nome processo.

CATEGORY_MAP = {
    "coding": [
        "code.exe", "code - insiders.exe", "idea64.exe", "idea.exe",
        "pycharm64.exe", "pycharm.exe", "webstorm64.exe", "clion64.exe",
        "rider64.exe", "devenv.exe",          # Visual Studio
        "sublime_text.exe", "notepad++.exe",
        "vim.exe", "nvim.exe", "emacs.exe",
        "windowsterminal.exe", "cmd.exe", "powershell.exe", "wt.exe",
        "git-bash.exe", "bash.exe",
        "docker desktop.exe", "postman.exe", "insomnia.exe",
    ],
    "gaming": [
        "valorant.exe", "valorant-win64-shipping.exe",
        "steam.exe", "steamwebhelper.exe",
        "epicgameslauncher.exe", "gog galaxy.exe",
        "minecraft.exe", "javaw.exe",
        "leagueclient.exe", "league of legends.exe",
        "csgo.exe", "cs2.exe",
        "overwatch.exe", "battlenet.exe",
    ],
    "browsing": [
        "chrome.exe", "msedge.exe", "firefox.exe",
        "opera.exe", "operagx.exe", "brave.exe", "vivaldi.exe",
    ],
    "communication": [
        "discord.exe", "slack.exe", "teams.exe", "msteams.exe",
        "outlook.exe", "thunderbird.exe",
        "telegram.exe", "whatsapp.exe", "signal.exe",
        "zoom.exe", "webex.exe", "skype.exe",
    ],
    "media": [
        "spotify.exe", "vlc.exe", "mpv.exe",
        "obs64.exe", "obs32.exe",
        "foobar2000.exe", "winamp.exe",
        "dav vinci resolve.exe", "premiere pro.exe", "afterfx.exe",
        "photoshop.exe", "illustrator.exe", "figma.exe",
        "audacity.exe",
    ],
    "office": [
        "winword.exe", "excel.exe", "powerpnt.exe",
        "onenote.exe", "teams.exe",
        "acrobat.exe", "acrord32.exe",
        "notion.exe", "obsidian.exe",
        "wordpad.exe", "notepad.exe",
    ],
    "system": [
        "explorer.exe", "searchhost.exe", "taskmgr.exe",
        "runtimebroker.exe", "shellexperiencehost.exe",
        "startmenuexperiencehost.exe", "lockapp.exe",
        "dwm.exe", "svchost.exe", "lsass.exe",
        "db browser for sqlite.exe", "regedit.exe",
        "mmc.exe", "services.exe",
    ],
}

# Costruiamo la lookup inversa: processo → categoria
_PROCESS_TO_CATEGORY: dict[str, str] = {}
for _cat, _processes in CATEGORY_MAP.items():
    for _proc in _processes:
        _PROCESS_TO_CATEGORY[_proc] = _cat


# ── Helpers ───────────────────────────────────────────────────────────────────

def categorize_app(app: str) -> str:
    """Restituisce la categoria di un processo. Fallback: 'other'."""
    if not app:
        return "other"
    app_lower = app.lower().strip()
    # match esatto
    if app_lower in _PROCESS_TO_CATEGORY:
        return _PROCESS_TO_CATEGORY[app_lower]
    # match per sottostringa (es. "chrome" dentro "chrome.exe (sandbox)")
    for proc, cat in _PROCESS_TO_CATEGORY.items():
        if proc.replace(".exe", "") in app_lower:
            return cat
    return "other"


def is_noise(app: str, duration: float) -> bool:
    """True se l'attività è troppo breve o è un processo di sistema puro."""
    if duration < MIN_APP_DURATION:
        return True
    if categorize_app(app) == "system":
        return True
    return False


# ── SessionBuilder ────────────────────────────────────────────────────────────

class SessionBuilder:
    def __init__(self, db_path: str = "data/jarvis.db"):
        self.db = Database(db_path)
        self.cursor = self.db.cursor

    # ── Load ──────────────────────────────────────────────────────────────────

    def load_logs(self) -> list[tuple]:
        self.cursor.execute("""
            SELECT app_name, window_title, start_time, end_time, duration
            FROM activity_log
            ORDER BY start_time
        """)
        return self.cursor.fetchall()

    # ── Build ─────────────────────────────────────────────────────────────────

    def build_sessions(self) -> list[dict]:
        """
        Raggruppa i log in sessioni.
        Ogni sessione contiene:
        - start, end (datetime)
        - apps: {app_name: seconds}         → usato per calcoli interni
        - categories: {category: seconds}   → distribuzione per focus
        """
        logs = self.load_logs()
        sessions: list[dict] = []
        current: dict | None = None

        for app, title, start_str, end_str, duration in logs:

            # ── Filtro noise ──────────────────────────────────────────────────
            if is_noise(app, duration):
                continue

            start_dt = datetime.fromisoformat(start_str)
            end_dt   = datetime.fromisoformat(end_str)
            category = categorize_app(app)

            # Prima attività
            if current is None:
                current = self._new_session(start_dt, end_dt, app, title, duration, category)
                continue

            gap_minutes = (start_dt - current["end"]).total_seconds() / 60

            # Gap > soglia → chiudi sessione corrente, aprine una nuova
            if gap_minutes > GAP_MINUTES:
                finalized = self._finalize(current)
                if finalized:
                    sessions.append(finalized)
                current = self._new_session(start_dt, end_dt, app, title, duration, category)
                continue

            # Merge nella sessione corrente
            current["end"] = max(current["end"], end_dt)
            current["apps"][app]         = current["apps"].get(app, 0)         + duration
            current["categories"][category] = current["categories"].get(category, 0) + duration

        # Ultima sessione aperta
        if current:
            finalized = self._finalize(current)
            if finalized:
                sessions.append(finalized)

        return sessions

    # ── Finalize ──────────────────────────────────────────────────────────────

    def _finalize(self, session: dict) -> dict | None:
        """
        Pulisce una sessione prima di salvarla:
        - scarta sessioni troppo brevi
        - rimuove app con share < MIN_APP_SHARE
        - calcola focus pesato sul tempo
        - aggiunge metadati (durata totale, app dominante)
        """
        total_sec = (session["end"] - session["start"]).total_seconds()

        if total_sec < MIN_SESSION_DURATION:
            return None

        # Filtra app minoritarie (< 2% del tempo sessione)
        session["apps"] = {
            app: sec
            for app, sec in session["apps"].items()
            if sec / total_sec >= MIN_APP_SHARE
        }

        if not session["apps"]:
            return None

        # Ricalcola categorie dopo il filtro app
        session["categories"] = {}
        for app, sec in session["apps"].items():
            cat = categorize_app(app)
            session["categories"][cat] = session["categories"].get(cat, 0) + sec

        # Focus = categoria con più secondi (escluso "other" se ci sono alternative)
        cat_without_other = {k: v for k, v in session["categories"].items() if k != "other"}
        focus_source = cat_without_other if cat_without_other else session["categories"]
        focus = max(focus_source, key=focus_source.get)

        # App dominante (più tempo in assoluto)
        dominant_app = max(session["apps"], key=session["apps"].get)

        session["total_sec"]     = total_sec
        session["focus"]         = focus
        session["dominant_app"]  = dominant_app

        return session

    # ── New session ───────────────────────────────────────────────────────────

    def _new_session(self, start, end, app, title, duration, category) -> dict:
        return {
            "start":      start,
            "end":        end,
            "apps":       {app: duration},
            "categories": {category: duration},
        }

    # ── Save ──────────────────────────────────────────────────────────────────

    def save_sessions(self, sessions: list[dict]) -> int:
        """Salva le sessioni nel DB. Restituisce il numero di sessioni salvate."""
        import json

        saved = 0
        for s in sessions:
            # Apps ordinate per tempo decrescente
            apps_sorted = sorted(s["apps"].items(), key=lambda x: x[1], reverse=True)
            apps_list   = [a[0] for a in apps_sorted]

            self.cursor.execute("""
                INSERT INTO sessions (start_time, end_time, apps_used, label)
                VALUES (?, ?, ?, ?)
            """, (
                s["start"].isoformat(),
                s["end"].isoformat(),
                json.dumps(apps_list),
                s["focus"],
            ))
            saved += 1

        self.db.conn.commit()
        return saved

    # ── Debug print ───────────────────────────────────────────────────────────

    def print_sessions(self, sessions: list[dict]) -> None:
        for i, s in enumerate(sessions, 1):
            total_min = s.get("total_sec", 0) / 60
            cats = ", ".join(
                f"{k}={round(v/60)}m"
                for k, v in sorted(s["categories"].items(), key=lambda x: x[1], reverse=True)
            )
            print(f"\n[{i}] {s['start'].strftime('%H:%M')} → {s['end'].strftime('%H:%M')} "
                  f"({round(total_min)}m) | focus={s['focus']} | dominant={s['dominant_app']}")
            print(f"     categorie: {cats}")
            apps_sorted = sorted(s["apps"].items(), key=lambda x: x[1], reverse=True)
            for app, sec in apps_sorted[:5]:
                print(f"       {app:<40} {round(sec/60, 1)}m")


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    sb = SessionBuilder()
    sessions = sb.build_sessions()
    sb.print_sessions(sessions)
    saved = sb.save_sessions(sessions)
    print(f"\nSessioni salvate: {saved}")