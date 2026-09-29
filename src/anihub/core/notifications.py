"""A small in-app notification history: most desktop apps/sites have one, this app only had ad hoc OS tray
balloons (QSystemTrayIcon.showMessage) scattered across ui/main_window.py before. Kept Qt-free like the other core
services (services/downloads.py's on_change/on_batch pattern): the UI layer wires a Qt signal onto on_notify/on_change
instead of this module importing PySide6 itself."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable

KINDS = ("info", "success", "warning", "error")


@dataclass
class Notification:
    id: int
    title: str
    text: str
    kind: str = "info"
    when: float = field(default_factory=time.time)
    read: bool = False


class NotificationCenter:
    """Newest first; `on_notify`/`on_change` are set by the UI layer to a Qt signal's `.emit`."""

    MAX_HISTORY = 200

    def __init__(self) -> None:
        self._items: list[Notification] = []
        self._next_id = 1
        self.on_notify: Callable[[Notification], None] | None = None
        self.on_change: Callable[[], None] | None = None

    def notify(self, title: str, text: str, kind: str = "info") -> Notification:
        item = Notification(self._next_id, title, text, kind)
        self._next_id += 1
        self._items.insert(0, item)
        del self._items[self.MAX_HISTORY:]
        if self.on_notify:
            self.on_notify(item)
        if self.on_change:
            self.on_change()
        return item

    def all(self) -> list[Notification]:
        return list(self._items)

    def unread_count(self) -> int:
        return sum(1 for n in self._items if not n.read)

    def mark_all_read(self) -> None:
        if not self.unread_count():
            return
        for n in self._items:
            n.read = True
        if self.on_change:
            self.on_change()

    def clear(self) -> None:
        if not self._items:
            return
        self._items.clear()
        if self.on_change:
            self.on_change()
