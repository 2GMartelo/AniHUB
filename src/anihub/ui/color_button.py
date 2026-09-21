"""A button that shows a colour and opens the colour dialog."""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QColorDialog, QPushButton


class ColorButton(QPushButton):
    changed = Signal(str)

    def __init__(self, label: str, color: str, parent=None):
        super().__init__(label, parent)
        self.label, self.color = label, color
        self.clicked.connect(self._pick)
        self._paint()

    def set_color(self, color: str) -> None:
        self.color = color
        self._paint()

    def _paint(self) -> None:
        c = QColor(self.color)
        text = "#000000" if c.lightnessF() > 0.55 else "#ffffff"                  # the label stays readable on any colour
        self.setStyleSheet(f"QPushButton {{ background: {self.color}; color: {text}; border: 2px solid rgba(128,128,128,0.55);"
                           f" border-radius: 10px; padding: 7px 16px; }} QPushButton:hover {{ border-color: {text}; }}")
        self.setToolTip(self.color)

    def _pick(self) -> None:
        chosen = QColorDialog.getColor(QColor(self.color), self, self.label)
        if chosen.isValid():
            self.color = chosen.name()
            self._paint()
            self.changed.emit(self.color)
