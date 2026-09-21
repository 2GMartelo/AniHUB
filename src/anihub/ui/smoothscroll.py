"""Smooth mouse-wheel scrolling for every scrollable list, grid, table, tree, text and settings page of the application.

One event filter on the application: a plain wheel turn over a scroll area's viewport starts a short eased animation of the
vertical scroll bar instead of jumping (several turns in a row add up and keep the motion going). Ctrl / Shift / Alt + wheel,
touchpads (they scroll in pixels already), the widgets that handle the wheel themselves (the webtoon strip, sliders, combo
boxes) and a scroll area that cannot move any further (the wheel then reaches its parent) are left alone.
"""
from __future__ import annotations

from PySide6.QtCore import QAbstractAnimation, QEasingCurve, QEvent, QObject, QPropertyAnimation, Qt
from PySide6.QtWidgets import QAbstractItemView, QAbstractScrollArea, QApplication

DURATION_MS = 240
PIXELS_PER_NOTCH = 110                     # one wheel notch (angle delta 120)


class SmoothScroll(QObject):
    def __init__(self, enabled: bool = True):
        super().__init__()
        self.enabled = enabled
        self._anims: dict[int, QPropertyAnimation] = {}         # scroll bar id -> its running animation

    # --- helpers ---------------------------------------------------------------------------------------------

    @staticmethod
    def area_of(obj: QObject) -> QAbstractScrollArea | None:
        parent = obj.parent()
        return parent if isinstance(parent, QAbstractScrollArea) and parent.viewport() is obj else None

    @staticmethod
    def opted_out(area: QAbstractScrollArea) -> bool:
        return bool(area.property("smoothScroll") is False) or hasattr(area, "scroll_by")     # the webtoon strip animates itself

    def _animation(self, bar) -> QPropertyAnimation:
        key = id(bar)
        anim = self._anims.get(key)
        if anim is None:
            anim = QPropertyAnimation(bar, b"value", bar)
            anim.setEasingCurve(QEasingCurve.Type.OutCubic)
            anim.setDuration(DURATION_MS)
            bar.sliderPressed.connect(anim.stop)                 # grabbing the bar hands the control back to the user
            bar.destroyed.connect(lambda _o=None, k=key: self._anims.pop(k, None))
            self._anims[key] = anim
        return anim

    def scroll(self, area: QAbstractScrollArea, delta: int) -> bool:
        """Animate the vertical bar by `delta` px. False when it cannot move that way (the caller lets the event through)."""
        bar = area.verticalScrollBar()
        if bar.maximum() <= bar.minimum():
            return False
        anim = self._animation(bar)
        running = anim.state() == QAbstractAnimation.State.Running
        base = int(anim.endValue()) if running else bar.value()
        target = max(bar.minimum(), min(bar.maximum(), base + delta))
        if target == base:
            return running                                       # at the edge: swallow while moving, pass on once settled
        anim.stop()
        anim.setStartValue(bar.value())
        anim.setEndValue(target)
        anim.start()
        return True

    # --- the filter --------------------------------------------------------------------------------------------

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:      # noqa: N802
        if not self.enabled or event.type() != QEvent.Type.Wheel:
            return False
        area = self.area_of(obj)
        if area is None or self.opted_out(area):
            return False
        if event.modifiers() != Qt.KeyboardModifier.NoModifier or not event.pixelDelta().isNull():
            return False
        dy = event.angleDelta().y()
        if not dy or event.angleDelta().x():
            return False
        if isinstance(area, QAbstractItemView) and area.verticalScrollMode() != QAbstractItemView.ScrollMode.ScrollPerPixel:
            area.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)      # the bar counts pixels, not rows
            area.verticalScrollBar().setSingleStep(24)
        if self.scroll(area, -round(dy / 120 * PIXELS_PER_NOTCH)):
            event.accept()
            return True
        return False


_instance: SmoothScroll | None = None


def install(app: QApplication, enabled: bool = True) -> SmoothScroll:
    global _instance
    if _instance is None:
        _instance = SmoothScroll(enabled)
        app.installEventFilter(_instance)
    _instance.enabled = enabled
    return _instance


def set_enabled(enabled: bool) -> None:
    if _instance is not None:
        _instance.enabled = enabled
