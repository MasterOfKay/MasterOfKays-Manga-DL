"""
Asynchronous, cached cover loading.
"""

import os
from typing import Callable, Dict, List, Tuple

from PySide6.QtCore import QObject, QRunnable, QSize, Qt, QThreadPool, Signal
from PySide6.QtGui import QImage, QImageReader, QPainter, QPixmap

_Key = Tuple[str, int, int]


class _Loaded(QObject):
    ready = Signal(object, object)   # key, QImage


class _Load(QRunnable):
    def __init__(self, key: _Key, signal: _Loaded):
        super().__init__()
        self.key, self.signal = key, signal

    def run(self) -> None:
        path, w, h = self.key
        image = QImage()
        if path and os.path.exists(path):
            reader = QImageReader(path)
            reader.setAutoTransform(True)
            image = reader.read()
            if not image.isNull() and image.width() > image.height() * 1.25:
                # Banner/logo instead of a portrait cover: letterbox it rather than crop it away.
                scaled = image.scaled(QSize(w - 8, h), Qt.KeepAspectRatio, Qt.SmoothTransformation)
                canvas = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
                canvas.fill(Qt.transparent)
                painter = QPainter(canvas)
                painter.drawImage((w - scaled.width()) // 2, (h - scaled.height()) // 2, scaled)
                painter.end()
                image = canvas
            elif not image.isNull():
                # cover-crop to the target aspect ratio
                image = image.scaled(QSize(w, h), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
                x, y = (image.width() - w) // 2, (image.height() - h) // 2
                image = image.copy(max(0, x), max(0, y), w, h)
        self.signal.ready.emit(self.key, image)


class CoverCache:
    def __init__(self):
        self._pixmaps: Dict[_Key, QPixmap] = {}
        self._waiting: Dict[_Key, List[Callable[[QPixmap], None]]] = {}
        self._signal = _Loaded()
        self._signal.ready.connect(self._on_ready)
        self._pool = QThreadPool()
        self._pool.setMaxThreadCount(2)

    def request(self, path: str, width: int, height: int, dpr: float, callback: Callable[[QPixmap], None]) -> None:
        key = (path or '', int(width * dpr), int(height * dpr))
        if key in self._pixmaps:
            callback(self._pixmaps[key])
            return
        if key in self._waiting:
            self._waiting[key].append(callback)
            return
        self._waiting[key] = [callback]
        self._pool.start(_Load(key, self._signal))

    def invalidate(self, path: str) -> None:
        for key in [k for k in self._pixmaps if k[0] == path]:
            del self._pixmaps[key]

    def _on_ready(self, key: _Key, image: QImage) -> None:
        pixmap = QPixmap.fromImage(image) if not image.isNull() else QPixmap()
        self._pixmaps[key] = pixmap
        for callback in self._waiting.pop(key, []):
            try:
                callback(pixmap)
            except RuntimeError:
                pass   # widget deleted while loading


covers = None


def cover_cache() -> CoverCache:
    global covers
    if covers is None:
        covers = CoverCache()
    return covers
