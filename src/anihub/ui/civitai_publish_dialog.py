"""Preparing a LoRA to publish on CivitAI.red: pick showcase pictures, detect which base model(s) they were made
with, write a starting description -- then open the site's own upload page to finish there.

CivitAI has no upload API at all (only reads: search, model/version lookup, hash lookup), so there is no "Publish"
button here that actually uploads anything -- the real submission always happens on their own web form. This dialog
only gets everything ready for that: the description is copied to the clipboard, the pictures' folder is opened
so they're one drag-and-drop away, and the detected models are shown so you know which ones to link."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QUrl, Qt
from PySide6.QtGui import QDesktopServices, QGuiApplication, QPixmap
from PySide6.QtWidgets import (
    QDialog, QFileDialog, QFrame, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from anihub.context import AppContext
from anihub.core.i18n import tr
from anihub.services import civitai
from anihub.services import lora as lo
from anihub.services.generation import model_hash_of
from anihub.services.lora import Lora
from anihub.ui import style
from anihub.ui.prompt_builder import IMAGE_FILTER, placeholder_pixmap
from anihub.ui.workers import run_async

THUMB = 120
UPLOAD_URL = f"{civitai.SITE}/models/create"


class ArtRow(QFrame):
    """One showcase picture: thumbnail, file name, and (once resolved) the base model CivitAI says made it."""

    def __init__(self, path: Path):
        super().__init__()
        self.setObjectName("card")
        self.path = path
        thumb = QLabel()
        thumb.setObjectName("thumbHolder")
        thumb.setFixedSize(THUMB, THUMB)
        pm = QPixmap(str(path))
        thumb.setPixmap((pm if not pm.isNull() else placeholder_pixmap(path.name, THUMB)).scaled(
            THUMB, THUMB, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation))
        name = style.role(QLabel(path.name), "dim")
        name.setWordWrap(True)
        name.setFixedWidth(THUMB)
        self.remove_btn = style.ghost(QPushButton(tr("lt.remove_image")), "trash")
        self.model_label = style.role(QLabel(tr("civpub.detecting")), "dim")
        self.model_label.setWordWrap(True)
        self.model_label.setFixedWidth(THUMB)

        left = QVBoxLayout()
        left.addWidget(thumb, 0, Qt.AlignmentFlag.AlignHCenter)
        left.addWidget(name)
        left.addWidget(self.model_label)
        left.addWidget(self.remove_btn)
        row = QHBoxLayout(self)
        row.addLayout(left)

    def set_model(self, match: civitai.HashMatch | None) -> None:
        if match is None:
            self.model_label.setText(tr("civpub.model_unknown"))
            return
        text = match.model_name or match.version_name or "?"
        self.model_label.setText(f'<a href="{match.page_url}">{text}</a>')
        self.model_label.setOpenExternalLinks(True)
        self.model_label.setTextFormat(Qt.TextFormat.RichText)


class CivitPublishDialog(QDialog):
    """`lora` is the file being prepared for publishing; nothing here ever touches the file itself."""

    def __init__(self, ctx: AppContext, lora: Lora, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.lora = lora
        self.rows: list[ArtRow] = []
        self.setWindowTitle(tr("civpub.title", name=lora.name))
        self.resize(760, 640)

        intro = style.role(QLabel(tr("civpub.intro")), "dim")
        intro.setWordWrap(True)

        self.add_btn = style.primary(QPushButton(tr("civpub.add_pictures")), "upload")
        self.add_btn.clicked.connect(self._add_pictures)

        self.rows_area = QWidget()
        self.rows_layout = QHBoxLayout(self.rows_area)
        self.rows_layout.addStretch(1)
        rows_scroll = QScrollArea()
        rows_scroll.setWidgetResizable(True)
        rows_scroll.setFrameShape(QFrame.Shape.NoFrame)
        rows_scroll.setFixedHeight(THUMB + 90)
        rows_scroll.setWidget(self.rows_area)

        self.description = QPlainTextEdit(lo.default_description(lora))
        self.description.setMinimumHeight(160)

        self.copy_open_btn = style.primary(QPushButton(tr("civpub.copy_and_open")), "external")
        self.copy_open_btn.clicked.connect(self._copy_and_open)
        self.open_folder_btn = style.secondary(QPushButton(tr("civpub.open_folder")), "folder")
        self.open_folder_btn.clicked.connect(self._open_folder)
        self.open_folder_btn.setEnabled(False)
        self.message = style.role(QLabel(), "dim")
        self.message.setWordWrap(True)
        buttons = QHBoxLayout()
        buttons.addWidget(self.copy_open_btn)
        buttons.addWidget(self.open_folder_btn)
        buttons.addStretch(1)

        layout = QVBoxLayout(self)
        layout.addWidget(intro)
        layout.addWidget(self.add_btn, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(rows_scroll)
        layout.addWidget(style.role(QLabel(tr("civpub.description")), "h2"))
        layout.addWidget(self.description, 1)
        layout.addLayout(buttons)
        layout.addWidget(self.message)

    # --- showcase pictures -------------------------------------------------------------------------------------

    def _add_pictures(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(self, tr("civpub.add_pictures"), "", IMAGE_FILTER)
        existing = {row.path for row in self.rows}
        for f in files:
            path = Path(f)
            if path in existing:
                continue
            row = ArtRow(path)
            row.remove_btn.clicked.connect(lambda _=False, r=row: self._remove_row(r))
            self.rows.append(row)
            self.rows_layout.insertWidget(self.rows_layout.count() - 1, row)
            self._detect_model(row)
        self.open_folder_btn.setEnabled(bool(self.rows))

    def _remove_row(self, row: ArtRow) -> None:
        if row in self.rows:
            self.rows.remove(row)
            row.hide()
            row.setParent(None)
            row.deleteLater()
        self.open_folder_btn.setEnabled(bool(self.rows))

    def _detect_model(self, row: ArtRow) -> None:
        model_hash = model_hash_of(row.path)
        if not model_hash:
            row.set_model(None)
            return

        def done(match: civitai.HashMatch | None) -> None:
            if row in self.rows:
                row.set_model(match)

        def failed(_exc: Exception) -> None:
            if row in self.rows:
                row.set_model(None)

        run_async(lambda: civitai.find_by_hash(self.ctx.http, model_hash, self.ctx.cfg.get("civitai.token") or ""),
                  on_done=done, on_error=failed)

    # --- finishing on the real site -----------------------------------------------------------------------------

    def _copy_and_open(self) -> None:
        QGuiApplication.clipboard().setText(self.description.toPlainText())
        QDesktopServices.openUrl(QUrl(UPLOAD_URL))
        if self.rows:
            self._open_folder()
        self.message.setText(tr("civpub.done"))

    def _open_folder(self) -> None:
        if self.rows:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.rows[0].path.parent)))
