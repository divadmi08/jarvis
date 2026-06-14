from __future__ import annotations

import json
import os
import time
import winreg
from pathlib import Path


CACHE_TTL_SECONDS = 24 * 60 * 60
CACHE_FILE = Path(__file__).resolve().parent.parent / "data" / "app_registry_cache.json"

REGISTRY_KEYS = [
    (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
    (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
    (winreg.HKEY_CURRENT_USER,  r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
]

START_MENU_ROOTS = [
    Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs",
    Path(os.environ.get("ProgramData", "C:\\ProgramData")) / "Microsoft" / "Windows" / "Start Menu" / "Programs",
]

# Nomi di exe da scartare come path principale (uninstaller, updater, helper)
_BAD_EXE_STEMS = {
    "uninstall", "unins000", "uninst", "uninstaller",
    "update", "updater", "setup", "install", "installer",
    "crashhandler", "crashreporter", "crashpad_handler",
    "squirrel",
}


def _is_bad_exe(path: str) -> bool:
    stem = Path(path).stem.lower()
    return any(bad in stem for bad in _BAD_EXE_STEMS)


def _best_exe_in_dir(location: str, name_hint: str) -> str | None:
    """Cerca il miglior exe in una cartella data un hint sul nome."""
    try:
        loc = Path(location)
        if not loc.is_dir():
            return None
        candidates = [f for f in loc.iterdir() if f.suffix.lower() == ".exe" and not _is_bad_exe(str(f))]
        if not candidates:
            return None
        # Preferisci exe il cui nome contiene l'hint
        hint = name_hint.lower().split()[0]
        for c in candidates:
            if hint in c.stem.lower():
                return str(c)
        # Fallback: il più corto (di solito il main exe)
        return str(min(candidates, key=lambda f: len(f.stem)))
    except OSError:
        return None


def _read_registry_apps() -> dict[str, str]:
    apps: dict[str, str] = {}

    for hive, subkey in REGISTRY_KEYS:
        try:
            key = winreg.OpenKey(hive, subkey)
        except OSError:
            continue

        i = 0
        while True:
            try:
                subkey_name = winreg.EnumKey(key, i)
                i += 1
            except OSError:
                break

            try:
                app_key = winreg.OpenKey(key, subkey_name)
            except OSError:
                continue

            try:
                display_name, _ = winreg.QueryValueEx(app_key, "DisplayName")
                display_name = str(display_name).strip()
                if not display_name:
                    continue

                exe_path = None

                # 1. DisplayIcon → spesso punta all'exe principale
                try:
                    icon, _ = winreg.QueryValueEx(app_key, "DisplayIcon")
                    icon = str(icon).split(",")[0].strip().strip('"')
                    if (icon.lower().endswith(".exe")
                            and os.path.exists(icon)
                            and not _is_bad_exe(icon)):
                        exe_path = icon
                except OSError:
                    pass

                # 2. InstallLocation → cerca l'exe con hint
                if not exe_path:
                    try:
                        location, _ = winreg.QueryValueEx(app_key, "InstallLocation")
                        location = str(location).strip().strip('"')
                        if location:
                            exe_path = _best_exe_in_dir(location, display_name)
                    except OSError:
                        pass

                if exe_path and os.path.exists(exe_path):
                    key_name = display_name.lower()
                    if key_name not in apps or len(exe_path) < len(apps[key_name]):
                        apps[key_name] = exe_path

            except OSError:
                pass
            finally:
                try:
                    winreg.CloseKey(app_key)
                except Exception:
                    pass

        winreg.CloseKey(key)

    return apps


def _read_startmenu_apps() -> dict[str, str]:
    apps: dict[str, str] = {}
    try:
        import win32com.client  # type: ignore
        shell = win32com.client.Dispatch("WScript.Shell")
    except Exception:
        return apps

    for root in START_MENU_ROOTS:
        if not root.exists():
            continue
        for lnk in root.rglob("*.lnk"):
            try:
                shortcut = shell.CreateShortCut(str(lnk))
                target = shortcut.Targetpath
                if (target
                        and target.lower().endswith(".exe")
                        and os.path.exists(target)
                        and not _is_bad_exe(target)):
                    name = lnk.stem.lower()
                    if name not in apps or len(target) < len(apps[name]):
                        apps[name] = target
            except Exception:
                continue

    return apps


def scan_installed_apps(force: bool = False) -> dict[str, str]:
    """
    Costruisce il registry delle app installate da:
    1. Windows Registry (fonte primaria)
    2. Menu Start shortcuts .lnk (fonte supplementare)
    Cache su disco per 24h.
    """
    if not force and CACHE_FILE.exists():
        age = time.time() - CACHE_FILE.stat().st_mtime
        if age < CACHE_TTL_SECONDS:
            try:
                with open(CACHE_FILE, encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError):
                pass

    apps = _read_registry_apps()

    for name, path in _read_startmenu_apps().items():
        if name not in apps:
            apps[name] = path

    try:
        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(apps, f, ensure_ascii=False, indent=2)
    except OSError:
        pass

    return apps


def find_app(name: str, apps: dict[str, str] | None = None) -> str | None:
    """
    Cerca un'app per nome (case-insensitive).
    1. Match esatto
    2. needle contenuto nel nome display (es. "steam" trova "steam")
    3. nome display contenuto nel needle (es. "obs" trovato in "obs studio")
    """
    apps = apps if apps is not None else scan_installed_apps()
    needle = name.strip().lower()

    if not needle:
        return None

    if needle in apps:
        return apps[needle]

    if len(needle) < 4:
        return None

    for app_name, path in apps.items():
        if needle in app_name:
            return path

    for app_name, path in apps.items():
        if len(app_name) >= 4 and app_name in needle:
            return path

    return None


def format_apps_for_prompt(apps: dict[str, str], limit: int = 100) -> str:
    if not apps:
        return "No installed applications found."
    lines = [f"{name} -> {path}" for name, path in list(apps.items())[:limit]]
    return "Installed applications (display name -> exe path):\n" + "\n".join(lines)


if __name__ == "__main__":
    found = scan_installed_apps(force=True)
    print(f"Trovate {len(found)} app.")
    for app_name, app_path in sorted(found.items()):
        print(f"  {app_name:<40} {app_path}")


ALIASES_FILE = Path(__file__).resolve().parent.parent / "data" / "app_aliases.json"


def load_aliases() -> dict[str, str]:
    """Carica alias manuali da data/app_aliases.json."""
    try:
        with open(ALIASES_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return {k.lower(): v for k, v in data.items() if not k.startswith("_")}
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}