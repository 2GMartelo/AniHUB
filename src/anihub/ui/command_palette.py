"""Command palette (раздел 8, Ctrl+K): one box to jump to a section, run an action or find something in the library."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem, QVBoxLayout

from anihub.core.i18n import tr

MAX_RESULTS = 40


@dataclass
class Entry:
    title: str
    action: Callable[[], None]
    category: str = ""            # shown dimmed on the right: "Section", "Action", "Tag"...
    keywords: str = ""            # extra words the query may match (not shown)


def score(query: str, text: str) -> int:
    """0 = no match. Every word of the query must occur in the text; earlier / word-start / exact matches score higher."""
    words = query.lower().split()
    if not words:
        return 1
    low = text.lower()
    total = 0
    for word in words:
        pos = low.find(word)
        if pos < 0:
            return 0
        total += 10
        if pos == 0:
            total += 8
        elif low[pos - 1] in " _-:/.":
            total += 5                              # a word of the title starts here
        total += max(0, 4 - pos // 8)               # earlier is slightly better
    if low == query.lower().strip():
        total += 20
    return total


def rank(query: str, entries: list[Entry], limit: int = MAX_RESULTS) -> list[Entry]:
    scored = []
    for i, entry in enumerate(entries):
        s = score(query, f"{entry.title} {entry.keywords}") if query.strip() else 1
        if s:
            scored.append((-s, i, entry))                # ties keep the provider's order
    scored.sort(key=lambda t: (t[0], t[1]))
    return [e for _, _, e in scored[:limit]]


class CommandPalette(QDialog):
    """`providers`: functions query -> entries. Static commands ignore the query; dynamic ones (library search) use it."""

    def __init__(self, providers: list[Callable[[str], list[Entry]]], parent=None):
        super().__init__(parent, Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.providers = providers
        self.setModal(True)
        self.setObjectName("palette")
        self.resize(640, 420)
        self.edit = QLineEdit(placeholderText=tr("palette.placeholder"))
        self.list = QListWidget()
        self.list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.hint = QLabel(tr("palette.hint"))
        self.hint.setProperty("role", "muted")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 8)
        layout.addWidget(self.edit)
        layout.addWidget(self.list, 1)
        layout.addWidget(self.hint)
        self.edit.textChanged.connect(self.refresh)
        self.edit.returnPressed.connect(self.run_current)
        self.list.itemClicked.connect(lambda _i: self.run_current())
        self.refresh("")

    def refresh(self, text: str = "") -> None:
        text = self.edit.text()
        entries: list[Entry] = []
        for provider in self.providers:
            try:
                entries.extend(provider(text))
            except Exception:  # noqa: BLE001 - one broken provider must not break the palette
                continue
        self.list.clear()
        for entry in rank(text, entries):
            item = QListWidgetItem(entry.title + (f"    —  {entry.category}" if entry.category else ""))
            item.setData(Qt.ItemDataRole.UserRole, entry)
            self.list.addItem(item)
        if self.list.count():
            self.list.setCurrentRow(0)

    def current_entry(self) -> Entry | None:
        item = self.list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def run_current(self) -> None:
        entry = self.current_entry()
        if entry is None:
            return
        self.accept()
        entry.action()

    def keyPressEvent(self, e: QKeyEvent) -> None:  # noqa: N802
        k = e.key()
        if k in (Qt.Key.Key_Down, Qt.Key.Key_Up):
            step = 1 if k == Qt.Key.Key_Down else -1
            self.list.setCurrentRow(max(0, min(self.list.currentRow() + step, self.list.count() - 1)))
        elif k == Qt.Key.Key_Escape:
            self.reject()
        else:
            super().keyPressEvent(e)
