"""Small helpers to apply the design system from code: button roles, icons that follow the theme, empty states."""
from __future__ import annotations

import weakref

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QAbstractButton, QFrame, QLabel, QLayout, QPushButton, QVBoxLayout, QWidget

from anihub.ui import icons, theme

_bound: "weakref.WeakSet[QWidget]" = weakref.WeakSet()


def _icon_for(spec: tuple[str, str, int]) -> QIcon:
    name, mode, size = spec
    t = theme.current()
    if mode == "white":
        return icons.white_icon(name, size)
    if mode == "danger":
        return icons.icon(name, t.danger, size)
    if mode == "accent":
        return icons.icon(name, t.accent_text, size)
    return icons.icon(name, size=size)


def bind_icon(button: QAbstractButton, name: str, mode: str = "normal", size: int = 18) -> QAbstractButton:
    """Give a button a theme-aware icon; it is recoloured automatically when the theme changes."""
    button._icon_spec = (name, mode, size)  # type: ignore[attr-defined]
    button.setIcon(_icon_for(button._icon_spec))  # type: ignore[attr-defined]
    button.setIconSize(QSize(size, size))
    _bound.add(button)
    return button


def refresh_icons() -> None:
    for w in list(_bound):
        try:
            w.setIcon(_icon_for(w._icon_spec))  # type: ignore[attr-defined]
        except RuntimeError:  # the C++ widget is already gone
            pass


def repolish(widget: QWidget) -> None:
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.update()


def _no_default(button: QAbstractButton) -> None:
    """In a dialog the first push button would otherwise become the 'default' one and be painted as the primary action."""
    if isinstance(button, QPushButton):
        button.setAutoDefault(False)


def _variant(button: QAbstractButton, name: str, icon: str | None, mode: str) -> QAbstractButton:
    if name != "primary":
        _no_default(button)
    button.setProperty("variant", name)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    if icon:
        bind_icon(button, icon, mode)
    repolish(button)
    return button


def primary(button: QAbstractButton, icon: str | None = None) -> QAbstractButton:
    """The one main action of a screen."""
    return _variant(button, "primary", icon, "white")


def secondary(button: QAbstractButton, icon: str | None = None) -> QAbstractButton:
    _no_default(button)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    if icon:
        bind_icon(button, icon)
    return button


def ghost(button: QAbstractButton, icon: str | None = None) -> QAbstractButton:
    return _variant(button, "ghost", icon, "normal")


def danger(button: QAbstractButton, icon: str | None = None) -> QAbstractButton:
    return _variant(button, "danger", icon, "danger")


def role(label: QLabel, name: str) -> QLabel:
    """Typography role: title | h2 | dim | muted | error | chip."""
    label.setProperty("role", name)
    repolish(label)
    return label


def state_color(state: str) -> str:
    t = theme.current()
    return {"stopped": t.muted, "starting": t.warning, "running": t.success, "external": t.success,
            "failed": t.danger}.get(state, t.muted)


def tidy(layout: QLayout, margins: int = 0, spacing: int = 10) -> QLayout:
    layout.setContentsMargins(margins, margins, margins, margins)
    layout.setSpacing(spacing)
    return layout


class EmptyState(QWidget):
    """Centered icon + title + text for sections that have nothing to show yet."""

    def __init__(self, icon_name: str, title: str, text: str, parent=None):
        super().__init__(parent)
        self._icon_name = icon_name
        self.icon_label = QLabel(alignment=Qt.AlignmentFlag.AlignCenter)
        self.title = role(QLabel(title, alignment=Qt.AlignmentFlag.AlignCenter), "h2")
        self.text = role(QLabel(text, alignment=Qt.AlignmentFlag.AlignCenter, wordWrap=True), "dim")
        self.text.setMaximumWidth(460)
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(10)
        for w in (self.icon_label, self.title):
            layout.addWidget(w, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(self.text, 0, Qt.AlignmentFlag.AlignHCenter)
        _bound.add(self)
        self.refresh()

    def refresh(self) -> None:
        self.icon_label.setPixmap(icons.pixmap(self._icon_name, theme.current().muted, 48, 1.6))

    # duck-typed hook used by refresh_icons()
    _icon_spec = ("", "", 0)

    def setIcon(self, _icon) -> None:  # noqa: N802 - Qt-style name expected by refresh_icons
        self.refresh()


def hline() -> QFrame:
    line = QFrame()
    line.setFrameShape(QFrame.Shape.HLine)
    return line


def card(widget: QWidget | None = None, margins: int = 14) -> QFrame:
    """A rounded panel. Pass a widget to put inside, or add children to the returned frame's layout."""
    frame = QFrame()
    frame.setObjectName("card")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(margins, margins, margins, margins)
    if widget is not None:
        layout.addWidget(widget)
    return frame


class StatusChip(QFrame):
    """Pill with a coloured dot and a short text: the state of a background service."""

    def __init__(self, parent=None):
        super().__init__(parent)
        from PySide6.QtWidgets import QHBoxLayout

        self.setObjectName("chip")
        self.dot = QLabel("●")
        self.text = QLabel()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 4, 14, 4)
        layout.setSpacing(7)
        layout.addWidget(self.dot)
        layout.addWidget(self.text)

    def set_state(self, state: str, text: str) -> None:
        self.dot.setStyleSheet(f"color: {state_color(state)}; font-size: 14px;")
        self.text.setText(text)
