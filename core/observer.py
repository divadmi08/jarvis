import time
import win32gui
import win32process
import psutil

from data.database import get_connection


class Observer:

    def observe(self):

        hwnd = win32gui.GetForegroundWindow()

        window_title = win32gui.GetWindowText(hwnd)

        _, pid = win32process.GetWindowThreadProcessId(hwnd)

        try:
            process = psutil.Process(pid)
            app_name = process.name()

        except Exception:
            app_name = "Unknown"

        self.save_activity(
            app_name,
            window_title
        )

        print(f"{app_name} | {window_title}")

    def save_activity(
        self,
        app_name,
        window_title
    ):

        conn = get_connection()

        cursor = conn.cursor()

        cursor.execute("""
        INSERT INTO activity_log
        (
            app_name,
            window_title,
            duration_sec
        )
        VALUES (?, ?, ?)
        """, (
            app_name,
            window_title,
            5
        ))

        conn.commit()
        conn.close()