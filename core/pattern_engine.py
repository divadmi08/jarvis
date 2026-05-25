"""
pattern_engine.py — Jarvis v2

Tre livelli di pattern, dal più semplice al più utile per l'AI:

1. CO-OCCURRENCE  — quali app apri sempre insieme (base per routine)
2. TEMPORAL       — a che ora del giorno usi certi set di app (base per trigger automatici)
3. SEQUENCE       — in che ordine apri le app (base per riprodurre esattamente il workflow)

Ogni pattern viene salvato nella tabella `patterns` con:
- tipo, app coinvolte, occorrenze, prima/ultima volta visto
- flag `proposed` e `accepted` per il loop di approvazione utente
"""

import json
import sqlite3
import sys
import os
from collections import defaultdict
from datetime import datetime, timedelta
from itertools import combinations

# Aggiunge la root del progetto al path così "data.database" è trovabile
# sia lanciando da core/ che dalla root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from data.database import Database
from session_builder import is_noise, MIN_APP_DURATION

# ── Configurazione ────────────────────────────────────────────────────────────

MIN_OCCURRENCES     = 5     # quante volte un pattern deve comparire per essere candidato
LOOKBACK_DAYS       = 30    # quanti giorni di storia analizzare
MAX_COMBO_SIZE      = 4     # dimensione massima combinazione di app (co-occurrence)
TEMPORAL_SLOT_HOURS = 1     # granularità slot orari (1 = ogni ora, 2 = ogni 2 ore, ecc.)
SEQUENCE_WINDOW_SEC = 300   # finestra (secondi) entro cui le app devono aprirsi in sequenza


# ── PatternEngine ─────────────────────────────────────────────────────────────

class PatternEngine:
    def __init__(self, db_path: str = "data/jarvis.db"):
        self.db   = Database(db_path)
        self.cursor = self.db.cursor

    # ── Load sessioni ─────────────────────────────────────────────────────────

    def load_sessions(self, days: int = LOOKBACK_DAYS) -> list[dict]:
        """
        Carica le sessioni degli ultimi N giorni.
        Restituisce lista di dict con start, end, apps (lista ordinata per uso).
        """
        since = (datetime.now() - timedelta(days=days)).isoformat()

        self.cursor.execute("""
            SELECT id, start_time, end_time, apps_used, label
            FROM sessions
            WHERE start_time >= ?
            ORDER BY start_time
        """, (since,))

        sessions = []
        for row in self.cursor.fetchall():
            sid, start, end, apps_json, label = row
            try:
                apps = json.loads(apps_json)
            except Exception:
                # fallback per il vecchio formato stringa
                apps = apps_json.strip("[]").replace("'", "").split(", ")
                apps = [a.strip() for a in apps if a.strip()]

            sessions.append({
                "id":    sid,
                "start": datetime.fromisoformat(start),
                "end":   datetime.fromisoformat(end),
                "apps":  apps,
                "label": label,
            })

        return sessions

    # ──────────────────────────────────────────────────────────────────────────
    # 1. CO-OCCURRENCE PATTERNS
    # ──────────────────────────────────────────────────────────────────────────
    # "Quali app apri sempre insieme?"
    # Utile per: generare routine "apri tutto questo insieme"

    def find_cooccurrence_patterns(self, sessions: list[dict]) -> list[dict]:
        """
        Per ogni sessione, considera tutte le combinazioni di app (coppie, triplette, ...).
        Conta quante volte ogni combinazione appare insieme.
        Soglia: MIN_OCCURRENCES.
        """
        combo_count: dict[tuple, int]   = defaultdict(int)
        combo_first: dict[tuple, str]   = {}
        combo_last:  dict[tuple, str]   = {}

        for s in sessions:
            apps = s["apps"]
            if len(apps) < 2:
                continue

            # Genera tutte le combinazioni da 2 a MAX_COMBO_SIZE
            for size in range(2, min(MAX_COMBO_SIZE + 1, len(apps) + 1)):
                for combo in combinations(apps, size):
                    key = tuple(sorted(combo))
                    combo_count[key] += 1
                    ts = s["start"].isoformat()
                    if key not in combo_first:
                        combo_first[key] = ts
                    combo_last[key] = ts

        # Filtra per soglia minima
        patterns = []
        for combo, count in combo_count.items():
            if count >= MIN_OCCURRENCES:
                patterns.append({
                    "type":         "cooccurrence",
                    "apps":         list(combo),
                    "occurrences":  count,
                    "first_seen":   combo_first[combo],
                    "last_seen":    combo_last[combo],
                    "metadata":     {},
                })

        # Ordina per occorrenze decrescenti
        patterns.sort(key=lambda x: x["occurrences"], reverse=True)
        return patterns

    # ──────────────────────────────────────────────────────────────────────────
    # 2. TEMPORAL PATTERNS
    # ──────────────────────────────────────────────────────────────────────────
    # "A che ora del giorno usi certi set di app?"
    # Utile per: trigger automatici ("ogni mattina alle 9 apri coding mode")

    def find_temporal_patterns(self, sessions: list[dict]) -> list[dict]:
        """
        Raggruppa le sessioni per fascia oraria e giorno della settimana.
        Identifica combinazioni app+orario che si ripetono spesso.

        Slot orari: 0–1, 1–2, ... 23–24 (o aggregati se TEMPORAL_SLOT_HOURS > 1)
        """
        # slot → {frozenset(apps): [timestamps]}
        slot_map: dict[tuple, dict[frozenset, list]] = defaultdict(lambda: defaultdict(list))

        for s in sessions:
            if not s["apps"]:
                continue

            hour_slot = s["start"].hour // TEMPORAL_SLOT_HOURS
            weekday   = s["start"].weekday()   # 0=Mon … 6=Sun
            key_apps  = frozenset(s["apps"][:4])  # top 4 app della sessione

            # Chiave = (slot_orario, giorno_settimana)
            slot_key = (hour_slot, weekday)
            slot_map[slot_key][key_apps].append(s["start"].isoformat())

        patterns = []
        for (hour_slot, weekday), apps_dict in slot_map.items():
            for app_set, timestamps in apps_dict.items():
                if len(timestamps) < MIN_OCCURRENCES:
                    continue

                hour_label = f"{hour_slot * TEMPORAL_SLOT_HOURS:02d}:00"
                day_label  = ["Lun","Mar","Mer","Gio","Ven","Sab","Dom"][weekday]

                patterns.append({
                    "type":        "temporal",
                    "apps":        sorted(list(app_set)),
                    "occurrences": len(timestamps),
                    "first_seen":  min(timestamps),
                    "last_seen":   max(timestamps),
                    "metadata":    {
                        "hour_slot": hour_label,
                        "weekday":   day_label,
                        "weekday_n": weekday,
                    },
                })

        patterns.sort(key=lambda x: x["occurrences"], reverse=True)
        return patterns

    # ──────────────────────────────────────────────────────────────────────────
    # 3. SEQUENCE PATTERNS
    # ──────────────────────────────────────────────────────────────────────────
    # "In che ordine preciso apri le app?"
    # Utile per: riprodurre esattamente il workflow, step by step

    def find_sequence_patterns(self, sessions: list[dict]) -> list[dict]:
        """
        Analizza i log raw (activity_log) per trovare sequenze di apertura app
        che si ripetono nello stesso ordine entro una finestra temporale.

        Usa i log grezzi, non le sessioni aggregate, per avere l'ordine preciso.
        """
        # Carica i log raw ordinati per start_time, con durata per il filtro noise
        self.cursor.execute("""
            SELECT app_name, start_time, duration
            FROM activity_log
            ORDER BY start_time
        """)
        raw_logs_all = self.cursor.fetchall()

        if not raw_logs_all:
            return []

        # Applica lo stesso noise filtering del session_builder:
        # - scarta app di sistema (categoria "system")
        # - scarta attività sotto MIN_APP_DURATION secondi
        raw_logs = [
            (app, start)
            for app, start, duration in raw_logs_all
            if not is_noise(app, duration)
        ]

        if not raw_logs:
            return []

        # Costruisce finestre temporali: sequenze di app entro SEQUENCE_WINDOW_SEC
        windows: list[list[str]] = []
        i = 0
        while i < len(raw_logs):
            app_i, start_i = raw_logs[i]
            t_i = datetime.fromisoformat(start_i)
            window = [app_i]

            for j in range(i + 1, len(raw_logs)):
                app_j, start_j = raw_logs[j]
                t_j = datetime.fromisoformat(start_j)
                if (t_j - t_i).total_seconds() <= SEQUENCE_WINDOW_SEC:
                    if app_j not in window:  # deduplica nella finestra
                        window.append(app_j)
                else:
                    break

            if len(window) >= 2:
                windows.append(window)
            i += 1

        # Conta sequenze identiche
        seq_count: dict[tuple, int]  = defaultdict(int)
        seq_first: dict[tuple, str]  = {}
        seq_last:  dict[tuple, str]  = {}

        for idx, window in enumerate(windows):
            key = tuple(window[:5])  # max 5 step per sequenza
            seq_count[key] += 1
            ts = raw_logs[idx][1]
            if key not in seq_first:
                seq_first[key] = ts
            seq_last[key] = ts

        patterns = []
        for seq, count in seq_count.items():
            if count >= MIN_OCCURRENCES:
                patterns.append({
                    "type":        "sequence",
                    "apps":        list(seq),
                    "occurrences": count,
                    "first_seen":  seq_first[seq],
                    "last_seen":   seq_last[seq],
                    "metadata":    {
                        "steps": len(seq),
                    },
                })

        patterns.sort(key=lambda x: x["occurrences"], reverse=True)
        return patterns

    # ──────────────────────────────────────────────────────────────────────────
    # SALVATAGGIO
    # ──────────────────────────────────────────────────────────────────────────

    def save_patterns(self, patterns: list[dict]) -> int:
        """
        Salva i pattern nel DB.
        Se un pattern identico (stesso tipo + stesse app) esiste già,
        aggiorna occorrenze e last_seen invece di duplicare.
        """
        # Assicuriamoci che la tabella patterns esista con lo schema corretto
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS patterns (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                pattern_type    TEXT NOT NULL,
                apps_sequence   TEXT NOT NULL,
                occurrences     INTEGER DEFAULT 1,
                first_seen      DATETIME,
                last_seen       DATETIME,
                metadata        TEXT,
                proposed        INTEGER DEFAULT 0,
                accepted        INTEGER DEFAULT 0
            )
        """)
        self.db.conn.commit()

        saved = 0
        updated = 0

        for p in patterns:
            apps_json = json.dumps(p["apps"])
            meta_json = json.dumps(p.get("metadata", {}))

            # Controlla se esiste già
            self.cursor.execute("""
                SELECT id, occurrences FROM patterns
                WHERE pattern_type = ? AND apps_sequence = ?
            """, (p["type"], apps_json))

            existing = self.cursor.fetchone()

            if existing:
                pid, old_count = existing
                new_count = max(old_count, p["occurrences"])
                self.cursor.execute("""
                    UPDATE patterns
                    SET occurrences = ?, last_seen = ?, metadata = ?
                    WHERE id = ?
                """, (new_count, p["last_seen"], meta_json, pid))
                updated += 1
            else:
                self.cursor.execute("""
                    INSERT INTO patterns
                    (pattern_type, apps_sequence, occurrences, first_seen, last_seen, metadata)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    p["type"],
                    apps_json,
                    p["occurrences"],
                    p["first_seen"],
                    p["last_seen"],
                    meta_json,
                ))
                saved += 1

        self.db.conn.commit()
        print(f"Pattern salvati: {saved} nuovi, {updated} aggiornati")
        return saved + updated

    # ──────────────────────────────────────────────────────────────────────────
    # EXPORT PER AI
    # ──────────────────────────────────────────────────────────────────────────

    def export_for_ai(self, top_n: int = 20) -> str:
        """
        Genera un testo strutturato con i pattern più forti,
        pronto per essere iniettato nel system prompt di Gemini/Claude.

        Formato leggibile dall'AI, non JSON grezzo.
        """
        self.cursor.execute("""
            SELECT pattern_type, apps_sequence, occurrences, metadata
            FROM patterns
            WHERE accepted = 0
            ORDER BY occurrences DESC
            LIMIT ?
        """, (top_n,))

        rows = self.cursor.fetchall()

        if not rows:
            return "Nessun pattern identificato ancora."

        lines = ["## Pattern comportamentali dell'utente\n"]

        for ptype, apps_json, count, meta_json in rows:
            apps = json.loads(apps_json)
            meta = json.loads(meta_json) if meta_json else {}

            if ptype == "cooccurrence":
                lines.append(
                    f"- Usa spesso insieme: {', '.join(apps)} "
                    f"({count} sessioni)"
                )
            elif ptype == "temporal":
                lines.append(
                    f"- Ogni {meta.get('weekday','?')} alle {meta.get('hour_slot','?')} "
                    f"usa: {', '.join(apps)} "
                    f"({count} volte)"
                )
            elif ptype == "sequence":
                steps = " → ".join(apps)
                lines.append(
                    f"- Sequenza ricorrente: {steps} "
                    f"({count} volte)"
                )

        return "\n".join(lines)

    # ──────────────────────────────────────────────────────────────────────────
    # RUN COMPLETO
    # ──────────────────────────────────────────────────────────────────────────

    def run(self) -> dict:
        """Esegue l'analisi completa e salva tutto nel DB."""
        sessions = self.load_sessions()
        print(f"Sessioni caricate: {len(sessions)}")

        if not sessions:
            print("Nessuna sessione trovata. Esegui prima session_builder.py")
            return {}

        print("\n── Analisi co-occurrence ──")
        co = self.find_cooccurrence_patterns(sessions)
        print(f"  Pattern trovati: {len(co)}")

        print("── Analisi temporale ──")
        temp = self.find_temporal_patterns(sessions)
        print(f"  Pattern trovati: {len(temp)}")

        print("── Analisi sequenze ──")
        seq = self.find_sequence_patterns(sessions)
        print(f"  Pattern trovati: {len(seq)}")

        all_patterns = co + temp + seq
        print(f"\nTotale pattern candidati: {len(all_patterns)}")

        self.save_patterns(all_patterns)

        # Mostra export AI
        print("\n── Export per AI ──")
        print(self.export_for_ai())

        return {
            "cooccurrence": co,
            "temporal":     temp,
            "sequence":     seq,
        }


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    engine = PatternEngine()
    engine.run()