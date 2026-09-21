"""Zoom and pan for pictures: Ctrl + mouse wheel zooms around the cursor, dragging pans, double click returns to "fit"."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, QSizeF, Qt, Signal
from PySide6.QtGui import QMouseEvent, QPainter, QPixmap, QWheelEvent
from PySide6.QtWidgets import QLabel

MIN_ZOOM, MAX_ZOOM = 0.25, 16.0
STEP = 1.15                          # per wheel notch


def clamp_zoom(zoom: float) -> float:
    return max(MIN_ZOOM, min(MAX_ZOOM, zoom))


def zoom_pan(zoom: float, new_zoom: float, pan: QPointF, anchor: QPointF, area: QSizeF, fitted: QSizeF) -> QPointF:
    """The pan that keeps the picture point under `anchor` (widget coordinates) fixed while the zoom changes.
    `fitted` is the picture size at zoom 1 (fit to the area)."""
    centre = QPointF(area.width() / 2, area.height() / 2)
    old_size = QSizeF(fitted.width() * zoom, fitted.height() * zoom)
    new_size = QSizeF(fitted.width() * new_zoom, fitted.height() * new_zoom)
    old_centre = centre + pan
    u = QPointF((anchor.x() - (old_centre.x() - old_size.width() / 2)) / max(old_size.width(), 1e-6),
                (anchor.y() - (old_centre.y() - old_size.height() / 2)) / max(old_size.height(), 1e-6))
    new_centre = QPointF(anchor.x() - u.x() * new_size.width() + new_size.width() / 2,
                         anchor.y() - u.y() * new_size.height() + new_size.height() / 2)
    return clamp_pan(new_centre - centre, new_size, area)


def clamp_pan(pan: QPointF, size: QSizeF, area: QSizeF) -> QPointF:
    """A picture smaller than the area stays centred; a bigger one may not leave a gap at its edges."""
    def one(value: float, picture: float, space: float) -> float:
        if picture <= space:
            return 0.0
        limit = (picture - space) / 2
        return max(-limit, min(limit, value))
    return QPointF(one(pan.x(), size.width(), area.width()), one(pan.y(), size.height(), area.height()))


class ZoomLabel(QLabel):
    """A QLabel that can also show a zoomable, pannable picture (`set_source`); text and movies work as in any QLabel."""
    zoom_changed = Signal(float)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._src: QPixmap | None = None
        self.zoom = 1.0
        self._pan = QPointF()
        self._press: QPointF | None = None
        self._dragging = False

    # --- picture ---------------------------------------------------------------------------------------------

    def set_source(self, pixmap: QPixmap | None) -> None:
        self._src = pixmap
        self.zoom, self._pan = 1.0, QPointF()
        self.update()

    def has_source(self) -> bool:
        return self._src is not None

    def _fitted(self) -> QSizeF:
        if self._src is None or self._src.isNull():
            return QSizeF(0, 0)
        w, h = self._src.width() / self._src.devicePixelRatio(), self._src.height() / self._src.devicePixelRatio()
        scale = min(self.width() / w, self.height() / h)
        return QSizeF(w * scale, h * scale)

    def _rect(self) -> QRectF:
        fitted = self._fitted()
        size = QSizeF(fitted.width() * self.zoom, fitted.height() * self.zoom)
        centre = QPointF(self.width() / 2, self.height() / 2) + self._pan
        return QRectF(centre.x() - size.width() / 2, centre.y() - size.height() / 2, size.width(), size.height())

    def set_zoom(self, zoom: float, anchor: QPointF | None = None) -> None:
        zoom = clamp_zoom(zoom)
        if self._src is None or zoom == self.zoom:
            return
        area = QSizeF(self.width(), self.height())
        anchor = anchor if anchor is not None else QPointF(area.width() / 2, area.height() / 2)
        self._pan = zoom_pan(self.zoom, zoom, self._pan, anchor, area, self._fitted())
        self.zoom = zoom
        self.update()
        self.zoom_changed.emit(zoom)

    def reset_zoom(self) -> None:
        self._pan = QPointF()
        if self.zoom != 1.0:
            self.zoom = 1.0
            self.zoom_changed.emit(1.0)
        self.update()

    # --- events ----------------------------------------------------------------------------------------------

    def paintEvent(self, event) -> None:                      # noqa: N802
        if self._src is None:
            super().paintEvent(event)
            return
        p = QPainter(self)
        p.setRenderHints(QPainter.RenderHint.SmoothPixmapTransform | QPainter.RenderHint.Antialiasing)
        p.drawPixmap(self._rect(), self._src, QRectF(self._src.rect()))

    def resizeEvent(self, event) -> None:                     # noqa: N802
        super().resizeEvent(event)
        area = QSizeF(self.width(), self.height())
        fitted = self._fitted()
        self._pan = clamp_pan(self._pan, QSizeF(fitted.width() * self.zoom, fitted.height() * self.zoom), area)

    def wheelEvent(self, event: QWheelEvent) -> None:         # noqa: N802
        if self._src is not None and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            delta = event.angleDelta().y()
            if delta:
                self.set_zoom(self.zoom * STEP ** (delta / 120), event.position())
            event.accept()
        else:
            event.ignore()                                    # a plain wheel flips to the next picture (the window decides)

    def mousePressEvent(self, event: QMouseEvent) -> None:    # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self._src is not None and self.zoom > 1.0:
            self._press, self._dragging = event.position(), True
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:     # noqa: N802
        if self._dragging and self._press is not None:
            delta = event.position() - self._press
            self._press = event.position()
            fitted = self._fitted()
            self._pan = clamp_pan(self._pan + delta, QSizeF(fitted.width() * self.zoom, fitted.height() * self.zoom),
                                  QSizeF(self.width(), self.height()))
            self.update()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._dragging:
            self._dragging, self._press = False, None
            self.unsetCursor()
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:   # noqa: N802
        if self._src is not None:
            self.reset_zoom()
        super().mouseDoubleClickEvent(event)
