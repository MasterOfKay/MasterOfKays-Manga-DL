"""
Background checks for new chapters.

Events on the bus:
    check_state     (manga_id, checking: bool)
    new_chapters    (manga_id, title, count)
    check_progress  (done, total)
    check_finished  (new_total, manga_with_new, errors, manual)
    notify          (event, title, message, level)
"""

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Optional, Set

from .downloads import DownloadManager
from .events import EventBus
from .library import Library

MAX_PARALLEL_CHECKS = 3


class UpdateChecker:
    def __init__(self, library: Library, downloads: DownloadManager, settings, bus: EventBus):
        self.library = library
        self.downloads = downloads
        self.settings = settings
        self.bus = bus
        self._lock = threading.Lock()
        self._checking: Set[int] = set()
        self._bulk_running = False
        self._stop = threading.Event()
        self._timer = threading.Thread(target=self._timer_loop, name="update-timer", daemon=True)

    # ------------------------------------------------------------ lifecycle
    def start(self) -> None:
        if not self._timer.is_alive():
            self._timer.start()

    def stop(self) -> None:
        self._stop.set()

    # ------------------------------------------------------------------ API
    @property
    def bulk_running(self) -> bool:
        return self._bulk_running

    def is_checking(self, manga_id: int) -> bool:
        with self._lock:
            return manga_id in self._checking

    def last_check(self) -> Optional[datetime]:
        value = self.settings.get('updates.last_check', '')
        try:
            return datetime.fromisoformat(value) if value else None
        except ValueError:
            return None

    def check_all(self, manual: bool = True) -> bool:
        """Check every manga in a background thread. Returns False if a full check is already running."""
        with self._lock:
            if self._bulk_running:
                return False
            self._bulk_running = True
        threading.Thread(target=self._check_all, args=(manual,), name="update-check", daemon=True).start()
        return True

    def check_one(self, manga_id: int) -> bool:
        with self._lock:
            if manga_id in self._checking:
                return False
            self._checking.add(manga_id)
        threading.Thread(target=self._check_single, args=(manga_id,), name=f"check-{manga_id}", daemon=True).start()
        return True

    # -------------------------------------------------------------- workers
    def _timer_loop(self) -> None:
        if self.settings.get('updates.auto_check') and self.settings.get('updates.check_on_startup'):
            if self._stop.wait(8):          # let the window settle first
                return
            self.check_all(manual=False)
        while not self._stop.wait(30):
            if not self.settings.get('updates.auto_check'):
                continue
            interval = max(5, int(self.settings.get('updates.interval_minutes', 60))) * 60
            last = self.last_check()
            if last is None or (datetime.now() - last).total_seconds() >= interval:
                self.check_all(manual=False)

    def _check_single(self, manga_id: int) -> None:
        try:
            new = self._run_check(manga_id, already_marked=True)
            manga = self.library.get_manga(manga_id) or {}
            if new == 0:
                self.bus.emit('notify', 'manual', manga.get('title', 'Manga'), 'No new chapters', 'info')
        except Exception as e:
            title = (self.library.get_manga(manga_id) or {}).get('title', 'Manga')
            self.bus.emit('notify', 'errors', f"Couldn't check {title}", str(e), 'error')

    def _check_all(self, manual: bool) -> None:
        new_total = manga_with_new = errors = 0
        try:
            mangas = [m for m in self.library.list_manga() if m.get('url')]
            self.bus.emit('check_progress', 0, len(mangas))
            with ThreadPoolExecutor(max_workers=MAX_PARALLEL_CHECKS, thread_name_prefix="check") as pool:
                futures = {pool.submit(self._run_check, m['id']): m for m in mangas}
                for done, future in enumerate(as_completed(futures), start=1):
                    try:
                        count = future.result()
                        if count:
                            new_total += count
                            manga_with_new += 1
                    except Exception as e:
                        errors += 1
                        logging.warning(f"Update check failed for {futures[future].get('title')}: {e}")
                    self.bus.emit('check_progress', done, len(mangas))
        finally:
            self.settings.set('updates.last_check', datetime.now().isoformat(timespec='seconds'))
            with self._lock:
                self._bulk_running = False
            self.bus.emit('check_finished', new_total, manga_with_new, errors, manual)
            if manual and new_total == 0:
                detail = "Everything is up to date" + (f" ({errors} couldn't be checked)" if errors else "")
                self.bus.emit('notify', 'manual', 'Update check finished', detail, 'warning' if errors else 'info')

    def _run_check(self, manga_id: int, already_marked: bool = False) -> int:
        if not already_marked:
            with self._lock:
                if manga_id in self._checking:
                    return 0
                self._checking.add(manga_id)
        self.bus.emit('check_state', manga_id, True)
        try:
            new_refs = self.library.refresh(manga_id)
            if new_refs:
                manga = self.library.get_manga(manga_id) or {}
                title = manga.get('title', 'Manga')
                self.bus.emit('new_chapters', manga_id, title, len(new_refs))
                if self.settings.notification_enabled('new_chapters'):
                    numbers = ', '.join(r.number for r in new_refs[:5]) + ('…' if len(new_refs) > 5 else '')
                    noun = 'chapter' if len(new_refs) == 1 else 'chapters'
                    self.bus.emit('notify', 'new_chapters', title, f"{len(new_refs)} new {noun}: {numbers}", 'accent')
            if self.settings.get('updates.auto_download'):
                # New chapters, plus new ones that were early access before and are free now.
                unlocked = [r for r in self.library.chapters(manga_id)
                            if r.is_new and r.free_at and not r.downloaded and not r.early_access]
                wanted = {r.key: r for r in new_refs + unlocked if not r.early_access}
                if wanted:
                    self.downloads.add(manga_id, list(wanted.values()))
            return len(new_refs)
        finally:
            with self._lock:
                self._checking.discard(manga_id)
            self.bus.emit('check_state', manga_id, False)
            time.sleep(0.2)   # be gentle with the sites
