"""Before/after comparison of two pictures (ТЗ 3.8): a draggable divider, or side by side."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QKeyEvent, QMouseEvent, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from anihub.core.i18n import tr
from anihub.ui import style, theme


def fit_rect(size, target: QRectF) -> QRectF:
    """The largest rectangle of the picture's aspect ratio that fits `target`, centred in it."""
    if size.width() <= 0 or size.height() <= 0:
        return QRectF()
    scale = min(target.width() / size.width(), target.height() / size.height())
    w, h = size.width() * scale, size.height() * scale
    return QRectF(target.x() + (target.width() - w) / 2, target.y() + (target.height() - h) / 2, w, h)


class CompareCanvas(QWidget):
    def __init__(self, before: QPixmap, after: QPixmap, parent=None):
        super().__init__(parent)
        self.before, self.after = before, after
        self.side_by_side = False
        self.split = 0.5                      # divider position, 0..1 of the widget width
        self._dragging = False
        self.setMinimumSize(480, 360)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.SplitHCursor)

    def set_side_by_side(self, value: bool) -> None:
        self.side_by_side = value
        self.setCursor(Qt.CursorShape.ArrowCursor if value else Qt.CursorShape.SplitHCursor)
        self.update()

    def swap(self) -> None:
        self.before, self.after = self.after, self.before
        self.update()

    def set_split(self, value: float) -> None:
        self.split = min(max(value, 0.0), 1.0)
        self.update()

    # --- painting ---------------------------------------------------------------------------------

    def _tag(self, p: QPainter, text: str, x: float, y: float, right: bool = False) -> None:
        font = QFont(self.font())
        font.setPixelSize(12)
        font.setWeight(QFont.Weight.DemiBold)
        p.setFont(font)
        metrics = p.fontMetrics()
        w = metrics.horizontalAdvance(text) + 18
        rect = QRectF(x - w if right else x, y, w, 24)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 170))
        p.drawRoundedRect(rect, 12, 12)
        p.setPen(QColor("white"))
        p.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
        t = theme.current()
        p.fillRect(self.rect(), QColor(t.surface))
        area = QRectF(self.rect()).adjusted(6, 6, -6, -6)
        if self.side_by_side:
            half = (area.width() - 8) / 2
            left = QRectF(area.x(), area.y(), half, area.height())
            right = QRectF(area.x() + half + 8, area.y(), half, area.height())
            for pixmap, box, label, at_right in ((self.before, left, tr("compare.before"), False),
                                                 (self.after, right, tr("compare.after"), False)):
                p.drawPixmap(fit_rect(pixmap.size(), box), pixmap, QRectF(pixmap.rect()))
                self._tag(p, label, box.x() + 8, box.y() + 8)
            return
        # the "after" picture fills the frame; the "before" one is revealed to the left of the divider
        rect_after, rect_before = fit_rect(self.after.size(), area), fit_rect(self.before.size(), area)
        p.drawPixmap(rect_after, self.after, QRectF(self.after.rect()))
        x = area.x() + area.width() * self.split
        p.save()
        p.setClipRect(QRectF(area.x(), area.y(), x - area.x(), area.height()))
        p.drawPixmap(rect_before, self.before, QRectF(self.before.rect()))
        p.restore()
        self._tag(p, tr("compare.before"), area.x() + 8, area.y() + 8)
        self._tag(p, tr("compare.after"), area.right() - 8, area.y() + 8, right=True)
        p.setPen(QPen(QColor("white"), 2))
        p.drawLine(QPointF(x, area.top()), QPointF(x, area.bottom()))
        p.setPen(QPen(QColor(0, 0, 0, 120), 1))
        p.setBrush(QColor(t.accent))
        cy = area.center().y()
        p.drawEllipse(QPointF(x, cy), 15, 15)
        p.setPen(QPen(QColor("white"), 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        p.drawPolyline([QPointF(x - 3, cy - 5), QPointF(x - 8, cy), QPointF(x - 3, cy + 5)])
        p.drawPolyline([QPointF(x + 3, cy - 5), QPointF(x + 8, cy), QPointF(x + 3, cy + 5)])

    # --- input ------------------------------------------------------------------------------------

    def _set_from_x(self, x: float) -> None:
        area_x, area_w = 6, max(self.width() - 12, 1)
        self.set_split((x - area_x) / area_w)

    def mousePressEvent(self, e: QMouseEvent) -> None:  # noqa: N802
        if e.button() == Qt.MouseButton.LeftButton and not self.side_by_side:
            self._dragging = True
            self._set_from_x(e.position().x())

    def mouseMoveEvent(self, e: QMouseEvent) -> None:  # noqa: N802
        if self._dragging:
            self._set_from_x(e.position().x())

    def mouseReleaseEvent(self, _e: QMouseEvent) -> None:  # noqa: N802
        self._dragging = False


class CompareDialog(QDialog):
    """`before` / `after`: (path, caption). Space or the button switches the view, ←/→ move the divider."""

    def __init__(self, before: tuple[Path, str], after: tuple[Path, str], parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("compare.title"))
        self.resize(1100, 760)
        self.canvas = CompareCanvas(QPixmap(str(before[0])), QPixmap(str(after[0])))
        self.captions = [before, after]
        self.info = QLabel()
        self.info.setWordWrap(True)
        style.role(self.info, "dim")
        self.mode_btn = style.secondary(QPushButton(tr("compare.side_by_side")), "columns")
        self.mode_btn.setCheckable(True)
        self.swap_btn = style.secondary(QPushButton(tr("compare.swap")), "refresh")
        self.close_btn = style.secondary(QPushButton(tr("action.close")), "x")
        bar = QHBoxLayout()
        bar.addWidget(self.mode_btn)
        bar.addWidget(self.swap_btn)
        bar.addStretch(1)
        bar.addWidget(self.close_btn)
        hint = QLabel(tr("compare.hint"))
        style.role(hint, "muted")
        layout = QVBoxLayout(self)
        layout.addWidget(self.canvas, 1)
        layout.addWidget(self.info)
        layout.addLayout(bar)
        layout.addWidget(hint)
        self.mode_btn.toggled.connect(self.canvas.set_side_by_side)
        self.swap_btn.clicked.connect(self._swap)
        self.close_btn.clicked.connect(self.accept)
        for w in (self.mode_btn, self.swap_btn, self.close_btn):
            w.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._describe()

    def _describe(self) -> None:
        def line(path: Path, caption: str, pixmap: QPixmap) -> str:
            size = path.stat().st_size / 1024 if path.exists() else 0
            return f"{caption}: {pixmap.width()}×{pixmap.height()} · {size:,.0f} KB".replace(",", " ")

        self.info.setText("   |   ".join(line(path, caption, pm) for (path, caption), pm in
                                        zip(self.captions, (self.canvas.before, self.canvas.after))))

    def _swap(self) -> None:
        self.captions.reverse()
        self.canvas.swap()
        self._describe()

    def keyPressEvent(self, e: QKeyEvent) -> None:  # noqa: N802
        key = e.key()
        if key == Qt.Key.Key_Left:
            self.canvas.set_split(self.canvas.split - 0.03)
        elif key == Qt.Key.Key_Right:
            self.canvas.set_split(self.canvas.split + 0.03)
        elif key == Qt.Key.Key_Space:
            self.mode_btn.toggle()
        elif key == Qt.Key.Key_X:
            self._swap()
        else:
            super().keyPressEvent(e)
