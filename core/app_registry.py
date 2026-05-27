from __future__ import annotations

import os

from core.routine_proposal_types import ProposedRoutineStep


APP_REGISTRY: dict[str, dict[str, object]] = {
    "discord": {
        "aliases": ["discord", "discord.exe"],
        "target": "discord",
    },
    "opera": {
        "aliases": ["opera", "opera.exe"],
        "target": "opera",
    },
    "visual studio code": {
        "aliases": ["code", "code.exe", "vscode", "visual studio code"],
        "target": "code",
    },
    "chrome": {
        "aliases": ["chrome", "chrome.exe", "google chrome"],
        "target": "chrome",
    },
    "brave": {
        "aliases": ["brave", "brave.exe"],
        "target": "brave",
    },
    "terminal": {
        "aliases": ["terminal", "windows terminal", "wt", "powershell", "powershell.exe"],
        "target": "wt",
    },
    "cursor": {
        "aliases": ["cursor", "cursor.exe"],
        "target": "cursor",
    },
    "docker": {
        "aliases": ["docker", "docker desktop", "docker.exe"],
        "target": "docker",
    },
    "slack": {
        "aliases": ["slack", "slack.exe"],
        "target": "slack",
    },
    "notion": {
        "aliases": ["notion", "notion.exe"],
        "target": "notion",
    },
}


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
    config = APP_REGISTRY[canonical_name]
    target = config.get("target")
    return str(target) if isinstance(target, str) and target else None


def proposal_step_from_app(app_name: str, action: str = "open_app") -> ProposedRoutineStep | None:
    target = app_target_for(app_name)
    if target is None:
        return None
    return ProposedRoutineStep(action=action, target=target)
