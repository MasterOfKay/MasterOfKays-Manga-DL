"""
Reusable themed widgets.
"""

from typing import Iterable, Optional, Tuple

from PySide6.QtCore import (Property, QEasingCurve, QPropertyAnimation, QRectF, QSize, Qt, Signal)
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import (QAbstractButton, QButtonGroup, QFrame, QHBoxLayout, QLabel, QPushButton,
                               QSizePolicy, QToolButton, QVBoxLayout, QWidget)

from . import icons, theme
from .images import cover_cache


def label(text: str = '', role: Optional[str] = None, parent: Optional[QWidget] = None, wrap: bool = False) -> QLabel:
    lbl = QLabel(parent)
    lbl.setTextFormat(Qt.PlainText)     # titles like "<title>" must not be parsed as HTML
    lbl.setText(text)
    if role:
        lbl.setProperty('role', role)
    lbl.setWordWrap(wrap)
    return lbl


def restyle(widget: QWidget) -> None:
    """Re-evaluate the stylesheet after changing a dynamic property."""
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.update()


def divider(parent: Optional[QWidget] = None) -> QFrame:
    line = QFrame(parent)
    line.setObjectName('Divider')
    line.setFrameShape(QFrame.NoFrame)
    return line


class Card(QFrame):
    clicked = Signal()

    def __init__(self, parent: Optional[QWidget] = None, clickable: bool = False):
        super().__init__(parent)
        self.setProperty('card', True)
        self._clickable = clickable
        if clickable:
            self.setProperty('clickable', True)
            self.setCursor(Qt.PointingHandCursor)

    def mouseReleaseEvent(self, event):
        if self._clickable and event.button() == Qt.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class Button(QPushButton):
    """Push button with a theme-aware icon. variant: None | primary | ghost | danger."""

    def __init__(self, text: str = '', icon_name: Optional[str] = None, variant: Optional[str] = None,
                 parent: Optional[QWidget] = None):
        super().__init__(text, parent)
        self._icon_name = icon_name
        if variant:
            self.setProperty('variant', variant)
        self.setCursor(Qt.PointingHandCursor)
        self.setIconSize(QSize(16, 16))
        theme.notifier.changed.connect(self._refresh_icon)
        self._refresh_icon()

    def set_icon_name(self, name: Optional[str]) -> None:
        self._icon_name = name
        self._refresh_icon()

    def _refresh_icon(self) -> None:
        if not self._icon_name:
            self.setIcon(icons.QIcon())
            return
        t = theme.current()
        variant = self.property('variant')
        color = {'primary': t['on_accent'], 'danger': t['danger'], 'ghost': t['text_muted']}.get(variant, t['text'])
        self.setIcon(icons.icon(self._icon_name, color, 16, 2.0))


class IconButton(QToolButton):
    def __init__(self, icon_name: str, tooltip: str = '', parent: Optional[QWidget] = None,
                 size: int = 32, icon_size: int = 18, tone: str = 'text_muted'):
        super().__init__(parent)
        self._icon_name, self._tone, self._icon_px = icon_name, tone, icon_size
        self.setToolTip(tooltip)
        self.setFixedSize(size, size)
        self.setIconSize(QSize(icon_size, icon_size))
        self.setCursor(Qt.PointingHandCursor)
        theme.notifier.changed.connect(self._refresh_icon)
        self._refresh_icon()

    def set_icon_name(self, name: str, tooltip: Optional[str] = None) -> None:
        self._icon_name = name
        if tooltip is not None:
            self.setToolTip(tooltip)
        self._refresh_icon()

    def set_tone(self, tone: str) -> None:
        self._tone = tone
        self._refresh_icon()

    def _refresh_icon(self) -> None:
        self.setIcon(icons.icon(self._icon_name, theme.current()[self._tone], self._icon_px, 1.9))


class Toggle(QAbstractButton):
    """iOS / Fluent style switch."""

    def __init__(self, checked: bool = False, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(checked)
        self.setCursor(Qt.PointingHandCursor)
        self._offset = 1.0 if checked else 0.0
        self._anim = QPropertyAnimation(self, b"offset", self)
        self._anim.setDuration(140)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self.toggled.connect(self._animate)
        theme.notifier.changed.connect(self.update)

    def sizeHint(self) -> QSize:
        return QSize(40, 22)

    def _get_offset(self) -> float:
        return self._offset

    def _set_offset(self, value: float) -> None:
        self._offset = value
        self.update()

    offset = Property(float, _get_offset, _set_offset)

    def _animate(self, checked: bool) -> None:
        self._anim.stop()
        self._anim.setStartValue(self._offset)
        self._anim.setEndValue(1.0 if checked else 0.0)
        self._anim.start()

    def setChecked(self, checked: bool) -> None:   # noqa: N802 - Qt naming
        blocked = self.signalsBlocked()
        super().setChecked(checked)
        if blocked:   # no toggled signal -> jump without animation
            self._offset = 1.0 if checked else 0.0
            self.update()

    def paintEvent(self, _event) -> None:
        t = theme.current()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(0.5, 0.5, 39, 21)
        off = QColor(t['border_strong'])
        on = QColor(t['accent'])
        mix = QColor(
            round(off.red() + (on.red() - off.red()) * self._offset),
            round(off.green() + (on.green() - off.green()) * self._offset),
            round(off.blue() + (on.blue() - off.blue()) * self._offset),
        )
        if not self.isEnabled():
            mix.setAlpha(110)
        p.setPen(Qt.NoPen)
        p.setBrush(mix)
        p.drawRoundedRect(rect, 10.5, 10.5)
        knob = 16
        x = 3 + (40 - knob - 6) * self._offset
        p.setBrush(QColor('#FFFFFF'))
        p.drawEllipse(QRectF(x, 3, knob, knob))


class Cover(QWidget):
    """Rounded cover image with an initial-letter placeholder."""

    def __init__(self, width: int = 52, height: int = 74, radius: int = 8, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setFixedSize(width, height)
        self._radius = radius
        self._pixmap: Optional[QPixmap] = None
        self._title = ''
        self._path = ''
        theme.notifier.changed.connect(self.update)

    def set_cover(self, path: str, title: str = '') -> None:
        self._title = title
        if path == self._path and self._pixmap is not None:
            return
        self._path = path
        self._pixmap = None
        self.update()
        if path:
            cover_cache().request(path, self.width(), self.height(), self.devicePixelRatioF(),
                                  lambda pixmap, p=path: self._loaded(p, pixmap))

    def _loaded(self, path: str, pixmap: QPixmap) -> None:
        if path != self._path:
            return          # result for a cover that was replaced meanwhile - would overwrite the new one
        self._pixmap = pixmap if not pixmap.isNull() else None
        self.update()

    def paintEvent(self, _event) -> None:
        t = theme.current()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        rect = QRectF(self.rect())
        path = QPainterPath()
        path.addRoundedRect(rect, self._radius, self._radius)
        p.setClipPath(path)
        if self._pixmap:
            p.fillRect(rect, QColor(t['surface_alt']))
            p.drawPixmap(self.rect(), self._pixmap)
        else:
            p.fillRect(rect, QColor(t['accent_soft']))
            p.setPen(QColor(t['accent_text']))
            font = QFont(self.font())
            font.setPixelSize(max(12, int(self.height() * 0.32)))
            font.setBold(True)
            p.setFont(font)
            p.drawText(rect, Qt.AlignCenter, (self._title[:1] or '?').upper())
        p.setClipping(False)
        p.setPen(QColor(t['border']))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), self._radius, self._radius)


class Pill(QLabel):
    def __init__(self, text: str = '', tone: str = 'neutral', parent: Optional[QWidget] = None):
        super().__init__(text, parent)
        self.setProperty('pill', True)
        self.setProperty('tone', tone)
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)

    def set(self, text: str, tone: Optional[str] = None) -> None:
        self.setText(text)
        if tone and tone != self.property('tone'):
            self.setProperty('tone', tone)
            restyle(self)


class ElidedLabel(QLabel):
    """Single-line label that elides with … instead of growing the layout."""
    clicked = Signal()

    def __init__(self, text: str = '', parent: Optional[QWidget] = None, clickable: bool = False):
        super().__init__(text, parent)
        self._clickable = clickable
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.setMinimumWidth(40)
        if clickable:
            self.setCursor(Qt.PointingHandCursor)
            self.setProperty('role', 'link')

    def setText(self, text: str) -> None:   # noqa: N802 - Qt naming
        super().setText(text)
        self.setToolTip(text if self._clickable or len(text) > 40 else '')

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setPen(self.palette().color(self.foregroundRole()))
        p.setFont(self.font())
        rect = self.contentsRect()
        text = QFontMetrics(self.font()).elidedText(self.text(), Qt.ElideRight, rect.width())
        p.drawText(rect, int(self.alignment()) | Qt.AlignVCenter, text)

    def minimumSizeHint(self) -> QSize:
        return QSize(40, super().minimumSizeHint().height())

    def mouseReleaseEvent(self, event):
        if self._clickable and event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class Segmented(QFrame):
    """Row of exclusive pill buttons."""
    changed = Signal(str)

    def __init__(self, options: Iterable[Tuple[str, str]], current: str = '', parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName('Segmented')
        layout = QHBoxLayout(self)
        layout.setContentsMargins(3, 3, 3, 3)
        layout.setSpacing(2)
        self._group = QButtonGroup(self)
        self._buttons = {}
        for key, text in options:
            btn = QPushButton(text, self)
            btn.setProperty('segment', True)
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            self._group.addButton(btn)
            self._buttons[key] = btn
            layout.addWidget(btn)
            btn.clicked.connect(lambda _=False, k=key: self.changed.emit(k))
        if current in self._buttons:
            self._buttons[current].setChecked(True)
        elif self._buttons:
            next(iter(self._buttons.values())).setChecked(True)

    def current(self) -> str:
        return next((k for k, b in self._buttons.items() if b.isChecked()), '')

    def set_current(self, key: str) -> None:
        if key in self._buttons:
            self._buttons[key].setChecked(True)

    def set_label(self, key: str, text: str) -> None:
        if key in self._buttons:
            self._buttons[key].setText(text)

    def set_visible(self, key: str, visible: bool) -> None:
        if key in self._buttons:
            self._buttons[key].setVisible(visible)


class EmptyState(QWidget):
    def __init__(self, icon_name: str, title: str, text: str = '', parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._icon_name = icon_name
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 36, 24, 36)
        layout.setSpacing(6)
        layout.setAlignment(Qt.AlignCenter)
        self._icon = QLabel(self)
        self._icon.setAlignment(Qt.AlignCenter)
        self._title = label(title, 'h3', self)
        self._title.setAlignment(Qt.AlignCenter)
        self._text = label(text, 'muted', self, wrap=True)
        self._text.setAlignment(Qt.AlignCenter)
        self._text.setFixedWidth(380)
        layout.addWidget(self._icon)
        layout.addSpacing(4)
        layout.addWidget(self._title)
        layout.addWidget(self._text, 0, Qt.AlignHCenter)
        theme.notifier.changed.connect(self._refresh)
        self._refresh()

    def set_text(self, title: str, text: str = '') -> None:
        self._title.setText(title)
        self._text.setText(text)

    def _refresh(self) -> None:
        self._icon.setPixmap(icons.pixmap(self._icon_name, theme.current()['text_faint'], 40, 1.5))
