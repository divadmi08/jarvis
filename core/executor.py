"""
executor.py — Jarvis v2

Esegue azioni reali sul sistema operativo.
Ogni azione è atomica, loggata e con timeout.

Azioni disponibili:
- open_app        → apre un eseguibile
- focus_window    → porta in foreground una finestra per titolo o nome processo
- run_command     → esegue un comando shell
- type_text       → digita testo nella finestra attiva
- click           → click su coordinate assolute
- wait_for_window → aspetta che una finestra appaia (usato dopo open_app)
- notify_user     → mostra una notifica Windows non intrusiva
- sleep           → pausa esplicita tra step

Formato routine JSON:
{
  "name": "Coding Mode",
  "steps": [
    {"action": "open_app",     "target": "C:/Users/.../Code.exe"},
    {"action": "wait_for_window", "target": "Visual Studio Code", "timeout": 15},
    {"action": "open_app",     "target": "C:/Users/.../opera.exe"},
    {"action": "focus_window", "target": "Visual Studio Code"},
    {"action": "notify_user",  "msg": "Coding mode attivo"}
  ]
}
"""

import json
import os
import subprocess
import sys
import time
import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional

import win32gui
import win32con
import win32process
import psutil
import pyautogui

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from system.permissions import PermissionSystem

# ── Logging ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("executor")

# ── Configurazione ────────────────────────────────────────────────────────────

DEFAULT_TIMEOUT    = 10    # secondi massimi per ogni azione
OPEN_APP_WAIT      = 2     # secondi di attesa dopo open_app prima del prossimo step
POLL_INTERVAL      = 0.5   # secondi tra i check in wait_for_window
MAX_RETRIES        = 3     # tentativi massimi per step fallito

# ── Tipi ──────────────────────────────────────────────────────────────────────

class StepStatus(Enum):
    SUCCESS  = "success"
    FAILED   = "failed"
    SKIPPED  = "skipped"


@dataclass
class StepResult:
    action:  str
    target:  str          = ""
    status:  StepStatus   = StepStatus.SUCCESS
    message: str          = ""
    retries: int          = 0
    elapsed: float        = 0.0


@dataclass
class RoutineResult:
    name:       str
    started_at: datetime             = field(default_factory=datetime.now)
    ended_at:   Optional[datetime]   = None
    steps:      list[StepResult]     = field(default_factory=list)
    status:     str                  = "success"   # success / partial / failed / cancelled

    @property
    def success_count(self):
        return sum(1 for s in self.steps if s.status == StepStatus.SUCCESS)

    @property
    def failed_count(self):
        return sum(1 for s in self.steps if s.status == StepStatus.FAILED)

    def summary(self) -> str:
        total = len(self.steps)
        elapsed = (self.ended_at - self.started_at).total_seconds() if self.ended_at else 0
        return (
            f"Routine '{self.name}' — {self.status.upper()} "
            f"({self.success_count}/{total} step, {round(elapsed, 1)}s)"
        )


# ── Helpers Windows ───────────────────────────────────────────────────────────

def _find_window_by_title(substring: str) -> Optional[int]:
    """Cerca una finestra il cui titolo contiene `substring` (case-insensitive)."""
    result = []

    def callback(hwnd, _):
        if win32gui.IsWindowVisible(hwnd):
            title = win32gui.GetWindowText(hwnd)
            if substring.lower() in title.lower():
                result.append(hwnd)

    win32gui.EnumWindows(callback, None)
    return result[0] if result else None


def _find_window_by_process(process_name: str) -> Optional[int]:
    """Cerca una finestra appartenente a un processo con quel nome."""
    result = []
    proc_lower = process_name.lower().replace(".exe", "")

    def callback(hwnd, _):
        if win32gui.IsWindowVisible(hwnd) and win32gui.GetWindowText(hwnd):
            try:
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                proc = psutil.Process(pid)
                if proc_lower in proc.name().lower():
                    result.append(hwnd)
            except Exception:
                pass

    win32gui.EnumWindows(callback, None)
    return result[0] if result else None


def _bring_to_front(hwnd: int) -> bool:
    """
    Porta una finestra in foreground in modo affidabile.
    Windows blocca SetForegroundWindow se il processo chiamante non ha il focus:
    la workaround standard è simulare un ALT keypress prima della chiamata.
    """
    import ctypes
    try:
        if win32gui.IsIconic(hwnd):
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        # ALT keypress sblocca il lock sul foreground di Windows
        ctypes.windll.user32.keybd_event(0x12, 0, 0, 0)          # ALT down
        win32gui.SetForegroundWindow(hwnd)
        ctypes.windll.user32.keybd_event(0x12, 0, 2, 0)          # ALT up
        return True
    except Exception as e:
        log.warning(f"SetForegroundWindow fallito: {e}")
        return False


# ── Azioni atomiche ───────────────────────────────────────────────────────────

def action_open_app(target: str, **kwargs) -> StepResult:
    """
    Apre un eseguibile.
    Se il processo è già in esecuzione, porta in foreground la finestra esistente
    invece di aprire una seconda istanza.
    """
    t0 = time.time()
    try:
        if target.startswith("http://") or target.startswith("https://"):
            import webbrowser
            webbrowser.open(target)
        else:
            # Estrai il nome del processo dal path (es. "Code.exe")
            proc_name = os.path.basename(target.split()[0])

            # Controlla se è già in esecuzione
            already_running = any(
                p.name().lower() == proc_name.lower()
                for p in psutil.process_iter(["name"])
                if p.info["name"]
            )

            if already_running:
                # Cerca la finestra e portala in foreground
                hwnd = _find_window_by_process(proc_name)
                if hwnd:
                    _bring_to_front(hwnd)
                    log.info(f"  open_app: '{proc_name}' già aperto — portato in foreground")
                    return StepResult(
                        action="open_app", target=target,
                        status=StepStatus.SUCCESS,
                        message="already_running",
                        elapsed=time.time() - t0,
                    )

            # Non in esecuzione — avvia normalmente
            # Wrappa tra virgolette se il path contiene spazi
            launch = f'"{target}"' if ' ' in target and not target.startswith('"') else target
            subprocess.Popen(launch, shell=True)
            time.sleep(OPEN_APP_WAIT)

        return StepResult(
            action="open_app", target=target,
            status=StepStatus.SUCCESS,
            elapsed=time.time() - t0,
        )
    except Exception as e:
        return StepResult(
            action="open_app", target=target,
            status=StepStatus.FAILED, message=str(e),
            elapsed=time.time() - t0,
        )


def action_focus_window(target: str, **kwargs) -> StepResult:
    """
    Porta in foreground la finestra che corrisponde a `target`.
    Prova prima per titolo, poi per nome processo.
    """
    t0 = time.time()
    hwnd = _find_window_by_title(target) or _find_window_by_process(target)

    if not hwnd:
        return StepResult(
            action="focus_window", target=target,
            status=StepStatus.FAILED,
            message=f"Finestra non trovata: '{target}'",
            elapsed=time.time() - t0,
        )

    success = _bring_to_front(hwnd)
    return StepResult(
        action="focus_window", target=target,
        status=StepStatus.SUCCESS if success else StepStatus.FAILED,
        elapsed=time.time() - t0,
    )


def action_wait_for_window(target: str, timeout: int = DEFAULT_TIMEOUT, **kwargs) -> StepResult:
    """
    Aspetta che una finestra con `target` nel titolo appaia.
    Utile dopo open_app per app lente ad avviarsi.
    """
    t0 = time.time()
    deadline = t0 + timeout

    while time.time() < deadline:
        hwnd = _find_window_by_title(target) or _find_window_by_process(target)
        if hwnd:
            return StepResult(
                action="wait_for_window", target=target,
                status=StepStatus.SUCCESS,
                elapsed=time.time() - t0,
            )
        time.sleep(POLL_INTERVAL)

    return StepResult(
        action="wait_for_window", target=target,
        status=StepStatus.FAILED,
        message=f"Timeout dopo {timeout}s — finestra '{target}' non apparsa",
        elapsed=time.time() - t0,
    )


def action_run_command(target: str, timeout: int = DEFAULT_TIMEOUT, **kwargs) -> StepResult:
    """
    Esegue un comando shell con timeout.
    Output viene loggato ma non bloccante.
    """
    t0 = time.time()
    try:
        result = subprocess.run(
            target, shell=True,
            capture_output=True, text=True,
            timeout=timeout,
        )
        status = StepStatus.SUCCESS if result.returncode == 0 else StepStatus.FAILED
        msg = result.stderr.strip() if result.returncode != 0 else ""
        return StepResult(
            action="run_command", target=target,
            status=status, message=msg,
            elapsed=time.time() - t0,
        )
    except subprocess.TimeoutExpired:
        return StepResult(
            action="run_command", target=target,
            status=StepStatus.FAILED,
            message=f"Timeout dopo {timeout}s",
            elapsed=time.time() - t0,
        )
    except Exception as e:
        return StepResult(
            action="run_command", target=target,
            status=StepStatus.FAILED, message=str(e),
            elapsed=time.time() - t0,
        )


def action_type_text(target: str, **kwargs) -> StepResult:
    """Digita testo nella finestra attiva. Usa pyautogui."""
    t0 = time.time()
    try:
        pyautogui.write(target, interval=0.05)
        return StepResult(
            action="type_text", target=target,
            status=StepStatus.SUCCESS,
            elapsed=time.time() - t0,
        )
    except Exception as e:
        return StepResult(
            action="type_text", target=target,
            status=StepStatus.FAILED, message=str(e),
            elapsed=time.time() - t0,
        )


def action_click(target: str, **kwargs) -> StepResult:
    """
    Click su coordinate. `target` deve essere "x,y" es. "960,540".
    """
    t0 = time.time()
    try:
        x, y = map(int, target.split(","))
        pyautogui.click(x, y)
        return StepResult(
            action="click", target=target,
            status=StepStatus.SUCCESS,
            elapsed=time.time() - t0,
        )
    except Exception as e:
        return StepResult(
            action="click", target=target,
            status=StepStatus.FAILED, message=str(e),
            elapsed=time.time() - t0,
        )


def action_notify_user(target: str = "", msg: str = "", **kwargs) -> StepResult:
    """Mostra una notifica Windows tramite PowerShell (zero dipendenze extra).
    Accetta sia 'target' (campo standard) che 'msg' (alias per leggibilità nel JSON).
    """
    text = target or msg  # funziona con entrambi i campi
    t0 = time.time()
    try:
        ps_script = (
            f'Add-Type -AssemblyName System.Windows.Forms; '
            f'$n = New-Object System.Windows.Forms.NotifyIcon; '
            f'$n.Icon = [System.Drawing.SystemIcons]::Information; '
            f'$n.Visible = $true; '
            f'$n.ShowBalloonTip(3000, "Jarvis", "{text}", '
            f'[System.Windows.Forms.ToolTipIcon]::Info); '
            f'Start-Sleep -Milliseconds 3500; '
            f'$n.Dispose()'
        )
        subprocess.Popen(
            ["powershell", "-WindowStyle", "Hidden", "-Command", ps_script],
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return StepResult(
            action="notify_user", target=text,
            status=StepStatus.SUCCESS,
            elapsed=time.time() - t0,
        )
    except Exception as e:
        return StepResult(
            action="notify_user", target=text,
            status=StepStatus.FAILED, message=str(e),
            elapsed=time.time() - t0,
        )


def action_sleep(target: str, **kwargs) -> StepResult:
    """Pausa esplicita. `target` è il numero di secondi (stringa)."""
    t0 = time.time()
    try:
        seconds = float(target)
        time.sleep(seconds)
        return StepResult(
            action="sleep", target=target,
            status=StepStatus.SUCCESS,
            elapsed=time.time() - t0,
        )
    except Exception as e:
        return StepResult(
            action="sleep", target=target,
            status=StepStatus.FAILED, message=str(e),
            elapsed=time.time() - t0,
        )


# ── Dispatch ──────────────────────────────────────────────────────────────────

ACTION_MAP = {
    "open_app":        action_open_app,
    "focus_window":    action_focus_window,
    "wait_for_window": action_wait_for_window,
    "run_command":     action_run_command,
    "type_text":       action_type_text,
    "click":           action_click,
    "notify_user":     action_notify_user,
    "sleep":           action_sleep,
}


# ── Executor ──────────────────────────────────────────────────────────────────

class Executor:
    def __init__(self):
        # Blocca pyautogui se il mouse va in alto a sinistra (failsafe)
        pyautogui.FAILSAFE = True
        self.permissions = PermissionSystem()

    def run_routine(self, routine: dict, on_step: callable = None) -> RoutineResult:
        """
        Esegue una routine.

        `on_step` è un callback opzionale chiamato dopo ogni step:
            on_step(step_index, step_def, step_result)
        Utile per aggiornare una UI in tempo reale.

        Ogni step ha MAX_RETRIES tentativi prima di essere marcato come fallito.
        Se uno step fallisce tutti i tentativi, la routine continua con gli step
        successivi ma il risultato finale sarà "partial".
        """
        result = RoutineResult(name=routine.get("name", "unnamed"))
        steps  = routine.get("steps", [])

        log.info(f"▶ Avvio routine '{result.name}' ({len(steps)} step)")

        for i, step in enumerate(steps):
            action  = step.get("action", "")
            target  = step.get("target", step.get("msg", ""))
            timeout = step.get("timeout", DEFAULT_TIMEOUT)

            if action not in ACTION_MAP:
                sr = StepResult(
                    action=action, target=target,
                    status=StepStatus.FAILED,
                    message=f"Azione sconosciuta: '{action}'",
                )
                result.steps.append(sr)
                log.warning(f"  [{i+1}/{len(steps)}] {action} — AZIONE SCONOSCIUTA")
                if on_step:
                    on_step(i, step, sr)
                continue

            # Controlla permessi prima di eseguire
            perm = self.permissions.check(action, target)
            if not perm.granted:
                sr = StepResult(
                    action=action, target=target,
                    status=StepStatus.SKIPPED,
                    message=f"Permesso negato — {perm.reason}",
                )
                result.steps.append(sr)
                log.warning(f"  [{i+1}/{len(steps)}] {action} — PERMESSO NEGATO")
                if on_step:
                    on_step(i, step, sr)
                continue

            # Retry loop — passa tutto lo step come kwargs
            sr = None
            for attempt in range(MAX_RETRIES):
                sr = ACTION_MAP[action](**{k: v for k, v in step.items() if k != "action"})
                sr.retries = attempt

                if sr.status == StepStatus.SUCCESS:
                    log.info(
                        f"  [{i+1}/{len(steps)}] {action}({target[:40]}) "
                        f"✓ {round(sr.elapsed, 1)}s"
                        + (f" (retry {attempt})" if attempt > 0 else "")
                    )
                    break

                log.warning(
                    f"  [{i+1}/{len(steps)}] {action}({target[:40]}) "
                    f"✗ tentativo {attempt+1}/{MAX_RETRIES} — {sr.message}"
                )

                if attempt < MAX_RETRIES - 1:
                    time.sleep(1)  # breve pausa prima del retry

            result.steps.append(sr)

            if on_step:
                on_step(i, step, sr)

        # Stato finale routine
        result.ended_at = datetime.now()
        failed = result.failed_count
        if failed == 0:
            result.status = "success"
        elif failed == len(steps):
            result.status = "failed"
        else:
            result.status = "partial"

        log.info(f"■ {result.summary()}")
        return result

    def run_from_file(self, path: str) -> RoutineResult:
        """Carica ed esegue una routine da file JSON."""
        with open(path, encoding="utf-8") as f:
            routine = json.load(f)
        return self.run_routine(routine)

    def run_from_json(self, json_str: str) -> RoutineResult:
        """Carica ed esegue una routine da stringa JSON."""
        routine = json.loads(json_str)
        return self.run_routine(routine)


# ── Entry point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    # Usa il path passato come argomento, oppure la routine di default
    routine_path = sys.argv[1] if len(sys.argv) > 1 else "routines/dev_mode.json"

    executor = Executor()
    result   = executor.run_from_file(routine_path)

    print("\n── Riepilogo step ──")
    for sr in result.steps:
        icon = "✓" if sr.status == StepStatus.SUCCESS else "✗"
        print(f"  {icon} {sr.action:<18} {sr.target[:45]:<45} {round(sr.elapsed,1)}s")

    print(f"\n{result.summary()}")