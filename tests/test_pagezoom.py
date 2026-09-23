from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication, QHBoxLayout, QPushButton, QWidget

from anihub.ui import style
from anihub.ui.pagezoom import MAX_FACTOR, MIN_FACTOR, PageZoom


def make_page():
    page = QWidget()
    btn = style.primary(QPushButton("go"), "zap")
    plain = QPushButton("plain")           # no icon: must be ignored, not crash
    layout = QHBoxLayout(page)
    layout.addWidget(btn)
    layout.addWidget(plain)
    return page, btn, plain


def wheel_event(widget, ctrl: bool, up: bool = True) -> QWheelEvent:
    mods = Qt.KeyboardModifier.ControlModifier if ctrl else Qt.KeyboardModifier.NoModifier
    return QWheelEvent(QPointF(5, 5), QPointF(5, 5), QPoint(0, 0), QPoint(0, 120 if up else -120),
                       Qt.MouseButton.NoButton, mods, Qt.ScrollPhase.NoScrollPhase, False)


def test_zoom_in_scales_icon_bound_buttons_only(qapp):
    page, btn, plain = make_page()
    zoom = PageZoom(page)
    assert btn.iconSize().width() == 18                        # style.primary's default icon size
    zoom.zoom(1)
    assert btn.iconSize().width() == round(18 * 1.1)            # 20: 18 * 1.1 rounded
    assert plain.icon().isNull()                                # untouched, never had an icon to begin with


def test_zoom_out_shrinks_and_clamps_at_the_minimum(qapp):
    page, btn, _plain = make_page()
    zoom = PageZoom(page)
    for _ in range(20):
        zoom.zoom(-1)
    assert zoom.factor == MIN_FACTOR
    assert btn.iconSize().width() == max(10, round(18 * MIN_FACTOR))


def test_zoom_clamps_at_the_maximum(qapp):
    page, btn, _plain = make_page()
    zoom = PageZoom(page)
    for _ in range(20):
        zoom.zoom(1)
    assert zoom.factor == MAX_FACTOR
    assert btn.iconSize().width() == round(18 * MAX_FACTOR)


def test_on_zoom_callback_receives_the_new_factor(qapp):
    page, _btn, _plain = make_page()
    seen = []
    zoom = PageZoom(page, on_zoom=seen.append)
    zoom.zoom(1)
    zoom.zoom(1)
    assert seen == [1.1, 1.2]


def test_ctrl_wheel_over_a_child_widget_triggers_zoom_and_plain_wheel_does_not(qapp):
    page, btn, _plain = make_page()
    seen = []
    zoom = PageZoom(page, on_zoom=seen.append)
    handled = QApplication.sendEvent(btn, wheel_event(btn, ctrl=True))
    assert handled and seen == [1.1]                            # the event filter intercepted it before the button saw it

    handled2 = QApplication.sendEvent(btn, wheel_event(btn, ctrl=False))
    assert seen == [1.1]                                        # a plain wheel is left alone, not swallowed as a zoom
