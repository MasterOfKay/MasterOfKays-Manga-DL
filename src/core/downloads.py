"""
Download queue. One worker thread processes jobs (one job = one manga with a
list of chapters) in order. Everything the UI needs to know is published on
the EventBus:

    queue_changed       ()                                   jobs added/removed/status changed
    job_progress        (job_id)                             counters/progress of a job changed
    chapter_state       (manga_id, language, number, state, progress)
    job_finished        (job_id, status)
    notify              (event, title, message, level)
"""

import itertools
import json
import logging
import os
import re
import shutil
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from ..sites.base import ChapterInfo, ChapterUnavailable, StorageUnavailable
from .events import EventBus
from .library import Library
from .metadata_files import embed_chapter_metadata, write_folder_metadata
from .models import MULTI_LANGUAGE_SITES, ChapterKey, ChapterRef, chapter_file_name, is_novel_url
from .paths import data_dir

QUEUED, DOWNLOADING, DONE, FAILED, CANCELLED = 'queued', 'downloading', 'done', 'failed', 'cancelled'
JOB_QUEUED, JOB_RUNNING, JOB_PAUSED = 'queued', 'downloading', 'paused'
JOB_DONE, JOB_FAILED, JOB_CANCELLED = 'done', 'failed', 'cancelled'
FINISHED_STATES = (JOB_DONE, JOB_FAILED, JOB_CANCELLED)

_ids = itertools.count(1)

# Storage problems stop the whole queue (every job writes to the same place) until they are fixed.
STORAGE_OFFLINE, STORAGE_FULL = 'offline', 'full'
MIN_FREE_BYTES = 100 * 1024 * 1024
_DISK_FULL = re.compile(r'Errno 28\]|No space left|WinError (112|39)\]|not enough space|disk is full', re.I)


def storage_problem(root: str, error: str = '') -> Optional[Tuple[str, str]]:
    """(kind, message) when the download folder is unreachable or (nearly) full, else None."""
    if not os.path.isdir(root):
        return STORAGE_OFFLINE, f"The download folder can't be reached: {root}"
    try:
        free = shutil.disk_usage(root).free
    except OSError:
        free = None
    if (free is not None and free < MIN_FREE_BYTES) or _DISK_FULL.search(error or ''):
        # A share can report free space but still refuse writes (quota) - only show small numbers.
        left = f" ({free / 1024 ** 2:.0f} MB left)" if free is not None and free < 1024 ** 3 else ''
        return STORAGE_FULL, f"The drive is full{left}"
    return None


@dataclass
class Job:
    manga_id: int
    title: str
    url: str
    site_type: str
    cover_path: str = ''
    folder_name: str = ''            # existing folder on disk (may differ from the title in case/punctuation)
    chapters: List[ChapterRef] = field(default_factory=list)
    id: int = field(default_factory=lambda: next(_ids))
    status: str = JOB_QUEUED
    states: Dict[ChapterKey, str] = field(default_factory=dict)
    progress: Dict[ChapterKey, int] = field(default_factory=dict)
    current: Optional[ChapterRef] = None
    error: str = ''
    errors: Dict[ChapterKey, str] = field(default_factory=dict)   # why a chapter failed
    paused: bool = False
    user_paused: bool = False        # paused by the user (not just for closing the app)
    cancelled: bool = False
    blocked: str = ''                # stopped by a storage problem (drive offline/full) - the message

    @property
    def total(self) -> int:
        return len(self.chapters)

    @property
    def done_count(self) -> int:
        return sum(1 for s in self.states.values() if s == DONE)

    @property
    def failed_count(self) -> int:
        return sum(1 for s in self.states.values() if s == FAILED)

    @property
    def finished(self) -> bool:
        return self.status in FINISHED_STATES

    @property
    def percent(self) -> float:
        """Overall progress 0..100, including the partial current chapter."""
        if not self.total:
            return 0.0
        handled = sum(1 for s in self.states.values() if s in (DONE, FAILED))
        partial = self.progress.get(self.current.key, 0) / 100 if self.current and self.status == JOB_RUNNING else 0
        return min(100.0, (handled + partial) * 100 / self.total)


# Chapters after the current one that sites with slow page servers may start loading.
READ_AHEAD = 3


class DownloadManager:
    def __init__(self, library: Library, settings, bus: EventBus):
        self.library = library
        self.settings = settings
        self.bus = bus
        self._jobs: List[Job] = []
        self._lock = threading.RLock()
        self._wake = threading.Condition(self._lock)
        self._stopping = False
        self._draining = False           # closing: finish the current chapter, start nothing new
        self._restoring = False
        self._storage: Optional[Tuple[str, str]] = None    # (kind, message) while the queue is stopped
        self._storage_root = ''      # folder the current/blocked job saves to (novels may have their own)
        self._save_lock = threading.Lock()
        self.queue_file = os.path.join(data_dir(), 'queue.json')
        self._thread = threading.Thread(target=self._run, name="downloader", daemon=True)
        bus.on('queue_changed', self.save_queue)     # keep the saved queue current (also survives crashes)

# Lifecycle: start() is called when the app starts, shutdown() when it is closing. The queue is saved
# with each change, so it is always up to date. prepare_shutdown() is called when the user closes the app, 
# so the worker can finish the current chapter and save the queue before the app exits
    def start(self) -> None:
        self.restore_queue()
        if not self._thread.is_alive():
            self._thread.start()

    def shutdown(self) -> None:
        """Stop the worker. Call save_queue()/prepare_shutdown() first - nothing is saved here."""
        with self._lock:
            self._stopping = True
            for job in self._jobs:
                job.cancelled = True
            self._wake.notify_all()

    def prepare_shutdown(self) -> None:
        """Pause everything so the worker stops after the chapter it is on. The queue is
        saved with each job's own paused state, so it continues on the next start."""
        with self._lock:
            self._draining = True
            for job in self._jobs:
                if not job.finished:
                    job.paused = True
                    if job.status == JOB_QUEUED:
                        job.status = JOB_PAUSED
            self._wake.notify_all()
        self.save_queue()
        self.bus.emit('queue_changed')

    def is_busy(self) -> bool:
        """True while a chapter is still being downloaded."""
        with self._lock:
            return any(j.status == JOB_RUNNING for j in self._jobs)

    def current_chapter(self) -> Optional[tuple]:
        with self._lock:
            job = next((j for j in self._jobs if j.status == JOB_RUNNING), None)
            return (job.title, job.current.number) if job and job.current else None

# Queue persistence: the queue is saved to a JSON file in the app data folder. It is restored on start.
    def save_queue(self) -> None:
        if self._stopping or self._restoring:
            return
        with self._lock:
            data = {'version': 1, 'jobs': [
                {'manga_id': j.manga_id, 'title': j.title, 'paused': j.user_paused,
                 'chapters': [list(c.key) for c in j.chapters if j.states.get(c.key) in (QUEUED, DOWNLOADING)]}
                for j in self._jobs if not j.finished and not j.cancelled
            ]}
        data['jobs'] = [j for j in data['jobs'] if j['chapters']]
        with self._save_lock:
            try:
                tmp = self.queue_file + '.tmp'
                with open(tmp, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=1)
                os.replace(tmp, self.queue_file)
            except OSError as e:
                logging.warning(f"Could not save the download queue: {e}")

    def restore_queue(self) -> int:
        """Re-queue what was waiting when the app was closed. Returns the number of chapters."""
        try:
            with open(self.queue_file, encoding='utf-8') as f:
                saved = json.load(f).get('jobs', [])
        except (OSError, ValueError):
            return 0
        restored = 0
        self._restoring = True
        try:
            for entry in saved:
                order = {tuple(k): i for i, k in enumerate(entry.get('chapters', []))}
                refs = [r for r in self.library.chapters(entry.get('manga_id', 0))
                        if r.key in order and not r.downloaded]
                refs.sort(key=lambda r: order[r.key])
                job = self.add(entry['manga_id'], refs)
                if job is None:
                    continue
                restored += len(refs)
                if entry.get('paused'):
                    self.pause(job.id)
        finally:
            self._restoring = False
        self.save_queue()
        if restored:
            logging.info(f"Restored {restored} queued chapters from the last session")
        return restored

    # ------------------------------------------------------------------ API
    def add(self, manga_id: int, chapters: List[ChapterRef]) -> Optional[Job]:
        """Queue chapters of a manga. Merges into a waiting/running job of the
        same manga instead of creating a duplicate."""
        manga = self.library.get_manga(manga_id)
        chapters = [c for c in chapters if not c.early_access]     # still behind the paywall
        if not manga or not chapters:
            return None
        with self._lock:
            job = next((j for j in self._jobs if j.manga_id == manga_id and not j.finished), None)
            if job is None:
                job = Job(manga_id=manga_id, title=manga['title'], url=manga['url'],
                          site_type=manga['site_type'], cover_path=manga.get('cover_image_path') or '')
                self._jobs.append(job)
            added = 0
            for ref in chapters:
                if job.states.get(ref.key) in (QUEUED, DOWNLOADING):
                    continue
                if ref.key not in job.states:
                    job.chapters.append(ref)
                else:       # downloaded again - maybe from another release group now
                    job.chapters = [ref if c.key == ref.key else c for c in job.chapters]
                job.states[ref.key] = QUEUED
                job.progress[ref.key] = 0
                added += 1
            if not added:
                return job
            self._wake.notify_all()
        for ref in chapters:
            self.bus.emit('chapter_state', manga_id, ref.language, ref.number, QUEUED, 0)
        self.bus.emit('queue_changed')
        self.bus.emit('job_progress', job.id)
        return job

    def pause(self, job_id: int) -> None:
        self._set_paused(job_id, True)

    def resume(self, job_id: int) -> None:
        with self._lock:
            job = self._find(job_id)
            blocked = bool(job and job.blocked)
        self._set_paused(job_id, False)
        if blocked:
            self.resume_storage()

    def storage_error(self) -> Optional[Tuple[str, str]]:
        with self._lock:
            return self._storage

    def resume_storage(self) -> None:
        """Continue after the drive is back / has space again. If it still isn't fixed
        the queue simply stops again at the next chapter."""
        with self._lock:
            self._storage = None
            for job in self._jobs:
                if job.blocked:
                    job.blocked = ''
                    if job.status == JOB_PAUSED and not job.paused:
                        job.status = JOB_QUEUED
            self._wake.notify_all()
        self.bus.emit('queue_changed')

    def chapter_error(self, manga_id: int, key: ChapterKey) -> str:
        with self._lock:
            for job in reversed(self._jobs):
                if job.manga_id == manga_id and key in job.errors:
                    return job.errors[key]
        return ''

    def cancel(self, job_id: int) -> None:
        with self._lock:
            job = self._find(job_id)
            if not job or job.finished:
                return
            job.cancelled = True
            job.paused = False
            finished_now = job.status != JOB_RUNNING
            if finished_now:
                self._finish_cancelled(job)
            self._wake.notify_all()
        self.bus.emit('queue_changed')
        if finished_now:
            self.bus.emit('job_finished', job.id, job.status)

    def remove_finished(self, job_id: Optional[int] = None) -> None:
        with self._lock:
            self._jobs = [j for j in self._jobs if not (j.finished and (job_id is None or j.id == job_id))]
        self.bus.emit('queue_changed')

    def retry_failed(self, job_id: int) -> None:
        with self._lock:
            job = self._find(job_id)
            if not job:
                return
            failed = [c for c in job.chapters if job.states.get(c.key) in (FAILED, CANCELLED)]
            manga_id = job.manga_id
            if job.finished:
                self._jobs.remove(job)
        if failed:
            self.add(manga_id, failed)

    def pause_all(self) -> None:
        with self._lock:
            for job in self._jobs:
                if not job.finished and not job.paused:
                    job.paused = job.user_paused = True
                    if job.status == JOB_QUEUED:
                        job.status = JOB_PAUSED
            self._wake.notify_all()
        self.bus.emit('queue_changed')

    def resume_all(self) -> None:
        with self._lock:
            blocked = any(j.blocked for j in self._jobs)
            for job in self._jobs:
                if not job.finished and (job.paused or job.status == JOB_PAUSED):
                    job.paused = job.user_paused = False
                    if job.status == JOB_PAUSED:
                        job.status = JOB_QUEUED
            self._wake.notify_all()
        if blocked:
            self.resume_storage()       # also emits queue_changed
        else:
            self.bus.emit('queue_changed')

    def failed_total(self) -> int:
        """Failed chapters over all jobs (what 'Retry all' would queue again)."""
        with self._lock:
            return sum(sum(1 for c in j.chapters if j.states.get(c.key) == FAILED) for j in self._jobs)

    def retry_all_failed(self) -> int:
        """Queue every failed chapter of every job again. Returns how many."""
        count = self.failed_total()
        with self._lock:
            ids = [j.id for j in self._jobs if any(j.states.get(c.key) == FAILED for c in j.chapters)]
        for job_id in ids:
            self._retry_failed_only(job_id)
        return count

    def _retry_failed_only(self, job_id: int) -> None:
        with self._lock:
            job = self._find(job_id)
            if not job:
                return
            failed = [c for c in job.chapters if job.states.get(c.key) == FAILED]
            manga_id = job.manga_id
            if job.finished:
                self._jobs.remove(job)
        if failed:
            self.add(manga_id, failed)

    def jobs(self) -> List[Job]:
        with self._lock:
            return list(self._jobs)

    def active_count(self) -> int:
        with self._lock:
            return sum(1 for j in self._jobs if not j.finished)

    def chapter_states(self, manga_id: int) -> Dict[ChapterKey, tuple]:
        """Live (state, progress) of chapters in unfinished jobs for one manga."""
        with self._lock:
            result: Dict[ChapterKey, tuple] = {}
            for job in self._jobs:
                if job.manga_id != manga_id:
                    continue
                for key, state in job.states.items():
                    if state in (QUEUED, DOWNLOADING) or (state == FAILED and key not in result):
                        result[key] = (state, job.progress.get(key, 0))
            return result

    def job_for_manga(self, manga_id: int) -> Optional[Job]:
        with self._lock:
            return next((j for j in self._jobs if j.manga_id == manga_id and not j.finished), None)

    # Worker thread: pick the next job and download its chapters one by one. The UI is notified of all changes.
    def _run(self) -> None:
        while True:
            storage = self.storage_error()
            root = self._storage_root or self.library.download_root()
            if storage and storage[0] == STORAGE_OFFLINE and not storage_problem(root):
                logging.info("The download folder is reachable again - continuing")
                self.resume_storage()      # a full drive waits for the user instead
            with self._lock:
                if self._stopping:
                    return
                job = self._next_job()
                if job is None:
                    # While the server is offline, look again every 30 s.
                    self._wake.wait(timeout=30 if self._storage else None)
                    continue
                job.status = JOB_RUNNING
            self.bus.emit('queue_changed')
            try:
                self._process(job)
            except Exception as e:
                logging.exception(f"Download of {job.title} crashed")
                with self._lock:
                    job.current = None
                    job.status, job.error = JOB_FAILED, str(e)
                    for ref in job.chapters:       # so they count as failed and can be retried
                        if job.states.get(ref.key) in (QUEUED, DOWNLOADING):
                            job.states[ref.key] = FAILED
                            job.errors[ref.key] = str(e)
                            self._emit_chapter(job, ref)
            self.bus.emit('queue_changed')
            self.bus.emit('job_progress', job.id)
            if job.finished:
                self.bus.emit('job_finished', job.id, job.status)
                self._announce_finished(job)

    def _next_job(self) -> Optional[Job]:
        if self._draining or self._storage:
            return None
        return next((j for j in self._jobs if j.status == JOB_QUEUED and not j.paused and not j.cancelled), None)

    def _process(self, job: Job) -> None:
        key, site = self.library.resolve(job.url)
        if not site:
            raise RuntimeError("Unsupported or outdated link")
        novel = is_novel_url(job.url)
        root = self.library.download_root(novel)
        self._storage_root = root
        try:
            os.makedirs(root, exist_ok=True)
        except OSError as e:
            self._block(job, storage_problem(root, str(e)) or (STORAGE_OFFLINE, str(e)))
            return
        folder = self.library.manga_folder(job.title, novel)
        job.folder_name = os.path.basename(folder)

        if self.settings.notification_enabled('download_started'):
            self.bus.emit('notify', 'download_started', 'Download started', job.title, 'info')

        manga = self.library.get_manga(job.manga_id) or {}
        manga['_total'] = self.library.chapter_total(job.manga_id)
        try:
            write_folder_metadata(manga, folder, self.settings, manga['_total'])
        except OSError as e:
            problem = storage_problem(root, str(e))
            if problem:
                self._block(job, problem)
                return
            logging.warning(f"Could not write the folder metadata of {job.title}: {e}")

        while True:
            with self._lock:
                if job.paused and not job.cancelled:
                    # Step aside so the next manga in the queue can run.
                    job.current = None
                    job.status = JOB_PAUSED
                    return
                # Chapters can be added while the job runs
                waiting = [c for c in job.chapters if job.states.get(c.key) == QUEUED][:1 + READ_AHEAD]
            if not waiting or job.cancelled or self._stopping:
                break
            ref = waiting[0]
            for after in waiting[1:]:
                try:
                    site.prefetch(after.url)
                except Exception as e:
                    logging.debug(f"Read-ahead of {job.title} chapter {after.number} failed: {e}")
            problem = storage_problem(root)
            if problem:
                self._block(job, problem)
                return
            problem = self._download_one(job, key, site, ref, root, folder, manga)
            if problem:
                self._block(job, problem)
                return

        with self._lock:
            job.current = None
            if job.cancelled:
                self._finish_cancelled(job)
            elif job.failed_count and not job.done_count:
                job.status = JOB_FAILED
                job.error = job.error or "All chapters failed"
            else:
                job.status = JOB_DONE

    def _download_one(self, job: Job, site_key: str, site, ref: ChapterRef, root: str, folder: str,
                      manga: dict) -> Optional[Tuple[str, str]]:
        """Download one chapter. Returns the storage problem if the drive went away / filled up
        (the chapter is put back in the queue then), else None."""
        with self._lock:
            job.current = ref
            job.states[ref.key] = DOWNLOADING
            job.progress[ref.key] = 0
        self._emit_chapter(job, ref)

        attempts = max(1, self.settings.get_retry_attempts() + 1)
        path, error, problem = '', '', None
        for attempt in range(attempts):
            if job.cancelled or self._interrupted(job, site_key):
                break
            try:
                path = self._call_site(job, site_key, site, ref, root)
                if path:
                    break
                error = "The site returned no file"
            except ChapterUnavailable as e:
                error = str(e)       # locked / no pages: retrying right away won't help
                break
            except Exception as e:
                error = str(e)
                if not job.cancelled:
                    logging.warning(f"{job.title} ch.{ref.number} attempt {attempt + 1} failed: {e}")
            # Not the site's fault: retrying won't help until the drive is back / has space.
            problem = storage_problem(root, error)
            if problem or self._interrupted(job, site_key):
                break
            if attempt + 1 < attempts and not job.cancelled:
                time.sleep(2 * (attempt + 1))

        if not path and not job.cancelled and (problem or self._interrupted(job, site_key)):
            # Paused mid-chapter / storage gone: put it back so it starts over later.
            with self._lock:
                job.states[ref.key] = QUEUED
                job.progress[ref.key] = 0
                job.current = None
            self._emit_chapter(job, ref)
            self.bus.emit('job_progress', job.id)
            return problem

        if job.cancelled and not path:
            with self._lock:
                job.states[ref.key] = CANCELLED
            self._emit_chapter(job, ref)
            return None

        if path and site_key != 'mangadex':          # MangaDex files carry their own naming
            path = self.library.name_chapter_file(path, ref)
        if path:
            self._drop_replaced_file(ref, path, folder)
            language = ref.language if site_key in MULTI_LANGUAGE_SITES else None
            self.library.db.mark_chapter_downloaded(job.manga_id, ref.number, path, language=language)
            downloaded = [r for r in self.library.db.get_chapters_for_manga(job.manga_id) if r['is_downloaded']]
            chapter = {'number': ref.number, 'name': ref.display_name, 'language': ref.language, 'volume': ref.volume,
                       'is_first': self.library.first_chapter_number(downloaded) == ref.number}
            embed_chapter_metadata(path, manga, chapter, self.settings, manga.get('_total', 0), folder)
            with self._lock:
                job.states[ref.key] = DONE
                job.progress[ref.key] = 100
            self.bus.emit('library_changed', job.manga_id)
            if self.settings.notification_enabled('chapter_finished'):
                self.bus.emit('notify', 'chapter_finished', job.title, f"Chapter {ref.number} downloaded", 'success')
        else:
            with self._lock:
                job.states[ref.key] = FAILED
                job.errors[ref.key] = error or 'unknown error'
                job.error = f"Chapter {ref.number}: {error or 'unknown error'}"
            logging.error(f"Failed {job.title} chapter {ref.number}: {error}")
        self._emit_chapter(job, ref)
        self.bus.emit('job_progress', job.id)

    @staticmethod
    def _drop_replaced_file(ref: ChapterRef, path: str, folder: str) -> None:
        """Downloaded again under another name (other release group, other novel format):
        remove the old file so the chapter isn't in the folder twice."""
        old = ref.file_path
        if not old or not os.path.isfile(old) or os.path.normcase(os.path.abspath(old)) == os.path.normcase(
                os.path.abspath(path)):
            return
        if os.path.normcase(os.path.dirname(os.path.abspath(old))) != os.path.normcase(os.path.abspath(folder)):
            return      # only files in this manga's folder
        try:
            os.remove(old)
            logging.info(f"Replaced {os.path.basename(old)} with {os.path.basename(path)}")
        except OSError as e:
            logging.warning(f"Couldn't remove the old file {old}: {e}")

    def _call_site(self, job: Job, site_key: str, site, ref: ChapterRef, root: str) -> str:
        last = [-1]

        def on_progress(current=0, total=0, *_):
            percent = int(current * 100 / total) if total else 0
            if percent != last[0] and not job.cancelled:
                last[0] = percent
                with self._lock:
                    job.progress[ref.key] = percent
                self.bus.emit('chapter_state', job.manga_id, ref.language, ref.number, DOWNLOADING, percent)
                self.bus.emit('job_progress', job.id)

        name = job.folder_name or job.title   # sites create/use <root>/<name>/
        if site_key == 'mangadex':
            info = ChapterInfo()
            info.chapter_number, info.title = ref.number, ref.display_name
            info.volume_number, info.language = ref.volume, ref.language
            info.scanlation_group, info.chapter_url = ref.group, ref.url
            result = site.download_chapter(
                ref.url, ref.number, name, root, on_progress,
                language=ref.language, chapter_info=info,
                # Pausing stops the chapter right away (it is re-queued) instead of
                # blocking the worker, so the next manga in the queue can start.
                cancel_check=lambda: job.cancelled or self._interrupted(job, site_key),
            )
        elif is_novel_url(job.url) and hasattr(site, 'download_novel_chapter'):
            manga = self.library.get_manga(job.manga_id) or {}
            result = site.download_novel_chapter(
                ref.url, ref.number, name, root, on_progress,
                fmt=self.settings.get('novels.format', 'epub'), series=job.title, title=ref.display_name,
                author=manga.get('author') or '', cover_path=manga.get('cover_image_path') or '',
                language=ref.language)
        elif hasattr(site, 'download_chapter_with_name') and ref.name:
            result = site.download_chapter_with_name(ref.url, ref.number, ref.name, name, root, on_progress)
        else:
            result = site.download_chapter(ref.url, ref.number, name, root, on_progress)

        if isinstance(result, dict):
            if not result.get('success', True):
                raise RuntimeError(result.get('error') or 'Download failed')
            return result.get('path', '') or ''
        return result or ''

# Helpers for the worker thread. They are called with the lock held, so they must not block or call back into the manager.
    def _set_paused(self, job_id: int, paused: bool) -> None:
        with self._lock:
            job = self._find(job_id)
            if not job or job.finished:
                return
            job.paused = paused
            job.user_paused = paused
            if not paused and job.status == JOB_PAUSED:
                job.status = JOB_QUEUED
            elif paused and job.status == JOB_QUEUED:
                job.status = JOB_PAUSED
            self._wake.notify_all()
        self.bus.emit('queue_changed')

    def _interrupted(self, job: Job, site_key: str) -> bool:
        """MangaDex chapters can be stopped between pages, so a pause takes effect at once.
        Other sites finish the chapter they are on. When closing the app (draining) the
        current chapter is always finished."""
        return site_key == 'mangadex' and job.paused and not job.cancelled and not self._draining

    def _block(self, job: Job, problem: Tuple[str, str]) -> None:
        """Stop the queue because of a storage problem. The job keeps its place and continues
        with resume_storage() - or by itself once an offline server is reachable again."""
        kind, message = problem
        with self._lock:
            first = self._storage is None
            self._storage = problem
            job.blocked = message
            job.current = None
            job.status = JOB_PAUSED
        logging.warning(f"Downloads stopped: {message}")
        if first and self.settings.notification_enabled('errors'):
            hint = "They continue by themselves once it is back." if kind == STORAGE_OFFLINE \
                else "Free up space, then press Continue."
            title = "Download folder not reachable" if kind == STORAGE_OFFLINE else "Drive is full"
            self.bus.emit('notify', 'errors', title, f"{message}\nDownloads are paused. {hint}", 'error')

    def _finish_cancelled(self, job: Job) -> None:
        job.status = JOB_CANCELLED
        for ref in job.chapters:
            if job.states.get(ref.key) in (QUEUED, DOWNLOADING):
                job.states[ref.key] = CANCELLED
                self.bus.emit('chapter_state', job.manga_id, ref.language, ref.number, CANCELLED, 0)

    def _emit_chapter(self, job: Job, ref: ChapterRef) -> None:
        self.bus.emit('chapter_state', job.manga_id, ref.language, ref.number,
                      job.states.get(ref.key, QUEUED), job.progress.get(ref.key, 0))

    def _find(self, job_id: int) -> Optional[Job]:
        return next((j for j in self._jobs if j.id == job_id), None)

    def _announce_finished(self, job: Job) -> None:
        if job.status == JOB_DONE and self.settings.notification_enabled('download_finished'):
            detail = f"{job.done_count} chapter{'s' if job.done_count != 1 else ''} downloaded"
            if job.failed_count:
                detail += f", {job.failed_count} failed"
            self.bus.emit('notify', 'download_finished', job.title, detail, 'warning' if job.failed_count else 'success')
        elif job.status == JOB_FAILED and self.settings.notification_enabled('errors'):
            self.bus.emit('notify', 'errors', f"{job.title} failed", job.error or 'Download failed', 'error')
