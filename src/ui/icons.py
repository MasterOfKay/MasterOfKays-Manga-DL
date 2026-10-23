"""
Small built-in line icon set (24x24, stroke based) rendered from SVG and
tinted to any color, so the app ships without an icon font or image files.
"""

from functools import lru_cache

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

_PATHS = {
    'download': '<path d="M12 4v11"/><path d="M7 10.5l5 5 5-5"/><path d="M5 20h14"/>',
    'library': '<rect x="4" y="4" width="4.5" height="16" rx="1.2"/><rect x="10.5" y="4" width="4.5" height="16" rx="1.2"/>'
               '<path d="M17.3 5.4l3.2 14"/>',
    'settings': '<path d="M4 7h9"/><path d="M17 7h3"/><circle cx="15" cy="7" r="2"/><path d="M4 17h3"/><path d="M11 17h9"/>'
                '<circle cx="9" cy="17" r="2"/>',
    'refresh': '<path d="M20 12a8 8 0 1 1-2.6-5.9"/><path d="M20 4.5V9h-4.5"/>',
    'pause': '<path d="M9 6v12"/><path d="M15 6v12"/>',
    'play': '<path d="M8 5.5v13l10.5-6.5z" fill="{c}"/>',
    'x': '<path d="M6.5 6.5l11 11"/><path d="M17.5 6.5l-11 11"/>',
    'folder': '<path d="M3.5 7.5a2 2 0 0 1 2-2h3.8l2 2.2h7.2a2 2 0 0 1 2 2v7.8a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2z"/>',
    'trash': '<path d="M4.5 7h15"/><path d="M9.5 7V4.8h5V7"/><path d="M6.5 7l.9 12.2h9.2L17.5 7"/>',
    'check': '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
    'plus': '<path d="M12 5v14"/><path d="M5 12h14"/>',
    'search': '<circle cx="11" cy="11" r="6.5"/><path d="M20 20l-4.3-4.3"/>',
    'more': '<circle cx="5.5" cy="12" r="1.4" fill="{c}"/><circle cx="12" cy="12" r="1.4" fill="{c}"/>'
            '<circle cx="18.5" cy="12" r="1.4" fill="{c}"/>',
    'link': '<path d="M10 14a4.2 4.2 0 0 0 6 0l3-3a4.2 4.2 0 0 0-6-6l-1 1"/><path d="M14 10a4.2 4.2 0 0 0-6 0l-3 3a4.2 4.2 0 0 0 6 6l1-1"/>',
    'list': '<path d="M9 6.5h11"/><path d="M9 12h11"/><path d="M9 17.5h11"/><circle cx="4.8" cy="6.5" r="1" fill="{c}"/>'
            '<circle cx="4.8" cy="12" r="1" fill="{c}"/><circle cx="4.8" cy="17.5" r="1" fill="{c}"/>',
    'external': '<path d="M14 4.5h5.5V10"/><path d="M19.5 4.5L11 13"/><path d="M18 14v4.5a1 1 0 0 1-1 1H5.5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1H10"/>',
    'chevron-right': '<path d="M9.5 6l6 6-6 6"/>',
    'chevron-down': '<path d="M6 9.5l6 6 6-6"/>',
    'chevron-left': '<path d="M14.5 6l-6 6 6 6"/>',
    'compass': '<circle cx="12" cy="12" r="8.5"/><path d="M15.6 8.4l-2.2 5-5 2.2 2.2-5z"/>',
    'sort': '<path d="M8 5v14"/><path d="M4.5 15.5L8 19l3.5-3.5"/><path d="M16 19V5"/><path d="M12.5 8.5L16 5l3.5 3.5"/>',
    'bell': '<path d="M6.5 16.5v-5a5.5 5.5 0 0 1 11 0v5l1.5 2h-14z"/><path d="M10 21h4"/>',
    'alert': '<circle cx="12" cy="12" r="8.5"/><path d="M12 7.8v5"/><path d="M12 16.2v.1"/>',
    'info': '<circle cx="12" cy="12" r="8.5"/><path d="M12 11v5"/><path d="M12 7.8v.1"/>',
    'success': '<circle cx="12" cy="12" r="8.5"/><path d="M8.3 12.3l2.6 2.6 4.9-5.2"/>',
    'sparkle': '<path d="M12 3.5l1.9 5.3 5.3 1.9-5.3 1.9L12 17.9l-1.9-5.3-5.3-1.9 5.3-1.9z"/><path d="M18.5 16.5l.7 1.8 1.8.7-1.8.7-.7 1.8-.7-1.8-1.8-.7 1.8-.7z"/>',
    'update': '<circle cx="12" cy="12" r="8.5"/><path d="M12 16.5v-9"/><path d="M8.3 11L12 7.3l3.7 3.7"/>',
    'retry': '<path d="M4 12a8 8 0 0 1 13.7-5.6L20 8.5"/><path d="M20 4v4.5h-4.5"/><path d="M20 12a8 8 0 0 1-13.7 5.6L4 15.5"/><path d="M4 20v-4.5h4.5"/>',
    'stack': '<path d="M12 4l8 4-8 4-8-4z"/><path d="M4 12l8 4 8-4"/><path d="M4 16l8 4 8-4"/>',
    'clock': '<circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3 2"/>',
}

_TEMPLATE = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{c}" '
             'stroke-width="{w}" stroke-linecap="round" stroke-linejoin="round">{body}</svg>')


@lru_cache(maxsize=512)
def pixmap(name: str, color: str, size: int = 18, stroke: float = 1.8, dpr: float = 2.0) -> QPixmap:
    body = _PATHS.get(name, _PATHS['info']).replace('{c}', color)
    svg = _TEMPLATE.format(c=color, w=stroke, body=body)
    renderer = QSvgRenderer(QByteArray(svg.encode('utf-8')))
    px = QPixmap(int(size * dpr), int(size * dpr))
    px.fill(Qt.transparent)
    painter = QPainter(px)
    painter.setRenderHint(QPainter.Antialiasing)
    renderer.render(painter, QRectF(0, 0, size * dpr, size * dpr))
    painter.end()
    px.setDevicePixelRatio(dpr)
    return px


def icon(name: str, color: str, size: int = 18, stroke: float = 1.8) -> QIcon:
    return QIcon(pixmap(name, color, size, stroke))
