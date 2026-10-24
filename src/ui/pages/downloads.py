"""
Downloads page: add a link, see the active download, the queue and finished jobs.
"""

import os
from typing import Dict, Optional

from PySide6.QtCore import QUrl, Qt, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QFileDialog, QHBoxLayout, QLineEdit, QProgressBar, QScrollArea, QVBoxLayout, QWidget)

from ...core import AppCore
from ...core.downloads import (JOB_CANCELLED, JOB_DONE, JOB_FAILED, JOB_PAUSED, JOB_QUEUED, JOB_RUNNING,
                               STORAGE_OFFLINE, Job)
from ...core.models import is_novel_url, site_label
from .. import icons, theme
from ..bridge import Bridge
from ..tasks import run_async
from ..widgets import (Button, Card, Cover, ElidedLabel, EmptyState, IconButton, divider, label, restyle)


class JobRow(Card):
    open_manga = Signal(int)

    def __init__(self, core: AppCore, job: Job, big: bool = False, parent=None):
        super().__init__(parent)
        self.core = core
        self.job_id = job.id
        self.manga_id = job.manga_id
        self.big = big

        layout = QHBoxLayout(self)
        if big:
            layout.setContentsMargins(16, 14, 14, 14)
        else:
            layout.setContentsMargins(12, 10, 10, 10)
        layout.setSpacing(16 if big else 12)

        self.cover = Cover(64, 92, 9, self) if big else Cover(40, 56, 6, self)
        cover = job.cover_path
        if not cover or not os.path.exists(cover):
            # The job keeps the path from when it was queued; the cover may have been replaced since.
            cover = (core.library.get_manga(job.manga_id) or {}).get('cover_image_path') or ''
            job.cover_path = cover
        self.cover.set_cover(cover, job.title)
        self.cover.setCursor(Qt.PointingHandCursor)
        self.cover.mouseReleaseEvent = lambda _e: self.open_manga.emit(self.manga_id)
        layout.addWidget(self.cover, 0, Qt.AlignVCenter)

        middle = QVBoxLayout()
        middle.setSpacing(5 if big else 3)
        top = QHBoxLayout()
        top.setSpacing(8)
        self.title = ElidedLabel(job.title, self, clickable=True)
        if big:
            font = self.title.font()
            font.setPointSizeF(font.pointSizeF() * 1.12)
            self.title.setFont(font)
        self.title.clicked.connect(lambda: self.open_manga.emit(self.manga_id))
        top.addWidget(self.title, 1)
        self.percent = label('', 'muted', self)
        top.addWidget(self.percent)
        middle.addLayout(top)

        self.status = ElidedLabel('', self)
        self.status.setProperty('role', 'muted')
        middle.addWidget(self.status)
        self.bar = QProgressBar(self)
        self.bar.setRange(0, 1000)
        self.bar.setTextVisible(False)
        if not big:
            self.bar.setProperty('thin', True)
        middle.addWidget(self.bar)
        if big:
            self.chapter_line = label('', 'faint', self)
            middle.addWidget(self.chapter_line)
        layout.addLayout(middle, 1)

        buttons = QHBoxLayout()
        buttons.setSpacing(2)
        self.chapters_btn = IconButton('list', 'Show chapters', self)
        self.chapters_btn.clicked.connect(lambda: self.open_manga.emit(self.manga_id))
        self.pause_btn = IconButton('pause', 'Pause', self)
        self.pause_btn.clicked.connect(self._toggle_pause)
        self.retry_btn = Button('Retry', 'retry', 'danger', self)
        self.retry_btn.setStyleSheet('padding: 4px 10px;')
        self.retry_btn.clicked.connect(self._retry)
        self.cancel_btn = IconButton('x', 'Cancel', self)
        self.cancel_btn.clicked.connect(self._cancel_or_remove)
        for b in (self.chapters_btn, self.pause_btn, self.retry_btn, self.cancel_btn):
            buttons.addWidget(b)
        layout.addLayout(buttons)
        if big:
            self.setProperty('active', True)
        self.update_from(job)

    def update_from(self, job: Job) -> None:
        total, done, failed = job.total, job.done_count, job.failed_count
        finished = job.finished
        storage = self.core.downloads.storage_error()
        percent = job.percent
        self.bar.setValue(int(percent * 10))
        tone = 'success' if job.status == JOB_DONE and not failed else None
        if self.bar.property('tone') != tone:
            self.bar.setProperty('tone', tone)
            restyle(self.bar)

        if job.status == JOB_RUNNING and job.paused:
            text = f"Pausing after this chapter · {done} of {total}"
        elif job.status == JOB_RUNNING and job.current:
            text = f"Chapter {job.current.number} · {done} of {total} done"
        elif job.status == JOB_RUNNING:
            text = f"Starting · {total} chapters"
        elif job.blocked:
            text = f"{job.blocked} · {done} of {total} done"
        elif job.status == JOB_PAUSED:
            text = f"Paused · {done} of {total} done"
        elif job.status == JOB_QUEUED and storage:
            text = f"Waiting for the download folder · {total} chapter{'s' if total != 1 else ''}"
        elif job.status == JOB_QUEUED:
            text = f"Waiting · {total} chapter{'s' if total != 1 else ''}"
        elif job.status == JOB_DONE:
            text = f"Finished · {done} chapter{'s' if done != 1 else ''}"
        elif job.status == JOB_CANCELLED:
            text = f"Cancelled · {done} of {total} downloaded"
        else:
            text = job.error or 'Failed'
        if failed and job.status not in (JOB_FAILED,):
            text += f" · {failed} failed"
        kind = '  ·  Light novel' if is_novel_url(job.url) else ''
        self.status.setText(f"{site_label(job.site_type)}{kind}  ·  {text}")
        role = 'error' if job.blocked else 'muted'
        if self.status.property('role') != role:
            self.status.setProperty('role', role)
            restyle(self.status)
        self.percent.setText('' if job.status in (JOB_QUEUED,) else f"{int(percent)}%")

        if self.big:
            current = job.current
            if current and job.status == JOB_RUNNING:
                ch_progress = job.progress.get(current.key, 0)
                name = current.display_name
                self.chapter_line.setText(f"Current: Chapter {current.number}" + (f" - {name}" if name else '')
                                          + f"  ·  {ch_progress}%")
            else:
                self.chapter_line.setText('')

        paused = job.paused or job.status == JOB_PAUSED
        self.pause_btn.setVisible(not finished)
        self.pause_btn.set_icon_name('play' if paused else 'pause', 'Resume' if paused else 'Pause')
        retryable = failed if failed else (total - done if job.status == JOB_CANCELLED else 0)
        self.retry_btn.setVisible(retryable > 0 or bool(job.blocked))
        self.retry_btn.setText(f"Retry {retryable} failed" if failed else f"Resume {retryable}")
        if job.blocked:
            offline = bool(storage) and storage[0] == STORAGE_OFFLINE
            self.retry_btn.setText('Retry' if offline else 'Continue')
            self.retry_btn.setToolTip("Try again now (this also happens by itself every 30 seconds)" if offline
                                      else "Continue downloading once you have freed up space")
        elif failed:
            reasons = sorted(set(job.errors.values()))
            self.retry_btn.setToolTip('Why it failed:\n' + '\n'.join(f'• {r}' for r in reasons[:5]))
        else:
            self.retry_btn.setToolTip('Queue the chapters that were cancelled again')
        self.cancel_btn.set_icon_name('x', 'Remove from list' if finished else 'Cancel download')

    def _retry(self) -> None:
        job = next((j for j in self.core.downloads.jobs() if j.id == self.job_id), None)
        if job and job.blocked:
            self.core.downloads.resume_storage()
        else:
            self.core.downloads.retry_failed(self.job_id)

    def _toggle_pause(self) -> None:
        job = next((j for j in self.core.downloads.jobs() if j.id == self.job_id), None)
        if not job:
            return
        if job.paused or job.status == JOB_PAUSED:
            self.core.downloads.resume(self.job_id)
        else:
            self.core.downloads.pause(self.job_id)

    def _cancel_or_remove(self) -> None:
        job = next((j for j in self.core.downloads.jobs() if j.id == self.job_id), None)
        if job and job.finished:
            self.core.downloads.remove_finished(self.job_id)
        else:
            self.core.downloads.cancel(self.job_id)


class DownloadsPage(QWidget):
    open_manga = Signal(int)
    open_preview = Signal(object)
    toast = Signal(str, str, str)

    def __init__(self, core: AppCore, bridge: Bridge, parent=None):
        super().__init__(parent)
        self.core = core
        self._rows: Dict[int, JobRow] = {}
        self._fetching = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        outer.addWidget(scroll)
        body = QWidget(scroll)
        scroll.setWidget(body)
        col = QVBoxLayout(body)
        col.setContentsMargins(32, 28, 32, 32)
        col.setSpacing(12)

        col.addWidget(label('Downloads', 'h1', body))
        col.addWidget(label('Paste a link, pick the chapters you want and follow the progress here.', 'muted', body))
        col.addSpacing(6)

        # ---- add link card
        add = Card(body)
        al = QVBoxLayout(add)
        al.setContentsMargins(18, 16, 18, 14)
        al.setSpacing(10)
        al.addWidget(label('Add manga', 'h3', add))
        row = QHBoxLayout()
        row.setSpacing(8)
        self.url = QLineEdit(add)
        self.url.setObjectName('UrlInput')
        self.url.setPlaceholderText('https://mangadex.org/title/…  ·  https://asurascans.com/comics/…')
        self.url.setClearButtonEnabled(True)
        self._url_icon = self.url.addAction(icons.icon('link', theme.current()['text_faint'], 18), QLineEdit.LeadingPosition)
        self.url.textChanged.connect(self._validate)
        self.url.returnPressed.connect(self._fetch)
        row.addWidget(self.url, 1)
        self.fetch_btn = Button('Find chapters', 'search', 'primary', add)
        self.fetch_btn.setMinimumHeight(38)
        self.fetch_btn.clicked.connect(self._fetch)
        row.addWidget(self.fetch_btn)
        al.addLayout(row)
        self.hint = label('', 'faint', add)
        al.addWidget(self.hint)
        self.fetch_bar = QProgressBar(add)
        self.fetch_bar.setProperty('thin', True)
        self.fetch_bar.setRange(0, 0)
        self.fetch_bar.setVisible(False)
        al.addWidget(self.fetch_bar)
        al.addWidget(divider(add))

        folder_row = QHBoxLayout()
        folder_row.setSpacing(8)
        self.folder_icon = label('', None, add)
        folder_row.addWidget(self.folder_icon)
        folder_row.addWidget(label('Saving to', 'muted', add))
        self.folder = ElidedLabel('', add)
        folder_row.addWidget(self.folder, 1)
        change = Button('Change', None, 'ghost', add)
        change.clicked.connect(self._change_folder)
        folder_row.addWidget(change)
        open_btn = IconButton('external', 'Open folder', add)
        open_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(self.core.library.download_root())))
        folder_row.addWidget(open_btn)
        al.addLayout(folder_row)
        col.addWidget(add)

        # ---- queue-wide actions
        col.addSpacing(10)
        self.toolbar = QWidget(body)
        tl = QHBoxLayout(self.toolbar)
        tl.setContentsMargins(0, 0, 0, 0)
        tl.setSpacing(6)
        tl.addStretch(1)
        self.pause_all_btn = Button('Pause all', 'pause', None, self.toolbar)
        self.pause_all_btn.setToolTip('Pause every download in the queue. MangaDex stops right away, '
                                      'other sites after the chapter they are on.')
        self.pause_all_btn.clicked.connect(self.core.downloads.pause_all)
        self.resume_all_btn = Button('Resume all', 'play', 'primary', self.toolbar)
        self.resume_all_btn.setToolTip('Continue every paused download')
        self.resume_all_btn.clicked.connect(self.core.downloads.resume_all)
        self.retry_all_btn = Button('Retry all failed', 'retry', 'danger', self.toolbar)
        self.retry_all_btn.setToolTip('Queue every chapter that failed again, in all downloads')
        self.retry_all_btn.clicked.connect(self._retry_all)
        for b in (self.pause_all_btn, self.resume_all_btn, self.retry_all_btn):
            tl.addWidget(b)
        col.addWidget(self.toolbar)

        # ---- sections
        self.active_label = label('NOW DOWNLOADING', 'section', body)
        col.addWidget(self.active_label)
        self.active_box = QVBoxLayout()
        self.active_box.setSpacing(8)
        col.addLayout(self.active_box)

        self.queue_label = label('UP NEXT', 'section', body)
        col.addSpacing(6)
        col.addWidget(self.queue_label)
        self.queue_box = QVBoxLayout()
        self.queue_box.setSpacing(6)
        col.addLayout(self.queue_box)

        finished_head = QHBoxLayout()
        self.finished_label = label('FINISHED', 'section', body)
        finished_head.addWidget(self.finished_label)
        finished_head.addStretch(1)
        self.clear_btn = Button('Clear list', None, 'ghost', body)
        self.clear_btn.setStyleSheet('padding: 3px 8px;')
        self.clear_btn.clicked.connect(lambda: self.core.downloads.remove_finished())
        finished_head.addWidget(self.clear_btn)
        col.addSpacing(6)
        col.addLayout(finished_head)
        self.finished_box = QVBoxLayout()
        self.finished_box.setSpacing(6)
        col.addLayout(self.finished_box)

        self.empty = EmptyState('download', 'Nothing in the queue',
                                'Paste a link above. You choose the chapters in the panel that opens on the right.', body)
        col.addWidget(self.empty)
        col.addStretch(1)

        bridge.queue_changed.connect(self.rebuild)
        bridge.job_progress.connect(self._on_progress)
        theme.notifier.changed.connect(self._refresh_icons)
        self._refresh_icons()
        self._validate('')
        self.refresh_path()
        self.rebuild()

    # --------------------------------------------------------------- link
    def _validate(self, text: str) -> None:
        text = text.strip()
        key, _ = self.core.library.resolve(text) if text else (None, None)
        if not text:
            self.hint.setText('Supported: ' + '  ·  '.join(self.core.library.supported_sites()))
            self.hint.setProperty('role', 'faint')
        elif key:
            self.hint.setText(f"✓  {site_label(key)} link")
            self.hint.setProperty('role', 'muted')
        else:
            self.hint.setText("This link isn't from a supported site (or isn't a series page).")
            self.hint.setProperty('role', 'error')
        restyle(self.hint)
        self.fetch_btn.setEnabled(bool(key) and not self._fetching)

    def _fetch(self) -> None:
        url = self.url.text().strip()
        if self._fetching or not url:
            return
        key, _ = self.core.library.resolve(url)
        if not key:
            self._validate(url)
            return
        self._set_fetching(True)

        def done(fetched):
            self._set_fetching(False)
            self.url.clear()
            self.open_preview.emit(fetched)

        def failed(message):
            self._set_fetching(False)
            self.toast.emit("Couldn't load that link", message, 'error')

        run_async(lambda: self.core.library.fetch(url), done, failed)

    def _set_fetching(self, busy: bool) -> None:
        self._fetching = busy
        self.fetch_bar.setVisible(busy)
        self.url.setEnabled(not busy)
        self.fetch_btn.setText('Looking up…' if busy else 'Find chapters')
        self._validate(self.url.text())

    # ------------------------------------------------------------- folder
    def refresh_path(self) -> None:
        path = self.core.library.download_root()
        self.folder.setText(path)
        self.folder.setToolTip(path)

    def _change_folder(self) -> None:
        change_download_folder(self, self.core)
        self.refresh_path()

    def showEvent(self, event):   # noqa: N802
        self.refresh_path()
        super().showEvent(event)

    def _refresh_icons(self) -> None:
        t = theme.current()
        self.folder_icon.setPixmap(icons.pixmap('folder', t['text_muted'], 16))
        self._url_icon.setIcon(icons.icon('link', t['text_faint'], 18))

    # -------------------------------------------------------------- queue
    def rebuild(self) -> None:
        for row in self._rows.values():
            # hide() instead of setParent(None): a row the layout has not shown yet would
            # otherwise pop up as its own window for a moment when Qt shows it later.
            row.hide()
            row.deleteLater()
        self._rows.clear()

        jobs = self.core.downloads.jobs()
        running = [j for j in jobs if j.status == JOB_RUNNING]
        waiting = [j for j in jobs if j.status in (JOB_QUEUED, JOB_PAUSED)]
        finished = [j for j in jobs if j.finished]

        for box, items, big in ((self.active_box, running, True), (self.queue_box, waiting, False),
                                (self.finished_box, list(reversed(finished)), False)):
            for job in items:
                row = JobRow(self.core, job, big, self)
                row.open_manga.connect(self.open_manga)
                box.addWidget(row)
                self._rows[job.id] = row

        self.active_label.setVisible(bool(running))
        self.queue_label.setText(f"UP NEXT  ·  {len(waiting)}")
        self.queue_label.setVisible(bool(waiting))
        self.finished_label.setVisible(bool(finished))
        self.clear_btn.setVisible(bool(finished))
        self.empty.setVisible(not jobs)
        self._update_toolbar(jobs)

    def _update_toolbar(self, jobs=None) -> None:
        jobs = self.core.downloads.jobs() if jobs is None else jobs
        unfinished = [j for j in jobs if not j.finished]
        paused = [j for j in unfinished if j.paused or j.status == JOB_PAUSED]
        failed = self.core.downloads.failed_total()
        self.pause_all_btn.setVisible(len(paused) < len(unfinished))
        self.resume_all_btn.setVisible(bool(paused))
        self.retry_all_btn.setText(f"Retry {failed} failed" if failed else 'Retry all failed')
        self.retry_all_btn.setVisible(failed > 0)
        self.toolbar.setVisible(bool(unfinished) or failed > 0)

    def _retry_all(self) -> None:
        count = self.core.downloads.retry_all_failed()
        if count:
            noun = 'chapter' if count == 1 else 'chapters'
            self.toast.emit('Retrying', f"{count} failed {noun} queued again", 'info')

    def _on_progress(self, job_id: int) -> None:
        row = self._rows.get(job_id)
        if not row:
            return
        job = next((j for j in self.core.downloads.jobs() if j.id == job_id), None)
        if job:
            row.update_from(job)
            self._update_toolbar()


def change_novel_folder(parent: QWidget, core: AppCore, reset: bool = False) -> Optional[str]:
    """Separate folder for light novels ('' = the normal download folder). Returns the folder in use."""
    if reset:
        path = ''
    else:
        current = core.library.download_root(novel=True)
        path = QFileDialog.getExistingDirectory(parent, 'Choose the folder for light novels',
                                                current if os.path.isdir(current) else '')
        if not path:
            return None
        os.makedirs(path, exist_ok=True)
    core.settings.set('novels.download_path', path)

    def resync():
        core.library.sync_all()
        return True

    run_async(resync, lambda _ok: core.bus.emit('library_changed', 0))
    return core.library.download_root(novel=True)


def change_download_folder(parent: QWidget, core: AppCore) -> Optional[str]:
    current = core.library.download_root()
    path = QFileDialog.getExistingDirectory(parent, 'Choose download folder', current if os.path.isdir(current) else '')
    if not path:
        return None
    os.makedirs(path, exist_ok=True)
    core.settings.set_download_path(path)

    def resync():
        core.library.sync_all()
        return True

    run_async(resync, lambda _ok: core.bus.emit('library_changed', 0))
    return path
