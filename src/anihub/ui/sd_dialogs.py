"""Small SD dialogs: LoRA / embedding picker."""
from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog, QDoubleSpinBox, QHBoxLayout, QLabel, QLineEdit, QListWidget, QPushButton, QVBoxLayout,
)

from anihub.core.i18n import tr
from anihub.ui import style
from anihub.ui.workers import run_status


class InsertDialog(QDialog):
    """Pick names from a list Forge provides and insert them into the prompt (the dialog stays open for more).

    loader() -> list of (label, name) is blocking and runs in a worker; make_text(name, weight) builds the prompt text.
    """
    inserted = Signal(str)

    def __init__(self, title: str, loader: Callable[[], list[tuple[str, str]]], make_text: Callable[[str, float], str],
                 refresher: Callable[[], None] | None = None, with_weight: bool = False, parent=None):
        super().__init__(parent)
        self.loader, self.make_text, self.refresher = loader, make_text, refresher
        self.setWindowTitle(title)
        self.resize(420, 520)
        self.filter = QLineEdit(placeholderText=tr("tags.filter"))
        self.list = QListWidget()
        self.weight = QDoubleSpinBox(minimum=-2.0, maximum=2.0, singleStep=0.1, decimals=2, value=0.8)
        self.weight.setVisible(with_weight)
        self.weight_label = QLabel(tr("sd.lora_weight"))
        self.weight_label.setVisible(with_weight)
        self.insert_btn = QPushButton(tr("sd.insert"))
        self.refresh_btn = style.ghost(QPushButton(), "refresh")
        self.refresh_btn.setFixedWidth(34)
        self.refresh_btn.setVisible(refresher is not None)
        self.status = QLabel()
        top = QHBoxLayout()
        top.addWidget(self.filter, 1)
        top.addWidget(self.refresh_btn)
        bottom = QHBoxLayout()
        bottom.addWidget(self.weight_label)
        bottom.addWidget(self.weight)
        bottom.addStretch(1)
        bottom.addWidget(self.insert_btn)
        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(self.list, 1)
        layout.addLayout(bottom)
        layout.addWidget(self.status)
        self._items: list[tuple[str, str]] = []
        self.filter.textChanged.connect(self._fill)
        self.list.itemDoubleClicked.connect(lambda _i: self._insert())
        self.insert_btn.clicked.connect(self._insert)
        self.refresh_btn.clicked.connect(self._refresh)
        self.reload()

    def reload(self) -> None:
        self.status.setText(tr("status.loading"))

        def done(items: list) -> None:
            self._items = items
            self._fill()
            self.status.setText(tr("sd.insert_count", n=len(items)))

        run_status(self.loader, on_done=done, status=self.status)

    def _refresh(self) -> None:
        def work():
            self.refresher()
            return self.loader()

        self.status.setText(tr("status.loading"))
        run_status(work, on_done=lambda items: (setattr(self, "_items", items), self._fill(),
                                               self.status.setText(tr("sd.insert_count", n=len(items)))), status=self.status)

    def _fill(self) -> None:
        text = self.filter.text().lower().strip()
        self.list.clear()
        for label, name in self._items:
            if text in label.lower():
                self.list.addItem(label)
                self.list.item(self.list.count() - 1).setData(Qt.ItemDataRole.UserRole, name)

    def _insert(self) -> None:
        for item in self.list.selectedItems() or ([self.list.currentItem()] if self.list.currentItem() else []):
            self.inserted.emit(self.make_text(item.data(Qt.ItemDataRole.UserRole), self.weight.value()))
