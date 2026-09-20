"""Tag autocomplete for search boxes and tag editors (ТЗ 6.9)."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtWidgets import QCompleter, QLineEdit

from anihub.core.db import Database

NAME_ROLE = Qt.ItemDataRole.UserRole


def split_last_token(text: str) -> tuple[str, str, str]:
    """'cat -bl' -> ('cat ', '-', 'bl'): text before the last word, its '-' prefix, the word itself."""
    head, sep, tail = text.rpartition(" ")
    head = head + sep
    minus = "-" if tail.startswith("-") else ""
    return head, minus, tail[len(minus):]


class TagCompleter(QCompleter):
    """Completes the LAST word of a multi-tag line from the database, keeping '-' prefixes.

    `multi=False` turns it into a single-tag completer (tag editors, hierarchy forms).
    """

    def __init__(self, db: Database, line_edit: QLineEdit, multi: bool = True, limit: int = 15):
        super().__init__(line_edit)
        self.db, self.multi, self.limit = db, multi, limit
        self._model = QStandardItemModel(self)
        self.setModel(self._model)
        self.setWidget(line_edit)
        self.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        self.setFilterMode(Qt.MatchFlag.MatchContains)  # suggestions already match; keep substring hits visible
        self.setMaxVisibleItems(12)
        line_edit.setCompleter(self)
        line_edit.textEdited.connect(self._refresh)

    def _parts(self, text: str) -> tuple[str, str, str]:
        return split_last_token(text) if self.multi else ("", "", text.strip())

    def _refresh(self, text: str) -> None:
        _, _, token = self._parts(text)
        self._model.clear()
        if not token:
            return
        for name, category, count in self.db.suggest_tags(token, self.limit):
            item = QStandardItem(f"{name}  ({count})" if count else name)
            item.setData(name, NAME_ROLE)
            self._model.appendRow(item)

    def splitPath(self, path: str) -> list[str]:  # what the popup filters on
        return [self._parts(path)[2]]

    def pathFromIndex(self, index) -> str:  # the text the line edit gets after choosing a suggestion
        name = index.data(NAME_ROLE) or index.data()
        head, minus, _ = self._parts(self.widget().text())
        return f"{head}{minus}{name} " if self.multi else name


def tag_line_edit(db: Database, placeholder: str = "", multi: bool = True) -> QLineEdit:
    edit = QLineEdit(placeholderText=placeholder)
    edit.tag_completer = TagCompleter(db, edit, multi=multi)  # keep a reference alive
    return edit
