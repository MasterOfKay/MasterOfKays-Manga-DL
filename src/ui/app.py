"""
Application entry point.
"""

import subprocess
import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication

from ..core import create_core
from . import theme
from .bridge import Bridge
from .main_window import MainWindow, app_icon


def _windows_taskbar_identity() -> None:
    """Without this Windows groups the window under python.exe and shows its icon."""
    if sys.platform == 'win32':
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('MasterOfKay.MangaDL')
        except Exception:
            pass


def main() -> int:
    _windows_taskbar_identity()
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setApplicationName('Manga DL')
    app.setOrganizationName('MasterOfKay')
    app.setStyle('Fusion')
    app.setFont(theme.default_font())
    app.setWindowIcon(app_icon())


    core = create_core()
    settings = core.settings
    theme.apply(app, settings.get('appearance.theme'), settings.get('appearance.accent'))

    def follow_system_theme(*_args):
        if settings.get('appearance.theme') == 'system':
            theme.apply(app, 'system', settings.get('appearance.accent'))

    QGuiApplication.styleHints().colorSchemeChanged.connect(follow_system_theme)

    bridge = Bridge(core.bus)
    window = MainWindow(core, bridge)
    window.show()
    core.start()

    code = app.exec()
    core.shutdown()
    command = core.app_updates.restart_command
    if window.restart_after_close and command:
        subprocess.Popen(command, close_fds=True)     # the freshly installed version
    return code
