import time
import threading
from typing import Optional, Callable
from core.sync_engine import SyncEngine

class SyncWatcher:
    def __init__(self, engine: SyncEngine, interval_seconds: int = 300):
        self.engine = engine
        self.interval_seconds = interval_seconds
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        self.engine.log(f"Watcher started. Checking every {self.interval_seconds} seconds.")

    def stop(self):
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2)
            self._thread = None
        self.engine.log("Watcher stopped.")

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _run_loop(self):
        # Run immediately upon start
        self.engine.run_sync_cycle()

        while not self._stop_event.is_set():
            # Wait with check intervals so stop is responsive
            for _ in range(self.interval_seconds):
                if self._stop_event.is_set():
                    break
                time.sleep(1)

            if not self._stop_event.is_set():
                self.engine.run_sync_cycle()
