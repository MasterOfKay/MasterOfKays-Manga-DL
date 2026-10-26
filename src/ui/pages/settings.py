"""
Settings page.
"""

import os

from PySide6.QtCore import QUrl, Qt, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QButtonGroup, QComboBox, QHBoxLayout, QPushButton, QScrollArea, QSpinBox,
                               QVBoxLayout, QWidget)

from ...core import AppCore
from ...core.downloads import MAX_WORKERS, PARALLEL_REGULAR, PARALLEL_SAFE
from ...core.metadata_files import PRESETS
from ...core.paths import data_dir
from .. import theme
from ..widgets import Button, Card, ElidedLabel, IconButton, Segmented, Toggle, divider, label
from ..tasks import run_async
from .downloads import change_download_folder, change_novel_folder

INTERVALS = [(15, '15 minutes'), (30, '30 minutes'), (60, '1 hour'), (180, '3 hours'),
             (360, '6 hours'), (720, '12 hours'), (1440, 'Once a day')]


class SettingsPage(QWidget):
    appearance_changed = Signal()
    notifications_changed = Signal()
    toast = Signal(str, str, str)
    test_notification = Signal()

    def __init__(self, core: AppCore, parent=None):
        super().__init__(parent)
        self.core = core
        self.s = core.settings
        self._toggles = {}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        outer.addWidget(scroll)
        body = QWidget(scroll)
        scroll.setWidget(body)
        col = QVBoxLayout(body)
        col.setContentsMargins(32, 28, 32, 40)
        col.setSpacing(12)
        col.addWidget(label('Settings', 'h1', body))
        col.addWidget(label('Changes are saved right away.', 'muted', body))
        col.addSpacing(8)

        # ---------------------------------------------------- appearance
        card, box = self._section(body, col, 'Appearance')
        mode = Segmented([('system', 'System'), ('light', 'Light'), ('dark', 'Dark')],
                         self.s.get('appearance.theme'), card)
        mode.changed.connect(lambda v: self._set('appearance.theme', v, appearance=True))
        self._row(box, card, 'Theme', 'Follow your system or force light / dark.', mode)

        swatches = QWidget(card)
        sl = QHBoxLayout(swatches)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.setSpacing(8)
        group = QButtonGroup(swatches)
        current_accent = self.s.get('appearance.accent', '').lower()
        for name, color in theme.ACCENTS.items():
            btn = QPushButton(swatches)
            btn.setObjectName('Swatch')
            btn.setCheckable(True)
            btn.setToolTip(name)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setStyleSheet(f"QPushButton#Swatch {{ background: {color}; }}")
            btn.setChecked(color.lower() == current_accent)
            btn.clicked.connect(lambda _=False, c=color: self._set('appearance.accent', c, appearance=True))
            group.addButton(btn)
            sl.addWidget(btn)
        self._row(box, card, 'Accent color', 'Used for buttons, progress and highlights.', swatches, last=True)

        # ----------------------------------------------------- downloads
        card, box = self._section(body, col, 'Downloads')
        folder = QWidget(card)
        fl = QHBoxLayout(folder)
        fl.setContentsMargins(0, 0, 0, 0)
        fl.setSpacing(6)
        self.folder_label = ElidedLabel(self.core.library.download_root(), folder)
        self.folder_label.setProperty('role', 'muted')
        self.folder_label.setMinimumWidth(200)
        fl.addWidget(self.folder_label, 1)
        change = Button('Change…', 'folder', None, folder)
        change.clicked.connect(self._change_folder)
        fl.addWidget(change)
        self._row(box, card, 'Download folder', 'Each manga gets its own sub-folder with CBZ files.', folder, wide=True)

        retries = QSpinBox(card)
        retries.setRange(0, 5)
        retries.setValue(self.s.get_retry_attempts())
        retries.setFixedWidth(80)
        retries.valueChanged.connect(lambda v: self._set('download.retry_attempts', v))
        self._row(box, card, 'Retries per chapter', 'How often a failed chapter is retried before giving up.', retries)

        parallel = QSpinBox(card)
        parallel.setRange(1, MAX_WORKERS)
        parallel.setValue(self.core.downloads.worker_limit())
        parallel.setFixedWidth(80)
        self._row(box, card, 'Parallel downloads',
                  'How many series download at the same time. 1 downloads them one after another.', parallel)
        parallel_mode = Segmented([(PARALLEL_SAFE, 'Safe'), (PARALLEL_REGULAR, 'Regular')],
                                  self.s.get('download.parallel_mode', PARALLEL_SAFE), card)
        self._row(box, card, 'Parallel mode',
                  'Safe never downloads two series from the same site at once. It skips ahead in the queue to '
                  'a series from another site, so fewer downloads may run than set. Regular just takes the next '
                  'one in line. That is at your own risk: some sites ban your IP for hours or days when they '
                  'get too many downloads at once.', parallel_mode, last=True)
        parallel_mode.setEnabled(parallel.value() > 1)

        def set_parallel(value):
            self._set('download.parallel', value)
            parallel_mode.setEnabled(value > 1)
            self.core.downloads.settings_changed()

        def set_parallel_mode(mode):
            self._set('download.parallel_mode', mode)
            self.core.downloads.settings_changed()
        parallel.valueChanged.connect(set_parallel)
        parallel_mode.changed.connect(set_parallel_mode)

        # --------------------------------------------------------- novels
        from ...core.models import NOVEL_FORMATS
        card, box = self._section(body, col, 'Novels')
        novel_format = QComboBox(card)
        for key, (name, ext) in NOVEL_FORMATS.items():
            novel_format.addItem(f"{name}  ({ext})", key)
        current = self.s.get('novels.format', 'epub')
        novel_format.setCurrentIndex(max(0, list(NOVEL_FORMATS).index(current) if current in NOVEL_FORMATS else 0))
        novel_format.currentIndexChanged.connect(
            lambda i: self._set('novels.format', novel_format.itemData(i)))
        self._row(box, card, 'Save chapters as',
                  'Novels have text chapters instead of pages. EPUB works in Komga, Kavita and every e-reader; '
                  'PDF, Word, HTML, Markdown and text are there for other apps. Applies to new downloads.',
                  novel_format)
        novel_folder = QWidget(card)
        nl = QHBoxLayout(novel_folder)
        nl.setContentsMargins(0, 0, 0, 0)
        nl.setSpacing(6)
        self.novel_folder_label = ElidedLabel('', novel_folder)
        self.novel_folder_label.setProperty('role', 'muted')
        self.novel_folder_label.setMinimumWidth(200)
        nl.addWidget(self.novel_folder_label, 1)
        novel_change = Button('Change…', 'folder', None, novel_folder)
        novel_change.clicked.connect(lambda: self._change_novel_folder(False))
        nl.addWidget(novel_change)
        self.novel_reset = Button('Use download folder', None, 'ghost', novel_folder)
        self.novel_reset.clicked.connect(lambda: self._change_novel_folder(True))
        nl.addWidget(self.novel_reset)
        self._row(box, card, 'Novels folder',
                  'Novels can go to their own library folder (e.g. a Komga "Books" library). '
                  'Each novel still gets its own sub-folder.', novel_folder, last=True, wide=True)
        self._show_novel_folder()

        # ------------------------------------------------- media servers
        card, box = self._section(body, col, 'Metadata for Komga, Kavita & Jellyfin')
        presets = QWidget(card)
        pl = QHBoxLayout(presets)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.setSpacing(6)
        for key, text in (('komga', 'Komga'), ('kavita', 'Kavita'), ('jellyfin', 'Jellyfin'), ('all', 'All'),
                          ('none', 'None')):
            btn = Button(text, None, None, presets)
            btn.setStyleSheet('padding: 5px 12px;')
            btn.clicked.connect(lambda _=False, k=key: self._apply_preset(k))
            pl.addWidget(btn)
        self._row(box, card, 'Quick setup', 'Turns on exactly the files the selected app reads. Fine-tune below.',
                  presets)
        self._toggle_row(box, card, 'download.embed_comicinfo_in_cbz', 'ComicInfo.xml inside every chapter',
                         'Chapter title & number, series, authors, description, genres, language. '
                         'Read by Komga, Kavita, Jellyfin and most readers.')
        self._toggle_row(box, card, 'download.save_series_json', 'series.json (Mylar format)',
                         'Series description, status and publisher for Komga. '
                         'Enable "Import metadata from Mylar series.json" in the Komga library.')
        self._toggle_row(box, card, 'download.save_cover', 'Series cover (cover.png)',
                         'Series poster for Komga, Kavita and Jellyfin. Komga: enable "Local artwork".')
        self._toggle_row(box, card, 'download.save_comicinfo', 'ComicInfo.xml in the manga folder',
                         'Fallback for Jellyfin when a chapter has no metadata inside. Not needed for Komga/Kavita.')
        self._toggle_row(box, card, 'download.embed_cover_in_cbz', 'Series cover as first page of every chapter',
                         'Makes every chapter thumbnail show the series cover instead of the first page.')

        title_style = Segmented([('name', 'Chapter name'), ('full', 'Chapter N - Name')],
                                self.s.get('metadata.chapter_title', 'name'), card)
        title_style.changed.connect(lambda v: self._set('metadata.chapter_title', v))
        self._row(box, card, 'Chapter titles',
                  'Komga shows "1 - <title>", so the name alone avoids "1 - Chapter 1 - ...".', title_style)
        direction = Segmented([('ltr', 'Left to right'), ('rtl', 'Right to left')],
                              self.s.get('metadata.reading_direction', 'ltr'), card)
        direction.changed.connect(lambda v: self._set('metadata.reading_direction', v))
        self._row(box, card, 'Reading direction',
                  'Right to left for Japanese manga, left to right for manhwa & webtoons.', direction)
        from ...core.metadata_files import summary_mode
        summary = Segmented([('first', 'First chapter'), ('all', 'Every chapter'), ('none', 'None')],
                            summary_mode(self.s), card)
        summary.changed.connect(lambda v: self._set('metadata.chapter_summary', v))
        self._row(box, card, 'Series description',
                  'First chapter: Komga shows it as the series description, chapters stay clean. '
                  'Every chapter: Jellyfin shows it on each chapter (it has no series page).', summary)
        self._toggle_row(box, card, 'metadata.publisher_from_site', 'Source site as publisher',
                         'e.g. "Asura Comics" or "MangaDex" - lets you filter by source in Komga.')

        apply_box = QWidget(card)
        al = QHBoxLayout(apply_box)
        al.setContentsMargins(0, 0, 0, 0)
        al.setSpacing(6)
        self.apply_btn = Button('Add missing', 'stack', None, apply_box)
        self.apply_btn.setToolTip('Adds metadata where it is missing. Fast, even on a network share.')
        self.apply_btn.clicked.connect(lambda: self._write_existing(False))
        self.rewrite_btn = Button('Rewrite all', 'retry', 'ghost', apply_box)
        self.rewrite_btn.setToolTip('Replaces existing metadata too (e.g. after changing the options above). '
                                    'Rewrites every chapter file - slower on a network share.')
        self.rewrite_btn.clicked.connect(lambda: self._write_existing(True))
        al.addWidget(self.apply_btn)
        al.addWidget(self.rewrite_btn)
        self._row(box, card, 'Update chapters already on disk',
                  'Writes the files above for every manga in your library. Rescan in Komga/Jellyfin afterwards.',
                  apply_box, last=True)
        self.apply_status = label('', 'faint', card, wrap=True)
        box.addWidget(self.apply_status)
        self.apply_status.setVisible(False)

        # ------------------------------------------------------- updates
        card, box = self._section(body, col, 'New chapter checks')
        self._toggle_row(box, card, 'updates.auto_check', 'Check for new chapters automatically',
                         'Runs quietly in the background while the app is open.')
        interval = QComboBox(card)
        current = int(self.s.get('updates.interval_minutes', 60))
        for minutes, text in INTERVALS:
            interval.addItem(text, minutes)
        interval.setCurrentIndex(max(0, next((i for i, (m, _) in enumerate(INTERVALS) if m == current), 2)))
        interval.currentIndexChanged.connect(lambda i: self._set('updates.interval_minutes', interval.itemData(i)))
        self._row(box, card, 'Check every', 'How often the whole library is checked.', interval)
        self._toggle_row(box, card, 'updates.check_on_startup', 'Check when the app starts', '')
        self._toggle_row(box, card, 'updates.auto_download', 'Download new chapters automatically',
                         'New chapters are queued as soon as they are found.', last=True)

        # ---------------------------------------------------- app updates
        card, box = self._section(body, col, 'App updates')
        app_interval = Segmented([('hourly', 'Hourly'), ('daily', 'Daily'), ('weekly', 'Weekly'), ('never', 'Never')],
                                 self.s.get('app_updates.interval'), card)
        app_interval.changed.connect(lambda v: self._set('app_updates.interval', v))
        self._row(box, card, 'Look for new versions', 'Checks the releases on GitHub. Beta versions and the '
                  'release notes are on the Updates page.', app_interval, last=True)

        # ------------------------------------------------- notifications
        card, box = self._section(body, col, 'Notifications')
        self._toggle_row(box, card, 'notifications.in_app', 'In-app notifications',
                         'Small pop-ups in the corner of the window.', notify=True)
        self._toggle_row(box, card, 'notifications.desktop', 'Desktop notifications',
                         'System notifications while the window is in the background or minimized.', notify=True)
        box.addWidget(label('NOTIFY ME WHEN', 'section', card))
        box.addSpacing(2)
        self._toggle_row(box, card, 'notifications.events.new_chapters', 'New chapters are found', '', notify=True)
        self._toggle_row(box, card, 'notifications.events.download_finished', 'A download finishes', '', notify=True)
        self._toggle_row(box, card, 'notifications.events.download_started', 'A download starts', '', notify=True)
        self._toggle_row(box, card, 'notifications.events.chapter_finished', 'Each single chapter finishes',
                         'Can be a lot for big downloads.', notify=True)
        self._toggle_row(box, card, 'notifications.events.errors', 'Something fails', '', notify=True)
        self._toggle_row(box, card, 'notifications.events.app_update', 'A new version of Manga DL is out', '',
                         notify=True)
        test = Button('Send test notification', 'bell', None, card)
        test.clicked.connect(self.test_notification)
        self._row(box, card, 'Try it', 'Shows how notifications look with the current settings.', test, last=True)

        # ------------------------------------------------------ advanced
        card, box = self._section(body, col, 'Advanced')
        debug = Toggle(self.s.is_debug_mode(), card)
        debug.toggled.connect(self.s.set_debug_mode)
        self._row(box, card, 'Debug log', f"Writes a detailed log to {os.path.basename(self.s.log_file())}.", debug)
        open_data = IconButton('external', 'Open data folder', card)
        open_data.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(data_dir())))
        self._row(box, card, 'Data folder', data_dir(), open_data, last=True)
        col.addStretch(1)

    # ------------------------------------------------------------ builders
    def _section(self, body, col, title):
        col.addSpacing(6)
        col.addWidget(label(title.upper(), 'section', body))
        card = Card(body)
        box = QVBoxLayout(card)
        box.setContentsMargins(18, 8, 18, 8)
        box.setSpacing(0)
        col.addWidget(card)
        return card, box

    def _row(self, box, card, title, description, control, last=False, wide=False):
        row = QWidget(card)
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 11, 0, 11)
        rl.setSpacing(24)
        text = QVBoxLayout()
        text.setSpacing(2)
        text.addWidget(label(title, None, row))
        if description:
            desc = label(description, 'faint', row, wrap=True)
            text.addWidget(desc)
        rl.addLayout(text, 1)
        rl.addWidget(control, 1 if wide else 0, Qt.AlignVCenter | Qt.AlignRight)
        box.addWidget(row)
        if not last:
            box.addWidget(divider(card))

    def _toggle_row(self, box, card, key, title, description, last=False, notify=False):
        toggle = Toggle(bool(self.s.get(key)), card)
        toggle.toggled.connect(lambda v, k=key: self._set(k, v, notify=notify))
        self._toggles[key] = toggle
        self._row(box, card, title, description, toggle, last)

    # ------------------------------------------------------------- actions
    def _set(self, key, value, appearance=False, notify=False):
        self.s.set(key, value)
        if appearance:
            self.appearance_changed.emit()
        if notify:
            self.notifications_changed.emit()

    def _apply_preset(self, name):
        for key, value in PRESETS[name].items():
            self.s.set(key, value)
            toggle = self._toggles.get(key)
            if toggle is not None:
                toggle.setChecked(value)
        self.toast.emit('Metadata options updated', f"Preset: {name.title()}", 'success')

    def _write_existing(self, overwrite):
        self.apply_btn.setEnabled(False)
        self.rewrite_btn.setEnabled(False)
        self.apply_status.setVisible(True)
        self.apply_status.setText('Writing metadata... this can take a while on a network share.')
        library = self.core.library

        def work():
            totals = {}
            for manga in library.list_manga():
                for k, v in library.write_metadata(manga['id'], overwrite).items():
                    totals[k] = totals.get(k, 0) + v
            return totals

        def done(totals):
            self.apply_btn.setEnabled(True)
            self.rewrite_btn.setEnabled(True)
            changed = totals.get('added', 0) + totals.get('updated', 0)
            text = (f"{changed} chapters updated, {totals.get('unchanged', 0)} already up to date, "
                    f"{totals.get('folder_files', 0)} folder files written")
            if totals.get('error'):
                text += f", {totals['error']} failed (see log)"
            self.apply_status.setText(text)
            self.toast.emit('Metadata written', text, 'warning' if totals.get('error') else 'success')

        def failed(message):
            self.apply_btn.setEnabled(True)
            self.rewrite_btn.setEnabled(True)
            self.apply_status.setText(message)
            self.toast.emit('Writing metadata failed', message, 'error')

        run_async(work, done, failed)

    def _change_folder(self):
        if change_download_folder(self, self.core):
            self.folder_label.setText(self.core.library.download_root())
            self.toast.emit('Download folder changed', self.core.library.download_root(), 'success')

    def _show_novel_folder(self):
        own = bool((self.s.get('novels.download_path') or '').strip())
        self.novel_folder_label.setText(self.core.library.download_root(novel=True) if own
                                        else 'Same as the download folder')
        self.novel_reset.setVisible(own)

    def _change_novel_folder(self, reset):
        path = change_novel_folder(self, self.core, reset)
        if path is not None:
            self._show_novel_folder()
            self.toast.emit('Novels folder changed', path, 'success')

    def showEvent(self, event):   # noqa: N802
        self.folder_label.setText(self.core.library.download_root())
        self._show_novel_folder()
        super().showEvent(event)
