from __future__ import annotations

from datetime import datetime
import atexit
import threading
import time

from utils.window_utils import get_active_window

class Observer:
    def __init__(self, db, poll_interval: float = 2.0, clock=None, sleep_fn=None):
        self.db = db
        self.poll_interval = poll_interval
        self.current_app = None
        self.current_title = None
        self.last_switch_time = None
        self.clock = clock or datetime.now
        self.sleep_fn = sleep_fn or time.sleep
        self._flush_lock = threading.Lock()
        atexit.register(self.flush_current_activity)

    def flush_current_activity(self, end_time: datetime | None = None) -> bool:
        with self._flush_lock:
            if self.current_app is None or self.last_switch_time is None:
                return False

            flush_time = end_time or self.clock()
            duration = (flush_time - self.last_switch_time).total_seconds()
            if duration <= 0:
                return False

            self.db.save_activity(
                self.current_app,
                self.current_title,
                self.last_switch_time.isoformat(),
                flush_time.isoformat(),
                duration,
            )
            self.last_switch_time = flush_time
            return True

    def observe(self, stop_event: threading.Event | None = None):
        while not (stop_event and stop_event.is_set()):
            try:
                app, title = get_active_window()
                now = self.clock()

                if self.current_app is None:
                    self.current_app = app
                    self.current_title = title
                    self.last_switch_time = now

                elif app != self.current_app or title != self.current_title:
                    self.flush_current_activity(now)
                    self.current_app = app
                    self.current_title = title
                    self.last_switch_time = now

                self.sleep_fn(self.poll_interval)

            except Exception as e:
                print("Observer error:", e)
                self.sleep_fn(self.poll_interval)

        self.flush_current_activity()
