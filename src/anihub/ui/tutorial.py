"""First-run tutorial: the window is dimmed, one control is lit, a card explains it, "Next" slides the light and the card to
the next control (switching sections on the way). Runs once after the setup wizard; Settings and the command palette replay it."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from PySide6.QtCore import QEasingCurve, QEvent, QPoint, QPointF, QRectF, Qt, QTimer, QVariantAnimation, Signal
from PySide6.QtGui import QColor, QKeyEvent, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget

from anihub.core.i18n import tr
from anihub.ui import style, theme

PAD = 7                     # the light is a little bigger than the control
MARGIN = 14                 # the card keeps this far from the window edges
GAP = 18                    # ...and this far from the lit control


@dataclass
class Step:
    key: str                                          # i18n keys: tutorial.<key>.title / tutorial.<key>.text
    target: Callable[[], QWidget | None] | None       # None: a card in the middle, nothing lit
    prepare: Callable[[], None] | None = None         # switches to the section that contains the target


def place_card(size, hole: QRectF, bounds: QRectF) -> QPointF:
    """Where the card goes: below, to the right, above or to the left of the lit rectangle, whichever fits first;
    with no rectangle (or no room) it is centred."""
    if hole.isEmpty():
        return QPointF(bounds.center().x() - size.width() / 2, bounds.center().y() - size.height() / 2)
    w, h = size.width(), size.height()
    inner = bounds.adjusted(MARGIN, MARGIN, -MARGIN, -MARGIN)
    cx, cy = hole.center().x() - w / 2, hole.center().y() - h / 2
    candidates = [QPointF(cx, hole.bottom() + GAP), QPointF(hole.right() + GAP, cy), QPointF(cx, hole.top() - GAP - h),
                  QPointF(hole.left() - GAP - w, cy)]
    for p in candidates:
        if inner.contains(QRectF(p, size)):
            return p
    p = candidates[0]                                 # nothing fits: the first choice, pushed inside the window
    return QPointF(min(max(p.x(), inner.left()), inner.right() - w), min(max(p.y(), inner.top()), inner.bottom() - h))


def scroll_into_view(widget: QWidget) -> None:
    parent = widget.parentWidget()
    while parent is not None:
        if isinstance(parent, QScrollArea):
            parent.ensureWidgetVisible(widget, 0, 60)
            return
        parent = parent.parentWidget()


class TutorialOverlay(QWidget):
    finished = Signal(bool)                           # True: read to the end; False: skipped

    def __init__(self, window: QWidget, steps: list[Step]):
        super().__init__(window)
        self.window_, self.steps = window, steps
        self.index = -1
        self.shown_index = -1                             # the step whose card is (being) shown; lags `index` by a moment
        self._hole = QRectF()
        self._card_pos = QPointF()
        self._anim = QVariantAnimation(self, duration=420)
        self._anim.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self._anim.valueChanged.connect(self._on_anim)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setMouseTracking(True)

        self.card = QFrame(self)
        self.card.setObjectName("coach")
        self.counter = style.role(QLabel(), "dim")
        self.title = QLabel()
        self.title.setStyleSheet("font-size: 16px; font-weight: 700;")
        self.title.setWordWrap(True)
        self.text = QLabel()
        self.text.setWordWrap(True)
        self.text.setTextFormat(Qt.TextFormat.RichText)
        self.skip_btn = style.ghost(QPushButton(tr("tutorial.skip")), "x")
        self.back_btn = style.secondary(QPushButton(tr("tutorial.back")), "chevron-left")
        self.next_btn = style.primary(QPushButton(tr("tutorial.next")), "chevron-right")
        for b in (self.skip_btn, self.back_btn, self.next_btn):
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        buttons = QHBoxLayout()
        buttons.addWidget(self.skip_btn)
        buttons.addStretch(1)
        buttons.addWidget(self.back_btn)
        buttons.addWidget(self.next_btn)
        layout = QVBoxLayout(self.card)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(8)
        for w in (self.counter, self.title, self.text):
            layout.addWidget(w)
        layout.addSpacing(6)
        layout.addLayout(buttons)
        self.card.setFixedWidth(400)
        self.skip_btn.clicked.connect(lambda: self.finish(False))
        self.back_btn.clicked.connect(self.back)
        self.next_btn.clicked.connect(self.next)
        window.installEventFilter(self)
        self.setGeometry(window.rect())
        self.hide()

    # --- flow ----------------------------------------------------------------------------------------------------

    def start(self) -> None:
        self.setGeometry(self.window_.rect())
        self.raise_()
        self.show()
        self.setFocus()
        self.goto(0)

    def next(self) -> None:
        if self.index >= len(self.steps) - 1:
            self.finish(True)
        else:
            self.goto(self.index + 1)

    def back(self) -> None:
        if self.index > 0:
            self.goto(self.index - 1, backwards=True)

    def finish(self, completed: bool) -> None:
        self._anim.stop()
        self.window_.removeEventFilter(self)
        self.hide()
        self.finished.emit(completed)
        self.deleteLater()

    def goto(self, index: int, backwards: bool = False) -> None:
        """Show step `index`; a step whose control is not there (a hidden button, a missing tab) is skipped."""
        step = self.steps[index]
        if step.prepare:
            step.prepare()
        self.index = index
        # the target may only get its geometry after the section switched: measure on the next turn of the event loop
        QTimer.singleShot(40, lambda i=index, b=backwards: self._show_step(i, b))

    def _target_rect(self, step: Step) -> QRectF | None:
        if step.target is None:
            return QRectF()
        widget = step.target()
        if widget is None or not widget.isVisibleTo(self.window_) or widget.width() < 4:
            return None
        scroll_into_view(widget)
        origin = widget.mapTo(self.window_, QPoint(0, 0))
        return QRectF(origin.x(), origin.y(), widget.width(), widget.height()).adjusted(-PAD, -PAD, PAD, PAD)

    def _show_step(self, index: int, backwards: bool) -> None:
        if index != self.index or not self.isVisible():
            return
        step = self.steps[index]
        rect = self._target_rect(step)
        if rect is None:                              # nothing to show here
            if backwards and index > 0:
                self.goto(index - 1, True)
            elif index < len(self.steps) - 1:
                self.goto(index + 1)
            else:
                self.finish(True)
            return
        total = len(self.steps)
        self.counter.setText(tr("tutorial.counter", n=index + 1, total=total))
        self.title.setText(tr(f"tutorial.{step.key}.title"))
        self.text.setText(tr(f"tutorial.{step.key}.text"))
        self.back_btn.setVisible(index > 0)
        self.next_btn.setText(tr("tutorial.done") if index == total - 1 else tr("tutorial.next"))
        self.card.adjustSize()
        bounds = QRectF(self.rect())
        target_pos = place_card(self.card.size(), rect, bounds)
        start_hole = self._hole if not self._hole.isEmpty() else QRectF(rect.center(), rect.size() * 0.0)
        start_pos = self._card_pos if not self._card_pos.isNull() else target_pos
        self._from = (QRectF(start_hole), QPointF(start_pos))
        self._to = (QRectF(rect), QPointF(target_pos))
        self.shown_index = index
        self._anim.stop()
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.start()

    def _on_anim(self, value) -> None:
        t = float(value)
        (fh, fp), (th, tp) = self._from, self._to
        lerp = lambda a, b: a + (b - a) * t
        self._hole = QRectF(lerp(fh.x(), th.x()), lerp(fh.y(), th.y()), lerp(fh.width(), th.width()), lerp(fh.height(), th.height()))
        self._card_pos = QPointF(lerp(fp.x(), tp.x()), lerp(fp.y(), tp.y()))
        self.card.move(self._card_pos.toPoint())
        self.card.raise_()
        self.update()

    # --- drawing -------------------------------------------------------------------------------------------------

    def paintEvent(self, _event) -> None:             # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        shade = QPainterPath()
        shade.addRect(QRectF(self.rect()))
        if not self._hole.isEmpty():
            hole = QPainterPath()
            hole.addRoundedRect(self._hole, 12, 12)
            shade = shade.subtracted(hole)
        p.fillPath(shade, QColor(6, 5, 14, 178))
        if not self._hole.isEmpty():
            accent = theme.css_color(theme.current().accent)
            for grow, alpha in ((7, 30), (4, 55), (0, 255)):     # a soft glow around a crisp ring
                ring = QColor(accent)
                ring.setAlpha(alpha)
                p.setPen(QPen(ring, 2 if grow == 0 else 3))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawRoundedRect(self._hole.adjusted(-grow, -grow, grow, grow), 12 + grow, 12 + grow)

    # --- input / geometry ----------------------------------------------------------------------------------------

    def keyPressEvent(self, e: QKeyEvent) -> None:    # noqa: N802
        if e.key() in (Qt.Key.Key_Right, Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.next()
        elif e.key() in (Qt.Key.Key_Left, Qt.Key.Key_Backspace):
            self.back()
        elif e.key() == Qt.Key.Key_Escape:
            self.finish(False)
        else:
            super().keyPressEvent(e)

    def eventFilter(self, obj, event) -> bool:        # noqa: N802
        if obj is self.window_ and event.type() == QEvent.Type.Resize and self.isVisible():
            self.setGeometry(self.window_.rect())
            QTimer.singleShot(0, lambda: self._show_step(self.index, False) if self.index >= 0 else None)
        return False
