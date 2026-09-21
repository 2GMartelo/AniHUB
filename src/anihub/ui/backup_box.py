"""Settings card: backups of the library database (п. 6.16)."""
from __future__ import annotations

import os
import time
from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QMessageBox, QPushButton, QSpinBox, QVBoxLayout,
)

from anihub.context import AppContext
from anihub.core.i18n import tr
from anihub.services import backup
from anihub.ui import style
from anihub.ui.workers import run_async


class BackupBox(QGroupBox):
    def __init__(self, ctx: AppContext, parent=None):
        super().__init__(tr("backup.title"), parent)
        self.ctx = ctx
        cfg = ctx.cfg
        self.auto = QCheckBox(tr("backup.auto"), checked=bool(cfg.get("backup.auto", True)))
        self.include = QCheckBox(tr("backup.include_config"), checked=bool(cfg.get("backup.include_config", True)))
        self.interval = QSpinBox(minimum=1, maximum=365, value=int(cfg.get("backup.interval_days", 7)))
        self.keep = QSpinBox(minimum=1, maximum=100, value=int(cfg.get("backup.keep", 5)))
        self.now_btn = style.secondary(QPushButton(tr("backup.now")), "save")
        self.restore_btn = style.secondary(QPushButton(tr("backup.restore")), "upload")
        self.cancel_btn = style.ghost(QPushButton(tr("backup.cancel_restore")), "x")
        self.folder_btn = style.ghost(QPushButton(tr("backup.folder")), "folder")
        self.status = QLabel()
        style.role(self.status, "dim")
        self.status.setWordWrap(True)
        form = QFormLayout()
        form.addRow(tr("backup.interval"), self.interval)
        form.addRow(tr("backup.keep"), self.keep)
        row = QHBoxLayout()
        for w in (self.now_btn, self.restore_btn, self.cancel_btn, self.folder_btn):
            row.addWidget(w)
        row.addStretch(1)
        layout = QVBoxLayout(self)
        for w in (self.auto, self.include):
            layout.addWidget(w)
        layout.addLayout(form)
        layout.addLayout(row)
        layout.addWidget(self.status)
        self.auto.toggled.connect(lambda v: cfg.set("backup.auto", v))
        self.include.toggled.connect(lambda v: cfg.set("backup.include_config", v))
        self.interval.valueChanged.connect(lambda v: cfg.set("backup.interval_days", v))
        self.keep.valueChanged.connect(lambda v: cfg.set("backup.keep", v))
        self.now_btn.clicked.connect(self.backup_now)
        self.restore_btn.clicked.connect(self.restore)
        self.cancel_btn.clicked.connect(self._cancel_restore)
        self.folder_btn.clicked.connect(self._open_folder)
        self._refresh()

    def _refresh(self) -> None:
        pending = backup.pending_restore(self.ctx.paths) is not None
        self.cancel_btn.setVisible(pending)
        backups = backup.list_backups(self.ctx.paths)
        if pending:
            self.status.setText(tr("backup.pending"))
        elif backups:
            self.status.setText(tr("backup.last", when=backups[0].label, n=len(backups)))
        else:
            self.status.setText(tr("backup.none"))

    def backup_now(self) -> None:
        self.now_btn.setEnabled(False)
        self.status.setText(tr("status.loading"))
        ctx = self.ctx

        def work():
            path = backup.create_backup(ctx.paths, ctx.cfg, bool(ctx.cfg.get("backup.include_config", True)))
            ctx.cfg.set("backup.last", time.time())
            backup.prune(ctx.paths, int(ctx.cfg.get("backup.keep", 5)))
            return path

        def done(path) -> None:
            self.now_btn.setEnabled(True)
            self._refresh()
            self.status.setText(tr("backup.created", name=path.name))

        run_async(work, on_done=done, on_error=lambda exc: (self.now_btn.setEnabled(True), self.status.setText(tr("status.error", msg=str(exc)))))

    def restore(self) -> None:
        folder = backup.backup_dir(self.ctx.paths)
        folder.mkdir(parents=True, exist_ok=True)
        path, _ = QFileDialog.getOpenFileName(self, tr("backup.restore"), str(folder), "AniHUB backup (*.zip)")
        if not path:
            return
        try:
            items = backup.stage_restore(self.ctx.paths, Path(path))
        except backup.BackupError as exc:
            QMessageBox.warning(self, tr("backup.restore"), str(exc))
            return
        self._refresh()
        QMessageBox.information(self, tr("backup.restore"), tr("backup.staged", n=items))

    def _cancel_restore(self) -> None:
        backup.cancel_restore(self.ctx.paths)
        self._refresh()

    def _open_folder(self) -> None:
        folder = backup.backup_dir(self.ctx.paths)
        folder.mkdir(parents=True, exist_ok=True)
        os.startfile(folder)
