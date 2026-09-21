"""'Report a problem': shows exactly what would be shared, lets the user edit it, copy it or open a prefilled GitHub issue."""
from __future__ import annotations

import os

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import QCheckBox, QDialog, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QVBoxLayout

from anihub.core.config import config_dir
from anihub.core.i18n import tr
from anihub.services import bugreport
from anihub.services.updater import DEFAULT_REPO
from anihub.ui import style


class BugReportDialog(QDialog):
    def __init__(self, cfg, parent=None, description: str = ""):
        super().__init__(parent)
        self.cfg = cfg
        self.setWindowTitle(tr("bug.title"))
        self.resize(760, 620)
        intro = QLabel(tr("bug.intro"))
        intro.setWordWrap(True)
        style.role(intro, "dim")
        self.description = QPlainTextEdit(description, placeholderText=tr("bug.describe"))
        self.description.setMaximumHeight(110)
        self.include_log = QCheckBox(tr("bug.include_log"), checked=True)
        self.preview = QPlainTextEdit()
        self.copy_btn = style.secondary(QPushButton(tr("bug.copy")), "copy")
        self.issue_btn = style.primary(QPushButton(tr("bug.open_issue")), "external")
        self.logs_btn = style.ghost(QPushButton(tr("about.logs")), "folder")
        self.message = QLabel()
        style.role(self.message, "dim")
        row = QHBoxLayout()
        for w in (self.copy_btn, self.issue_btn, self.logs_btn):
            row.addWidget(w)
        row.addStretch(1)
        layout = QVBoxLayout(self)
        layout.addWidget(intro)
        layout.addWidget(self.description)
        layout.addWidget(self.include_log)
        layout.addWidget(QLabel(tr("bug.preview")))
        layout.addWidget(self.preview, 1)
        layout.addLayout(row)
        layout.addWidget(self.message)
        self.description.textChanged.connect(self.rebuild)
        self.include_log.toggled.connect(self.rebuild)
        self.copy_btn.clicked.connect(self.copy)
        self.issue_btn.clicked.connect(self.open_issue)
        self.logs_btn.clicked.connect(lambda: os.startfile(config_dir() / "logs") if (config_dir() / "logs").exists() else None)
        self.rebuild()

    def rebuild(self) -> None:
        """The preview is the report; if the user edits it, the edit is what gets copied (rebuilt only on option changes)."""
        self.preview.setPlainText(bugreport.build_report(self.description.toPlainText(), self.include_log.isChecked()))

    def report_text(self) -> str:
        return self.preview.toPlainText()

    def copy(self) -> None:
        QGuiApplication.clipboard().setText(self.report_text())
        self.message.setText(tr("bug.copied"))

    def open_issue(self) -> None:
        self.copy()
        title = (self.description.toPlainText().strip().splitlines() or [tr("bug.default_title")])[0][:80]
        repo = str(self.cfg.get("update.repo", DEFAULT_REPO) or DEFAULT_REPO)
        QDesktopServices.openUrl(QUrl(bugreport.issue_url(repo, title, self.report_text())))
        self.message.setText(tr("bug.opened"))
