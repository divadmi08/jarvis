from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Iterable


CACHE_TTL_SECONDS = 24 * 60 * 60  # 1 giorno
CACHE_FILE = Path(__file__).resolve().parent.parent / "data" / "app_registry_cache.json"

# Cartelle in cui cercare eseguibili.
SEARCH_ROOTS: list[str] = [
    os.environ.get("LOCALAPPDATA", ""),
    os.environ.get("APPDATA", ""),
    os.environ.get("ProgramFiles", ""),
    os.environ.get("ProgramFiles(x86)", ""),
    os.environ.get("ProgramW6432", ""),
    str(Path.home() / "Desktop"),
    # Cartelle di sistema per app native Windows (explorer, notepad, ecc.)
    str(Path(os.environ.get("SystemRoot", "C:\\Windows")) / "System32"),
    str(Path(os.environ.get("SystemRoot", "C:\\Windows")) / "SysWOW64"),
]

# Cartelle che vogliamo scansionare solo superficialmente (depth 1)
# per evitare scan lenti su alberi enormi come System32.
MAX_DEPTH = 4  # profondità massima per i root standard

# Cartelle scansionate solo superficialmente (depth 1) per evitare
# scan lenti su alberi enormi come System32.
SHALLOW_ROOTS: set[str] = {
    str(Path(os.environ.get("SystemRoot", "C:\\Windows")) / "System32"),
    str(Path(os.environ.get("SystemRoot", "C:\\Windows")) / "SysWOW64"),
}

# Cartelle da escludere per non perdere tempo / evitare rumore.
EXCLUDE_DIR_NAMES = {
    "node_modules", "__pycache__", ".git", "Windows",
    "WindowsApps", "Temp", "Cache", "Crashpad", "logs",
}


def _is_excluded(dirname: str) -> bool:
    return dirname in EXCLUDE_DIR_NAMES or dirname.startswith(".")


def _iter_exe_files(root: str, max_depth: int) -> Iterable[Path]:
    root_path = Path(root)
    if not root_path.exists():
        return

    root_depth = len(root_path.parts)
    for current_root, dirnames, filenames in os.walk(root_path):
        depth = len(Path(current_root).parts) - root_depth
        if depth >= max_depth:
            dirnames[:] = []
            continue

        dirnames[:] = [d for d in dirnames if not _is_excluded(d)]

        for filename in filenames:
            if filename.lower().endswith(".exe"):
                yield Path(current_root) / filename


def scan_installed_apps(force: bool = False) -> dict[str, str]:
    """
    Scansiona il filesystem per trovare eseguibili (.exe) installati.

    Ritorna un dizionario {nome_app_lowercase: path_assoluto}.
    Usa una cache su disco con TTL di 1 giorno per evitare scan ripetuti
    (la scansione completa può richiedere diversi secondi/minuti).
    """
    if not force and CACHE_FILE.exists():
        age = time.time() - CACHE_FILE.stat().st_mtime
        if age < CACHE_TTL_SECONDS:
            try:
                with open(CACHE_FILE, encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError):
                pass  # cache corrotta, ri-scansiona

    apps: dict[str, str] = {}
    for root in SEARCH_ROOTS:
        if not root:
            continue
        depth = 1 if root in SHALLOW_ROOTS else MAX_DEPTH
        for exe_path in _iter_exe_files(root, depth):
            name = exe_path.stem.lower()
            existing = apps.get(name)
            # Preferisci path più corti (di solito sono l'eseguibile principale,
            # non file dentro sottocartelle versionate/cache).
            if existing is None or len(str(exe_path)) < len(existing):
                apps[name] = str(exe_path)

    try:
        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(apps, f, ensure_ascii=False, indent=2)
    except OSError:
        pass

    return apps


def find_app(name: str, apps: dict[str, str] | None = None) -> str | None:
    """
    Cerca un'app per nome (case-insensitive, match parziale).
    Ritorna il path assoluto del primo match o None.
    """
    apps = apps if apps is not None else scan_installed_apps()
    needle = name.strip().lower()

    if not needle:
        return None

    if needle in apps:
        return apps[needle]

    # Match parziale: richiede almeno 3 caratteri per evitare falsi positivi
    # (es. una needle vuota o di 1-2 caratteri che "matcherebbe" quasi tutto
    # tramite l'operatore `in`).
    if len(needle) < 3:
        return None

    for app_name, path in apps.items():
        if len(app_name) < 3:
            continue
        if needle in app_name or app_name in needle:
            return path

    return None


def format_apps_for_prompt(apps: dict[str, str], limit: int = 60) -> str:
    """
    Formatta la lista app in modo compatto per inserirla nel context del planner.
    Limita il numero di righe per non gonfiare troppo il prompt.
    """
    if not apps:
        return "No installed applications found."

    lines = [f"{name} -> {path}" for name, path in list(apps.items())[:limit]]
    return "Installed applications (name -> path):\n" + "\n".join(lines)


if __name__ == "__main__":
    found = scan_installed_apps(force=True)
    print(f"Trovate {len(found)} app.")
    for app_name, app_path in sorted(found.items()):
        print(f"  {app_name:<30} {app_path}")