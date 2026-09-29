"""A tiny app-level undo/redo stack (Ctrl+Z/Ctrl+Y is standard in almost every app) for library edits -- trash and
restore, the one action users actually want a safety net for. Not a generic QUndoStack/QUndoCommand machinery: each
entry is just a label plus two callables the caller already has everything needed to build, since every mutation
here is one `LibraryService` call, not worth wrapping in command classes."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass
class UndoEntry:
    label: str
    undo: Callable[[], None]
    redo: Callable[[], None]


class UndoStack:
    MAX = 50

    def __init__(self) -> None:
        self._undo: list[UndoEntry] = []
        self._redo: list[UndoEntry] = []
        self.on_change: Callable[[], None] | None = None

    def push(self, label: str, undo: Callable[[], None], redo: Callable[[], None]) -> None:
        """Call once the action has already happened; `redo()` is only used to re-apply it later."""
        self._undo.append(UndoEntry(label, undo, redo))
        if len(self._undo) > self.MAX:
            del self._undo[0]
        self._redo.clear()
        self._changed()

    def can_undo(self) -> bool:
        return bool(self._undo)

    def can_redo(self) -> bool:
        return bool(self._redo)

    def undo(self) -> str | None:
        if not self._undo:
            return None
        entry = self._undo.pop()
        entry.undo()
        self._redo.append(entry)
        self._changed()
        return entry.label

    def redo(self) -> str | None:
        if not self._redo:
            return None
        entry = self._redo.pop()
        entry.redo()
        self._undo.append(entry)
        self._changed()
        return entry.label

    def _changed(self) -> None:
        if self.on_change:
            self.on_change()
