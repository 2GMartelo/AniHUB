"""Downloads window and the status-bar button (раздел 14)."""
from __future__ import annotations

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QDialog, QDoubleSpinBox, QHBoxLayout, QLabel, QPushButton, QSpinBox, QToolButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
)

from anihub.context import AppContext
from anihub.core.i18n import tr
from anihub.services.downloads import CANCELLED, DONE, DUPLICATE, FAILED, QUEUED, RUNNING, BatchResult
from anihub.ui import style


class DownloadSignals(QObject):
    """The manager calls back from worker threads; emitting a signal hands the news over to the GUI thread."""

    changed = Signal()
    batch = Signal(object)                    # a BatchResult


STATE_ICON = {QUEUED: "…", RUNNING: "↓", DONE: "✓", DUPLICATE: "=", FAILED: "✕", CANCELLED: "–"}


def summary_text(counts: dict[str, int]) -> str:
    parts = [(tr("dl.saved", n=counts.get(DONE, 0)), counts.get(DONE)), (tr("dl.duplicates", n=counts.get(DUPLICATE, 0)), counts.get(DUPLICATE)),
             (tr("dl.failed_n", n=counts.get(FAILED, 0)), counts.get(FAILED)), (tr("dl.cancelled_n", n=counts.get(CANCELLED, 0)), counts.get(CANCELLED))]
    return ", ".join(text for text, n in parts if n) or tr("dl.nothing")


class DownloadsDialog(QDialog):
    def __init__(self, ctx: AppContext, signals: DownloadSignals, parent=None):
        super().__init__(parent)
        self.ctx, self.manager = ctx, ctx.downloads
        self.setWindowTitle(tr("dl.title"))
        self.resize(760, 520)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels([tr("dl.col.title"), tr("dl.col.status"), tr("dl.col.info")])
        self.tree.setRootIsDecorated(False)
        self.tree.setColumnWidth(0, 340)
        self.tree.setColumnWidth(1, 120)
        self.tree.setSelectionMode(QTreeWidget.SelectionMode.ExtendedSelection)
        self.pause_btn = style.secondary(QPushButton(tr("dl.pause")), "pause")
        self.cancel_btn = style.secondary(QPushButton(tr("dl.cancel_selected")), "x")
        self.cancel_all_btn = style.danger(QPushButton(tr("dl.cancel_all")), "stop")
        self.retry_btn = style.secondary(QPushButton(tr("dl.retry")), "refresh")
        self.clear_btn = style.ghost(QPushButton(tr("dl.clear")), "trash")
        self.parallel = QSpinBox(minimum=1, maximum=16, value=self.manager.parallel)
        self.speed = QDoubleSpinBox(minimum=0, maximum=1000, decimals=1, singleStep=0.5,
                                    value=float(ctx.cfg.get("network.speed_limit_mb", 0) or 0), specialValueText=tr("dl.unlimited"))
        self.speed.setSuffix(" " + tr("dl.mb_s"))
        self.summary = QLabel()
        style.role(self.summary, "dim")
        buttons = QHBoxLayout()
        for w in (self.pause_btn, self.cancel_btn, self.cancel_all_btn, self.retry_btn, self.clear_btn):
            buttons.addWidget(w)
        buttons.addStretch(1)
        limits = QHBoxLayout()
        limits.addWidget(QLabel(tr("dl.parallel")))
        limits.addWidget(self.parallel)
        limits.addSpacing(16)
        limits.addWidget(QLabel(tr("dl.speed")))
        limits.addWidget(self.speed)
        limits.addStretch(1)
        layout = QVBoxLayout(self)
        layout.addLayout(buttons)
        layout.addWidget(self.tree, 1)
        layout.addWidget(self.summary)
        layout.addLayout(limits)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.refresh)
        signals.changed.connect(lambda: self._timer.start(250))         # many small changes -> one redraw
        self.pause_btn.clicked.connect(self._toggle_pause)
        self.cancel_btn.clicked.connect(self._cancel_selected)
        self.cancel_all_btn.clicked.connect(lambda: self.manager.cancel(abort_running=True))
        self.retry_btn.clicked.connect(self.manager.retry_failed)
        self.clear_btn.clicked.connect(self.manager.clear_finished)
        self.parallel.valueChanged.connect(self._set_parallel)
        self.speed.valueChanged.connect(lambda v: ctx.cfg.set("network.speed_limit_mb", float(v)))
        self.refresh()

    def _toggle_pause(self) -> None:
        self.manager.resume() if self.manager.paused else self.manager.pause()
        self.refresh()

    def _set_parallel(self, value: int) -> None:
        self.ctx.cfg.set("downloads.parallel", value)
        self.manager._ensure_workers()

    def _cancel_selected(self) -> None:
        ids = {it.data(0, Qt.ItemDataRole.UserRole) for it in self.tree.selectedItems()}
        if ids:
            self.manager.cancel(ids)

    def refresh(self) -> None:
        selected = {it.data(0, Qt.ItemDataRole.UserRole) for it in self.tree.selectedItems()}
        self.tree.setUpdatesEnabled(False)
        self.tree.clear()
        jobs = self.manager.jobs()
        for job in jobs[-500:]:                                          # a huge history is not worth drawing
            item = QTreeWidgetItem([job.title, f"{STATE_ICON[job.status]} {tr('dl.st.' + job.status)}",
                                    job.error[:120] if job.status == FAILED else (tr("dl.similar_n", n=job.similar) if job.similar else "")])
            item.setData(0, Qt.ItemDataRole.UserRole, job.id)
            self.tree.addTopLevelItem(item)
            item.setSelected(job.id in selected)
        self.tree.setUpdatesEnabled(True)
        counts = self.manager.counts()
        self.summary.setText(tr("dl.summary", active=counts.get(QUEUED, 0) + counts.get(RUNNING, 0), running=counts.get(RUNNING, 0),
                                done=counts.get(DONE, 0), dup=counts.get(DUPLICATE, 0), failed=counts.get(FAILED, 0)))
        paused = self.manager.paused
        self.pause_btn.setText(tr("dl.resume") if paused else tr("dl.pause"))
        style.bind_icon(self.pause_btn, "play" if paused else "pause", "normal", 18)
        self.retry_btn.setEnabled(bool(counts.get(FAILED)))


class DownloadsButton(QToolButton):
    """Status-bar button: shows the number of active downloads and opens the window."""

    def __init__(self, ctx: AppContext, signals: DownloadSignals, parent=None):
        super().__init__(parent)
        self.ctx, self.signals = ctx, signals
        self.setObjectName("updateNotice")
        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._dialog: DownloadsDialog | None = None
        signals.changed.connect(self.refresh)
        self.clicked.connect(self.open_window)
        self.hide()

    def refresh(self) -> None:
        counts = self.ctx.downloads.counts()
        active = counts.get(QUEUED, 0) + counts.get(RUNNING, 0)
        if not counts:
            self.hide()
            return
        style.bind_icon(self, "download", "accent", 16)
        label = tr("dl.button_active", n=active) if active else tr("dl.button_idle")
        self.setText(label + (" ⏸" if self.ctx.downloads.paused else ""))
        self.show()

    def open_window(self) -> None:
        if self._dialog is None:
            self._dialog = DownloadsDialog(self.ctx, self.signals, self.window())
        self._dialog.refresh()
        self._dialog.show()
        self._dialog.raise_()
        self._dialog.activateWindow()


def notify_text(result: BatchResult) -> str:
    return tr("dl.batch_done", n=result.total, details=summary_text(result.counts))
