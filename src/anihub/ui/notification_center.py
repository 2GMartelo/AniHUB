"""In-app notification center (bell button + history panel + toast popups) -- replaces main_window.py's ad hoc
QSystemTrayIcon.showMessage() calls as the *primary* way to notice a background event; the OS tray balloon is now
only used as a fallback while the window itself is hidden (see MainWindow._notify)."""
from __future__ import annotations

import time

from PySide6.QtCore import QEvent, QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QDialog, QFrame, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton, QToolButton, QVBoxLayout, QWidget,
)

from anihub.context import AppContext
from anihub.core.i18n import tr
from anihub.core.notifications import Notification
from anihub.ui import icons, style, theme

KIND_ICON = {"success": "check", "warning": "alert-triangle", "error": "zap"}


def _kind_color(kind: str) -> str:
    t = theme.current()
    return {"success": t.success, "warning": t.warning, "error": t.danger}.get(kind, t.accent_text)


class NotificationSignals(QObject):
    """The core NotificationCenter is Qt-free (like services/downloads.py); this hands its callbacks a signal."""

    posted = Signal(object)   # a fresh Notification
    changed = Signal()        # list or read-state changed -- refresh the badge/panel


class ToastHost(QObject):
    """Stacks small auto-closing popups in the top-right corner of `window` while it is visible -- the in-app
    equivalent of an OS balloon. Popups are plain QFrame children of `window` itself, not a separate top-level
    window, so no platform-specific frameless-window handling is needed."""

    MARGIN = 16
    GAP = 8
    LIFETIME_MS = 6000

    def __init__(self, window: QWidget):
        super().__init__(window)
        self.window = window
        self._toasts: list[QFrame] = []
        window.installEventFilter(self)

    def show_toast(self, item: Notification) -> None:
        frame = QFrame(self.window)
        frame.setObjectName("card")
        frame.setFixedWidth(320)
        icon = QLabel()
        icon.setPixmap(icons.pixmap(KIND_ICON.get(item.kind, "bell"), _kind_color(item.kind), 18))
        title = style.role(QLabel(item.title), "h2")
        title.setWordWrap(True)
        close_btn = QToolButton()
        style.bind_icon(close_btn, "x", "normal", 12)
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.setAutoRaise(True)
        top = QHBoxLayout()
        top.addWidget(icon)
        top.addWidget(title, 1)
        top.addWidget(close_btn)
        text = QLabel(item.text)
        text.setWordWrap(True)
        style.role(text, "dim")
        layout = QVBoxLayout(frame)
        layout.addLayout(top)
        layout.addWidget(text)
        close_btn.clicked.connect(lambda: self._dismiss(frame))
        frame.show()
        self._toasts.append(frame)
        self._relayout()
        timer = QTimer(frame)
        timer.setSingleShot(True)
        timer.timeout.connect(lambda: self._dismiss(frame))
        timer.start(self.LIFETIME_MS)

    def _dismiss(self, frame: QFrame) -> None:
        if frame not in self._toasts:
            return
        self._toasts.remove(frame)
        frame.deleteLater()
        self._relayout()

    def _relayout(self) -> None:
        y = self.MARGIN
        for frame in self._toasts:
            frame.adjustSize()
            frame.move(self.window.width() - frame.width() - self.MARGIN, y)
            frame.raise_()
            y += frame.height() + self.GAP

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        if obj is self.window and event.type() == QEvent.Type.Resize:
            self._relayout()
        return False


class NotificationsDialog(QDialog):
    def __init__(self, ctx: AppContext, signals: NotificationSignals, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.setWindowTitle(tr("notif.title"))
        self.resize(420, 480)
        self.list = QListWidget()
        self.clear_btn = style.ghost(QPushButton(tr("notif.clear")), "trash")
        layout = QVBoxLayout(self)
        layout.addWidget(self.list, 1)
        layout.addWidget(self.clear_btn)
        self.clear_btn.clicked.connect(self._clear)
        signals.changed.connect(self.refresh)
        self.refresh()

    def refresh(self) -> None:
        self.list.clear()
        items = self.ctx.notifications.all()
        if not items:
            empty = QListWidgetItem(tr("notif.empty"))
            empty.setFlags(Qt.ItemFlag.NoItemFlags)
            self.list.addItem(empty)
            return
        for n in items:
            when = time.strftime("%H:%M", time.localtime(n.when))
            self.list.addItem(QListWidgetItem(f"{when}  ·  {n.title}\n{n.text}"))

    def _clear(self) -> None:
        self.ctx.notifications.clear()


class NotificationsButton(QToolButton):
    """Status-bar bell with an unread badge; opens the history panel and marks everything read."""

    def __init__(self, ctx: AppContext, signals: NotificationSignals, parent=None):
        super().__init__(parent)
        self.ctx, self.signals = ctx, signals
        self.setObjectName("updateNotice")
        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(tr("notif.title"))
        self._dialog: NotificationsDialog | None = None
        signals.changed.connect(self.refresh)
        self.clicked.connect(self.open_panel)
        self.refresh()

    def refresh(self) -> None:
        style.bind_icon(self, "bell", "normal", 16)
        n = self.ctx.notifications.unread_count()
        self.setText(str(n) if n else "")
        self.setVisible(bool(self.ctx.notifications.all()))

    def open_panel(self) -> None:
        if self._dialog is None:
            self._dialog = NotificationsDialog(self.ctx, self.signals, self.window())
        self._dialog.refresh()
        self._dialog.show()
        self._dialog.raise_()
        self._dialog.activateWindow()
        self.ctx.notifications.mark_all_read()
