"""
Tiny thread-safe publish/subscribe bus.

The core emits events from worker threads; the UI layer subscribes and
forwards them to its own event loop (see ui/bridge.py). Keeping this free of
Qt means the same core can later back a web or CLI frontend.
"""

import logging
import threading
from collections import defaultdict
from typing import Callable, DefaultDict, List


class EventBus:
    def __init__(self):
        self._subscribers: DefaultDict[str, List[Callable]] = defaultdict(list)
        self._lock = threading.Lock()

    def on(self, event: str, callback: Callable) -> None:
        with self._lock:
            self._subscribers[event].append(callback)

    def emit(self, event: str, *args) -> None:
        with self._lock:
            callbacks = list(self._subscribers.get(event, ()))
        for callback in callbacks:
            try:
                callback(*args)
            except Exception:
                logging.exception(f"Event handler for '{event}' failed")
