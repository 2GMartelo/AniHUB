"""Library health: integrity check, cleaning records without files, database optimisation."""
from __future__ import annotations

import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QHBoxLayout, QLabel, QMessageBox, QProgressBar, QPushButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
)

from anihub.context import AppContext
from anihub.core.i18n import tr
from anihub.services import integrity
from anihub.services.integrity import Report
from anihub.ui import style
from anihub.ui.workers import run_async


class IntegrityDialog(QDialog):
    changed = Signal()
    progress_changed = Signal(int, int)               # from the worker thread

    def __init__(self, ctx: AppContext, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.report: Report | None = None
        self._cancel = False
        self._paused = False
        self._running = False
        self.setWindowTitle(tr("integrity.title"))
        self.resize(760, 560)
        hint = QLabel(tr("integrity.hint"))
        hint.setWordWrap(True)
        style.role(hint, "dim")
        self.hashes = QCheckBox(tr("integrity.hashes"))
        self.start_btn = style.primary(QPushButton(tr("integrity.start")), "check")
        self.pause_btn = style.secondary(QPushButton(tr("integrity.pause")), "pause")
        self.pause_btn.setEnabled(False)
        self.stop_btn = style.secondary(QPushButton(tr("wizard.cancel")), "x")
        self.stop_btn.setEnabled(False)
        self.fix_btn = style.danger(QPushButton(tr("integrity.remove_missing")), "trash")
        self.fix_btn.setEnabled(False)
        self.optimize_btn = style.secondary(QPushButton(tr("integrity.optimize")), "zap")
        self.folder_btn = style.ghost(QPushButton(tr("integrity.show_orphans")), "folder")
        self.folder_btn.setEnabled(False)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels([tr("integrity.col.kind"), tr("integrity.col.path")])
        self.tree.setRootIsDecorated(False)
        self.tree.setColumnWidth(0, 170)
        row = QHBoxLayout()
        for w in (self.start_btn, self.pause_btn, self.stop_btn, self.hashes):
            row.addWidget(w)
        row.addStretch(1)
        row2 = QHBoxLayout()
        for w in (self.fix_btn, self.folder_btn, self.optimize_btn):
            row2.addWidget(w)
        row2.addStretch(1)
        layout = QVBoxLayout(self)
        layout.addWidget(hint)
        layout.addLayout(row)
        layout.addWidget(self.progress)
        layout.addWidget(self.summary)
        layout.addWidget(self.tree, 1)
        layout.addLayout(row2)
        self.progress_changed.connect(self._progress)
        self.start_btn.clicked.connect(self.start)
        self.pause_btn.clicked.connect(self._toggle_pause)
        self.stop_btn.clicked.connect(self._stop)
        self.fix_btn.clicked.connect(self._fix)
        self.optimize_btn.clicked.connect(self._optimize)
        self.folder_btn.clicked.connect(lambda: os.startfile(self.ctx.paths.arts))

    def _progress(self, done: int, total: int) -> None:
        self.progress.setRange(0, total or 1)
        self.progress.setValue(done)

    def _stop(self) -> None:
        self._cancel = True
        self.stop_btn.setEnabled(False)

    def _toggle_pause(self) -> None:
        self._paused = not self._paused
        self.pause_btn.setText(tr("integrity.resume") if self._paused else tr("integrity.pause"))

    def start(self) -> None:
        if self._running:
            return
        self._running, self._cancel, self._paused = True, False, False
        self.start_btn.setEnabled(False)
        self.pause_btn.setEnabled(True)
        self.pause_btn.setText(tr("integrity.pause"))
        self.stop_btn.setEnabled(True)
        self.fix_btn.setEnabled(False)
        self.tree.clear()
        self.summary.setText(tr("status.loading"))
        ctx, verify = self.ctx, self.hashes.isChecked()

        def work() -> Report:
            return integrity.check_library(ctx.db, ctx.paths, verify, lambda d, t: self.progress_changed.emit(d, t),
                                           lambda: self._cancel, lambda: self._paused)

        run_async(work, on_done=self._done, on_error=self._failed)

    def _failed(self, exc: Exception) -> None:
        self._running = False
        self.start_btn.setEnabled(True)
        self.pause_btn.setEnabled(False)
        self.stop_btn.setEnabled(False)
        self.summary.setText(tr("status.error", msg=str(exc)))

    def _done(self, report: Report) -> None:
        self._running = False
        self.report = report
        self.start_btn.setEnabled(True)
        self.pause_btn.setEnabled(False)
        self.stop_btn.setEnabled(False)
        self.progress.setValue(self.progress.maximum())
        names = {"missing": tr("integrity.kind.missing"), "damaged": tr("integrity.kind.damaged"), "orphan": tr("integrity.kind.orphan")}
        for p in report.problems[:2000]:
            self.tree.addTopLevelItem(QTreeWidgetItem([names[p.kind], p.path]))
        missing, damaged, orphans = len(report.of("missing")), len(report.of("damaged")), len(report.of("orphan"))
        parts = [tr("integrity.db_ok") if report.db_ok else tr("integrity.db_bad", msg=report.db_message),
                 tr("integrity.checked", n=report.checked)]
        if report.clean:
            parts.append(tr("integrity.clean"))
        else:
            parts.append(tr("integrity.found", missing=missing, damaged=damaged, orphans=orphans))
        self.summary.setText("  ·  ".join(parts))
        self.fix_btn.setEnabled(missing > 0)
        self.folder_btn.setEnabled(orphans > 0)

    def _fix(self) -> None:
        if self.report is None:
            return
        ids = [p.item_id for p in self.report.of("missing") if p.item_id is not None]
        if not ids or QMessageBox.question(self, tr("integrity.remove_missing"), tr("integrity.remove_confirm", n=len(ids))) \
                != QMessageBox.StandardButton.Yes:
            return
        n = integrity.remove_missing(self.ctx.db, ids)
        self.changed.emit()
        self.summary.setText(tr("integrity.removed", n=n))
        self.fix_btn.setEnabled(False)

    def _optimize(self) -> None:
        self.optimize_btn.setEnabled(False)
        self.summary.setText(tr("status.loading"))
        run_async(lambda: integrity.optimize(self.ctx.db),
                  on_done=lambda _r: (self.optimize_btn.setEnabled(True), self.summary.setText(tr("integrity.optimized"))),
                  on_error=lambda exc: (self.optimize_btn.setEnabled(True), self.summary.setText(tr("status.error", msg=str(exc)))))
