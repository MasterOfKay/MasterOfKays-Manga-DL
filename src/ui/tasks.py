"""
Run blocking work (network, disk) off the UI thread and get the result back
on the UI thread.
"""

import logging
from typing import Any, Callable, Optional, Set

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal


class _Relay(QObject):
    done = Signal(object)
    failed = Signal(str)


class _Task(QRunnable):
    def __init__(self, fn: Callable[[], Any], relay: _Relay):
        super().__init__()
        self.fn = fn
        self.relay = relay

    def run(self) -> None:
        try:
            try:
                result = self.fn()
            except Exception as e:
                logging.exception("Background task failed")
                self.relay.failed.emit(str(e) or e.__class__.__name__)
            else:
                self.relay.done.emit(result)
        except RuntimeError:
            pass   # the app was closed while this task was still running


_alive: Set[_Relay] = set()


def _safe(callback: Optional[Callable], *args) -> None:
    if callback is None:
        return
    try:
        callback(*args)
    except RuntimeError as e:
        # The widget that asked for the result was closed in the meantime.
        if 'already deleted' not in str(e):
            raise


def run_async(fn: Callable[[], Any], on_done: Optional[Callable[[Any], None]] = None,
              on_error: Optional[Callable[[str], None]] = None) -> None:
    relay = _Relay()
    _alive.add(relay)

    def finished(result):
        _alive.discard(relay)
        _safe(on_done, result)

    def failed(message):
        _alive.discard(relay)
        _safe(on_error, message)

    relay.done.connect(finished)
    relay.failed.connect(failed)
    QThreadPool.globalInstance().start(_Task(fn, relay))
