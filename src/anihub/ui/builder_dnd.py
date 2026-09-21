"""Dragging in the prompt builder, the way files are moved in Explorer: tag tiles and LoRA tiles are dragged onto categories of the tree,
and categories are dragged onto other categories (or onto a slot to become a top-level category of it)."""
from __future__ import annotations

import json

from PySide6.QtCore import QMimeData, QPoint, Qt, Signal
from PySide6.QtGui import QDrag
from PySide6.QtWidgets import QAbstractItemView, QApplication, QListWidget, QTreeWidget

TAG_MIME = "application/x-anihub-tags"          # JSON list of tag ids
NODE_MIME = "application/x-anihub-node"         # JSON id of a category
LORA_MIME = "application/x-anihub-loras"        # JSON list of LoRA file paths
ROLE = Qt.ItemDataRole.UserRole


def make_mime(kind: str, payload) -> QMimeData:
    mime = QMimeData()
    mime.setData(kind, json.dumps(payload).encode("utf-8"))
    return mime


def read_mime(mime: QMimeData, kind: str):
    return json.loads(bytes(mime.data(kind)).decode("utf-8")) if mime.hasFormat(kind) else None


def drop_allowed(kind: str, target) -> bool:
    """Which tree rows take what: a tag goes into a category; a category into another category or a slot; a LoRA into one of the LoRA groups."""
    if not target:
        return False
    if kind == TAG_MIME:
        return target[0] == "node"
    if kind == NODE_MIME:
        return target[0] in ("node", "slot")
    if kind == LORA_MIME:
        return target[0] == "lora" and target[1] is not None
    return False


class CatalogTree(QTreeWidget):
    """The category tree: categories can be dragged out of it, tags / LoRAs / categories dropped onto it."""
    tags_dropped = Signal(list, object)             # tag ids, the row they were dropped on
    node_dropped = Signal(int, object)
    loras_dropped = Signal(list, object)

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setDropIndicatorShown(True)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self._hover = None

    def mimeTypes(self) -> list[str]:  # noqa: N802
        return [TAG_MIME, NODE_MIME, LORA_MIME]

    def startDrag(self, supported) -> None:  # noqa: N802
        item = self.currentItem()
        data = item.data(0, ROLE) if item is not None else None
        if not data or data[0] != "node":                     # only real categories are moved
            return
        drag = QDrag(self)
        drag.setMimeData(make_mime(NODE_MIME, data[1]))
        drag.exec(Qt.DropAction.MoveAction)

    def _kind(self, event) -> str | None:
        mime = event.mimeData()
        return next((k for k in (TAG_MIME, NODE_MIME, LORA_MIME) if mime.hasFormat(k)), None)

    def _target(self, pos: QPoint):
        item = self.itemAt(pos)
        return (item, item.data(0, ROLE)) if item is not None else (None, None)

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if self._kind(event):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        kind = self._kind(event)
        item, data = self._target(event.position().toPoint())
        ok = bool(kind) and drop_allowed(kind, data)
        if ok and kind == NODE_MIME and data[0] == "node" and data[1] == read_mime(event.mimeData(), NODE_MIME):
            ok = False                                       # not onto itself
        if ok:
            self.viewport().update()
            event.acceptProposedAction()
            self._hover = item
        else:
            self._hover = None
            event.ignore()

    def dropEvent(self, event) -> None:  # noqa: N802
        kind = self._kind(event)
        item, data = self._target(event.position().toPoint())
        self._hover = None
        if not kind or not drop_allowed(kind, data):
            event.ignore()
            return
        payload = read_mime(event.mimeData(), kind)
        {TAG_MIME: self.tags_dropped, NODE_MIME: self.node_dropped, LORA_MIME: self.loras_dropped}[kind].emit(payload, data)
        event.acceptProposedAction()

    def drawRow(self, painter, option, index) -> None:  # noqa: N802
        super().drawRow(painter, option, index)
        hover = self._hover
        if hover is not None and self.indexFromItem(hover) == index:
            from PySide6.QtGui import QColor, QPen

            from anihub.ui import theme
            painter.save()
            painter.setPen(QPen(theme.css_color(theme.current().accent), 2))
            painter.setBrush(QColor(theme.css_color(theme.current().accent).red(), theme.css_color(theme.current().accent).green(),
                                    theme.css_color(theme.current().accent).blue(), 40))
            painter.drawRoundedRect(option.rect.adjusted(2, 1, -2, -1), 6, 6)
            painter.restore()

    def dragLeaveEvent(self, event) -> None:  # noqa: N802
        self._hover = None
        self.viewport().update()
        super().dragLeaveEvent(event)


class DragGrid(QListWidget):
    """A grid of tiles that can be dragged: each tile's `ROLE + 1` data is `(mime type, payload)`. (The selection stays off: a tile click
    is a toggle, so the view's own drag, which needs a selection, is replaced by this one.)"""

    def __init__(self):
        super().__init__()
        self._press_item = None
        self._press_pos = QPoint()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_item = self.itemAt(event.position().toPoint())
            self._press_pos = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        item = self._press_item
        if (item is not None and event.buttons() & Qt.MouseButton.LeftButton
                and (event.position().toPoint() - self._press_pos).manhattanLength() >= QApplication.startDragDistance()):
            spec = item.data(ROLE + 1)
            self._press_item = None
            if spec:
                drag = QDrag(self)
                drag.setMimeData(make_mime(spec[0], spec[1]))
                icon = item.icon()
                if not icon.isNull():
                    drag.setPixmap(icon.pixmap(56, 56))
                    drag.setHotSpot(QPoint(28, 28))
                drag.exec(Qt.DropAction.MoveAction)
                return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self._press_item = None
        super().mouseReleaseEvent(event)
