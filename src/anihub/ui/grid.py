"""Thumbnail grid shared by the site browser, the library and the SD results.

Extras over a plain list view: badges/marks on thumbnails, infinite scroll, a large preview popup when the
mouse rests on a thumbnail (ТЗ 3.5), a context-menu signal and a Delete-key signal.
"""
from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QPoint, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor, QFont, QFontMetrics, QGuiApplication, QIcon, QImage, QKeyEvent, QPainter, QPainterPath, QPen, QPixmap)
from PySide6.QtWidgets import (
    QAbstractItemView, QLabel, QListView, QListWidget, QListWidgetItem, QStyle, QStyledItemDelegate)

from anihub.ui import theme
from anihub.ui.workers import run_async

PAYLOAD = Qt.ItemDataRole.UserRole
CAPTION = Qt.ItemDataRole.UserRole + 1
HOVER_DELAY_MS = 450
HOVER_MAX = 560


def _stamp(painter: QPainter, text: str, x: int, y: int, size: int, anchor_right: bool = False,
           anchor_bottom: bool = False, width_limit: int = 0) -> None:
    font = QFont()
    font.setBold(True)
    font.setPixelSize(max(10, size // 14))
    painter.setFont(font)
    metrics = QFontMetrics(font)
    w, h = metrics.horizontalAdvance(text) + 14, metrics.height() + 4
    if anchor_right:
        x = width_limit - w - 6
    if anchor_bottom:
        y = y - h - 2
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(10, 12, 16, 190))
    painter.drawRoundedRect(x, y, w, h, h / 2, h / 2)
    painter.setPen(QColor("white"))
    painter.drawText(x, y, w, h, Qt.AlignmentFlag.AlignCenter, text)


def image_to_thumb(data: bytes, size: int, badge: str = "", mark: str = "") -> QImage | None:
    """Scale to a thumbnail. `badge` ("▶", "GIF", unread count) goes top-left, `mark` ("♥ ★3") bottom-left."""
    img = QImage.fromData(data)
    if img.isNull():
        return None
    img = img.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
    if badge or mark:
        img = img.convertToFormat(QImage.Format.Format_ARGB32)
        painter = QPainter(img)
        if badge:
            _stamp(painter, badge, 6, 6, size)
        if mark:
            _stamp(painter, mark, 6, img.height() - 6, size, anchor_bottom=True)
        painter.end()
    return img


class HoverPreview(QLabel):
    """Frameless popup with a large version of the hovered image; never takes focus or mouse input."""

    def __init__(self):
        super().__init__(None, Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setStyleSheet("background: #101214; color: #e6e6e6; border: 1px solid #555; padding: 4px;")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)

    def show_image(self, image: QImage, caption: str, anchor: QPoint) -> None:
        pm = QPixmap.fromImage(image.scaled(HOVER_MAX, HOVER_MAX, Qt.AspectRatioMode.KeepAspectRatio,
                                            Qt.TransformationMode.SmoothTransformation))
        self.setPixmap(pm)
        self.adjustSize()
        screen = QGuiApplication.screenAt(anchor) or QGuiApplication.primaryScreen()
        area = screen.availableGeometry()
        x = anchor.x() + 12
        if x + self.width() > area.right():
            x = anchor.x() - self.width() - 12
        y = min(max(anchor.y() - self.height() // 2, area.top()), area.bottom() - self.height())
        self.move(max(x, area.left()), y)
        self.show()


class ThumbDelegate(QStyledItemDelegate):
    """Cards: a rounded panel with the picture inside, an accent outline when selected, a soft one on hover."""

    def paint(self, painter, option, index) -> None:
        t = theme.current()
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        rect = QRectF(option.rect).adjusted(1, 1, -1, -1)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(t.surface3 if hovered and not selected else t.card))
        painter.drawRoundedRect(rect, 12, 12)
        inner = rect.adjusted(6, 6, -6, -6)
        icon = index.data(Qt.ItemDataRole.DecorationRole)
        pm = icon.pixmap(QSize(int(inner.width()), int(inner.height()))) if isinstance(icon, QIcon) and not icon.isNull() else None
        if pm is not None and not pm.isNull():
            ratio = pm.devicePixelRatio() or 1.0
            w, h = pm.width() / ratio, pm.height() / ratio
            scale = min(inner.width() / w, inner.height() / h, 1.0)
            w, h = w * scale, h * scale
            target = QRectF(inner.center().x() - w / 2, inner.center().y() - h / 2, w, h)
            clip = QPainterPath()
            clip.addRoundedRect(target, 8, 8)
            painter.setClipPath(clip)
            painter.drawPixmap(target, pm, QRectF(pm.rect()))
            painter.setClipping(False)
        else:  # not loaded yet: a quiet placeholder instead of a hole
            painter.setBrush(QColor(t.surface3))
            painter.drawRoundedRect(inner, 8, 8)
        if selected:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(t.accent), 2.2))
            painter.drawRoundedRect(rect.adjusted(1, 1, -1, -1), 11, 11)
        elif hovered:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(t.border_hover), 1.2))
            painter.drawRoundedRect(rect, 12, 12)
        painter.restore()

    def sizeHint(self, option, index):  # noqa: N802
        hint = index.data(Qt.ItemDataRole.SizeHintRole)
        return hint if hint is not None else super().sizeHint(option, index)


class ThumbGrid(QListWidget):
    need_more = Signal()                 # scrolled near the bottom (or the viewport is not filled yet)
    context_requested = Signal(QPoint)   # global position of a right click
    delete_pressed = Signal()

    def __init__(self, thumb_size: int = 180, parent=None):
        super().__init__(parent)
        self.thumb_size = thumb_size
        self._generation = 0
        # hover_loader(payload) -> a blocking callable returning a large QImage (or None to show no preview)
        self.hover_loader: Callable[[object], Callable[[], QImage | None] | None] | None = None
        self._empty: tuple[str, str, str] | None = None
        self._hover_token = 0
        self._hover_item: QListWidgetItem | None = None
        self._preview: HoverPreview | None = None
        self.setViewMode(QListView.ViewMode.IconMode)
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setMovement(QListView.Movement.Static)
        self.setUniformItemSizes(True)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setWordWrap(False)
        self.setMouseTracking(True)
        self.setObjectName("thumbGrid")
        self.setItemDelegate(ThumbDelegate(self))
        self.setSpacing(2)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.set_thumb_size(thumb_size)
        self.verticalScrollBar().valueChanged.connect(self._check_more)
        self.verticalScrollBar().valueChanged.connect(self._hide_preview)
        self.customContextMenuRequested.connect(lambda pos: self.context_requested.emit(self.viewport().mapToGlobal(pos)))
        self.itemEntered.connect(self._on_entered)
        self._hover_timer = QTimer(self)
        self._hover_timer.setSingleShot(True)
        self._hover_timer.timeout.connect(self._show_preview)

    def set_empty(self, icon_name: str, title: str, text: str = "") -> None:
        """What to show in the middle of an empty grid (icon, title, hint)."""
        self._empty = (icon_name, title, text)
        self.viewport().update()

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        if self.count() or not self._empty:
            return
        from anihub.ui import icons

        t = theme.current()
        icon_name, title, text = self._empty
        painter = QPainter(self.viewport())
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.viewport().rect()
        cx, cy = rect.center().x(), rect.center().y() - 30
        painter.drawPixmap(cx - 24, cy - 48, icons.pixmap(icon_name, t.muted, 48, 1.6))
        font = self.font()
        font.setPointSizeF(font.pointSizeF() + 2)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QColor(t.text))
        painter.drawText(QRectF(rect.left(), cy + 12, rect.width(), 28), Qt.AlignmentFlag.AlignHCenter, title)
        if text:
            font.setBold(False)
            font.setPointSizeF(font.pointSizeF() - 2)
            painter.setFont(font)
            painter.setPen(QColor(t.dim))
            painter.drawText(QRectF(rect.left() + 40, cy + 44, rect.width() - 80, 60),
                             Qt.AlignmentFlag.AlignHCenter | Qt.TextFlag.TextWordWrap, text)
        painter.end()

    def set_thumb_size(self, size: int) -> None:
        self.thumb_size = size
        self.setIconSize(QSize(size, size))
        self.setGridSize(QSize(size + 16, size + 16))

    def clear_items(self) -> None:
        self._generation += 1
        self._hide_preview()
        self.clear()

    def add_entry(self, payload, tooltip: str, loader: Callable[[], QImage | None]) -> None:
        item = QListWidgetItem()
        item.setData(PAYLOAD, payload)
        item.setData(CAPTION, tooltip)
        if self.hover_loader is None:  # with the preview popup a tooltip would just cover it
            item.setToolTip(tooltip)
        item.setSizeHint(QSize(self.thumb_size + 8, self.thumb_size + 8))
        self.addItem(item)
        generation = self._generation

        def done(img: QImage | None) -> None:
            if img is not None and generation == self._generation:
                item.setIcon(QIcon(QPixmap.fromImage(img)))

        run_async(loader, on_done=done)

    def payloads(self) -> list:
        return [self.item(i).data(PAYLOAD) for i in range(self.count())]

    def selected_payloads(self) -> list:
        return [it.data(PAYLOAD) for it in self.selectedItems()]

    def _check_more(self) -> None:
        bar = self.verticalScrollBar()
        if bar.maximum() == 0 or bar.value() >= bar.maximum() - 3 * self.thumb_size:
            self.need_more.emit()

    def request_fill(self) -> None:
        """Call after appending items: keeps loading while the viewport is not yet scrollable."""
        self._check_more()

    # --- hover preview ---------------------------------------------------------------------------

    def _on_entered(self, item: QListWidgetItem) -> None:
        if self.hover_loader is None or item is self._hover_item:
            return
        self._hide_preview()
        self._hover_item = item
        self._hover_timer.start(HOVER_DELAY_MS)

    def _show_preview(self) -> None:
        item = self._hover_item
        if item is None or self.hover_loader is None:
            return
        try:
            loader = self.hover_loader(item.data(PAYLOAD))
        except RuntimeError:
            return
        if loader is None:
            return
        token = self._hover_token

        def done(image: QImage | None) -> None:
            if image is None or token != self._hover_token or self._hover_item is not item:
                return
            if self._preview is None:
                self._preview = HoverPreview()
            rect = self.visualItemRect(item)
            self._preview.show_image(image, item.data(CAPTION) or "", self.viewport().mapToGlobal(rect.topRight()))

        run_async(loader, on_done=done)

    def _hide_preview(self, *_) -> None:
        self._hover_token += 1
        self._hover_timer.stop()
        self._hover_item = None
        if self._preview is not None:
            self._preview.hide()

    def leaveEvent(self, event) -> None:
        self._hide_preview()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:
        self._hide_preview()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        super().mouseMoveEvent(event)
        if self._hover_item is not None and self.itemAt(event.position().toPoint()) is not self._hover_item:
            self._hide_preview()  # moved onto empty space or another cell

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Delete:
            self.delete_pressed.emit()
        else:
            super().keyPressEvent(event)
