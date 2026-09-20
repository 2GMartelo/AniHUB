"""Inpaint mask editor (ТЗ 5.3): paint over the part of the picture that Stable Diffusion should redraw."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QKeyEvent, QMouseEvent, QPainter, QPen, QPixmap, QWheelEvent
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QHBoxLayout, QLabel, QPushButton, QSlider, QVBoxLayout, QWidget,
)

from anihub.core.i18n import tr
from anihub.ui import style, theme
from anihub.ui.compare import fit_rect

UNDO_LIMIT = 30
OVERLAY = QColor(255, 60, 90, 140)


class MaskCanvas(QWidget):
    """Shows the picture with the mask drawn over it. The mask lives in picture pixels (so it is exact at any zoom):
    an alpha image, opaque = repaint."""

    def __init__(self, source: QPixmap, parent=None):
        super().__init__(parent)
        self.source = source
        self.mask = QImage(source.size(), QImage.Format.Format_ARGB32_Premultiplied)
        self.mask.fill(Qt.GlobalColor.transparent)
        self.brush = max(8, min(source.width(), source.height()) // 12)     # in picture pixels
        self.erasing = False
        self._undo: list[QImage] = []
        self._was_erasing = False
        self._last: QPointF | None = None
        self._hover: QPointF | None = None
        self.setMinimumSize(520, 420)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.CrossCursor)

    # --- geometry ----------------------------------------------------------------------------------

    def _frame(self) -> QRectF:
        return fit_rect(self.source.size(), QRectF(self.rect()).adjusted(6, 6, -6, -6))

    def _to_image(self, pos: QPointF) -> QPointF:
        frame = self._frame()
        scale = self.source.width() / max(frame.width(), 1)
        return QPointF((pos.x() - frame.x()) * scale, (pos.y() - frame.y()) * scale)

    # --- painting ----------------------------------------------------------------------------------

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
        p.fillRect(self.rect(), QColor(theme.current().surface))
        frame = self._frame()
        p.drawPixmap(frame, self.source, QRectF(self.source.rect()))
        tinted = QImage(self.mask.size(), QImage.Format.Format_ARGB32_Premultiplied)
        tinted.fill(Qt.GlobalColor.transparent)
        q = QPainter(tinted)
        q.drawImage(0, 0, self.mask)
        q.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
        q.fillRect(tinted.rect(), OVERLAY)
        q.end()
        p.drawImage(frame, tinted)
        if self._hover is not None and frame.contains(self._hover):
            radius = self.brush / 2 * frame.width() / self.source.width()
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(QColor("white"), 1.5))
            p.drawEllipse(self._hover, radius, radius)
            p.setPen(QPen(QColor(0, 0, 0, 160), 1))
            p.drawEllipse(self._hover, radius + 1.5, radius + 1.5)

    # --- editing -----------------------------------------------------------------------------------

    def _push_undo(self) -> None:
        self._undo.append(self.mask.copy())
        del self._undo[:-UNDO_LIMIT]

    def undo(self) -> None:
        if self._undo:
            self.mask = self._undo.pop()
            self.update()

    def clear(self) -> None:
        self._push_undo()
        self.mask.fill(Qt.GlobalColor.transparent)
        self.update()

    def invert(self) -> None:
        self._push_undo()
        inverted = QImage(self.mask.size(), QImage.Format.Format_ARGB32_Premultiplied)
        inverted.fill(QColor(255, 255, 255, 255))
        q = QPainter(inverted)
        q.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationOut)
        q.drawImage(0, 0, self.mask)
        q.end()
        self.mask = inverted
        self.update()

    def is_empty(self) -> bool:
        gray = self.mask_gray()             # keep the image alive while its buffer is read
        return not any(bytes(gray.constBits()))

    def _stroke(self, a: QPointF, b: QPointF) -> None:
        q = QPainter(self.mask)
        q.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self.erasing:
            q.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
        pen = QPen(QColor(255, 255, 255, 255), self.brush, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                   Qt.PenJoinStyle.RoundJoin)
        q.setPen(pen)
        if a == b:
            q.drawPoint(a)              # a click: Qt draws nothing for a zero-length line, but a point gets the round cap
        else:
            q.drawLine(a, b)
        q.end()
        self.update()

    def mousePressEvent(self, e: QMouseEvent) -> None:  # noqa: N802
        if e.button() in (Qt.MouseButton.LeftButton, Qt.MouseButton.RightButton):
            self._push_undo()
            self._was_erasing = self.erasing
            if e.button() == Qt.MouseButton.RightButton:
                self.erasing = not self.erasing          # right button = the opposite tool while held
            self._last = self._to_image(e.position())
            self._stroke(self._last, self._last)

    def mouseMoveEvent(self, e: QMouseEvent) -> None:  # noqa: N802
        self._hover = e.position()
        if self._last is not None and e.buttons():
            now = self._to_image(e.position())
            self._stroke(self._last, now)
            self._last = now
        else:
            self.update()

    def mouseReleaseEvent(self, _e: QMouseEvent) -> None:  # noqa: N802
        if self._last is not None:
            self.erasing = self._was_erasing
        self._last = None

    def leaveEvent(self, _e) -> None:  # noqa: N802
        self._hover = None
        self.update()

    def wheelEvent(self, e: QWheelEvent) -> None:  # noqa: N802
        step = 1.15 if e.angleDelta().y() > 0 else 1 / 1.15
        self.set_brush(int(round(self.brush * step)))

    def set_brush(self, size: int) -> None:
        self.brush = max(2, min(size, max(self.source.width(), self.source.height())))
        self.brush_changed(self.brush)
        self.update()

    def brush_changed(self, size: int) -> None:  # hook for the dialog's slider
        pass

    # --- result ------------------------------------------------------------------------------------

    def mask_gray(self) -> QImage:
        """The mask as Forge wants it: white = repaint, black = keep. Same size as the picture."""
        gray = QImage(self.mask.size(), QImage.Format.Format_RGB32)
        gray.fill(QColor("black"))
        q = QPainter(gray)
        q.drawImage(0, 0, self.mask)          # white strokes over black
        q.end()
        return gray.convertToFormat(QImage.Format.Format_Grayscale8)


class MaskDialog(QDialog):
    def __init__(self, source: QPixmap, existing: QImage | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("mask.title"))
        self.resize(1000, 780)
        self.canvas = MaskCanvas(source)
        if existing is not None and not existing.isNull():
            self._load_existing(existing)
        self.size_slider = QSlider(Qt.Orientation.Horizontal)
        top = max(source.width(), source.height())
        self.size_slider.setRange(2, max(top // 2, 8))
        self.size_slider.setValue(self.canvas.brush)
        self.size_label = QLabel()
        self.eraser = QCheckBox(tr("mask.eraser"))
        self.undo_btn = style.secondary(QPushButton(tr("mask.undo")), "rotate")
        self.clear_btn = style.secondary(QPushButton(tr("mask.clear")), "trash")
        self.invert_btn = style.secondary(QPushButton(tr("mask.invert")), "refresh")
        self.ok_btn = style.primary(QPushButton(tr("mask.use")), "check")
        self.cancel_btn = style.secondary(QPushButton(tr("wizard.cancel")), "x")
        bar = QHBoxLayout()
        bar.addWidget(QLabel(tr("mask.brush")))
        bar.addWidget(self.size_slider, 1)
        bar.addWidget(self.size_label)
        bar.addWidget(self.eraser)
        for w in (self.undo_btn, self.clear_btn, self.invert_btn):
            bar.addWidget(w)
        buttons = QHBoxLayout()
        hint = QLabel(tr("mask.hint"))
        style.role(hint, "muted")
        hint.setWordWrap(True)
        buttons.addWidget(hint, 1)
        buttons.addWidget(self.ok_btn)
        buttons.addWidget(self.cancel_btn)
        layout = QVBoxLayout(self)
        layout.addWidget(self.canvas, 1)
        layout.addLayout(bar)
        layout.addLayout(buttons)
        self.canvas.brush_changed = self._brush_from_canvas
        self.size_slider.valueChanged.connect(self._brush_from_slider)
        self.eraser.toggled.connect(lambda v: setattr(self.canvas, "erasing", v))
        self.undo_btn.clicked.connect(self.canvas.undo)
        self.clear_btn.clicked.connect(self.canvas.clear)
        self.invert_btn.clicked.connect(self.canvas.invert)
        self.ok_btn.clicked.connect(self.accept)
        self.cancel_btn.clicked.connect(self.reject)
        self._update_label()

    def _load_existing(self, gray: QImage) -> None:
        """Re-open an earlier mask for editing: white pixels become opaque strokes."""
        scaled = gray.scaled(self.canvas.mask.size(), Qt.AspectRatioMode.IgnoreAspectRatio) \
            if gray.size() != self.canvas.mask.size() else gray
        alpha = scaled.convertToFormat(QImage.Format.Format_Grayscale8)
        overlay = QImage(alpha.size(), QImage.Format.Format_ARGB32_Premultiplied)
        overlay.fill(QColor(255, 255, 255, 255))
        overlay.setAlphaChannel(alpha)
        self.canvas.mask = overlay.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)

    def _update_label(self) -> None:
        self.size_label.setText(f"{self.canvas.brush} px")

    def _brush_from_slider(self, value: int) -> None:
        self.canvas.brush = value
        self._update_label()
        self.canvas.update()

    def _brush_from_canvas(self, value: int) -> None:
        self.size_slider.blockSignals(True)
        self.size_slider.setValue(value)
        self.size_slider.blockSignals(False)
        self._update_label()

    def has_mask(self) -> bool:
        return not self.canvas.is_empty()

    def result_mask(self) -> QImage:
        return self.canvas.mask_gray()

    def keyPressEvent(self, e: QKeyEvent) -> None:  # noqa: N802
        if e.key() == Qt.Key.Key_Z and e.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.canvas.undo()
        elif e.key() == Qt.Key.Key_E:
            self.eraser.toggle()
        else:
            super().keyPressEvent(e)
