import win32gui
import win32process
import psutil


def clean_window_title(title: str) -> str:
    if not title:
        return "Unknown"

    title = title.strip()

    if title == "":
        return "Unknown"

    # rimuove spazi multipli
    title = " ".join(title.split())

    return title


def get_active_window():
    try:
        hwnd = win32gui.GetForegroundWindow()
        title = win32gui.GetWindowText(hwnd)

        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        process = psutil.Process(pid)

        app = process.name()

        title = clean_window_title(title)

        if not app:
            app = "Unknown"

        return app, title

    except Exception:
        return "Unknown", "Unknown"