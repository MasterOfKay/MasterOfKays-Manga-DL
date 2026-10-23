"""
Stacked in-window toast notifications (bottom-right).

Toasts are plain child widgets of the main window - they never create their
own OS window, so nothing flashes on screen or steals focus.
"""

from typing import List

from PySide6.QtCore import QEasingCurve, QEvent, QObject, QPropertyAnimation, QTimer, Qt
from PySide6.QtWidgets import QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from . import icons, theme
from .widgets import IconButton

_LEVEL_ICON = {'info': 'info', 'success': 'success', 'warning': 'alert', 'error': 'alert', 'accent': 'sparkle'}
_LEVEL_TONE = {'info': 'info', 'success': 'success', 'warning': 'warning', 'error': 'danger', 'accent': 'accent'}
MAX_VISIBLE = 4
WIDTH = 340


class Toast(QFrame):
    def __init__(self, host: 'ToastHost', title: str, message: str, level: str, duration: int):
        super().__init__(host.parentWidget())
        self.setObjectName('Toast')
        self.setFixedWidth(WIDTH)
        self._host = host
        self._closing = False

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 12, 8, 12)
        layout.setSpacing(12)

        icon = QLabel(self)
        icon.setFixedSize(20, 20)
        icon.setPixmap(icons.pixmap(_LEVEL_ICON.get(level, 'info'),
                                    theme.current()[_LEVEL_TONE.get(level, 'info')], 20, 1.9))
        layout.addWidget(icon, 0, Qt.AlignTop)

        text = QVBoxLayout()
        text.setSpacing(2)
        title_lbl = QLabel(title, self)
        title_lbl.setObjectName('ToastTitle')
        title_lbl.setWordWrap(True)
        text.addWidget(title_lbl)
        if message:
            body = QLabel(message, self)
            body.setObjectName('ToastBody')
            body.setWordWrap(True)
            text.addWidget(body)
        layout.addLayout(text, 1)

        close = IconButton('x', 'Dismiss', self, size=24, icon_size=14)
        close.clicked.connect(self.dismiss)
        layout.addWidget(close, 0, Qt.AlignTop)

        self._effect = QGraphicsOpacityEffect(self)
        self._effect.setOpacity(0.0)
        self.setGraphicsEffect(self._effect)
        self._fade = QPropertyAnimation(self._effect, b"opacity", self)
        self._fade.setDuration(180)
        self._fade.setEasingCurve(QEasingCurve.OutCubic)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.dismiss)
        self._timer.start(duration)

    def appear(self) -> None:
        self.adjustSize()
        self.show()
        self.raise_()
        self._fade.setStartValue(0.0)
        self._fade.setEndValue(1.0)
        self._fade.start()

    def enterEvent(self, event):
        self._timer.stop()           # keep it while the mouse is over it
        super().enterEvent(event)

    def leaveEvent(self, event):
        if not self._closing:
            self._timer.start(2500)
        super().leaveEvent(event)

    def dismiss(self) -> None:
        if self._closing:
            return
        self._closing = True
        self._fade.stop()
        self._fade.setStartValue(self._effect.opacity())
        self._fade.setEndValue(0.0)
        self._fade.finished.connect(self._remove)
        self._fade.start()

    def _remove(self) -> None:
        self._host.remove(self)
        self.deleteLater()


class ToastHost(QObject):
    """Keeps toasts positioned in the bottom-right corner of `parent`."""

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self._parent = parent
        self._toasts: List[Toast] = []
        parent.installEventFilter(self)

    def parentWidget(self) -> QWidget:   # noqa: N802 - mirrors Qt naming
        return self._parent

    def show(self, title: str, message: str = '', level: str = 'info') -> None:
        duration = 8000 if level == 'error' else 5000
        toast = Toast(self, title, message, level, duration)
        self._toasts.append(toast)
        while len(self._toasts) > MAX_VISIBLE:
            self._toasts[0].dismiss()
            self._toasts.pop(0)
        toast.appear()
        self._layout()

    def remove(self, toast: Toast) -> None:
        if toast in self._toasts:
            self._toasts.remove(toast)
        self._layout()

    def eventFilter(self, obj, event):
        if obj is self._parent and event.type() == QEvent.Resize:
            self._layout()
        return False

    def _layout(self) -> None:
        margin, gap = 20, 10
        y = self._parent.height() - margin
        for toast in reversed(self._toasts):
            toast.adjustSize()
            y -= toast.height()
            toast.move(self._parent.width() - toast.width() - margin, y)
            toast.raise_()
            y -= gap
