from __future__ import annotations

import os
import shutil
import glob

from core.routine_proposal_types import ProposedRoutineStep


# ── Registry con alias e candidati di ricerca ─────────────────────────────────
# "exe_names": nomi dell'eseguibile da cercare nei path standard
# "target": fallback se non trovato (comando nel PATH di sistema)

APP_REGISTRY: dict[str, dict[str, object]] = {
    "discord": {
        "aliases": ["discord", "discord.exe"],
        "exe_names": ["Discord.exe"],
        "search_hints": [
            r"%LOCALAPPDATA%\Discord",
        ],
        "target": "discord",
    },
    "opera": {
        "aliases": ["opera", "opera.exe"],
        "exe_names": ["opera.exe"],
        "search_hints": [
            r"%LOCALAPPDATA%\Programs\Opera",
            r"%LOCALAPPDATA%\Programs\Opera GX",
        ],
        "target": "opera",
    },
    "visual studio code": {
    "aliases": ["code", "code.exe", "vscode", "visual studio code"],
    "exe_names": ["Code.exe"],
    "search_hints": [
        r"D:\vs_code\Microsoft VS Code",
        r"%LOCALAPPDATA%\Programs\Microsoft VS Code",
        r"%PROGRAMFILES%\Microsoft VS Code",
    ],
    "target": r"D:\vs_code\Microsoft VS Code\Code.exe",
},
    "chrome": {
        "aliases": ["chrome", "chrome.exe", "google chrome"],
        "exe_names": ["chrome.exe"],
        "search_hints": [
            r"%PROGRAMFILES%\Google\Chrome\Application",
            r"%PROGRAMFILES(X86)%\Google\Chrome\Application",
            r"%LOCALAPPDATA%\Google\Chrome\Application",
        ],
        "target": "chrome",
    },
    "brave": {
        "aliases": ["brave", "brave.exe"],
        "exe_names": ["brave.exe"],
        "search_hints": [
            r"%PROGRAMFILES%\BraveSoftware\Brave-Browser\Application",
            r"%LOCALAPPDATA%\BraveSoftware\Brave-Browser\Application",
        ],
        "target": "brave",
    },
    "terminal": {
        "aliases": ["terminal", "windows terminal", "wt", "powershell", "powershell.exe"],
        "exe_names": ["wt.exe"],
        "search_hints": [
            r"%LOCALAPPDATA%\Microsoft\WindowsApps",
        ],
        "target": "wt",
    },
    "cursor": {
        "aliases": ["cursor", "cursor.exe"],
        "exe_names": ["Cursor.exe"],
        "search_hints": [
            r"%LOCALAPPDATA%\Programs\cursor",
            r"%LOCALAPPDATA%\Programs\Cursor",
        ],
        "target": "cursor",
    },
    "docker": {
        "aliases": ["docker", "docker desktop", "docker.exe"],
        "exe_names": ["Docker Desktop.exe"],
        "search_hints": [
            r"%PROGRAMFILES%\Docker\Docker",
        ],
        "target": "docker",
    },
    "slack": {
        "aliases": ["slack", "slack.exe"],
        "exe_names": ["slack.exe"],
        "search_hints": [
            r"%LOCALAPPDATA%\slack",
        ],
        "target": "slack",
    },
    "notion": {
        "aliases": ["notion", "notion.exe"],
        "exe_names": ["Notion.exe"],
        "search_hints": [
            r"%LOCALAPPDATA%\Programs\Notion",
        ],
        "target": "notion",
    },
}


# ── Auto-discovery ─────────────────────────────────────────────────────────────

def _expand(path: str) -> str:
    """Espande le variabili d'ambiente Windows nel path (es. %LOCALAPPDATA%)."""
    return os.path.expandvars(path)


def _find_exe(exe_names: list[str], search_hints: list[str]) -> str | None:
    """
    Cerca un eseguibile in questo ordine:
    1. Path hints specifici dell'app (più veloce e preciso)
    2. Cartelle standard di Windows (%PROGRAMFILES%, %LOCALAPPDATA%, ecc.)
    3. PATH di sistema tramite shutil.which
    """
    # 1. Controlla gli hints specifici
    for hint in search_hints:
        expanded = _expand(hint)
        for exe_name in exe_names:
            full_path = os.path.join(expanded, exe_name)
            if os.path.isfile(full_path):
                return full_path

    # 2. Cerca nelle cartelle standard di Windows
    standard_roots = [
        _expand(r"%PROGRAMFILES%"),
        _expand(r"%PROGRAMFILES(X86)%"),
        _expand(r"%LOCALAPPDATA%\Programs"),
        _expand(r"%LOCALAPPDATA%"),
        _expand(r"%APPDATA%"),
    ]
    for root in standard_roots:
        if not os.path.isdir(root):
            continue
        for exe_name in exe_names:
            # Cerca ricorsivamente (max 3 livelli per non essere lento)
            pattern = os.path.join(root, "**", exe_name)
            matches = glob.glob(pattern, recursive=True)
            # Filtra path che contengono "Uninstall" o "temp"
            matches = [
                m for m in matches
                if not any(x in m.lower() for x in ("uninstall", "temp", "cache", "crash"))
            ]
            if matches:
                return matches[0]

    # 3. Fallback: PATH di sistema
    for exe_name in exe_names:
        found = shutil.which(exe_name)
        if found:
            return found

    return None


# Cache dei target risolti (calcolata una volta sola al primo uso)
_resolved_cache: dict[str, str | None] = {}


def _resolve_target(canonical_name: str) -> str | None:
    """
    Risolve il target reale per un'app: prima prova auto-discovery,
    poi usa il target di fallback dal registry.
    """
    if canonical_name in _resolved_cache:
        return _resolved_cache[canonical_name]

    config = APP_REGISTRY[canonical_name]
    exe_names = config.get("exe_names", [])
    search_hints = config.get("search_hints", [])

    # Prova auto-discovery
    found = _find_exe(exe_names, search_hints) if exe_names else None

    # Fallback al target manuale
    result = found or config.get("target") or None
    if isinstance(result, str):
        result = result.strip() or None

    _resolved_cache[canonical_name] = result
    return result


# ── Lookup ────────────────────────────────────────────────────────────────────

def _normalize_lookup_token(name: str) -> str:
    normalized = name.strip().lower().replace("\\", "/")
    if not normalized:
        return ""
    basename = os.path.basename(normalized)
    if basename.endswith(".exe"):
        basename = basename[:-4]
    return basename.strip()


def normalize_app_name(name: str) -> str | None:
    lookup = _normalize_lookup_token(name)
    if not lookup:
        return None
    for canonical_name, config in APP_REGISTRY.items():
        aliases = config.get("aliases", [])
        candidates = (canonical_name, *[str(alias) for alias in aliases])
        if any(_normalize_lookup_token(candidate) == lookup for candidate in candidates):
            return canonical_name
    return None


def app_target_for(name: str) -> str | None:
    canonical_name = normalize_app_name(name)
    if canonical_name is None:
        return None
    return _resolve_target(canonical_name)


def proposal_step_from_app(app_name: str, action: str = "open_app") -> ProposedRoutineStep | None:
    target = app_target_for(app_name)
    if target is None:
        return None
    return ProposedRoutineStep(action=action, target=target)