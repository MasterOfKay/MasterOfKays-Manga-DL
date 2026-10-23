"""
Updates page: the newest version of the app, the release history from GitHub
and the switch for beta (pre-release) updates.
"""

import re
from datetime import datetime
from typing import List, Optional

from PySide6.QtCore import QUrl, Qt, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QHBoxLayout, QLabel, QProgressBar, QScrollArea, QVBoxLayout, QWidget

from ...core import AppCore
from ...core.app_updates import CURRENT, RELEASES_PAGE, Release, format_version, install_kind
from .. import icons, theme
from ..bridge import Bridge
from ..widgets import Button, Card, EmptyState, IconButton, Pill, Toggle, divider, label


def _date(value: Optional[datetime]) -> str:
    return value.astimezone().strftime('%d %b %Y').lstrip('0') if value else ''


def _ago(value: Optional[datetime]) -> str:
    if not value:
        return 'never'
    seconds = (datetime.now() - value).total_seconds()
    if seconds < 90:
        return 'just now'
    if seconds < 3600:
        return f"{int(seconds // 60)} minutes ago"
    if value.date() == datetime.now().date():
        return f"today at {value:%H:%M}"
    return f"{value:%d %b %Y} at {value:%H:%M}".lstrip('0')


class ReleaseCard(Card):
    install = Signal(object)

    def __init__(self, release: Release, installable: bool, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 14, 18, 16)
        layout.setSpacing(8)

        head = QHBoxLayout()
        head.setSpacing(8)
        head.addWidget(label(f"Version {release.label}", 'h3', self))
        if release.prerelease:
            head.addWidget(Pill('Beta', 'warning', self))
        if release.is_current:
            head.addWidget(Pill('Installed', 'success', self))
        elif release.is_newer:
            head.addWidget(Pill('New', 'accent', self))
        head.addStretch(1)
        head.addWidget(label(_date(release.published), 'faint', self))
        if installable:
            button = Button(f"Install {release.label}", 'download', 'primary', self)
            button.clicked.connect(lambda: self.install.emit(release))
            head.addWidget(button)
        page = IconButton('external', 'Open on GitHub', self)
        page.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(release.page_url)))
        head.addWidget(page)
        layout.addLayout(head)

        name = release.name
        if name and name.lower().lstrip('v') not in (release.tag.lower().lstrip('v'), release.label):
            layout.addWidget(label(name, 'muted', self, wrap=True))

        notes = QLabel(self)
        notes.setTextFormat(Qt.MarkdownText)       # release notes are written in Markdown on GitHub
        # Headings would render huge inside a card - show them as bold lines instead.
        text = re.sub(r'^#{1,6}\s*(.+?)\s*#*$', r'**\1**', release.notes, flags=re.M)
        notes.setText(text or '_No notes for this release._')
        notes.setWordWrap(True)
        notes.setOpenExternalLinks(True)
        notes.setTextInteractionFlags(Qt.TextBrowserInteraction)
        layout.addWidget(notes)


class UpdatesPage(QWidget):
    restart_requested = Signal()
    available_changed = Signal(bool)

    def __init__(self, core: AppCore, bridge: Bridge, parent=None):
        super().__init__(parent)
        self.core = core
        self.updater = core.app_updates
        self._cards: List[QWidget] = []

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
        col.addWidget(label('Updates', 'h1', body))
        col.addWidget(label('New versions of Manga DL come from the releases on GitHub.', 'muted', body))
        col.addSpacing(8)

        # ---- status
        status = Card(body)
        sl = QVBoxLayout(status)
        sl.setContentsMargins(18, 16, 18, 16)
        sl.setSpacing(10)
        top = QHBoxLayout()
        top.setSpacing(14)
        self.status_icon = QLabel(status)
        self.status_icon.setFixedSize(32, 32)
        top.addWidget(self.status_icon, 0, Qt.AlignTop)
        text = QVBoxLayout()
        text.setSpacing(3)
        self.status_title = label('', 'h2', status)
        self.status_text = label('', 'muted', status, wrap=True)
        text.addWidget(self.status_title)
        text.addWidget(self.status_text)
        top.addLayout(text, 1)
        self.check_btn = Button('Check now', 'refresh', None, status)
        self.check_btn.clicked.connect(lambda: self.updater.check(manual=True))
        self.install_btn = Button('Install', 'download', 'primary', status)
        self.install_btn.clicked.connect(lambda: self._install(self.updater.available()))
        self.restart_btn = Button('Restart now', 'retry', 'primary', status)
        self.restart_btn.clicked.connect(self.restart_requested)
        self.github_btn = Button('Open on GitHub', 'external', None, status)
        self.github_btn.clicked.connect(self._open_github)
        for b in (self.check_btn, self.github_btn, self.install_btn, self.restart_btn):
            top.addWidget(b, 0, Qt.AlignTop)
        sl.addLayout(top)
        self.bar = QProgressBar(status)
        self.bar.setProperty('thin', True)
        self.bar.setTextVisible(False)
        self.bar.hide()
        sl.addWidget(self.bar)
        col.addWidget(status)

        # ---- beta
        beta = Card(body)
        bl = QHBoxLayout(beta)
        bl.setContentsMargins(18, 12, 18, 12)
        bl.setSpacing(24)
        bt = QVBoxLayout()
        bt.setSpacing(2)
        bt.addWidget(label('Beta updates', None, beta))
        bt.addWidget(label('Also show and offer pre-releases. They get new features first, '
                           'but something may break.', 'faint', beta, wrap=True))
        bl.addLayout(bt, 1)
        self.beta = Toggle(self.updater.beta, beta)
        self.beta.toggled.connect(self._set_beta)
        bl.addWidget(self.beta, 0, Qt.AlignVCenter)
        col.addWidget(beta)

        # ---- history
        col.addSpacing(10)
        col.addWidget(label('RELEASE HISTORY', 'section', body))
        self.history = QVBoxLayout()
        self.history.setSpacing(10)
        col.addLayout(self.history)
        self.empty = EmptyState('update', 'No releases loaded yet', 'Use “Check now” to load them from GitHub.', body)
        col.addWidget(self.empty)
        col.addStretch(1)

        bridge.app_update_changed.connect(self.refresh)
        bridge.app_update_progress.connect(self._progress)
        theme.notifier.changed.connect(self.refresh)
        self.refresh()

    # ------------------------------------------------------------ state
    def refresh(self) -> None:
        u = self.updater
        update = u.available()
        kind = install_kind()
        t = theme.current()
        current = format_version(CURRENT)
        checked = f"Last checked {_ago(u.last_check())}"

        if u.restart_command:
            icon, tone = 'success', t['success']
            title, text = 'Update installed', 'Restart Manga DL to use the new version. Downloads continue after the restart.'
        elif u.installing:
            icon, tone = 'download', t['accent']
            title, text = f"Installing {update.label if update else 'update'}…", 'Downloading from GitHub.'
        elif u.checking:
            icon, tone = 'refresh', t['text_muted']
            title, text = 'Checking for updates…', f"You have version {current}."
        elif u.install_error:
            icon, tone = 'alert', t['danger']
            title, text = "The update couldn't be installed", u.install_error
        elif u.error:
            icon, tone = 'alert', t['danger']
            title, text = "Couldn't check for updates", f"{u.error}. You have version {current}."
        elif update:
            icon, tone = 'sparkle', t['accent']
            title = f"Version {update.label} is available" + (' (beta)' if update.prerelease else '')
            text = f"You have version {current}. {checked}."
            if kind == 'git':
                text += ' This copy runs from a git checkout - update it with “git pull”.'
        elif u.releases:
            icon, tone = 'success', t['success']
            title, text = "You're up to date", f"Version {current} is the newest. {checked}."
        else:
            icon, tone = 'update', t['text_muted']
            title, text = f"Version {current}", f"{checked}."
        self.status_icon.setPixmap(icons.pixmap(icon, tone, 32, 1.7))
        self.status_title.setText(title)
        self.status_text.setText(text)

        busy = u.checking or u.installing
        self.check_btn.setEnabled(not busy)
        self.check_btn.setVisible(not u.restart_command)
        can_install = bool(update) and kind != 'git' and not u.restart_command
        self.install_btn.setVisible(can_install)
        self.install_btn.setEnabled(not busy)
        if update:
            self.install_btn.setText(f"Install {update.label}")
        self.github_btn.setVisible(bool(update) and kind == 'git')
        self.restart_btn.setVisible(bool(u.restart_command))
        if not u.installing:
            self.bar.hide()

        self._fill_history()
        self.available_changed.emit(bool(update) and not u.restart_command)

    def _fill_history(self) -> None:
        for card in self._cards:
            card.hide()
            card.deleteLater()
        self._cards.clear()
        u = self.updater
        releases = u.visible_releases()
        allow = install_kind() != 'git' and not u.installing and not u.restart_command
        for release in releases:
            card = ReleaseCard(release, allow and u.can_install(release), self)
            card.install.connect(self._install)
            self.history.addWidget(card)
            self._cards.append(card)
        self.empty.setVisible(not releases and not u.checking)

    # ---------------------------------------------------------- actions
    def _install(self, release: Optional[Release]) -> None:
        if release and self.updater.install(release):
            self.bar.setRange(0, 0)
            self.bar.show()

    def _progress(self, done: int, total: int) -> None:
        if total:
            self.bar.setRange(0, total)
            self.bar.setValue(done)

    def _set_beta(self, on: bool) -> None:
        self.core.settings.set('app_updates.beta', on)
        self.refresh()

    def _open_github(self) -> None:
        update = self.updater.available()
        QDesktopServices.openUrl(QUrl(update.page_url if update else RELEASES_PAGE))

    def showEvent(self, event):   # noqa: N802
        u = self.updater
        if not u.releases and not u.checking and not u.error:
            u.check(manual=False)        # fill the history the first time the page is opened
        else:
            self.refresh()               # "last checked" text
        super().showEvent(event)
