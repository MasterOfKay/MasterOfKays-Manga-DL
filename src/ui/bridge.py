"""
Forwards core EventBus events (emitted on worker threads) to Qt signals.
Qt queues cross-thread signal deliveries, so slots always run on the UI thread.
"""

from PySide6.QtCore import QObject, Signal

from ..core.events import EventBus


class Bridge(QObject):
    queue_changed = Signal()
    job_progress = Signal(int)
    job_finished = Signal(int, str)
    chapter_state = Signal(int, str, str, str, int)    # manga_id, language, number, state, progress
    library_changed = Signal(int)
    check_state = Signal(int, bool)
    check_progress = Signal(int, int)
    check_finished = Signal(int, int, int, bool)
    new_chapters = Signal(int, str, int)
    notify = Signal(str, str, str, str)                 # event, title, message, level
    app_update_changed = Signal()
    app_update_progress = Signal(int, int)              # bytes done, total

    def __init__(self, bus: EventBus):
        super().__init__()
        for name in ('queue_changed', 'job_progress', 'job_finished', 'chapter_state', 'library_changed',
                     'check_state', 'check_progress', 'check_finished', 'new_chapters', 'notify',
                     'app_update_changed', 'app_update_progress'):
            bus.on(name, getattr(self, name).emit)
