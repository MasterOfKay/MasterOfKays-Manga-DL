"""
Side panel listing every chapter of one manga with its live state
(downloaded / downloading / queued / failed / new / not downloaded) and
letting the user pick chapters to download.

It works in two modes:
  * library mode - a manga stored in the database (manga_id)
  * preview mode - a freshly looked-up link that isn't stored yet (FetchedManga)
"""

import os
import re
from typing import Dict, List, Optional, Set

from PySide6.QtCore import (QAbstractListModel, QModelIndex, QPoint, QRect, QRectF, QSize, Qt, QTimer, QUrl, Signal)
from PySide6.QtGui import QColor, QDesktopServices, QFont, QFontMetrics, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QComboBox, QFrame, QHBoxLayout, QLineEdit, QListView, QMenu, QProgressBar,
                               QSizePolicy, QStyle, QStyledItemDelegate, QVBoxLayout, QWidget)

from ..core import AppCore
from ..core.downloads import CANCELLED, DONE, DOWNLOADING, FAILED, QUEUED
from ..core.models import (ChapterKey, ChapterRef, FetchedManga, chapter_sort_key, is_novel_url, language_name,
                           pick_source, site_label)
from . import icons, theme
from .bridge import Bridge
from .tasks import run_async
from .widgets import Button, Cover, IconButton, Pill, Segmented, divider, label

ROW_HEIGHT = 50
EARLY = 'early'      # paywalled on the site for now - can't be selected


# ============================================================== model
class ChapterModel(QAbstractListModel):
    RefRole = Qt.UserRole + 1
    selection_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._all: List[ChapterRef] = []
        self._rows: List[ChapterRef] = []
        self._row_of: Dict[ChapterKey, int] = {}
        self.live: Dict[ChapterKey, tuple] = {}
        self.selected: Set[ChapterKey] = set()
        self.errors: Dict[ChapterKey, str] = {}
        self.filter_mode = 'all'
        self.search = ''
        self.newest_first = True

    # --- data
    def set_chapters(self, chapters: List[ChapterRef]) -> None:
        self._all = chapters
        keys = {c.key for c in chapters}
        self.selected &= keys
        self._apply()

    def chapters(self) -> List[ChapterRef]:
        return self._all

    def visible(self) -> List[ChapterRef]:
        return self._rows

    def state_of(self, ref: ChapterRef) -> str:
        live = self.live.get(ref.key)
        if live and live[0] in (QUEUED, DOWNLOADING):
            return live[0]
        if ref.downloaded:
            return DONE
        if live and live[0] == FAILED:
            return FAILED
        if ref.early_access:
            return EARLY
        return 'new' if ref.is_new else 'none'

    def set_live(self, key: ChapterKey, state: str, progress: int) -> None:
        if state in (DONE, CANCELLED):
            self.live.pop(key, None)
            if state == DONE:
                for ref in self._all:
                    if ref.key == key:
                        ref.downloaded = True
        else:
            self.live[key] = (state, progress)
        row = self._row_of.get(key)
        if row is not None:
            idx = self.index(row)
            self.dataChanged.emit(idx, idx)

    # --- filtering
    def set_filter(self, mode: str) -> None:
        self.filter_mode = mode
        self._apply()

    def set_search(self, text: str) -> None:
        self.search = text.strip().lower()
        self._apply()

    def toggle_sort(self) -> None:
        self.newest_first = not self.newest_first
        self._apply()

    def _apply(self) -> None:
        self.beginResetModel()
        rows = []
        for ref in self._all:
            state = self.state_of(ref)
            if self.filter_mode == 'missing' and state == DONE:
                continue
            if self.filter_mode == 'downloaded' and state != DONE:
                continue
            if self.filter_mode == 'new' and not ref.is_new:
                continue
            if self.search and self.search not in ref.number.lower() and self.search not in (ref.name or '').lower():
                continue
            rows.append(ref)
        rows.sort(key=lambda r: chapter_sort_key(r.number), reverse=self.newest_first)
        self._rows = rows
        self._row_of = {ref.key: i for i, ref in enumerate(rows)}
        self.endResetModel()
        self.selection_changed.emit()

    # --- selection
    def toggle(self, row: int) -> bool:
        ref = self._rows[row]
        if ref.early_access:
            return False
        if ref.key in self.selected:
            self.selected.discard(ref.key)
            value = False
        else:
            self.selected.add(ref.key)
            value = True
        self._changed(row, row)
        return value

    def set_range(self, first: int, last: int, value: bool) -> None:
        lo, hi = sorted((first, last))
        for ref in self._rows[lo:hi + 1]:
            if value and ref.early_access:
                continue
            (self.selected.add if value else self.selected.discard)(ref.key)
        self._changed(lo, hi)

    def select_where(self, predicate, value: bool = True) -> None:
        for ref in self._rows:
            if predicate(ref) and not (value and ref.early_access):
                (self.selected.add if value else self.selected.discard)(ref.key)
        if self._rows:
            self._changed(0, len(self._rows) - 1)

    def clear_selection(self) -> None:
        self.selected.clear()
        if self._rows:
            self._changed(0, len(self._rows) - 1)

    def selected_refs(self) -> List[ChapterRef]:
        return sorted((r for r in self._all if r.key in self.selected and not r.early_access), key=lambda r: chapter_sort_key(r.number))

    def _changed(self, first: int, last: int) -> None:
        self.dataChanged.emit(self.index(first), self.index(last))
        self.selection_changed.emit()

    # --- Qt API
    def rowCount(self, parent=QModelIndex()) -> int:   # noqa: N802
        return 0 if parent.isValid() else len(self._rows)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if not index.isValid():
            return None
        ref = self._rows[index.row()]
        if role == self.RefRole:
            return ref
        if role == Qt.DisplayRole:
            return f"Chapter {ref.number}"
        if role == Qt.ToolTipRole and self.state_of(ref) == FAILED:
            reason = self.errors.get(ref.key) or 'Download failed'
            return f"{reason}\n\nClick Retry to try again."
        if role == Qt.ToolTipRole and len(ref.sources) > 1:
            how = 'picked by you' if ref.group_locked else 'from the group filter'
            others = ', '.join(s.group for s in ref.sources if s.group != ref.group)
            return (f"Release group: {ref.group} ({how})\nAlso available from: {others}\n\n"
                    "Click the group to download this chapter from another one.")
        if role == Qt.ToolTipRole and self.state_of(ref) == EARLY:
            return (f"Early access on the site - {ref.free_label.lower()}.\n"
                    "It can't be downloaded before that.")
        return None

    def failed(self) -> List[ChapterRef]:
        return [r for r in self._all if self.state_of(r) == FAILED]


# ============================================================ delegate
class ChapterDelegate(QStyledItemDelegate):
    def __init__(self, model: ChapterModel, parent=None):
        super().__init__(parent)
        self.model = model
        self.chips: Dict[ChapterKey, tuple] = {}     # x-range of the release group chip per chapter

    def sizeHint(self, option, index) -> QSize:
        return QSize(option.rect.width(), ROW_HEIGHT)

    def paint(self, p: QPainter, option, index: QModelIndex) -> None:
        t = theme.current()
        ref: ChapterRef = index.data(ChapterModel.RefRole)
        state = self.model.state_of(ref)
        selected = ref.key in self.model.selected
        hovered = bool(option.state & QStyle.State_MouseOver)
        rect = QRect(option.rect).adjusted(6, 2, -6, -2)

        p.save()
        p.setRenderHint(QPainter.Antialiasing)

        # row background
        if selected:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(t['accent_soft']))
            p.drawRoundedRect(QRectF(rect), 8, 8)
        elif hovered:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(t['hover']))
            p.drawRoundedRect(QRectF(rect), 8, 8)

        # checkbox
        box = QRectF(rect.left() + 10, rect.center().y() - 8.5, 17, 17)
        if selected:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(t['accent']))
            p.drawRoundedRect(box, 5, 5)
            pen = QPen(QColor(t['on_accent']), 2.0, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
            p.setPen(pen)
            path = QPainterPath()
            path.moveTo(box.left() + 4.2, box.center().y() + 0.3)
            path.lineTo(box.left() + 7.3, box.bottom() - 4.4)
            path.lineTo(box.right() - 3.8, box.top() + 5)
            p.drawPath(path)
        elif state == EARLY:
            p.setPen(QPen(QColor(t['border']), 1.2, Qt.DashLine))      # can't be ticked
            p.setBrush(QColor(t['surface_alt']))
            p.drawRoundedRect(box, 5, 5)
        else:
            p.setPen(QPen(QColor(t['border_strong']), 1.4))
            p.setBrush(QColor(t['surface']))
            p.drawRoundedRect(box, 5, 5)

        # status pill (right side)
        pill_text, fg, bg = self._pill(state, ref, t)
        font = QFont(option.font)
        font.setPointSizeF(font.pointSizeF() * 0.88)
        font.setBold(True)
        fm = QFontMetrics(font)
        pill_w = fm.horizontalAdvance(pill_text) + 18 if pill_text else 0
        right = rect.right() - 10
        if pill_text and state == 'none':
            # Quiet label instead of a pill - most rows look like this.
            font.setBold(False)
            p.setFont(font)
            p.setPen(QColor(fg))
            text_w = fm.horizontalAdvance(pill_text)
            p.drawText(QRectF(right - text_w - 9, rect.top(), text_w + 9, rect.height()),
                       Qt.AlignRight | Qt.AlignVCenter, pill_text)
            right = right - text_w - 19
        elif pill_text:
            pill = QRectF(right - pill_w, rect.center().y() - 10, pill_w, 20)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(bg))
            p.drawRoundedRect(pill, 10, 10)
            if state == DOWNLOADING:
                progress = self.model.live.get(ref.key, (DOWNLOADING, 0))[1]
                fill = QRectF(pill.left(), pill.top(), pill.width() * max(0.06, progress / 100), pill.height())
                clip = QPainterPath()
                clip.addRoundedRect(pill, 10, 10)
                p.save()
                p.setClipPath(clip)
                p.setBrush(QColor(t['accent_soft_strong']))
                p.drawRect(fill)
                p.restore()
            p.setFont(font)
            p.setPen(QColor(fg))
            p.drawText(pill, Qt.AlignCenter, pill_text)
            right = pill.left() - 10

        # release group chip - only when several groups uploaded this chapter
        if len(ref.sources) > 1:
            chip_font = QFont(option.font)
            chip_font.setPointSizeF(chip_font.pointSizeF() * 0.86)
            cfm = QFontMetrics(chip_font)
            chip_text = cfm.elidedText(ref.group or 'Group', Qt.ElideRight, 120)
            chip_w = cfm.horizontalAdvance(chip_text) + 30
            chip = QRectF(right - chip_w, rect.center().y() - 10, chip_w, 20)
            locked = ref.group_locked
            p.setPen(QPen(QColor(t['accent'] if locked else t['border_strong']), 1))
            p.setBrush(QColor(t['accent_soft'] if locked else t['surface']))
            p.drawRoundedRect(chip, 10, 10)
            color = QColor(t['accent_text'] if locked else t['text_muted'])
            p.setFont(chip_font)
            p.setPen(color)
            p.drawText(chip.adjusted(10, 0, -18, 0), Qt.AlignLeft | Qt.AlignVCenter, chip_text)
            chevron = QPainterPath()
            cx, cy = chip.right() - 12, chip.center().y()
            chevron.moveTo(cx - 3, cy - 1.5)
            chevron.lineTo(cx, cy + 1.5)
            chevron.lineTo(cx + 3, cy - 1.5)
            p.setPen(QPen(color, 1.4, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            p.setBrush(Qt.NoBrush)
            p.drawPath(chevron)
            self.chips[ref.key] = (chip.left(), chip.right())
            right = chip.left() - 10
        else:
            self.chips.pop(ref.key, None)

        # texts
        text_left = int(box.right()) + 12
        text_rect = QRect(text_left, rect.top(), max(10, int(right) - text_left), rect.height())
        title_font = QFont(option.font)
        title_font.setWeight(QFont.DemiBold)
        title = f"Chapter {ref.number}"
        if ref.volume:
            title += f"  ·  Vol. {ref.volume}"
        subtitle = ref.display_name
        if ref.group and len(ref.sources) < 2:      # several groups: shown in the chip
            subtitle = f"{subtitle}  ·  {ref.group}" if subtitle else ref.group

        p.setFont(title_font)
        p.setPen(QColor(t['text_muted'] if state == EARLY else t['text']))
        tfm = QFontMetrics(title_font)
        if subtitle:
            top = QRect(text_rect.left(), text_rect.top() + 6, text_rect.width(), text_rect.height() // 2 - 4)
            p.drawText(top, Qt.AlignLeft | Qt.AlignVCenter, tfm.elidedText(title, Qt.ElideRight, top.width()))
            sub_font = QFont(option.font)
            sub_font.setPointSizeF(sub_font.pointSizeF() * 0.92)
            p.setFont(sub_font)
            p.setPen(QColor(t['text_muted']))
            bottom = QRect(text_rect.left(), text_rect.center().y() + 1, text_rect.width(), text_rect.height() // 2 - 6)
            p.drawText(bottom, Qt.AlignLeft | Qt.AlignVCenter,
                       QFontMetrics(sub_font).elidedText(subtitle, Qt.ElideRight, bottom.width()))
        else:
            p.drawText(text_rect, Qt.AlignLeft | Qt.AlignVCenter, tfm.elidedText(title, Qt.ElideRight, text_rect.width()))
        p.restore()

    @staticmethod
    def _pill(state: str, ref: ChapterRef, t) -> tuple:
        if state == DONE:
            return 'Downloaded', t['success'], t['success_soft']
        if state == DOWNLOADING:
            return 'Downloading', t['accent_text'], t['accent_soft']
        if state == QUEUED:
            return 'Queued', t['info'], t['info_soft']
        if state == FAILED:
            return 'Failed · Retry', t['danger'], t['danger_soft']
        if state == EARLY:
            return f"Early access · {ref.free_label}", t['warning'], t['warning_soft']
        if state == 'new':
            return 'New', t['accent_text'], t['accent_soft']
        return 'Not downloaded', t['text_faint'], t['surface_alt']


class ChapterList(QListView):
    """List with click-to-toggle and shift-click range selection."""
    open_requested = Signal(object)
    redownload_requested = Signal(object)
    group_requested = Signal(object, QPoint)      # ref, global position for the menu

    def __init__(self, model: ChapterModel, parent=None):
        super().__init__(parent)
        self.setModel(model)
        self._delegate = ChapterDelegate(model, self)
        self.setItemDelegate(self._delegate)
        self.setSelectionMode(QListView.NoSelection)
        self.setMouseTracking(True)
        self.setUniformItemSizes(True)
        self.setVerticalScrollMode(QListView.ScrollPerPixel)
        self.setFocusPolicy(Qt.NoFocus)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu)
        self._model = model
        self._anchor: Optional[int] = None
        self._anchor_value = True
        theme.notifier.changed.connect(self.viewport().update)

    RETRY_HIT_WIDTH = 130     # right-hand area of a row holding the status pill

    def mousePressEvent(self, event):
        index = self.indexAt(event.position().toPoint())
        if event.button() == Qt.LeftButton and index.isValid():
            row = index.row()
            ref = index.data(ChapterModel.RefRole)
            if (self._model.state_of(ref) == FAILED
                    and event.position().x() > self.viewport().width() - self.RETRY_HIT_WIDTH):
                self.redownload_requested.emit(ref)
                return
            chip = self._delegate.chips.get(ref.key)
            if chip and len(ref.sources) > 1 and chip[0] <= event.position().x() <= chip[1]:
                rect = self.visualRect(index)
                self.group_requested.emit(ref, self.viewport().mapToGlobal(QPoint(int(chip[0]), rect.bottom())))
                return
            if event.modifiers() & Qt.ShiftModifier and self._anchor is not None:
                self._model.set_range(self._anchor, row, self._anchor_value)
            else:
                self._anchor_value = self._model.toggle(row)
                self._anchor = row
            return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        index = self.indexAt(event.position().toPoint())
        if index.isValid():
            ref = index.data(ChapterModel.RefRole)
            if ref.downloaded:
                self.open_requested.emit(ref)
                return
        self.mousePressEvent(event)

    def _menu(self, pos: QPoint) -> None:
        index = self.indexAt(pos)
        if not index.isValid():
            return
        ref: ChapterRef = index.data(ChapterModel.RefRole)
        menu = QMenu(self)
        row = index.row()
        t = theme.current()
        if ref.downloaded:
            menu.addAction(icons.icon('folder', t['text_muted']), "Show in folder", lambda: self.open_requested.emit(ref))
            menu.addAction(icons.icon('retry', t['text_muted']), "Download again", lambda: self.redownload_requested.emit(ref))
            menu.addSeparator()
        if len(ref.sources) > 1:
            menu.addAction(icons.icon('stack', t['text_muted']), f"Release group: {ref.group}…",
                           lambda: self.group_requested.emit(ref, self.viewport().mapToGlobal(pos)))
            menu.addSeparator()
        menu.addAction("Select this and all above", lambda: self._model.set_range(0, row, True))
        menu.addAction("Select this and all below", lambda: self._model.set_range(row, self._model.rowCount() - 1, True))
        menu.exec(self.viewport().mapToGlobal(pos))


# =============================================================== panel
class ChapterPanel(QFrame):
    closed = Signal()
    toast = Signal(str, str, str)          # title, message, level

    def __init__(self, core: AppCore, bridge: Bridge, parent=None):
        super().__init__(parent)
        self.setObjectName('ChapterPanel')
        self.setMinimumWidth(380)
        self.core = core
        self.manga_id: Optional[int] = None
        self.fetched: Optional[FetchedManga] = None
        self._by_language: Dict[str, List[ChapterRef]] = {}
        self._language = 'en'
        self._busy = False
        self._desc_expanded = False

        self.model = ChapterModel(self)
        self.model.selection_changed.connect(self._update_footer)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ---- header
        header = QWidget(self)
        hl = QHBoxLayout(header)
        hl.setContentsMargins(20, 18, 14, 14)
        hl.setSpacing(14)
        self.cover = Cover(72, 104, 10, header)
        hl.addWidget(self.cover, 0, Qt.AlignTop)

        info = QVBoxLayout()
        info.setSpacing(4)
        top = QHBoxLayout()
        top.setSpacing(6)
        self.title = label('', 'h2', header, wrap=True)
        self.title.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        top.addWidget(self.title, 1, Qt.AlignTop)
        self.close_btn = IconButton('x', 'Close', header, size=30)
        self.close_btn.clicked.connect(self.close_panel)
        top.addWidget(self.close_btn, 0, Qt.AlignTop)
        info.addLayout(top)

        badges = QHBoxLayout()
        badges.setSpacing(6)
        self.site_pill = Pill('', 'neutral', header)
        self.status_pill = Pill('', 'neutral', header)
        self.novel_pill = Pill('Novel', 'info', header)
        self.novel_pill.setToolTip('Text chapters - saved in the novel format chosen in Settings (EPUB by default)')
        badges.addWidget(self.site_pill)
        badges.addWidget(self.novel_pill)
        badges.addWidget(self.status_pill)
        badges.addStretch(1)
        info.addLayout(badges)
        self.byline = label('', 'muted', header, wrap=True)
        info.addWidget(self.byline)

        actions = QHBoxLayout()
        actions.setSpacing(4)
        self.refresh_btn = Button('Check for new', 'refresh', 'ghost', header)
        self.refresh_btn.clicked.connect(self._refresh)
        self.folder_btn = IconButton('folder', 'Open download folder', header)
        self.folder_btn.clicked.connect(self._open_folder)
        self.web_btn = IconButton('external', 'Open on website', header)
        self.web_btn.clicked.connect(self._open_web)
        actions.addWidget(self.refresh_btn)
        actions.addWidget(self.folder_btn)
        actions.addWidget(self.web_btn)
        actions.addStretch(1)
        info.addLayout(actions)
        hl.addLayout(info, 1)
        root.addWidget(header)

        self.description = label('', 'muted', self, wrap=True)
        self.description.setContentsMargins(20, 0, 20, 0)
        self.description.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.desc_toggle = Button('Show more', None, 'ghost', self)
        self.desc_toggle.setStyleSheet('padding: 2px 8px;')
        self.desc_toggle.clicked.connect(self._toggle_description)
        root.addWidget(self.description)
        dt = QHBoxLayout()
        dt.setContentsMargins(12, 0, 20, 4)
        dt.addWidget(self.desc_toggle)
        dt.addStretch(1)
        root.addLayout(dt)

        # ---- stats
        stats = QWidget(self)
        sl = QVBoxLayout(stats)
        sl.setContentsMargins(20, 6, 20, 10)
        sl.setSpacing(6)
        self.stats_label = label('', 'muted', stats)
        self.stats_bar = QProgressBar(stats)
        self.stats_bar.setProperty('tone', 'success')
        self.stats_bar.setTextVisible(False)
        sl.addWidget(self.stats_label)
        sl.addWidget(self.stats_bar)
        root.addWidget(stats)
        root.addWidget(divider(self))

        # ---- controls
        controls = QWidget(self)
        cl = QVBoxLayout(controls)
        cl.setContentsMargins(14, 10, 14, 6)
        cl.setSpacing(8)
        row1 = QHBoxLayout()
        row1.setSpacing(6)
        self.filter = Segmented([('all', 'All'), ('missing', 'Missing'), ('downloaded', 'Downloaded'), ('new', 'New')],
                                'all', controls)
        self.filter.changed.connect(self.model.set_filter)
        row1.addWidget(self.filter)
        row1.addStretch(1)
        self.sort_btn = IconButton('sort', 'Newest first', controls)
        self.sort_btn.clicked.connect(self._toggle_sort)
        row1.addWidget(self.sort_btn)
        cl.addLayout(row1)

        row2 = QHBoxLayout()
        row2.setSpacing(6)
        self.language = QComboBox(controls)
        self.language.setMinimumWidth(150)
        self.language.currentIndexChanged.connect(self._language_changed)
        row2.addWidget(self.language)
        self.group_filter = QComboBox(controls)
        self.group_filter.setMinimumWidth(150)
        self.group_filter.setToolTip('Release group to download from. Chapters this group didn\'t release '
                                     'use the first available group.\nClick the group on a chapter to change '
                                     'just that one.')
        self.group_filter.currentIndexChanged.connect(self._group_filter_changed)
        row2.addWidget(self.group_filter)
        self.search = QLineEdit(controls)
        self.search.setPlaceholderText('Find chapter…')
        self.search.setClearButtonEnabled(True)
        self.search.addAction(icons.icon('search', theme.current()['text_faint'], 16), QLineEdit.LeadingPosition)
        self.search.textChanged.connect(self.model.set_search)
        row2.addWidget(self.search, 1)
        self.range_input = QLineEdit(controls)
        self.range_input.setPlaceholderText('Range e.g. 1-20')
        self.range_input.setFixedWidth(130)
        self.range_input.setToolTip('Select a range of chapters and press Enter (e.g. "1-20", "5", "10-")')
        self.range_input.returnPressed.connect(self._select_range)
        row2.addWidget(self.range_input)
        cl.addLayout(row2)

        row3 = QHBoxLayout()
        row3.setSpacing(2)
        self.sel_missing = Button('Select missing', None, 'ghost', controls)
        self.sel_missing.clicked.connect(lambda: self.model.select_where(lambda r: not r.downloaded))
        self.sel_new = Button('Select new', None, 'ghost', controls)
        self.sel_new.clicked.connect(lambda: self.model.select_where(lambda r: r.is_new and not r.downloaded))
        self.sel_all = Button('Select all', None, 'ghost', controls)
        self.sel_all.clicked.connect(lambda: self.model.select_where(lambda r: True))
        self.sel_none = Button('Clear', None, 'ghost', controls)
        self.sel_none.clicked.connect(self.model.clear_selection)
        for b in (self.sel_missing, self.sel_new, self.sel_all, self.sel_none):
            b.setStyleSheet('padding: 4px 8px;')
            row3.addWidget(b)
        row3.addStretch(1)
        self.retry_btn = Button('Retry failed', 'retry', 'danger', controls)
        self.retry_btn.setStyleSheet('padding: 4px 10px;')
        self.retry_btn.clicked.connect(lambda: self._download(self.model.failed()))
        self.retry_btn.setVisible(False)
        row3.addWidget(self.retry_btn)
        cl.addLayout(row3)
        root.addWidget(controls)

        # ---- list
        self.list = ChapterList(self.model, self)
        self.list.open_requested.connect(self._show_file)
        self.list.redownload_requested.connect(lambda ref: self._download([ref]))
        self.list.group_requested.connect(self._group_menu)
        root.addWidget(self.list, 1)

        self.empty = label('No chapters match this filter.', 'faint', self)
        self.empty.setAlignment(Qt.AlignCenter)
        root.addWidget(self.empty)

        # ---- footer
        root.addWidget(divider(self))
        footer = QWidget(self)
        fl = QHBoxLayout(footer)
        fl.setContentsMargins(20, 12, 16, 14)
        fl.setSpacing(8)
        self.footer_label = label('', 'muted', footer)
        fl.addWidget(self.footer_label, 1)
        self.save_btn = Button('Save to library', 'plus', None, footer)
        self.save_btn.clicked.connect(self._save_only)
        fl.addWidget(self.save_btn)
        self.download_btn = Button('Download', 'download', 'primary', footer)
        self.download_btn.clicked.connect(lambda: self._download(self.model.selected_refs()))
        fl.addWidget(self.download_btn)
        root.addWidget(footer)

        self._reload_timer = QTimer(self)
        self._reload_timer.setSingleShot(True)
        self._reload_timer.setInterval(250)
        self._reload_timer.timeout.connect(self._reload_from_db)

        bridge.chapter_state.connect(self._on_chapter_state)
        bridge.library_changed.connect(self._on_library_changed)
        bridge.check_state.connect(self._on_check_state)

    # ================================================================ open
    def open_manga(self, manga_id: int) -> None:
        self._leave_current()
        manga = self.core.library.get_manga(manga_id)
        if not manga:
            return
        self.manga_id, self.fetched = manga_id, None
        self.model.clear_selection()
        self._fill_header(manga['title'], manga.get('site_type', ''), manga.get('status', ''),
                          manga.get('author', ''), manga.get('description', ''), manga.get('cover_image_path', ''))
        self.novel_pill.setVisible(is_novel_url(manga.get('url', '')))
        self._load_chapters(self.core.library.chapters(manga_id), keep_language=False)
        self._on_check_state(manga_id, self.core.updates.is_checking(manga_id))
        self._set_mode()

    def open_preview(self, fetched: FetchedManga) -> None:
        self._leave_current()
        if fetched.manga_id:
            # Already in the library: show real download states but keep the fresh chapter list.
            self.core.library.register(fetched)
            self.open_manga(fetched.manga_id)
            return
        self.manga_id, self.fetched = None, fetched
        self.model.clear_selection()
        meta = fetched.metadata
        self._fill_header(fetched.title, fetched.site_type, getattr(meta, 'status', ''),
                          getattr(meta, 'author', ''), getattr(meta, 'description', ''), fetched.cover_path)
        self.novel_pill.setVisible(fetched.is_novel)
        refs = [ChapterRef(**{**r.__dict__}) for refs in fetched.chapters.values() for r in refs]
        self._load_chapters(refs, keep_language=False)
        self._set_mode()

    def close_panel(self) -> None:
        self._leave_current()
        self.manga_id, self.fetched = None, None
        self.closed.emit()

    def current_manga_id(self) -> Optional[int]:
        return self.manga_id

    # ============================================================ helpers
    def _leave_current(self) -> None:
        if self.manga_id is not None:
            had_new = any(r.is_new for refs in self._by_language.values() for r in refs)
            if had_new:
                self.core.library.mark_seen(self.manga_id)

    def _fill_header(self, title, site_type, status, author, description, cover) -> None:
        self.title.setText(title)
        self.cover.set_cover(cover or '', title)
        self.site_pill.set(site_label(site_type), 'neutral')
        status = (status or '').lower()
        tone = {'ongoing': 'accent', 'completed': 'success', 'cancelled': 'danger', 'hiatus': 'warning'}.get(status, 'neutral')
        self.status_pill.set(status.title() if status and status != 'unknown' else 'Status unknown', tone)
        author = author if author and any(ch.isalnum() for ch in author) else ''
        self.byline.setText(f"by {author}" if author else '')
        self.byline.setVisible(bool(author))
        self._description = re.sub(r'\s+', ' ', description or '').strip()
        self._desc_expanded = False
        self._render_description()

    def _render_description(self) -> None:
        text = self._description
        long = len(text) > 220
        self.description.setText(text if (self._desc_expanded or not long) else text[:220].rsplit(' ', 1)[0] + '…')
        self.description.setVisible(bool(text))
        self.desc_toggle.setVisible(long)
        self.desc_toggle.setText('Show less' if self._desc_expanded else 'Show more')

    def _toggle_description(self) -> None:
        self._desc_expanded = not self._desc_expanded
        self._render_description()

    def _load_chapters(self, refs: List[ChapterRef], keep_language: bool = True) -> None:
        by_language: Dict[str, List[ChapterRef]] = {}
        for ref in refs:
            by_language.setdefault(ref.language, []).append(ref)
        self._by_language = by_language

        if not keep_language or self._language not in by_language:
            self._language = self._preferred_language(by_language)

        self.language.blockSignals(True)
        self.language.clear()
        ordered = sorted(by_language, key=lambda l: (l != 'en', language_name(l)))
        for lang in ordered:
            self.language.addItem(f"{language_name(lang)}  ({len(by_language[lang])})", lang)
        self.language.setCurrentIndex(max(0, ordered.index(self._language)) if self._language in ordered else 0)
        self.language.blockSignals(False)
        self.language.setVisible(len(by_language) > 1)

        self.model.live = {}
        if self.manga_id is not None:
            self.model.live = dict(self.core.downloads.chapter_states(self.manga_id))
            self.model.errors = {key: self.core.downloads.chapter_error(self.manga_id, key)
                                 for key, (state, _p) in self.model.live.items() if state == FAILED}
        self.model.set_chapters(by_language.get(self._language, []))
        self._fill_groups()
        self._update_stats()

    @staticmethod
    def _preferred_language(by_language: Dict[str, List[ChapterRef]]) -> str:
        if not by_language:
            return 'en'
        downloaded = {l: sum(r.downloaded for r in refs) for l, refs in by_language.items()}
        best = max(downloaded, key=downloaded.get)
        if downloaded[best]:
            return best
        if 'en' in by_language:
            return 'en'
        return max(by_language, key=lambda l: len(by_language[l]))

    def _language_changed(self, index: int) -> None:
        lang = self.language.itemData(index)
        if lang and lang != self._language:
            self._language = lang
            self.model.clear_selection()
            self.model.set_chapters(self._by_language.get(lang, []))
            self._fill_groups()
            self._update_stats()

    # ------------------------------------------------------ release groups
    def _preferred_group(self) -> str:
        if self.fetched is not None:
            return self.fetched.preferred_group
        return (self.core.library.get_manga(self.manga_id) or {}).get('preferred_group', '') if self.manga_id else ''

    def _fill_groups(self) -> None:
        """Groups of the shown language, the one with the most chapters first."""
        counts: Dict[str, int] = {}
        for ref in self.model.chapters():
            for group in ([s.group for s in ref.sources] or ([ref.group] if ref.group else [])):
                counts[group] = counts.get(group, 0) + 1
        preferred = self._preferred_group()
        self.group_filter.blockSignals(True)
        self.group_filter.clear()
        self.group_filter.addItem('Any release group', '')
        for group in sorted(counts, key=lambda g: (-counts[g], g.lower())):
            self.group_filter.addItem(f"{group}  ({counts[group]})", group)
        if preferred and preferred not in counts:
            self.group_filter.addItem(f"{preferred}  (0)", preferred)
        index = self.group_filter.findData(preferred)
        self.group_filter.setCurrentIndex(max(0, index))
        self.group_filter.blockSignals(False)
        self.group_filter.setVisible(len(counts) > 1)

    def _group_filter_changed(self, index: int) -> None:
        group = self.group_filter.itemData(index) or ''
        if self.fetched is not None:
            self.fetched.preferred_group = group
            for ref in self._preview_refs():
                if ref.sources and not ref.group_locked:
                    ref.use_source(pick_source(ref.sources, group))
            self.list.viewport().update()
        elif self.manga_id is not None:
            self.core.library.set_preferred_group(self.manga_id, group)
        missing = sum(1 for r in self.model.chapters() if r.sources and group
                      and all(s.group != group for s in r.sources) and not r.downloaded)
        if group and missing:
            self.toast.emit('Release group', f"{missing} chapters aren't released by {group} - "
                            "they use the first available group.", 'info')

    def _preview_refs(self) -> List[ChapterRef]:
        """The panel's chapters and the fetched result they were copied from (stored on save)."""
        return [r for refs in self._by_language.values() for r in refs] + \
               [r for refs in self.fetched.chapters.values() for r in refs]

    def _group_menu(self, ref: ChapterRef, pos: QPoint) -> None:
        menu = QMenu(self)
        auto = menu.addAction('Use the group filter')
        auto.setCheckable(True)
        auto.setChecked(not ref.group_locked)
        auto.triggered.connect(lambda: self._set_chapter_group(ref, ''))
        menu.addSeparator()
        for source in ref.sources:
            action = menu.addAction(source.group)
            action.setCheckable(True)
            action.setChecked(source.group == ref.group)
            action.triggered.connect(lambda _=False, g=source.group: self._set_chapter_group(ref, g))
        menu.exec(pos)

    def _set_chapter_group(self, ref: ChapterRef, group: str) -> None:
        if self.fetched is not None:
            source = next((s for s in ref.sources if s.group == group), None) if group else None
            locked = source is not None
            source = source or pick_source(ref.sources, self.fetched.preferred_group)
            for other in self._preview_refs():
                if other.key == ref.key and source:
                    other.use_source(source)
                    other.group_locked = locked
        elif self.manga_id is not None:
            self.core.library.set_chapter_group(self.manga_id, ref, group)
        self.list.viewport().update()
        if ref.downloaded and group:
            self.toast.emit('Release group changed', f"Chapter {ref.number} will come from {ref.group} "
                            "the next time it's downloaded (right-click › Download again).", 'info')

    def _update_retry(self) -> None:
        failed = len(self.model.failed())
        self.retry_btn.setText(f"Retry {failed} failed")
        self.retry_btn.setVisible(failed > 0)

    def _update_stats(self) -> None:
        chapters = self.model.chapters()
        total = len(chapters)
        done = sum(1 for r in chapters if r.downloaded)
        new = sum(1 for r in chapters if r.is_new and not r.downloaded)
        text = f"{done} of {total} chapters downloaded"
        if new:
            text += f"  ·  {new} new"
        self.stats_label.setText(text)
        self.stats_bar.setMaximum(max(1, total))
        self.stats_bar.setValue(done)
        self.filter.set_visible('new', new > 0 or self.model.filter_mode == 'new')
        self.sel_new.setVisible(new > 0)
        self._update_retry()
        self.filter.set_label('missing', f"Missing  {total - done}" if total - done else 'Missing')
        self.empty.setVisible(self.model.rowCount() == 0)
        self.list.setVisible(self.model.rowCount() > 0)

    def _set_mode(self) -> None:
        preview = self.fetched is not None
        self.refresh_btn.setVisible(not preview)
        self.folder_btn.setVisible(not preview)
        self.save_btn.setVisible(preview)
        self._update_footer()

    def _update_footer(self) -> None:
        count = len(self.model.selected)
        self.footer_label.setText(f"{count} selected" if count else 'Click chapters to select · Shift-click for a range')
        self.download_btn.setEnabled(count > 0 and not self._busy)
        self.save_btn.setEnabled(not self._busy)
        self.download_btn.setText(f"Download {count}" if count else 'Download')
        self.empty.setVisible(self.model.rowCount() == 0)
        self.list.setVisible(self.model.rowCount() > 0)

    def _toggle_sort(self) -> None:
        self.model.toggle_sort()
        self.sort_btn.setToolTip('Newest first' if self.model.newest_first else 'Oldest first')

    def _select_range(self) -> None:
        text = self.range_input.text().strip()
        match = re.fullmatch(r'(\d+(?:\.\d+)?)?\s*(-)?\s*(\d+(?:\.\d+)?)?', text)
        if not text or not match or not (match.group(1) or match.group(3)):
            self.toast.emit('Invalid range', 'Use a format like 1-20, 5, or 10-', 'warning')
            return
        lo = float(match.group(1)) if match.group(1) else float('-inf')
        if match.group(2):
            hi = float(match.group(3)) if match.group(3) else float('inf')
        else:
            hi = lo
        count_before = len(self.model.selected)
        self.model.select_where(lambda r: lo <= chapter_sort_key(r.number)[0] <= hi)
        added = len(self.model.selected) - count_before
        if not added:
            self.toast.emit('Nothing selected', f'No chapters between {text} in this list', 'info')
        self.range_input.clear()

    # ============================================================ actions
    def _download(self, refs: List[ChapterRef]) -> None:
        if not refs or self._busy:
            return
        if self.fetched is not None:
            fetched = self.fetched
            keys = {r.key for r in refs}
            self._set_busy(True)

            def done(manga_id):
                self._set_busy(False)
                stored = [r for r in self.core.library.chapters(manga_id) if r.key in keys]
                self.core.downloads.add(manga_id, stored)
                self.toast.emit('Added to queue', f"{fetched.title} · {len(stored)} chapters", 'success')
                if self.fetched is fetched:
                    self.open_manga(manga_id)

            run_async(lambda: self.core.library.register(fetched), done, self._failed)
            return
        if self.manga_id is not None:
            self.core.downloads.add(self.manga_id, refs)
            self.model.clear_selection()
            noun = 'chapter' if len(refs) == 1 else 'chapters'
            self.toast.emit('Added to queue', f"{self.title.text()} · {len(refs)} {noun}", 'success')

    def _save_only(self) -> None:
        if self.fetched is None or self._busy:
            return
        fetched = self.fetched
        self._set_busy(True)

        def done(manga_id):
            self._set_busy(False)
            self.toast.emit('Saved to library', fetched.title, 'success')
            if self.fetched is fetched:
                self.open_manga(manga_id)

        run_async(lambda: self.core.library.register(fetched), done, self._failed)

    def _failed(self, message: str) -> None:
        self._set_busy(False)
        self.toast.emit("Something went wrong", message, 'error')

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self._update_footer()

    def _refresh(self) -> None:
        if self.manga_id is not None:
            self.core.updates.check_one(self.manga_id)

    def _url(self) -> str:
        return self.fetched.url if self.fetched else (self.core.library.get_manga(self.manga_id) or {}).get('url', '')

    def _open_folder(self) -> None:
        novel = is_novel_url(self._url())
        folder = self.core.library.manga_folder(self.title.text(), novel)
        if not os.path.isdir(folder):
            folder = self.core.library.download_root(novel)
        QDesktopServices.openUrl(QUrl.fromLocalFile(folder))

    def _open_web(self) -> None:
        url = self._url()
        if url:
            QDesktopServices.openUrl(QUrl(url))

    def _show_file(self, ref: ChapterRef) -> None:
        path = ref.file_path if ref.file_path and os.path.exists(ref.file_path) else ''
        folder = os.path.dirname(path) if path else self.core.library.manga_folder(self.title.text(),
                                                                                    is_novel_url(self._url()))
        QDesktopServices.openUrl(QUrl.fromLocalFile(folder))

    # ============================================================= events
    def _on_chapter_state(self, manga_id: int, language: str, number: str, state: str, progress: int) -> None:
        if manga_id != self.manga_id:
            return
        key = (language, number)
        if state == FAILED:
            self.model.errors[key] = self.core.downloads.chapter_error(manga_id, key)
        self.model.set_live(key, state, progress)
        if state in (DONE, FAILED, QUEUED):
            self._update_retry()
        if state == DONE:
            self._update_stats()

    def _on_library_changed(self, manga_id: int) -> None:
        if manga_id == self.manga_id:
            self._reload_timer.start()

    def _reload_from_db(self) -> None:
        if self.manga_id is None:
            return
        manga = self.core.library.get_manga(self.manga_id)
        if not manga:
            self.close_panel()
            return
        selected = set(self.model.selected)
        scroll = self.list.verticalScrollBar().value()
        self.cover.set_cover(manga.get('cover_image_path') or '', manga['title'])
        self._load_chapters(self.core.library.chapters(self.manga_id))
        self.model.selected = selected & {r.key for r in self.model.chapters()}
        self.list.verticalScrollBar().setValue(scroll)
        self.list.viewport().update()
        self._update_footer()

    def _on_check_state(self, manga_id: int, checking: bool) -> None:
        if manga_id != self.manga_id:
            return
        self.refresh_btn.setEnabled(not checking)
        self.refresh_btn.setText('Checking…' if checking else 'Check for new')
