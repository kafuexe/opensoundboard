"""Run callbacks on the Tk thread from worker threads (Tk isn't thread-safe)."""
from __future__ import annotations

import queue
import threading
from typing import Callable


class Dispatcher:
    def __init__(self, root, interval_ms: int = 30):
        self._root = root
        self._queue: queue.Queue[Callable[[], None]] = queue.Queue()
        self._interval = interval_ms
        root.after(interval_ms, self._drain)

    def call(self, fn: Callable[[], None]) -> None:
        self._queue.put(fn)

    def run_in_background(self, work: Callable[[], object], on_done: Callable[[object], None],
                          on_error: Callable[[Exception], None]) -> None:
        def run() -> None:
            try:
                result = work()
            except Exception as exc:
                self.call(lambda: on_error(exc))
            else:
                self.call(lambda: on_done(result))
        threading.Thread(target=run, daemon=True).start()

    def _drain(self) -> None:
        try:
            while True:
                self._queue.get_nowait()()
        except queue.Empty:
            pass
        self._root.after(self._interval, self._drain)
