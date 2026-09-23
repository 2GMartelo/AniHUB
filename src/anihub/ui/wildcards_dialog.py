"""Editing the user's own wildcard lists (services/wildcards.py): named lists of tags, stored in config, that
`__name__` in a prompt picks a random entry from at generation time. No Forge extension involved -- the
substitution happens on the prompt text itself, before it is ever sent."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QInputDialog, QLabel, QListWidget, QListWidgetItem, QPlainTextEdit, QPushButton, QVBoxLayout,
)

from anihub.context import AppContext
from anihub.core.i18n import tr
from anihub.ui import style


class WildcardsDialog(QDialog):
    def __init__(self, ctx: AppContext, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.lists: dict[str, list[str]] = {k: list(v) for k, v in (ctx.cfg.get("wildcards", {}) or {}).items()}
        self.setWindowTitle(tr("wildcards.title"))
        self.resize(620, 440)

        hint = style.role(QLabel(tr("wildcards.hint")), "dim")
        hint.setWordWrap(True)

        self.names = QListWidget()
        self.names.setMaximumWidth(200)
        for name in sorted(self.lists):
            self.names.addItem(name)
        self.add_btn = style.ghost(QPushButton(tr("wildcards.new_list")), "plus")
        self.remove_btn = style.ghost(QPushButton(tr("wildcards.remove_list")), "trash")
        self.remove_btn.setEnabled(False)
        left_buttons = QHBoxLayout()
        left_buttons.addWidget(self.add_btn)
        left_buttons.addWidget(self.remove_btn)
        left = QVBoxLayout()
        left.addWidget(self.names, 1)
        left.addLayout(left_buttons)

        self.entries = QPlainTextEdit(placeholderText=tr("wildcards.entries_hint"))
        self.entries.setEnabled(False)
        right = QVBoxLayout()
        right.addWidget(style.role(QLabel(tr("wildcards.entries")), "h2"))
        right.addWidget(self.entries, 1)

        body = QHBoxLayout()
        body.addLayout(left)
        body.addLayout(right, 1)

        close_btn = style.primary(QPushButton(tr("forge.install.close")), "check")
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(close_btn)

        layout = QVBoxLayout(self)
        layout.addWidget(hint)
        layout.addLayout(body, 1)
        layout.addLayout(buttons)

        self.names.currentItemChanged.connect(self._select)
        self.entries.textChanged.connect(self._save_current)
        self.add_btn.clicked.connect(self._add_list)
        self.remove_btn.clicked.connect(self._remove_list)
        close_btn.clicked.connect(self.accept)

    def _select(self, current: QListWidgetItem | None, previous: QListWidgetItem | None) -> None:
        self.remove_btn.setEnabled(current is not None)
        self.entries.setEnabled(current is not None)
        self.entries.blockSignals(True)
        self.entries.setPlainText("\n".join(self.lists.get(current.text(), [])) if current else "")
        self.entries.blockSignals(False)

    def _save_current(self) -> None:
        current = self.names.currentItem()
        if current is None:
            return
        self.lists[current.text()] = [line.strip() for line in self.entries.toPlainText().splitlines() if line.strip()]
        self._persist()

    def _add_list(self) -> None:
        name, ok = QInputDialog.getText(self, tr("wildcards.new_list"), tr("wildcards.list_name"))
        name = name.strip()
        if not (ok and name) or name in self.lists:
            return
        self.lists[name] = []
        item = QListWidgetItem(name)
        self.names.addItem(item)
        self.names.setCurrentItem(item)
        self._persist()

    def _remove_list(self) -> None:
        current = self.names.currentItem()
        if current is None:
            return
        self.lists.pop(current.text(), None)
        self.names.takeItem(self.names.row(current))
        self._persist()

    def _persist(self) -> None:
        """Saved as it is edited (not only on close), so nothing is lost if the dialog is dismissed with Esc/X."""
        self.ctx.cfg.set("wildcards", {k: v for k, v in self.lists.items() if v})
