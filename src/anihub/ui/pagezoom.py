"""Ctrl+wheel "zoom" for a page: makes its buttons and thumbnails bigger or smaller together, so a page with a lot
of visual real estate (Generate, LoRA training) can be made denser on a small screen or roomier on a big one.

Every icon-bound button (anything built through style.bind_icon -- primary/secondary/ghost/danger all go through
it) is picked up automatically by walking the page's widget tree once at construction time, so pages do not need to
register their buttons one by one. Thumbnails are a separate concern per page (a ThumbGrid, a list of image rows,
...), so a page passes its own `on_zoom(factor)` callback to resize whatever it has."""
from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import QAbstractButton, QWidget

from anihub.ui import style

MIN_FACTOR = 0.6
MAX_FACTOR = 2.0
STEP = 0.1


class PageZoom(QObject):
    def __init__(self, page: QWidget, on_zoom: Callable[[float], None] | None = None):
        super().__init__(page)
        self.factor = 1.0
        self.on_zoom = on_zoom
        self._buttons: list[tuple[QAbstractButton, tuple]] = [
            (b, b._icon_spec) for b in page.findChildren(QAbstractButton) if getattr(b, "_icon_spec", None)]
        page.installEventFilter(self)
        for child in page.findChildren(QWidget):
            child.installEventFilter(self)

    def eventFilter(self, obj, event) -> bool:  # noqa: N802 - Qt's own naming
        if event.type() == QEvent.Type.Wheel and bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier):
            self.zoom(1 if event.angleDelta().y() > 0 else -1)
            return True
        return False

    def zoom(self, steps: int) -> None:
        self.factor = round(min(MAX_FACTOR, max(MIN_FACTOR, self.factor + steps * STEP)), 2)
        for button, (name, mode, base_size) in self._buttons:
            style.bind_icon(button, name, mode, max(10, round(base_size * self.factor)))
        if self.on_zoom:
            self.on_zoom(self.factor)
