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

import ctypes
import json
import os
import shlex
import subprocess
import sys
import time
import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
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

DEFAULT_TIMEOUT    = 10
OPEN_APP_WAIT      = 2
POLL_INTERVAL      = 0.5
MAX_RETRIES        = 3

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
    status:     str                  = "success"

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
    result = []
    def callback(hwnd, _):
        if win32gui.IsWindowVisible(hwnd):
            title = win32gui.GetWindowText(hwnd)
            if substring.lower() in title.lower():
                result.append(hwnd)
    win32gui.EnumWindows(callback, None)
    return result[0] if result else None


def _find_window_by_process(process_name: str) -> Optional[int]:
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
    try:
        if win32gui.IsIconic(hwnd):
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        ctypes.windll.user32.keybd_event(0x12, 0, 0, 0)
        win32gui.SetForegroundWindow(hwnd)
        ctypes.windll.user32.keybd_event(0x12, 0, 2, 0)
        return True
    except Exception as e:
        log.warning(f"SetForegroundWindow fallito: {e}")
        return False


def _contains_shell_metacharacters(command: str) -> bool:
    return any(token in command for token in ("&&", "||", "|", ">", "<", ";"))


def _split_command(command: str) -> list[str]:
    try:
        return shlex.split(command, posix=False)
    except ValueError:
        return []


def _normalize_argv(command: str) -> list[str]:
    stripped = command.strip()
    if not stripped:
        return []

    # Caso 1: path quotato (es. "C:\Program Files\app.exe" --arg)
    unquoted = stripped.strip('"')
    if os.path.exists(unquoted):
        return [unquoted]

    # Caso 2: split normale con shlex
    argv = _split_command(stripped)
    if not argv:
        return []

    executable = argv[0].strip('"')
    if os.path.exists(executable):
        argv[0] = executable
        return argv

    # Caso 3: path con spazi non quotato seguito da argomenti
    # (es. C:\Riot Games\app.exe --flag)
    # Proviamo a trovare il path consumando token fino a trovare un file esistente
    parts = stripped.split()
    for i in range(len(parts), 0, -1):
        candidate = " ".join(parts[:i]).strip('"')
        if os.path.exists(candidate):
            return [candidate] + parts[i:]

    return argv


def _shellexecute_elevated(exe: str, args: list[str]) -> None:
    """Lancia un exe con ShellExecute 'runas' per ottenere elevazione UAC."""
    # Costruisci la stringa parametri per ShellExecuteW
    # Ogni argomento con spazi va quotato
    if args:
        params = " ".join(f'"{a}"' if (" " in a and not a.startswith('"')) else a for a in args)
    else:
        params = None

    # ShellExecuteW vuole il path dell'exe senza argomenti
    # Se l'exe contiene spazi, quotarlo non serve (ShellExecuteW accetta path nudi)
    ret = ctypes.windll.shell32.ShellExecuteW(
        None,    # hwnd
        "runas", # verb
        exe,     # path eseguibile (solo l'exe, senza argomenti)
        params,  # argomenti separati
        None,    # directory di lavoro (None = directory corrente)
        1,       # SW_SHOWNORMAL
    )
    # Codici <= 32 sono errori; codice 2 = file not found
    if ret <= 32:
        error_map = {
            2: f"File non trovato: '{exe}'",
            3: f"Path non trovato: '{exe}'",
            5: "Accesso negato",
            8: "Memoria insufficiente",
            32: "File in uso",
        }
        msg = error_map.get(ret, f"codice errore {ret}")
        raise OSError(f"ShellExecuteW runas fallito: {msg}")


# ── Azioni atomiche ───────────────────────────────────────────────────────────

def action_open_app(target: str, **kwargs) -> StepResult:
    """
    Apre un eseguibile.
    - Se già in esecuzione: porta in foreground.
    - Se richiede elevazione (WinError 740/5): riprova con ShellExecute runas (UAC).
    - Supporta target con argomenti (es. "app.exe --flag value").
    """
    t0 = time.time()
    try:
        if target.startswith("http://") or target.startswith("https://"):
            import webbrowser
            webbrowser.open(target)
            return StepResult(
                action="open_app", target=target,
                status=StepStatus.SUCCESS,
                elapsed=time.time() - t0,
            )

        # URI Windows — gestiti con ShellExecute direttamente
        _WIN_URI_PREFIXES = (
            "ms-settings:", "ms-windows-store:", "ms-get-started:",
            "shell:", "explorer:", "mailto:", "tel:",
        )
        # Normalizza: aggiungi ":" se manca (es. "ms-windows-store" → "ms-windows-store:")
        _target_normalized = target.strip()
        for uri_prefix in _WIN_URI_PREFIXES:
            slug = uri_prefix.rstrip(":")
            if _target_normalized.lower() == slug or _target_normalized.lower() == uri_prefix:
                _target_normalized = uri_prefix
                break

        if any(_target_normalized.lower().startswith(p) for p in _WIN_URI_PREFIXES):
            ret = ctypes.windll.shell32.ShellExecuteW(None, "open", _target_normalized, None, None, 1)
            if ret <= 32:
                return StepResult(
                    action="open_app", target=target,
                    status=StepStatus.FAILED,
                    message=f"ShellExecute URI fallito con codice {ret}",
                    elapsed=time.time() - t0,
                )
            return StepResult(
                action="open_app", target=target,
                status=StepStatus.SUCCESS,
                elapsed=time.time() - t0,
            )

        if _contains_shell_metacharacters(target):
            raise ValueError("Target contiene operatori shell non consentiti")

        argv = _normalize_argv(target)
        if not argv:
            raise ValueError("Target applicazione non valido o non parsabile")

        exe = argv[0]
        args = argv[1:]
        proc_name = os.path.basename(exe)

        # Già in esecuzione → porta in foreground
        already_running = any(
            p.name().lower() == proc_name.lower()
            for p in psutil.process_iter(["name"])
            if p.info["name"]
        )
        if already_running:
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

        # Primo tentativo: Popen normale
        try:
            subprocess.Popen(
                [exe] + args,
                shell=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
            )
            time.sleep(OPEN_APP_WAIT)
            return StepResult(
                action="open_app", target=target,
                status=StepStatus.SUCCESS,
                elapsed=time.time() - t0,
            )
        except OSError as e:
            if getattr(e, "winerror", None) in (5, 740):
                # Accesso negato o elevazione richiesta → riprova con UAC
                log.info(f"  open_app: '{proc_name}' richiede elevazione, uso ShellExecute runas")
                _shellexecute_elevated(exe, args)
                time.sleep(OPEN_APP_WAIT)
                return StepResult(
                    action="open_app", target=target,
                    status=StepStatus.SUCCESS,
                    message="elevated",
                    elapsed=time.time() - t0,
                )
            raise

    except Exception as e:
        return StepResult(
            action="open_app", target=target,
            status=StepStatus.FAILED, message=str(e),
            elapsed=time.time() - t0,
        )


def action_focus_window(target: str, **kwargs) -> StepResult:
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


def action_run_command(
    target: str,
    timeout: int = DEFAULT_TIMEOUT,
    args: list[str] | None = None,
    use_shell: bool = False,
    **kwargs,
) -> StepResult:
    t0 = time.time()
    try:
        if args:
            command = list(args)
            shell = False
        elif use_shell:
            command = target
            shell = True
        else:
            if _contains_shell_metacharacters(target):
                raise ValueError("Operatori shell rilevati: usa 'use_shell': true per consentirli esplicitamente")
            command = _normalize_argv(target)
            if not command:
                raise ValueError("Comando non valido o vuoto")
            shell = False
        result = subprocess.run(command, shell=shell, capture_output=True, text=True, timeout=timeout)
        status = StepStatus.SUCCESS if result.returncode == 0 else StepStatus.FAILED
        msg = result.stderr.strip() if result.returncode != 0 else ""
        return StepResult(action="run_command", target=target, status=status, message=msg, elapsed=time.time() - t0)
    except subprocess.TimeoutExpired:
        return StepResult(action="run_command", target=target, status=StepStatus.FAILED, message=f"Timeout dopo {timeout}s", elapsed=time.time() - t0)
    except Exception as e:
        return StepResult(action="run_command", target=target, status=StepStatus.FAILED, message=str(e), elapsed=time.time() - t0)


def action_type_text(target: str, **kwargs) -> StepResult:
    t0 = time.time()
    try:
        pyautogui.write(target, interval=0.05)
        return StepResult(action="type_text", target=target, status=StepStatus.SUCCESS, elapsed=time.time() - t0)
    except Exception as e:
        return StepResult(action="type_text", target=target, status=StepStatus.FAILED, message=str(e), elapsed=time.time() - t0)


def action_click(target: str, **kwargs) -> StepResult:
    t0 = time.time()
    try:
        x, y = map(int, target.split(","))
        pyautogui.click(x, y)
        return StepResult(action="click", target=target, status=StepStatus.SUCCESS, elapsed=time.time() - t0)
    except Exception as e:
        return StepResult(action="click", target=target, status=StepStatus.FAILED, message=str(e), elapsed=time.time() - t0)


def action_notify_user(target: str = "", msg: str = "", **kwargs) -> StepResult:
    text = target or msg
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
        return StepResult(action="notify_user", target=text, status=StepStatus.SUCCESS, elapsed=time.time() - t0)
    except Exception as e:
        return StepResult(action="notify_user", target=text, status=StepStatus.FAILED, message=str(e), elapsed=time.time() - t0)


def action_sleep(target: str, **kwargs) -> StepResult:
    t0 = time.time()
    try:
        seconds = float(target)
        time.sleep(seconds)
        return StepResult(action="sleep", target=target, status=StepStatus.SUCCESS, elapsed=time.time() - t0)
    except Exception as e:
        return StepResult(action="sleep", target=target, status=StepStatus.FAILED, message=str(e), elapsed=time.time() - t0)


def _load_config() -> dict:
    """Carica jarvis_config.json dalla cartella data/."""
    config_path = Path(__file__).resolve().parent.parent / "data" / "jarvis_config.json"
    try:
        with open(config_path, encoding="utf-8") as f:
            import json as _json
            return _json.load(f)
    except Exception:
        return {}


def action_close_app(target: str, **kwargs) -> StepResult:
    """
    Chiude un'applicazione per nome processo (es. "Discord", "discord.exe").
    Usa taskkill in modo pulito — non richiede pop-up permessi extra
    perché è un'azione dedicata pre-approvabile.
    """
    t0 = time.time()
    try:
        proc_name = target.strip()
        if not proc_name.lower().endswith(".exe"):
            proc_name = proc_name + ".exe"

        # Prima prova a chiuderlo con grazia (WM_CLOSE)
        killed = False
        for proc in psutil.process_iter(["name", "pid"]):
            if proc.info["name"] and proc.info["name"].lower() == proc_name.lower():
                try:
                    proc.terminate()
                    killed = True
                except Exception:
                    pass

        if not killed:
            # Fallback: taskkill
            result = subprocess.run(
                ["taskkill", "/IM", proc_name, "/F"],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode != 0 and "not found" in result.stderr.lower():
                return StepResult(
                    action="close_app", target=target,
                    status=StepStatus.FAILED,
                    message=f"Processo '{proc_name}' non trovato",
                    elapsed=time.time() - t0,
                )

        return StepResult(action="close_app", target=target, status=StepStatus.SUCCESS, elapsed=time.time() - t0)
    except Exception as e:
        return StepResult(action="close_app", target=target, status=StepStatus.FAILED, message=str(e), elapsed=time.time() - t0)


def action_open_url(target: str, **kwargs) -> StepResult:
    """
    Apre un URL nel browser configurato in jarvis_config.json.
    Se non configurato, usa il browser di sistema.
    """
    t0 = time.time()
    try:
        url = target.strip()
        if not url.startswith("http://") and not url.startswith("https://"):
            url = "https://" + url

        config = _load_config()
        browser_path = config.get("default_browser", "")

        if browser_path and os.path.exists(browser_path):
            subprocess.Popen(
                [browser_path, url],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
            )
        else:
            import webbrowser
            webbrowser.open(url)

        return StepResult(action="open_url", target=url, status=StepStatus.SUCCESS, elapsed=time.time() - t0)
    except Exception as e:
        return StepResult(action="open_url", target=target, status=StepStatus.FAILED, message=str(e), elapsed=time.time() - t0)


# ── Dispatch ──────────────────────────────────────────────────────────────────

ACTION_MAP = {
    "open_app":        action_open_app,
    "close_app":       action_close_app,
    "open_url":        action_open_url,
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
        pyautogui.FAILSAFE = True
        self.permissions = PermissionSystem()

    def run_routine(self, routine: dict, on_step: callable = None) -> RoutineResult:
        result = RoutineResult(name=routine.get("name", "unnamed"))
        steps  = routine.get("steps", [])
        log.info(f"▶ Avvio routine '{result.name}' ({len(steps)} step)")

        for i, step in enumerate(steps):
            action  = step.get("action", "")
            target  = step.get("target", step.get("msg", ""))
            timeout = step.get("timeout", DEFAULT_TIMEOUT)

            if action not in ACTION_MAP:
                sr = StepResult(action=action, target=target, status=StepStatus.FAILED, message=f"Azione sconosciuta: '{action}'")
                result.steps.append(sr)
                log.warning(f"  [{i+1}/{len(steps)}] {action} — AZIONE SCONOSCIUTA")
                if on_step: on_step(i, step, sr)
                continue

            perm = self.permissions.check(action, target)
            if not perm.granted:
                sr = StepResult(action=action, target=target, status=StepStatus.SKIPPED, message=f"Permesso negato — {perm.reason}")
                result.steps.append(sr)
                log.warning(f"  [{i+1}/{len(steps)}] {action} — PERMESSO NEGATO")
                if on_step: on_step(i, step, sr)
                continue

            sr = None
            for attempt in range(MAX_RETRIES):
                sr = ACTION_MAP[action](**{k: v for k, v in step.items() if k != "action"})
                sr.retries = attempt
                if sr.status == StepStatus.SUCCESS:
                    log.info(f"  [{i+1}/{len(steps)}] {action}({target[:40]}) ✓ {round(sr.elapsed, 1)}s" + (f" (retry {attempt})" if attempt > 0 else ""))
                    break
                log.warning(f"  [{i+1}/{len(steps)}] {action}({target[:40]}) ✗ tentativo {attempt+1}/{MAX_RETRIES} — {sr.message}")
                if attempt < MAX_RETRIES - 1:
                    time.sleep(1)

            result.steps.append(sr)
            if on_step: on_step(i, step, sr)

        result.ended_at = datetime.now()
        failed = result.failed_count
        result.status = "success" if failed == 0 else ("failed" if failed == len(steps) else "partial")
        log.info(f"■ {result.summary()}")
        return result

    def run_from_file(self, path: str) -> RoutineResult:
        with open(path, encoding="utf-8") as f:
            routine = json.load(f)
        return self.run_routine(routine)

    def run_from_json(self, json_str: str) -> RoutineResult:
        routine = json.loads(json_str)
        return self.run_routine(routine)


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    routine_path = sys.argv[1] if len(sys.argv) > 1 else "routines/dev_mode.json"
    executor = Executor()
    result   = executor.run_from_file(routine_path)
    print("\n── Riepilogo step ──")
    for sr in result.steps:
        icon = "✓" if sr.status == StepStatus.SUCCESS else "✗"
        print(f"  {icon} {sr.action:<18} {sr.target[:45]:<45} {round(sr.elapsed,1)}s")
    print(f"\n{result.summary()}")