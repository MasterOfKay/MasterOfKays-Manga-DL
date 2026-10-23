"""
Browse page: newest manga per site, search and category filter across sites.
Clicking a manga opens the chapter panel (like pasting its link).
"""

from typing import Dict, List

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, QTimer, Signal
from PySide6.QtWidgets import (QComboBox, QFrame, QHBoxLayout, QLineEdit, QProgressBar, QPushButton, QScrollArea,
                               QVBoxLayout, QWidget)

from ...core import AppCore
from ...sites.browsing import BrowseItem
from .. import icons, theme
from ..bridge import Bridge
from ..tasks import run_async
from ..widgets import Button, Card, Cover, ElidedLabel, IconButton, Pill, label

CARD_WIDTH = 148
COVER_HEIGHT = 208


# -------------------------------------------------------------- thumbnails
class _ThumbRelay(QObject):
    ready = Signal(object, str)        # callback, local path


class _ThumbTask(QRunnable):
    def __init__(self, core, item, callback, relay):
        super().__init__()
        self.core, self.item, self.callback, self.relay = core, item, callback, relay

    def run(self):
        path = self.core.browse.thumbnail(self.item.cover_url, self.item.site)
        try:
            self.relay.ready.emit(self.callback, path)
        except RuntimeError:
            pass


class Thumbnails:
    """Downloads remote covers on a small private pool (doesn't block other tasks)."""

    def __init__(self, core):
        self.core = core
        self.pool = QThreadPool()
        self.pool.setMaxThreadCount(6)
        self.relay = _ThumbRelay()
        self.relay.ready.connect(self._deliver)

    def request(self, item: BrowseItem, callback) -> None:
        if item.cover_url:
            self.pool.start(_ThumbTask(self.core, item, callback, self.relay))

    @staticmethod
    def _deliver(callback, path):
        try:
            callback(path)
        except RuntimeError:
            pass   # card was removed meanwhile


# -------------------------------------------------------------------- card
class BrowseCard(QFrame):
    clicked = Signal(object)

    def __init__(self, item: BrowseItem, in_library: bool, thumbs: Thumbnails, parent=None):
        super().__init__(parent)
        self.item = item
        self.setFixedWidth(CARD_WIDTH)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(item.title + (f"\n{', '.join(item.genres[:6])}" if item.genres else ''))
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)
        self.cover = Cover(CARD_WIDTH, COVER_HEIGHT, 10, self)
        self.cover.set_cover('', item.title)
        layout.addWidget(self.cover)
        title = label(item.title, None, self, wrap=True)
        title.setMaximumHeight(title.fontMetrics().lineSpacing() * 2 + 2)
        title.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        font = title.font()
        font.setWeight(font.Weight.DemiBold)
        title.setFont(font)
        layout.addWidget(title)
        self.sub = ElidedLabel(item.latest or (item.status.title() if item.status else ''), self)
        self.sub.setProperty('role', 'faint')
        layout.addWidget(self.sub)
        if in_library:
            pill = Pill('In library', 'success', self)
            layout.addWidget(pill)
        layout.addStretch(1)
        thumbs.request(item, lambda path: self.cover.set_cover(path, item.title) if path else None)

    def set_busy(self, busy: bool) -> None:
        self.sub.setText('Loading…' if busy else (self.item.latest or self.item.status.title()))
        self.setEnabled(not busy)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit(self)
        super().mouseReleaseEvent(event)


class _Row(QScrollArea):
    """Horizontal row; the mouse wheel keeps scrolling the page, not the row."""
    near_end = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setFrameShape(QFrame.NoFrame)
        self.setFixedHeight(COVER_HEIGHT + 118)
        self.horizontalScrollBar().valueChanged.connect(self._check_end)

    def wheelEvent(self, event):
        # Trackpad swipes are handled by the page (see _PageScroll): a gesture is delivered
        # to whichever widget accepted its first event, so the page must own all of it.
        if event.modifiers() & Qt.ShiftModifier:
            super().wheelEvent(event)          # Shift + mouse wheel for PCs without a trackpad
        else:
            event.ignore()


    def _check_end(self, value):
        bar = self.horizontalScrollBar()
        if bar.maximum() and value >= bar.maximum() - CARD_WIDTH * 2:
            self.near_end.emit()


class _PageScroll(QScrollArea):
    """Vertical page scroller that sends sideways trackpad swipes to the row under the cursor."""

    def wheelEvent(self, event):
        pixel, angle = event.pixelDelta(), event.angleDelta()
        delta = pixel if not pixel.isNull() else angle
        if abs(delta.x()) > abs(delta.y()):
            row = self._row_at(event.position().toPoint())
            if row is not None:
                bar = row.horizontalScrollBar()
                bar.setValue(bar.value() - delta.x())
                event.accept()
                return
        super().wheelEvent(event)

    def _row_at(self, pos):
        widget = self.viewport().childAt(pos)
        while widget is not None and not isinstance(widget, _Row):
            widget = widget.parentWidget()
        return widget


# ----------------------------------------------------------------- section
class SiteSection(QWidget):
    open_item = Signal(object)

    def __init__(self, page: 'BrowsePage', site: str, label_text: str):
        super().__init__(page)
        self.page, self.site, self.site_label = page, site, label_text
        self._generation = 0
        self._page_no = 1
        self._has_more = False
        self._loading = False
        self._cards: List[BrowseCard] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        head = QHBoxLayout()
        head.setSpacing(8)
        self.title = label('', 'h2', self)
        head.addWidget(self.title)
        self.count = label('', 'faint', self)
        head.addWidget(self.count)
        head.addStretch(1)
        self.left = IconButton('chevron-left', 'Back', self)
        self.right = IconButton('chevron-right', 'More', self)
        self.left.clicked.connect(lambda: self._scroll(-1))
        self.right.clicked.connect(lambda: self._scroll(1))
        head.addWidget(self.left)
        head.addWidget(self.right)
        layout.addLayout(head)

        self.bar = QProgressBar(self)
        self.bar.setProperty('thin', True)
        self.bar.setRange(0, 0)
        self.bar.setTextVisible(False)
        layout.addWidget(self.bar)

        self.message = QWidget(self)
        ml = QHBoxLayout(self.message)
        ml.setContentsMargins(0, 4, 0, 4)
        self.message_text = label('', 'muted', self.message, wrap=True)
        ml.addWidget(self.message_text, 1)
        self.retry = Button('Try again', 'retry', None, self.message)
        self.retry.clicked.connect(self.reload)
        ml.addWidget(self.retry)
        layout.addWidget(self.message)

        self.row = _Row(self)
        self.row.near_end.connect(self._load_more)
        holder = QWidget(self.row)
        self.cards_layout = QHBoxLayout(holder)
        self.cards_layout.setContentsMargins(0, 0, 0, 8)
        self.cards_layout.setSpacing(14)
        self.cards_layout.addStretch(1)
        self.row.setWidget(holder)
        layout.addWidget(self.row)
        self.reload()

    # ------------------------------------------------------------ loading
    def reload(self) -> None:
        self._generation += 1
        self._page_no = 1
        self._has_more = False
        for card in self._cards:
            card.hide()
            card.deleteLater()
        self._cards.clear()
        self.row.horizontalScrollBar().setValue(0)
        query, category = self.page.query(), self.page.category()
        name = self.page.category_name()
        if query and category:
            self.title.setText(f"“{query}” in {name} on {self.site_label}")
        elif query:
            self.title.setText(f"“{query}” on {self.site_label}")
        elif category:
            self.title.setText(f"{name} on {self.site_label}")
        else:
            self.title.setText(f"New on {self.site_label}")
        if category and not self.page.core.browse.supports(self.site, category):
            self._show_message(f"{self.site_label} has no “{name}” category.", retry=False)
            self.row.hide()
            self.bar.hide()
            self.count.setText('')
            return
        self._fetch()

    def _load_more(self) -> None:
        if self._has_more and not self._loading:
            self._page_no += 1
            self._fetch()

    def _fetch(self) -> None:
        generation, page_no = self._generation, self._page_no
        query, category = self.page.query(), self.page.category()
        self._loading = True
        self.bar.show()
        if page_no == 1:
            self.message.hide()
        browse = self.page.core.browse

        def done(result):
            if generation != self._generation:
                return              # filters changed meanwhile
            items, has_more = result
            self._loading = False
            self._has_more = has_more
            self.bar.hide()
            self._add(items)
            if not self._cards:
                self._show_message('Nothing found.' if (query or category) else 'Nothing to show right now.',
                                   retry=False)
                self.row.hide()
            else:
                self.message.hide()
                self.row.show()
            self.count.setText(f"{len(self._cards)}{'+' if has_more else ''}")

        def failed(message):
            if generation != self._generation:
                return
            self._loading = False
            self.bar.hide()
            self._show_message(f"Couldn't load {self.site_label}: {message}", retry=True)
            if not self._cards:
                self.row.hide()

        run_async(lambda: browse.browse(self.site, query, category, page_no), done, failed)

    def _add(self, items: List[BrowseItem]) -> None:
        index = self.page.library_index
        known = {c.item.url for c in self._cards}
        for item in items:
            if item.url in known:
                continue
            card = BrowseCard(item, bool(self.page.core.browse.find_in_library(item, index)), self.page.thumbs,
                              self.row.widget())
            card.clicked.connect(self.open_item)
            self.cards_layout.insertWidget(self.cards_layout.count() - 1, card)
            self._cards.append(card)

    def _show_message(self, text: str, retry: bool) -> None:
        self.message_text.setText(text)
        self.retry.setVisible(retry)
        self.message.show()

    def _scroll(self, direction: int) -> None:
        bar = self.row.horizontalScrollBar()
        step = max(CARD_WIDTH * 2, self.row.viewport().width() - CARD_WIDTH)
        bar.setValue(bar.value() + direction * step)
        if direction > 0 and bar.value() >= bar.maximum() - CARD_WIDTH:
            self._load_more()


# -------------------------------------------------------------------- page
class BrowsePage(QWidget):
    open_item = Signal(object)          # BrowseCard
    toast = Signal(str, str, str)

    def __init__(self, core: AppCore, bridge: Bridge, parent=None):
        super().__init__(parent)
        self.core = core
        self.thumbs = Thumbnails(core)
        self.library_index = core.browse.library_index()
        self._sections: Dict[str, SiteSection] = {}
        self._started = False
        self._query = ''

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = _PageScroll(self)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        outer.addWidget(scroll)
        body = QWidget(scroll)
        scroll.setWidget(body)
        self.col = QVBoxLayout(body)
        self.col.setContentsMargins(32, 28, 32, 32)
        self.col.setSpacing(12)

        self.col.addWidget(label('Browse', 'h1', body))
        self.col.addWidget(label('The newest manga from every site. Search, filter by category, '
                                 'and click a manga to pick chapters.', 'muted', body))
        self.col.addSpacing(4)

        bar = Card(body)
        bl = QVBoxLayout(bar)
        bl.setContentsMargins(16, 14, 16, 14)
        bl.setSpacing(10)
        top = QHBoxLayout()
        top.setSpacing(8)
        self.search = QLineEdit(bar)
        self.search.setObjectName('UrlInput')
        self.search.setPlaceholderText('Search all sites…')
        self.search.setClearButtonEnabled(True)
        self._search_icon = self.search.addAction(icons.icon('search', theme.current()['text_faint'], 18),
                                                  QLineEdit.LeadingPosition)
        self.search.returnPressed.connect(self._apply)
        self.search.textChanged.connect(lambda t: self._apply() if not t and self._query else None)
        top.addWidget(self.search, 1)
        self.category_box = QComboBox(bar)
        self.category_box.setMinimumWidth(200)
        self.category_box.setMaxVisibleItems(12)      # compact popup that scrolls
        self.category_box.addItem('All categories', '')
        self.category_box.setEnabled(False)
        self.category_box.currentIndexChanged.connect(lambda _i: self._apply())
        top.addWidget(self.category_box)
        go = Button('Search', 'search', 'primary', bar)
        go.setMinimumHeight(38)
        go.clicked.connect(self._apply)
        top.addWidget(go)
        bl.addLayout(top)

        chips = QHBoxLayout()
        chips.setSpacing(6)
        chips.addWidget(label('Sites', 'faint', bar))
        self._chips: Dict[str, QPushButton] = {}
        enabled = core.settings.get('browse.sites') or [k for k, _ in core.browse.sites()]
        for key, name in core.browse.sites():
            chip = QPushButton(name, bar)
            chip.setProperty('chip', True)
            chip.setCheckable(True)
            chip.setChecked(key in enabled)
            chip.setCursor(Qt.PointingHandCursor)
            chip.toggled.connect(lambda checked, k=key: self._site_toggled(k, checked))
            chips.addWidget(chip)
            self._chips[key] = chip
        chips.addStretch(1)
        refresh = IconButton('refresh', 'Reload everything', bar)
        refresh.clicked.connect(self._apply)
        chips.addWidget(refresh)
        bl.addLayout(chips)
        self.col.addWidget(bar)
        self.col.addSpacing(8)

        self.sections_box = QVBoxLayout()
        self.sections_box.setSpacing(26)
        self.col.addLayout(self.sections_box)
        self.col.addStretch(1)

        self._index_timer = QTimer(self)
        self._index_timer.setSingleShot(True)
        self._index_timer.setInterval(500)
        self._index_timer.timeout.connect(self._refresh_index)
        bridge.library_changed.connect(lambda _id: self._index_timer.start())
        theme.notifier.changed.connect(
            lambda: self._search_icon.setIcon(icons.icon('search', theme.current()['text_faint'], 18)))

    # Load lazily: nothing hits the network until the tab is opened.
    def showEvent(self, event):   # noqa: N802
        super().showEvent(event)
        if not self._started:
            self._started = True
            self._load_categories()
            self._build_sections()

    # ------------------------------------------------------------ filters
    def query(self) -> str:
        return self._query

    def category(self) -> str:
        return self.category_box.currentData() or ''

    def category_name(self) -> str:
        category = self.core.browse.category(self.category())
        return category.name if category else ''

    def _load_categories(self) -> None:
        def done(categories):
            self.category_box.blockSignals(True)
            for c in categories:
                sites = len(c.slugs)
                self.category_box.addItem(f"{c.name}   ·  {sites} site{'s' if sites != 1 else ''}", c.key)
            self.category_box.blockSignals(False)
            self.category_box.setEnabled(True)

        run_async(self.core.browse.categories, done,
                  lambda m: self.toast.emit("Couldn't load categories", m, 'warning'))

    def _site_toggled(self, key: str, checked: bool) -> None:
        if not checked and not any(c.isChecked() for c in self._chips.values()):
            self._chips[key].setChecked(True)          # keep at least one site
            return
        self.core.settings.set('browse.sites', [k for k, c in self._chips.items() if c.isChecked()])
        self._build_sections()

    def _apply(self) -> None:
        self._query = self.search.text().strip()
        for section in self._sections.values():
            section.reload()

    def _build_sections(self) -> None:
        wanted = [k for k, c in self._chips.items() if c.isChecked()]
        for key in [k for k in self._sections if k not in wanted]:
            section = self._sections.pop(key)
            section.hide()
            section.deleteLater()
        labels = dict(self.core.browse.sites())
        for key in wanted:
            if key not in self._sections:
                section = SiteSection(self, key, labels[key])
                section.open_item.connect(self.open_item)
                self._sections[key] = section
        while self.sections_box.count():
            self.sections_box.takeAt(0)
        for key in wanted:
            self.sections_box.addWidget(self._sections[key])

    def _refresh_index(self) -> None:
        self.library_index = self.core.browse.library_index()
