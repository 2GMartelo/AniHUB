"""Settings card: version, updates, logs."""
from __future__ import annotations

import os

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QCheckBox, QGridLayout, QGroupBox, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from anihub import __version__
from anihub.context import AppContext
from anihub.core.config import config_dir
from anihub.core.i18n import tr
from anihub.services.updater import Release
from anihub.ui import style
from anihub.ui.about_box_text import update_error_text
from anihub.ui.bugreport_dialog import BugReportDialog
from anihub.ui.update_dialog import UpdateDialog, VersionsDialog
from anihub.ui.workers import run_async


class AboutBox(QGroupBox):
    update_found = Signal(object)          # a Release: the main window shows its notice too
    tutorial_requested = Signal()

    def __init__(self, ctx: AppContext, quit_app, parent=None):
        super().__init__(tr("about.title"), parent)
        self.ctx, self.quit_app = ctx, quit_app
        self.version = QLabel(tr("about.version", v=__version__))
        self.auto = QCheckBox(tr("about.auto"), checked=bool(ctx.cfg.get("update.auto", True)))
        self.check_btn = style.secondary(QPushButton(tr("about.check")), "refresh")
        self.versions_btn = style.secondary(QPushButton(tr("update.versions")), "list")
        self.logs_btn = style.ghost(QPushButton(tr("about.logs")), "folder")
        self.report_btn = style.secondary(QPushButton(tr("bug.button")), "external")
        self.tutorial_btn = style.secondary(QPushButton(tr("tutorial.replay")), "play")
        self.status = QLabel()
        style.role(self.status, "dim")
        self.status.setWordWrap(True)
        row = QGridLayout()                                   # three per line: long translations must not squeeze the buttons
        row.setHorizontalSpacing(8)
        row.setVerticalSpacing(8)
        for i, w in enumerate((self.check_btn, self.versions_btn, self.report_btn, self.tutorial_btn, self.logs_btn)):
            w.setMinimumWidth(w.sizeHint().width())
            row.addWidget(w, i // 3, i % 3)
        row.setColumnStretch(3, 1)
        layout = QVBoxLayout(self)
        for w in (self.version, self.auto):
            layout.addWidget(w)
        layout.addLayout(row)
        layout.addWidget(self.status)
        self.auto.toggled.connect(lambda v: ctx.cfg.set("update.auto", v))
        self.check_btn.clicked.connect(self.check_now)
        self.tutorial_btn.clicked.connect(self.tutorial_requested.emit)
        self.report_btn.clicked.connect(lambda: BugReportDialog(ctx.cfg, self).exec())
        self.versions_btn.clicked.connect(lambda: VersionsDialog(ctx.updater, quit_app, self).exec())
        self.logs_btn.clicked.connect(lambda: os.startfile(config_dir() / "logs") if (config_dir() / "logs").exists() else None)

    def check_now(self) -> None:
        self.check_btn.setEnabled(False)
        self.status.setText(tr("status.loading"))

        def done(release: Release | None) -> None:
            self.check_btn.setEnabled(True)
            if release is None:
                self.status.setText(tr("about.up_to_date"))
                return
            self.status.setText(tr("update.available", new=release.version, old=__version__))
            self.update_found.emit(release)
            UpdateDialog(self.ctx.updater, release, self.quit_app, self).exec()

        run_async(lambda: self.ctx.updater.check(force=True), on_done=done,
                  on_error=lambda exc: (self.check_btn.setEnabled(True), self.status.setText(update_error_text(exc))))
