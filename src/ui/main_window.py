"""
Main window: sidebar navigation, pages, and the chapter side panel.
"""

import base64
import os

from PySide6.QtCore import QByteArray, QSize, Qt, QTimer
from PySide6.QtGui import QAction, QIcon, QPixmap
from PySide6.QtWidgets import (QApplication, QButtonGroup, QHBoxLayout, QLabel, QMainWindow, QMenu, QProgressDialog,
                               QPushButton, QSplitter, QStackedWidget, QSystemTrayIcon, QVBoxLayout, QWidget)

from .. import __version__
from ..core import AppCore
from ..core.paths import resource_path
from . import icons, theme
from .bridge import Bridge
from .chapter_panel import ChapterPanel
from .pages.browse import BrowsePage
from .pages.downloads import DownloadsPage
from .pages.library import LibraryPage
from .pages.settings import SettingsPage
from .pages.updates import UpdatesPage
from .tasks import run_async
from .toasts import ToastHost
from .widgets import label

TRAY_ICONS = {'error': QSystemTrayIcon.Critical, 'warning': QSystemTrayIcon.Warning}


def app_icon() -> QIcon:
    for name in ('Logo.ico', 'Logo.png'):
        path = resource_path(name)
        if os.path.exists(path):
            return QIcon(path)
    return QIcon()


class NavButton(QPushButton):
    def __init__(self, icon_name: str, text: str, parent=None):
        super().__init__(text, parent)
        self.setObjectName('NavButton')
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setIconSize(QSize(18, 18))
        self._icon_name = icon_name
        self.badge = QLabel(self)
        self.badge.setObjectName('NavBadge')
        self.badge.setAlignment(Qt.AlignCenter)
        self.badge.hide()
        self.toggled.connect(lambda _c: self._refresh_icon())
        theme.notifier.changed.connect(self._refresh_icon)
        self._refresh_icon()

    def set_badge(self, count: int) -> None:
        self.badge.setText(str(count) if count < 100 else '99+')
        self.badge.adjustSize()
        self.badge.setFixedHeight(18)
        self.badge.setMinimumWidth(18)
        self.badge.setVisible(count > 0)
        self._place_badge()

    def resizeEvent(self, event):   # noqa: N802
        self._place_badge()
        super().resizeEvent(event)

    def _place_badge(self) -> None:
        self.badge.move(self.width() - self.badge.width() - 10, (self.height() - self.badge.height()) // 2)

    def _refresh_icon(self) -> None:
        t = theme.current()
        self.setIcon(icons.icon(self._icon_name, t['accent_text'] if self.isChecked() else t['text_muted'], 18, 1.9))


class Sidebar(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('Sidebar')
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFixedWidth(216)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 18, 14, 16)
        layout.setSpacing(4)

        brand = QHBoxLayout()
        brand.setSpacing(10)
        logo = QLabel(self)
        logo_path = resource_path('Logo.png')
        if os.path.exists(logo_path):
            logo.setPixmap(QPixmap(logo_path).scaled(30, 30, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        brand.addWidget(logo)
        names = QVBoxLayout()
        names.setSpacing(0)
        title = QLabel('Manga DL', self)
        title.setObjectName('Brand')
        sub = QLabel('Downloader & library', self)
        sub.setObjectName('BrandSub')
        names.addWidget(title)
        names.addWidget(sub)
        brand.addLayout(names, 1)
        layout.addLayout(brand)
        layout.addSpacing(22)

        self.group = QButtonGroup(self)
        self.downloads = NavButton('download', '  Downloads', self)
        self.browse = NavButton('compass', '  Browse', self)
        self.library = NavButton('library', '  Library', self)
        self.settings = NavButton('settings', '  Settings', self)
        self.updates = NavButton('update', '  Updates', self)
        for i, btn in enumerate((self.downloads, self.browse, self.library, self.settings, self.updates)):
            self.group.addButton(btn, i)
            layout.addWidget(btn)
        self.downloads.setChecked(True)
        layout.addStretch(1)
        version = label(f"Version {__version__}", 'faint', self)
        layout.addWidget(version)


class MainWindow(QMainWindow):
    def __init__(self, core: AppCore, bridge: Bridge):
        super().__init__()
        self.core = core
        self.bridge = bridge
        self.setWindowTitle('Manga DL')
        self.setWindowIcon(app_icon())
        self.setMinimumSize(980, 620)

        root = QWidget(self)
        root.setObjectName('Root')
        self.setCentralWidget(root)
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.sidebar = Sidebar(root)
        layout.addWidget(self.sidebar)

        self.splitter = QSplitter(Qt.Horizontal, root)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setHandleWidth(1)
        layout.addWidget(self.splitter, 1)

        self.stack = QStackedWidget(self.splitter)
        self.downloads = DownloadsPage(core, bridge, self.stack)
        self.browse = BrowsePage(core, bridge, self.stack)
        self.library = LibraryPage(core, bridge, self.stack)
        self.settings_page = SettingsPage(core, self.stack)
        self.updates_page = UpdatesPage(core, bridge, self.stack)
        for page in (self.downloads, self.browse, self.library, self.settings_page, self.updates_page):
            self.stack.addWidget(page)
        self.splitter.addWidget(self.stack)

        self.panel = ChapterPanel(core, bridge, self.splitter)
        self.splitter.addWidget(self.panel)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 0)
        self.panel.hide()

        self.toasts = ToastHost(root)
        self.restart_after_close = False
        self._ready_to_close = False
        self._close_dialog = None
        self.tray = None
        self._setup_tray()

        # navigation
        self.sidebar.group.idClicked.connect(self._navigate)

        # page wiring
        for page in (self.downloads, self.library):
            page.open_manga.connect(self.open_manga)
            page.toast.connect(self.toast)
        self.downloads.open_preview.connect(self.open_preview)
        self.browse.open_item.connect(self.open_browse_item)
        self.browse.toast.connect(self.toast)
        self.settings_page.toast.connect(self.toast)
        self.settings_page.appearance_changed.connect(self.apply_theme)
        self.settings_page.notifications_changed.connect(self._setup_tray)
        self.settings_page.test_notification.connect(self._test_notification)
        self.panel.toast.connect(self.toast)
        self.panel.closed.connect(self.panel.hide)
        self.library.new_count_changed.connect(self.sidebar.library.set_badge)
        self.updates_page.available_changed.connect(lambda new: self.sidebar.updates.set_badge(1 if new else 0))
        self.updates_page.restart_requested.connect(self._restart)

        bridge.notify.connect(self.notify)
        bridge.queue_changed.connect(self._update_download_badge)

        self._restore_geometry()

        # Disk sync can take a moment with big libraries - keep it off the UI thread.
        def initial_sync():
            core.library.clean_titles()      # "Title - Asura Scans" -> "Title" (merges duplicates)
            core.library.migrate_links()     # e.g. old asuracomic.net links -> asurascans.com
            core.library.fix_metadata()      # HTML descriptions, wrong Webtoon covers
            core.library.sync_all()
            return True

        run_async(initial_sync, lambda _ok: self.library.reload(), lambda _e: self.library.reload())

    # ------------------------------------------------------------- panel
    def _navigate(self, index: int) -> None:
        self.stack.setCurrentIndex(index)
        if self.stack.currentWidget() in (self.settings_page, self.updates_page) and self.panel.isVisible():
            self.panel.close_panel()

    def open_manga(self, manga_id: int) -> None:
        self.panel.open_manga(manga_id)
        self._show_panel()

    def open_browse_item(self, card) -> None:
        """A manga clicked on the Browse page: open it like a pasted link."""
        item = card.item
        manga_id = self.core.browse.find_in_library(item, self.core.browse.library_index())
        if manga_id:
            self.open_manga(manga_id)
            return
        card.set_busy(True)

        def done(fetched):
            card.set_busy(False)
            self.open_preview(fetched)

        def failed(message):
            card.set_busy(False)
            self.toast(f"Couldn't open {item.title}", message, 'error')

        run_async(lambda: self.core.library.fetch(item.url), done, failed)

    def open_preview(self, fetched) -> None:
        self.panel.open_preview(fetched)
        self._show_panel()

    def _show_panel(self) -> None:
        if not self.panel.isVisible():
            total = self.splitter.width()
            panel_w = max(400, min(520, int(total * 0.42)))
            self.panel.show()
            self.splitter.setSizes([total - panel_w, panel_w])

    # ------------------------------------------------------ notifications
    def toast(self, title: str, message: str = '', level: str = 'info') -> None:
        self.toasts.show(title, message, level)

    def notify(self, event: str, title: str, message: str, level: str) -> None:
        s = self.core.settings
        if event != 'manual' and not s.notification_enabled(event):
            return
        in_focus = self.isActiveWindow() and not self.isMinimized()
        use_desktop = (not in_focus and s.get('notifications.desktop') and self.tray is not None
                       and event != 'manual')
        if use_desktop:
            self.tray.showMessage(title, message, TRAY_ICONS.get(level, QSystemTrayIcon.Information), 6000)
        elif s.get('notifications.in_app') or event in ('manual', 'errors'):
            self.toast(title, message, level)

    def _test_notification(self) -> None:
        s = self.core.settings
        self.toast('This is an in-app notification', 'New chapters, finished downloads and errors look like this.',
                   'accent')
        if s.get('notifications.desktop') and self.tray is not None:
            self.tray.showMessage('Manga DL', 'Desktop notifications are working.', QSystemTrayIcon.Information, 5000)
        elif s.get('notifications.desktop'):
            self.toast('Desktop notifications unavailable', 'Your system has no notification area.', 'warning')

    def _setup_tray(self) -> None:
        want = bool(self.core.settings.get('notifications.desktop')) and QSystemTrayIcon.isSystemTrayAvailable()
        if want and self.tray is None:
            self.tray = QSystemTrayIcon(app_icon(), self)
            self.tray.setToolTip('Manga DL')
            menu = QMenu(self)
            show = QAction('Show Manga DL', menu)
            show.triggered.connect(self._raise)
            quit_action = QAction('Quit', menu)
            quit_action.triggered.connect(self.close)
            menu.addAction(show)
            menu.addSeparator()
            menu.addAction(quit_action)
            self.tray.setContextMenu(menu)
            self.tray.activated.connect(lambda reason: self._raise() if reason == QSystemTrayIcon.Trigger else None)
            self.tray.messageClicked.connect(self._raise)
            self.tray.show()
        elif not want and self.tray is not None:
            self.tray.hide()
            self.tray.deleteLater()
            self.tray = None

    def _restart(self) -> None:
        """Close normally (the queue is saved, the current chapter finishes) and start the new version."""
        self.restart_after_close = True
        self.close()

    def _raise(self) -> None:
        self.showNormal() if self.isMinimized() else self.show()
        self.raise_()
        self.activateWindow()

    # ---------------------------------------------------------- misc
    def apply_theme(self) -> None:
        s = self.core.settings
        theme.apply(QApplication.instance(), s.get('appearance.theme'), s.get('appearance.accent'))

    def _update_download_badge(self) -> None:
        self.sidebar.downloads.set_badge(self.core.downloads.active_count())

    def _restore_geometry(self) -> None:
        saved = self.core.settings.get('ui.geometry', '')
        restored = False
        if saved:
            try:
                restored = self.restoreGeometry(QByteArray(base64.b64decode(saved)))
            except Exception:
                restored = False
        if not restored:
            self.resize(1240, 800)

    def _wait_for_current_chapter(self) -> None:
        if self._close_dialog is not None:
            self._close_dialog.raise_()
            return
        dialog = QProgressDialog(self)
        dialog.setWindowTitle('Closing Manga DL')
        dialog.setRange(0, 0)
        dialog.setCancelButtonText('Quit now')
        dialog.setWindowModality(Qt.WindowModal)
        dialog.setMinimumDuration(0)
        dialog.setAutoClose(False)
        dialog.setAutoReset(False)
        dialog.setMinimumWidth(420)
        self._close_dialog = dialog

        def update():
            current = self.core.downloads.current_chapter()
            if not self.core.downloads.is_busy():
                finish()
                return
            what = f"chapter {current[1]} of {current[0]}" if current else "the current chapter"
            dialog.setLabelText(f"Finishing {what}…\n\nThe rest of the queue is paused and saved - "
                                "it continues the next time you open the app.")

        def finish():
            timer.stop()
            self._ready_to_close = True
            dialog.close()
            self.close()

        timer = QTimer(self)
        timer.setInterval(300)
        timer.timeout.connect(update)
        dialog.canceled.connect(finish)      # "Quit now": the unfinished chapter is re-queued next time
        update()
        timer.start()
        dialog.show()

    def closeEvent(self, event):   # noqa: N802
        downloads = self.core.downloads
        if not self._ready_to_close:
            # Pause the whole queue (it is saved and continues on the next start). If a
            # chapter is mid-download, let it finish first so no work is thrown away.
            downloads.prepare_shutdown()
            if downloads.is_busy():
                event.ignore()
                self._wait_for_current_chapter()
                return
        self.core.settings.set('ui.geometry', base64.b64encode(bytes(self.saveGeometry())).decode('ascii'))
        if self.panel.current_manga_id() is not None:
            self.panel.close_panel()
        if self.tray is not None:
            self.tray.hide()
        event.accept()
