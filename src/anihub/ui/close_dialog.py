"""The question asked when the main window is closed: quit for good or keep running in the tray."""
from __future__ import annotations

from PySide6.QtWidgets import QCheckBox, QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from anihub.core.i18n import tr
from anihub.ui import style


class CloseDialog(QDialog):
    """`choice` is "tray", "quit" or None (cancelled); `remember` is the state of the check box."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.choice: str | None = None
        self.setWindowTitle("AniHUB")
        self.setModal(True)
        text = QLabel(tr("close.ask"))
        text.setStyleSheet("font-size: 15px; font-weight: 600;")
        text.setWordWrap(True)
        info = style.role(QLabel(tr("close.info")), "dim")
        info.setWordWrap(True)
        self.remember_box = QCheckBox(tr("close.remember"))
        self.tray_btn = style.primary(QPushButton(tr("close.tray")), "download")
        self.quit_btn = style.secondary(QPushButton(tr("close.quit")), "x")
        self.cancel_btn = style.ghost(QPushButton(tr("close.cancel")), "chevron-left")
        for b in (self.tray_btn, self.quit_btn, self.cancel_btn):
            b.setMinimumHeight(38)
            b.setMinimumWidth(b.sizeHint().width() + 8)                # never narrower than its own text
        self.tray_btn.setDefault(True)
        body = QVBoxLayout()
        body.setSpacing(8)
        for w in (text, info, self.remember_box):
            body.addWidget(w)
        buttons = QHBoxLayout()
        buttons.setSpacing(10)
        buttons.addStretch(1)
        for b in (self.tray_btn, self.quit_btn, self.cancel_btn):
            buttons.addWidget(b)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(18)
        layout.addLayout(body)
        layout.addLayout(buttons)
        self.tray_btn.clicked.connect(lambda: self._done("tray"))
        self.quit_btn.clicked.connect(lambda: self._done("quit"))
        self.cancel_btn.clicked.connect(self.reject)
        self.setMinimumWidth(560)
        self.adjustSize()

    @property
    def remember(self) -> bool:
        return self.remember_box.isChecked()

    def _done(self, choice: str) -> None:
        self.choice = choice
        self.accept()
