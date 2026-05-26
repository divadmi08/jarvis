"""
permissions.py — Jarvis v2

Sistema di permessi a tre livelli per ogni azione dell'executor.

Livelli:
- SAFE   → esecuzione diretta, nessuna conferma
- MEDIUM → conferma la prima volta, poi ricorda la scelta
- RISKY  → conferma SEMPRE, senza eccezioni

Flusso:
    Executor chiama check(action, target)
    → PermissionSystem valuta il livello
    → SAFE: ritorna True immediatamente
    → MEDIUM: se già approvata in passato ritorna True, altrimenti chiede
    → RISKY: chiede sempre, non memorizza mai

La memoria delle approvazioni MEDIUM viene salvata in permissions_memory.json
nella cartella config/ così persiste tra i riavvii.
"""

import json
import os
import subprocess
import sys
import logging
from enum import Enum
from datetime import datetime
from typing import Optional

log = logging.getLogger("permissions")

# ── Livelli ───────────────────────────────────────────────────────────────────

class Level(Enum):
    SAFE   = "safe"
    MEDIUM = "medium"
    RISKY  = "risky"


# ── Mappa azione → livello ────────────────────────────────────────────────────
# Regola generale:
#   SAFE   = legge o apre, non modifica nulla di permanente
#   MEDIUM = scarica, installa, modifica impostazioni non critiche
#   RISKY  = elimina, sovrascrive, modifica registro, azioni irreversibili

ACTION_LEVELS: dict[str, Level] = {
    # ── SAFE ──────────────────────────────────────────────────────────────────
    "open_app":        Level.SAFE,
    "focus_window":    Level.SAFE,
    "wait_for_window": Level.SAFE,
    "notify_user":     Level.SAFE,
    "sleep":           Level.SAFE,
    "type_text":       Level.SAFE,
    "click":           Level.SAFE,

    # ── MEDIUM ────────────────────────────────────────────────────────────────
    "run_command":     Level.MEDIUM,   # dipende dal comando, ma meglio cauti
    "open_url":        Level.MEDIUM,   # potrebbe aprire siti non voluti
    "download_file":   Level.MEDIUM,
    "install_package": Level.MEDIUM,
    "write_file":      Level.MEDIUM,
    "modify_setting":  Level.MEDIUM,

    # ── RISKY ─────────────────────────────────────────────────────────────────
    "delete_file":     Level.RISKY,
    "delete_folder":   Level.RISKY,
    "modify_registry": Level.RISKY,
    "kill_process":    Level.RISKY,
    "format_drive":    Level.RISKY,
    "run_as_admin":    Level.RISKY,
}

# Livello di default per azioni non in mappa
DEFAULT_LEVEL = Level.MEDIUM


# ── Risultato check ───────────────────────────────────────────────────────────

class PermissionResult:
    def __init__(self, granted: bool, level: Level, reason: str = ""):
        self.granted = granted
        self.level   = level
        self.reason  = reason

    def __bool__(self):
        return self.granted

    def __repr__(self):
        icon = "✓" if self.granted else "✗"
        return f"Permission({icon} {self.level.value} — {self.reason})"


# ── PermissionSystem ──────────────────────────────────────────────────────────

class PermissionSystem:
    def __init__(self, memory_path: str = "config/permissions_memory.json"):
        self.memory_path = memory_path
        self.memory: dict[str, bool] = self._load_memory()

    # ── Memoria ───────────────────────────────────────────────────────────────

    def _load_memory(self) -> dict:
        """Carica le approvazioni MEDIUM salvate in precedenza."""
        if not os.path.exists(self.memory_path):
            return {}
        try:
            with open(self.memory_path, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def _save_memory(self) -> None:
        """Salva la memoria su disco."""
        os.makedirs(os.path.dirname(self.memory_path), exist_ok=True)
        with open(self.memory_path, "w", encoding="utf-8") as f:
            json.dump(self.memory, f, indent=2)

    def _memory_key(self, action: str, target: str) -> str:
        """
        Chiave univoca per una coppia azione+target.
        Per run_command usa il comando esatto.
        Per open_app usa solo il nome dell'eseguibile (non il path completo)
        così un path aggiornato non invalida l'approvazione.
        """
        if action == "open_app":
            target_key = os.path.basename(target.split()[0]).lower()
        else:
            target_key = target.strip().lower()[:100]
        return f"{action}::{target_key}"

    # ── Livello ───────────────────────────────────────────────────────────────

    def get_level(self, action: str) -> Level:
        return ACTION_LEVELS.get(action, DEFAULT_LEVEL)

    # ── Conferma utente ───────────────────────────────────────────────────────

    def _ask_user(self, action: str, target: str, level: Level) -> bool:
        """
        Mostra un popup di conferma nativo Windows via PowerShell.
        Ritorna True se l'utente clicca Sì, False se No.
        """
        level_label = {
            Level.MEDIUM: "⚠️  ATTENZIONE",
            Level.RISKY:  "🔴 AZIONE RISCHIOSA",
        }.get(level, "Conferma")

        # Tronca il target per leggibilità nel popup
        target_display = target if len(target) <= 80 else target[:77] + "..."

        message = (
            f"{level_label}\\n\\n"
            f"Azione: {action}\\n"
            f"Target: {target_display}\\n\\n"
            f"Vuoi procedere?"
        )

        ps_script = (
            f'Add-Type -AssemblyName System.Windows.Forms; '
            f'$result = [System.Windows.Forms.MessageBox]::Show('
            f'"{message}", '
            f'"Jarvis — Richiesta permesso", '
            f'[System.Windows.Forms.MessageBoxButtons]::YesNo, '
            f'[System.Windows.Forms.MessageBoxIcon]::Warning'
            f'); '
            f'if ($result -eq "Yes") {{ exit 0 }} else {{ exit 1 }}'
        )

        try:
            result = subprocess.run(
                ["powershell", "-WindowStyle", "Hidden", "-Command", ps_script],
                timeout=60,   # se l'utente non risponde entro 60s → nega
            )
            return result.returncode == 0
        except subprocess.TimeoutExpired:
            log.warning("Timeout conferma permesso — azione negata")
            return False
        except Exception as e:
            log.error(f"Errore popup permesso: {e}")
            return False

    # ── Check principale ──────────────────────────────────────────────────────

    def check(self, action: str, target: str = "") -> PermissionResult:
        """
        Punto di ingresso principale. Chiamato dall'executor prima di ogni azione.

        Returns PermissionResult con .granted = True/False
        """
        level = self.get_level(action)

        # ── SAFE: via libera ──────────────────────────────────────────────────
        if level == Level.SAFE:
            return PermissionResult(True, level, "safe — nessuna conferma richiesta")

        # ── MEDIUM: controlla memoria, altrimenti chiedi ──────────────────────
        if level == Level.MEDIUM:
            key = self._memory_key(action, target)

            if key in self.memory:
                if self.memory[key]:
                    return PermissionResult(True, level, "già approvata in precedenza")
                else:
                    return PermissionResult(False, level, "già negata in precedenza")

            # Prima volta — chiedi
            granted = self._ask_user(action, target, level)

            # Memorizza la scelta per le prossime volte
            self.memory[key] = granted
            self._save_memory()

            reason = "approvata dall'utente" if granted else "negata dall'utente"
            log.info(f"Permission MEDIUM {action}({target[:40]}) → {reason} — memorizzata")
            return PermissionResult(granted, level, reason)

        # ── RISKY: chiedi sempre, non memorizzare mai ─────────────────────────
        if level == Level.RISKY:
            granted = self._ask_user(action, target, level)
            reason = "approvata dall'utente" if granted else "negata dall'utente"
            log.info(f"Permission RISKY {action}({target[:40]}) → {reason}")
            return PermissionResult(granted, level, reason)

        # Fallback — nega per sicurezza
        return PermissionResult(False, level, "livello sconosciuto — negato per sicurezza")

    # ── Gestione memoria ──────────────────────────────────────────────────────

    def reset_memory(self, action: str = None, target: str = None) -> None:
        """
        Cancella le approvazioni memorizzate.
        - Senza argomenti: cancella tutto
        - Con action+target: cancella solo quella specifica
        """
        if action and target:
            key = self._memory_key(action, target)
            if key in self.memory:
                del self.memory[key]
                self._save_memory()
                log.info(f"Memoria rimossa per {key}")
        else:
            self.memory = {}
            self._save_memory()
            log.info("Memoria permessi azzerata")

    def list_memory(self) -> list[dict]:
        """Restituisce la lista delle approvazioni memorizzate."""
        return [
            {"key": k, "approved": v}
            for k, v in self.memory.items()
        ]


# ── Entry point / test ────────────────────────────────────────────────────────

if __name__ == "__main__":
    ps = PermissionSystem()

    print("\n── Test Permission System ──\n")

    tests = [
        ("open_app",     "C:/VS Code/Code.exe"),
        ("focus_window", "Visual Studio Code"),
        ("run_command",  "pip install requests"),
        ("delete_file",  "C:/Users/test.txt"),
    ]

    for action, target in tests:
        result = ps.check(action, target)
        icon = "✓" if result.granted else "✗"
        print(f"  {icon} [{result.level.value:<6}] {action:<16} — {result.reason}")

    print("\n── Memoria salvata ──")
    for entry in ps.list_memory():
        icon = "✓" if entry["approved"] else "✗"
        print(f"  {icon} {entry['key']}")
