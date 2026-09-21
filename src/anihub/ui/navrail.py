"""Vertical navigation rail: app logo, section buttons (icon over label), settings pinned to the bottom."""
from __future__ import annotations

import weakref

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QPainter
from PySide6.QtWidgets import QAbstractButton, QButtonGroup, QLabel, QVBoxLayout, QWidget

from anihub.ui import icons, theme
from anihub.ui.theme import css_color as _css_color
from anihub.ui.theme import make_app_icon

_rails: "weakref.WeakSet[NavRail]" = weakref.WeakSet()


def refresh_rails() -> None:
    for rail in list(_rails):
        rail.refresh_icons()


class NavButton(QAbstractButton):
    """Icon over label, both centred exactly; painted by hand so it looks the same on every DPI."""

    ICON = 24

    def __init__(self, text: str, icon_name: str, parent=None):
        super().__init__(parent)
        self.setText(text)
        self.setToolTip(text)
        self.setCheckable(True)
        self.setFixedHeight(62)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self._name = icon_name
        self.refresh_icon()

    def refresh_icon(self) -> None:
        self.setIcon(icons.nav_icon(self._name))
        self.update()

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(68, 62)

    def paintEvent(self, _event) -> None:  # noqa: N802
        t = theme.current()
        p = QPainter(self)
        p.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing)
        checked, hover = self.isChecked(), self.underMouse()
        if checked:
            p.setBrush(_css_color(t.soft))
        elif hover:
            p.setBrush(_css_color(t.surface3))
        else:
            p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 12, 12)
        mode = QIcon.Mode.Active if hover else QIcon.Mode.Normal
        state = QIcon.State.On if checked else QIcon.State.Off
        size = self.ICON
        top = 10
        self.icon().paint(p, int((self.width() - size) / 2), top, size, size, Qt.AlignmentFlag.AlignCenter, mode, state)
        font = QFont(self.font())
        font.setPixelSize(11)
        font.setWeight(QFont.Weight.DemiBold if checked else QFont.Weight.Medium)
        p.setFont(font)
        p.setPen(_css_color(t.accent_text if checked else (t.text if hover else t.dim)))
        label = QRectF(0, top + size + 3, self.width(), self.height() - top - size - 5)
        p.drawText(label, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, self.text())

    def enterEvent(self, event) -> None:  # noqa: N802
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self.update()
        super().leaveEvent(event)


class NavRail(QWidget):
    """Drop-in replacement for the old QListWidget navigation: setCurrentRow / currentRow / currentRowChanged."""

    currentRowChanged = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("navRail")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedWidth(84)
        self._buttons: list[NavButton] = []
        self._icons: list[str] = []
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._group.idClicked.connect(self._clicked)
        logo = QLabel(alignment=Qt.AlignmentFlag.AlignCenter)
        logo.setPixmap(make_app_icon().pixmap(38, 38))
        self._top = QVBoxLayout()
        self._top.setSpacing(4)
        self._bottom = QVBoxLayout()
        self._bottom.setSpacing(4)
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 14, 8, 12)
        root.setSpacing(0)
        root.addWidget(logo)
        root.addSpacing(16)
        root.addLayout(self._top)
        root.addStretch(1)
        root.addLayout(self._bottom)
        _rails.add(self)

    def add_item(self, text: str, icon_name: str, bottom: bool = False) -> int:
        button = NavButton(text, icon_name)
        (self._bottom if bottom else self._top).addWidget(button)
        index = len(self._buttons)
        self._buttons.append(button)
        self._icons.append(icon_name)
        self._group.addButton(button, index)
        return index

    def refresh_icons(self) -> None:
        for button in self._buttons:
            button.refresh_icon()

    def _clicked(self, index: int) -> None:
        self.currentRowChanged.emit(index)

    def currentRow(self) -> int:
        return self._group.checkedId()

    def setCurrentRow(self, index: int) -> None:  # noqa: N802 - mirrors QListWidget
        if 0 <= index < len(self._buttons):
            self._buttons[index].setChecked(True)
            self.currentRowChanged.emit(index)
