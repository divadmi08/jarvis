from datetime import datetime
import time
from utils.window_utils import get_active_window

class Observer:
    def __init__(self, db):
        self.db = db
        self.current_app = None
        self.current_title = None
        self.last_switch_time = None

    def observe(self):
        while True:
            try:
                app, title = get_active_window()
                now = datetime.now()

                if self.current_app is None:
                    self.current_app = app
                    self.current_title = title
                    self.last_switch_time = now

                elif app != self.current_app or title != self.current_title:

                    duration = (now - self.last_switch_time).total_seconds()

                    if duration > 0:
                        self.db.save_activity(
                            self.current_app,
                            self.current_title,
                            self.last_switch_time.isoformat(),
                            now.isoformat(),
                            duration
                        )

                    self.current_app = app
                    self.current_title = title
                    self.last_switch_time = now

                time.sleep(2)

            except Exception as e:
                print("Observer error:", e)
                time.sleep(2)