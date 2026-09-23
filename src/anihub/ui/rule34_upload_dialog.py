"""Preparing one picture to post on rule34.xxx: run the autotagger, let the person add/remove tags, then open the
site's own upload page to finish there.

rule34.xxx has no upload API (only reads: search, post lookup, tag lookup -- see sources/rule34.py), so there is no
"Upload" button here that actually posts anything -- the real submission always happens on their own web form. This
dialog only gets everything ready for that: the tags are copied to the clipboard and the picture's folder is opened
so it is one file-picker click away."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QUrl, Qt
from PySide6.QtGui import QDesktopServices, QGuiApplication, QPixmap
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget

from anihub.context import AppContext
from anihub.core.i18n import tr
from anihub.ui import style
from anihub.ui.lora_train_page import TagChip
from anihub.ui.manga_filters import FlowLayout
from anihub.ui.prompt_builder import placeholder_pixmap
from anihub.ui.workers import run_async

PREVIEW = 220
UPLOAD_URL = "https://rule34.xxx/index.php?page=post&s=add"


class Rule34UploadDialog(QDialog):
    """`path` is the picture being prepared for upload; nothing here ever touches the file itself."""

    def __init__(self, ctx: AppContext, path: Path, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.path = path
        self.tags: list[str] = []
        self.setWindowTitle(tr("rule34.title", name=path.stem))
        self.resize(620, 560)

        intro = style.role(QLabel(tr("rule34.intro")), "dim")
        intro.setWordWrap(True)

        preview = QLabel()
        preview.setFixedSize(PREVIEW, PREVIEW)
        pm = QPixmap(str(path))
        preview.setPixmap((pm if not pm.isNull() else placeholder_pixmap(path.name, PREVIEW)).scaled(
            PREVIEW, PREVIEW, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))

        self.rating_label = style.role(QLabel(tr("rule34.detecting")), "dim")
        self.rating_label.setWordWrap(True)

        self.chip_area = QWidget()
        self.flow = FlowLayout(self.chip_area, spacing=6)
        self.add_line = QLineEdit(placeholderText=tr("lt.add_tag"))
        self.add_line.setClearButtonEnabled(True)
        self.add_line.returnPressed.connect(self._add_tag_from_line)

        self.copy_open_btn = style.primary(QPushButton(tr("rule34.copy_and_open")), "external")
        self.copy_open_btn.clicked.connect(self._copy_and_open)
        self.open_folder_btn = style.secondary(QPushButton(tr("rule34.open_folder")), "folder")
        self.open_folder_btn.clicked.connect(self._open_folder)
        self.message = style.role(QLabel(), "dim")
        self.message.setWordWrap(True)
        buttons = QHBoxLayout()
        buttons.addWidget(self.copy_open_btn)
        buttons.addWidget(self.open_folder_btn)
        buttons.addStretch(1)

        top = QHBoxLayout()
        top.addWidget(preview, 0, Qt.AlignmentFlag.AlignTop)
        side = QVBoxLayout()
        side.addWidget(self.rating_label)
        side.addStretch(1)
        top.addLayout(side, 1)

        layout = QVBoxLayout(self)
        layout.addWidget(intro)
        layout.addLayout(top)
        layout.addWidget(style.role(QLabel(tr("rule34.tags")), "h2"))
        layout.addWidget(self.chip_area, 1)
        layout.addWidget(self.add_line)
        layout.addLayout(buttons)
        layout.addWidget(self.message)

        self._detect_tags()

    # --- tags ----------------------------------------------------------------------------------------------------

    def _rebuild_chips(self) -> None:
        while self.flow.count():
            item = self.flow.takeAt(0)
            if item.widget() is not None:
                item.widget().hide()
                item.widget().setParent(None)
                item.widget().deleteLater()
        for t in self.tags:
            chip = TagChip(t)
            chip.removed.connect(self._remove_tag)
            self.flow.addWidget(chip)
        self.chip_area.updateGeometry()

    def _remove_tag(self, text: str) -> None:
        if text in self.tags:
            self.tags.remove(text)
            self._rebuild_chips()

    def _add_tag_from_line(self) -> None:
        text = self.add_line.text().strip().replace(" ", "_")
        if text and text not in self.tags:
            self.tags.append(text)
            self._rebuild_chips()
        self.add_line.clear()

    def _detect_tags(self) -> None:
        if not self.ctx.autotagger.available:
            self.rating_label.setText(tr("lt.no_autotagger"))
            return

        def done(result) -> None:
            if result is None:
                self.rating_label.setText(tr("lt.no_autotagger"))
                return
            self.tags = [name for name, _cat in result.tags]
            self._rebuild_chips()
            self.rating_label.setText(tr("rule34.rating", rating=result.rating))

        run_async(lambda: self.ctx.autotagger.tag_file(self.path), on_done=done,
                  on_error=lambda _exc: self.rating_label.setText(tr("lt.no_autotagger")))

    # --- finishing on the real site -----------------------------------------------------------------------------

    def _copy_and_open(self) -> None:
        QGuiApplication.clipboard().setText(" ".join(self.tags))
        QDesktopServices.openUrl(QUrl(UPLOAD_URL))
        self._open_folder()
        self.message.setText(tr("rule34.done"))

    def _open_folder(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.path.parent)))
