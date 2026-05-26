"""
main.py — Jarvis v2

Avvia tutti i componenti in thread separati:
- Observer      → gira sempre, ogni 2s logga l'app attiva
- Scheduler     → ogni 30 minuti costruisce sessioni e aggiorna pattern
"""

import threading
import time
import logging
from datetime import datetime

from core.observer import Observer
from data.database import Database

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("jarvis")

# ── Configurazione ────────────────────────────────────────────────────────────

SESSION_BUILD_INTERVAL_MIN = 30   # ogni quanti minuti ricostruisce sessioni e pattern


# ── Job periodico ─────────────────────────────────────────────────────────────

def run_scheduler():
    """
    Gira in background. Ogni SESSION_BUILD_INTERVAL_MIN minuti:
    1. Costruisce le sessioni dai log raw
    2. Aggiorna i pattern dalle sessioni
    """
    import sys
    import os
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

    from session_builder import SessionBuilder
    from core.pattern_engine import PatternEngine

    interval_sec = SESSION_BUILD_INTERVAL_MIN * 60

    def build_and_learn():
        """Esegue session builder + pattern engine una volta."""
        try:
            log.info("── Scheduler: avvio session builder ──")
            sb = SessionBuilder()
            saved = sb.sync_sessions_incremental()
            log.info(f"── Scheduler: {saved} sessioni salvate ──")

            log.info("── Scheduler: avvio pattern engine ──")
            pe = PatternEngine()
            result = pe.run()
            total = sum(len(v) for v in result.values())
            log.info(f"── Scheduler: {total} pattern aggiornati ──")

        except Exception as e:
            log.error(f"── Scheduler errore: {e} ──")

    # Prima esecuzione immediata all'avvio
    build_and_learn()

    # Poi ogni 30 minuti
    while True:
        time.sleep(interval_sec)
        build_and_learn()


# ── Entry point ───────────────────────────────────────────────────────────────

def run():
    log.info("╔══════════════════════════════╗")
    log.info("║       Jarvis — avvio         ║")
    log.info("╚══════════════════════════════╝")

    db = Database()

    # Thread scheduler (sessioni + pattern ogni 30 min)
    scheduler_thread = threading.Thread(
        target=run_scheduler,
        name="scheduler",
        daemon=True,   # si chiude automaticamente quando il main si chiude
    )
    scheduler_thread.start()
    log.info(f"Scheduler avviato — intervallo: {SESSION_BUILD_INTERVAL_MIN} min")

    # Observer — gira nel thread principale (blocca qui)
    log.info("Observer avviato — in ascolto...")
    observer = Observer(db)
    observer.observe()


if __name__ == "__main__":
    run()
