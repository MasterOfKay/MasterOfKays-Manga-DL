"""
Library page: every manga in the database with download progress, new-chapter
badges and update checks.
"""

import os
from datetime import datetime
from typing import Dict, List

from PySide6.QtCore import QTimer, QUrl, Qt, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QLineEdit, QMenu, QMessageBox, QProgressBar,
                               QScrollArea, QVBoxLayout, QWidget)

from ...core import AppCore
from ...core.downloads import JOB_PAUSED, JOB_QUEUED, JOB_RUNNING
from ...core.models import site_label
from .. import icons, theme
from ..bridge import Bridge
from ..widgets import (Button, Card, Cover, ElidedLabel, EmptyState, IconButton, Pill, Segmented, label, restyle)


def ago(iso: str) -> str:
    if not iso:
        return 'never'
    try:
        then = datetime.fromisoformat(iso)
    except ValueError:
        return 'never'
    seconds = max(0, (datetime.now() - then).total_seconds())
    if seconds < 60:
        return 'just now'
    if seconds < 3600:
        return f"{int(seconds // 60)} min ago"
    if seconds < 86400:
        hours = int(seconds // 3600)
        return f"{hours} hour{'s' if hours != 1 else ''} ago"
    days = int(seconds // 86400)
    return f"{days} day{'s' if days != 1 else ''} ago"


class MangaCard(Card):
    open_manga = Signal(int)
    toast = Signal(str, str, str)

    def __init__(self, core: AppCore, data: Dict, parent=None):
        super().__init__(parent, clickable=True)
        self.core = core
        self.manga_id = data['id']
        self.data = data
        self.clicked.connect(lambda: self.open_manga.emit(self.manga_id))

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(14)
        self.cover = Cover(52, 74, 8, self)
        layout.addWidget(self.cover)

        middle = QVBoxLayout()
        middle.setSpacing(4)
        top = QHBoxLayout()
        top.setSpacing(8)
        self.title = ElidedLabel('', self)
        font = self.title.font()
        font.setPointSizeF(font.pointSizeF() * 1.08)
        font.setBold(True)
        self.title.setFont(font)
        top.addWidget(self.title, 1)
        self.new_pill = Pill('', 'accent', self)
        self.dl_pill = Pill('', 'accent', self)
        self.check_pill = Pill('Checking…', 'neutral', self)
        for pill in (self.check_pill, self.dl_pill, self.new_pill):
            top.addWidget(pill)
        middle.addLayout(top)

        self.meta = ElidedLabel('', self)
        self.meta.setProperty('role', 'muted')
        middle.addWidget(self.meta)

        progress_row = QHBoxLayout()
        progress_row.setSpacing(10)
        self.bar = QProgressBar(self)
        self.bar.setProperty('thin', True)
        self.bar.setTextVisible(False)
        self.bar.setMaximumWidth(260)
        progress_row.addWidget(self.bar, 1)
        self.count = label('', 'muted', self)
        progress_row.addWidget(self.count)
        progress_row.addStretch(1)
        self.checked = label('', 'faint', self)
        progress_row.addWidget(self.checked)
        middle.addLayout(progress_row)
        layout.addLayout(middle, 1)

        self.refresh_btn = IconButton('refresh', 'Check for new chapters', self)
        self.refresh_btn.clicked.connect(lambda: self.core.updates.check_one(self.manga_id))
        self.download_btn = IconButton('download', 'Download missing chapters', self)
        self.download_btn.clicked.connect(self._download_missing)
        self.more_btn = IconButton('more', 'More', self)
        self.more_btn.clicked.connect(self._menu)
        for b in (self.refresh_btn, self.download_btn, self.more_btn):
            layout.addWidget(b)

        self.update_from(data)
        self.set_checking(core.updates.is_checking(self.manga_id))
        self.set_job(core.downloads.job_for_manga(self.manga_id))

    def update_from(self, data: Dict) -> None:
        self.data = data
        title = data.get('title', '')
        self.title.setText(title)
        self.cover.set_cover(data.get('cover_image_path') or '', title)
        parts = [site_label(data.get('site_type', ''))]
        author = (data.get('author') or '').strip()
        if any(ch.isalnum() for ch in author):
            parts.append(author)
        status = (data.get('status') or '').lower()
        if status and status != 'unknown':
            parts.append(status.title())
        self.meta.setText('  ·  '.join(parts))

        total, done = data.get('total_chapters', 0), data.get('downloaded_chapters', 0)
        self.bar.setMaximum(max(1, total))
        self.bar.setValue(done)
        tone = 'success' if total and done >= total else None
        if self.bar.property('tone') != tone:
            self.bar.setProperty('tone', tone)
            restyle(self.bar)
        self.count.setText(f"{done} / {total} chapters")
        missing = total - done
        self.download_btn.setEnabled(missing > 0)
        self.download_btn.setToolTip(f"Download {missing} missing chapter{'s' if missing != 1 else ''}"
                                     if missing else 'Everything is downloaded')

        new = data.get('new_chapters', 0)
        self.new_pill.set(f"{new} new", 'accent')
        self.new_pill.setVisible(new > 0)
        self.refresh_time()

    def refresh_time(self) -> None:
        last = self.data.get('last_checked', '')
        self.checked.setText(f"Checked {ago(last)}" if last else 'Not checked yet')

    def set_checking(self, checking: bool) -> None:
        self.check_pill.setVisible(checking)
        self.refresh_btn.setEnabled(not checking)

    def set_job(self, job) -> None:
        if job is None:
            self.dl_pill.setVisible(False)
            return
        if job.status == JOB_RUNNING:
            self.dl_pill.set(f"Downloading {int(job.percent)}%", 'accent')
        elif job.status == JOB_PAUSED:
            self.dl_pill.set('Paused', 'warning')
        elif job.status == JOB_QUEUED:
            self.dl_pill.set('Queued', 'neutral')
        self.dl_pill.setVisible(True)

    def _download_missing(self) -> None:
        chapters = self.core.library.chapters(self.manga_id)
        languages = {c.language for c in chapters if c.downloaded} or ({'en'} if any(c.language == 'en' for c in chapters)
                                                                        else {c.language for c in chapters[:1]})
        missing = [c for c in chapters if not c.downloaded and c.language in languages]
        if not missing:
            return
        self.core.downloads.add(self.manga_id, missing)
        self.toast.emit('Added to queue', f"{self.data.get('title')} · {len(missing)} chapters", 'success')

    def _menu(self) -> None:
        t = theme.current()
        menu = QMenu(self)
        menu.addAction(icons.icon('list', t['text_muted']), 'Show chapters', lambda: self.open_manga.emit(self.manga_id))
        menu.addAction(icons.icon('folder', t['text_muted']), 'Open folder', self._open_folder)
        if self.data.get('url'):
            menu.addAction(icons.icon('external', t['text_muted']), 'Open on website',
                           lambda: QDesktopServices.openUrl(QUrl(self.data['url'])))
        menu.addSeparator()
        menu.addAction(icons.icon('trash', t['danger']), 'Remove from library…', self._remove)
        menu.exec(self.more_btn.mapToGlobal(self.more_btn.rect().bottomLeft()))

    def _open_folder(self) -> None:
        folder = self.core.library.manga_folder(self.data.get('title', ''))
        QDesktopServices.openUrl(QUrl.fromLocalFile(folder if os.path.isdir(folder) else self.core.library.download_root()))

    def _remove(self) -> None:
        answer = QMessageBox.question(
            self, 'Remove from library',
            f"Remove “{self.data.get('title')}” from your library?\n\nDownloaded files stay on disk.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if answer == QMessageBox.Yes:
            job = self.core.downloads.job_for_manga(self.manga_id)
            if job:
                self.core.downloads.cancel(job.id)
            self.core.library.remove(self.manga_id)


class LibraryPage(QWidget):
    open_manga = Signal(int)
    toast = Signal(str, str, str)
    new_count_changed = Signal(int)

    def __init__(self, core: AppCore, bridge: Bridge, parent=None):
        super().__init__(parent)
        self.core = core
        self._cards: Dict[int, MangaCard] = {}
        self._data: List[Dict] = []
        self._loaded = False

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

        head = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(4)
        titles.addWidget(label('Library', 'h1', body))
        self.summary = label('', 'muted', body)
        titles.addWidget(self.summary)
        head.addLayout(titles, 1)
        self.check_btn = Button('Check for updates', 'refresh', 'primary', body)
        self.check_btn.clicked.connect(self._check_all)
        head.addWidget(self.check_btn, 0, Qt.AlignTop)
        col.addLayout(head)

        status = QHBoxLayout()
        status.setSpacing(10)
        self.status = label('', 'faint', body)
        status.addWidget(self.status)
        self.check_bar = QProgressBar(body)
        self.check_bar.setProperty('thin', True)
        self.check_bar.setTextVisible(False)
        self.check_bar.setMaximumWidth(220)
        self.check_bar.setVisible(False)
        status.addWidget(self.check_bar)
        status.addStretch(1)
        col.addLayout(status)
        col.addSpacing(4)

        tools = QHBoxLayout()
        tools.setSpacing(8)
        self.search = QLineEdit(body)
        self.search.setPlaceholderText('Search your library…')
        self.search.setClearButtonEnabled(True)
        self._search_icon = self.search.addAction(icons.icon('search', theme.current()['text_faint'], 16),
                                                  QLineEdit.LeadingPosition)
        self.search.textChanged.connect(self._apply)
        tools.addWidget(self.search, 1)
        self.filter = Segmented([('all', 'All'), ('new', 'New chapters'), ('missing', 'Incomplete')], 'all', body)
        self.filter.changed.connect(lambda _k: self._apply())
        tools.addWidget(self.filter)
        self.sort = QComboBox(body)
        self.sort.addItem('Recently updated', 'recent')
        self.sort.addItem('Most new chapters', 'new')
        self.sort.addItem('Title A–Z', 'title')
        self.sort.currentIndexChanged.connect(lambda _i: self._apply())
        tools.addWidget(self.sort)
        col.addLayout(tools)
        col.addSpacing(2)

        self.list_box = QVBoxLayout()
        self.list_box.setSpacing(8)
        col.addLayout(self.list_box)
        self.empty = EmptyState('library', 'Your library is empty',
                                'Manga you download show up here, and new chapters get checked automatically.', body)
        col.addWidget(self.empty)
        col.addStretch(1)

        self._reload_timer = QTimer(self)
        self._reload_timer.setSingleShot(True)
        self._reload_timer.setInterval(300)
        self._reload_timer.timeout.connect(self.reload)
        self._clock = QTimer(self)
        self._clock.setInterval(60_000)
        self._clock.timeout.connect(self._tick)
        self._clock.start()

        bridge.library_changed.connect(lambda _id: self._reload_timer.start())
        bridge.check_state.connect(self._on_check_state)
        bridge.check_progress.connect(self._on_check_progress)
        bridge.check_finished.connect(self._on_check_finished)
        bridge.queue_changed.connect(self._update_jobs)
        bridge.job_progress.connect(lambda _id: self._update_jobs())
        theme.notifier.changed.connect(
            lambda: self._search_icon.setIcon(icons.icon('search', theme.current()['text_faint'], 16)))
        self._update_status()

    # ---------------------------------------------------------------- data
    def reload(self) -> None:
        self._data = self.core.library.list_manga()
        alive = {m['id'] for m in self._data}
        for manga_id in [i for i in self._cards if i not in alive]:
            card = self._cards.pop(manga_id)
            card.hide()
            card.deleteLater()
        for data in self._data:
            card = self._cards.get(data['id'])
            if card is None:
                card = MangaCard(self.core, data, self)
                card.open_manga.connect(self.open_manga)
                card.toast.connect(self.toast)
                self._cards[data['id']] = card
            else:
                card.update_from(data)
        self._loaded = True
        self._apply()
        total_downloaded = sum(m.get('downloaded_chapters', 0) for m in self._data)
        n = len(self._data)
        self.summary.setText(f"{n} series  ·  {total_downloaded} chapters downloaded")
        self.new_count_changed.emit(sum(1 for m in self._data if m.get('new_chapters')))

    def _apply(self) -> None:
        query = self.search.text().strip().lower()
        mode = self.filter.current()
        sort = self.sort.currentData()
        items = list(self._data)
        if sort == 'title':
            items.sort(key=lambda m: m.get('title', '').lower())
        elif sort == 'new':
            items.sort(key=lambda m: (-(m.get('new_chapters') or 0), m.get('title', '').lower()))
        else:
            # Only a newly found chapter moves a manga up - checking it (last_checked) or
            # refreshing its metadata (last_updated) must not reorder the list.
            items.sort(key=lambda m: m.get('title', '').lower())
            items.sort(key=lambda m: m.get('latest_chapter_at') or '', reverse=True)   # stable: ties stay A-Z

        while self.list_box.count():
            self.list_box.takeAt(0)
        shown = 0
        for data in items:
            card = self._cards[data['id']]
            visible = True
            if query and query not in data.get('title', '').lower() and query not in (data.get('author') or '').lower():
                visible = False
            if mode == 'new' and not data.get('new_chapters'):
                visible = False
            if mode == 'missing' and data.get('downloaded_chapters', 0) >= data.get('total_chapters', 0):
                visible = False
            self.list_box.addWidget(card)
            card.setVisible(visible)
            shown += visible

        if not self._data:
            self.empty.set_text('Your library is empty',
                                'Manga you download show up here, and new chapters get checked automatically.')
        else:
            self.empty.set_text('Nothing matches', 'Try a different search or filter.')
        self.empty.setVisible(self._loaded and shown == 0)

    # ------------------------------------------------------------- updates
    def _check_all(self) -> None:
        if not self._data:
            self.toast.emit('Nothing to check', 'Add a manga first.', 'info')
            return
        if self.core.updates.check_all(manual=True):
            self._set_bulk(True)

    def _set_bulk(self, running: bool) -> None:
        self.check_btn.setEnabled(not running)
        self.check_btn.setText('Checking…' if running else 'Check for updates')
        self.check_bar.setVisible(running)
        if not running:
            self._update_status()

    def _on_check_state(self, manga_id: int, checking: bool) -> None:
        card = self._cards.get(manga_id)
        if card:
            card.set_checking(checking)

    def _on_check_progress(self, done: int, total: int) -> None:
        self._set_bulk(True)
        self.check_bar.setMaximum(max(1, total))
        self.check_bar.setValue(done)
        self.status.setText(f"Checking {min(done + 1, total)} of {total}…")

    def _on_check_finished(self, new_total: int, manga_with_new: int, errors: int, manual: bool) -> None:
        self._set_bulk(False)
        self._reload_timer.start()

    def _update_status(self) -> None:
        if self.core.updates.bulk_running:
            return
        last = self.core.settings.get('updates.last_check', '')
        text = f"Last checked {ago(last)}" if last else "Not checked yet"
        if self.core.settings.get('updates.auto_check'):
            minutes = int(self.core.settings.get('updates.interval_minutes', 60))
            every = f"{minutes // 60} h" if minutes >= 60 and minutes % 60 == 0 else f"{minutes} min"
            text += f"  ·  checks automatically every {every}"
        else:
            text += "  ·  automatic checks are off"
        self.status.setText(text)

    def _tick(self) -> None:
        self._update_status()
        for card in self._cards.values():
            card.refresh_time()

    def _update_jobs(self) -> None:
        for manga_id, card in self._cards.items():
            card.set_job(self.core.downloads.job_for_manga(manga_id))

    def showEvent(self, event):   # noqa: N802
        self._update_status()
        super().showEvent(event)
