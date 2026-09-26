"""PNG Info tab (like Forge's own): read a picture's generation parameters, edit them, then send the whole thing -- or just
a few of its tags -- to the Generate form, or copy a single tag."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QDragEnterEvent, QDropEvent, QGuiApplication, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView, QFileDialog, QHBoxLayout, QLabel, QListWidget, QPlainTextEdit, QPushButton, QSplitter,
    QVBoxLayout, QWidget)

from anihub.core.i18n import tr
from anihub.services.generation import parse_infotext, png_info_meta, split_infotext, split_prompt
from anihub.ui import style
from anihub.ui.grid import decode_image

IMAGE_FILTER = "PNG (*.png)"


class PngInfoView(QWidget):
    add_to_prompt = Signal(str, str)      # prompt text, negative text: appended to the Generate form's own
    replace_prompt = Signal(str, str)     # ... or written over it
    load_params = Signal(dict)            # every parsed setting (with the edited prompts) -> the Generate form

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.path: Path | None = None
        self._infotext = ""

        self.open_btn = style.secondary(QPushButton(tr("pnginfo.open")), "image")
        self.paste_btn = QPushButton(tr("pnginfo.paste"))
        self.preview = QLabel(tr("pnginfo.drop_hint"))
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setWordWrap(True)
        self.preview.setMinimumSize(240, 240)
        self.status = QLabel()
        self.status.setWordWrap(True)

        self.prompt = QPlainTextEdit()
        self.negative = QPlainTextEdit()
        self.negative.setMaximumHeight(110)
        self.params = QPlainTextEdit()
        self.params.setMaximumHeight(90)
        self.tags = QListWidget()
        self.tags.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tags.setToolTip(tr("pnginfo.tags"))
        self.copy_btn = QPushButton(tr("pnginfo.copy_tags"))
        self.tags_prompt_btn = QPushButton(tr("pnginfo.tags_to_prompt"))
        self.tags_negative_btn = QPushButton(tr("pnginfo.tags_to_negative"))
        self.insert_btn = style.secondary(QPushButton(tr("pnginfo.insert")))
        self.replace_btn = QPushButton(tr("pnginfo.replace"))
        self.send_btn = style.primary(QPushButton(tr("pnginfo.send_all")))

        left = QVBoxLayout()
        left.addWidget(self.preview, 1)
        row = QHBoxLayout()
        row.addWidget(self.open_btn)
        row.addWidget(self.paste_btn)
        left.addLayout(row)
        left_box = QWidget()
        left_box.setLayout(left)

        right = QVBoxLayout()
        right.addWidget(QLabel(tr("sd.prompt")))
        right.addWidget(self.prompt, 3)
        right.addWidget(QLabel(tr("sd.negative")))
        right.addWidget(self.negative, 1)
        right.addWidget(QLabel(tr("pnginfo.params")))
        right.addWidget(self.params)
        right.addWidget(QLabel(tr("pnginfo.tags")))
        right.addWidget(self.tags, 3)
        tag_row = QHBoxLayout()
        for w in (self.copy_btn, self.tags_prompt_btn, self.tags_negative_btn):
            tag_row.addWidget(w)
        tag_row.addStretch(1)
        right.addLayout(tag_row)
        send_row = QHBoxLayout()
        for w in (self.insert_btn, self.replace_btn, self.send_btn):
            send_row.addWidget(w)
        send_row.addStretch(1)
        right.addLayout(send_row)
        right.addWidget(self.status)
        right_box = QWidget()
        right_box.setLayout(right)

        split = QSplitter(Qt.Orientation.Horizontal)
        split.addWidget(left_box)
        split.addWidget(right_box)
        split.setStretchFactor(0, 2)
        split.setStretchFactor(1, 3)
        split.setSizes([420, 620])
        layout = QVBoxLayout(self)
        layout.addWidget(split)

        self.open_btn.clicked.connect(self._choose)
        self.paste_btn.clicked.connect(self._paste)
        self.prompt.textChanged.connect(self._refresh_tags)
        self.tags.itemDoubleClicked.connect(lambda item: self._copy([item.text()]))
        self.tags.itemSelectionChanged.connect(self._update_buttons)
        self.copy_btn.clicked.connect(lambda: self._copy(self.selected_tags()))
        self.tags_prompt_btn.clicked.connect(lambda: self._send_tags(negative=False))
        self.tags_negative_btn.clicked.connect(lambda: self._send_tags(negative=True))
        self.insert_btn.clicked.connect(self._insert)
        self.replace_btn.clicked.connect(self._replace)
        self.send_btn.clicked.connect(self._send_all)
        self._update_buttons()

    # --- loading -------------------------------------------------------------------------------------------

    def _choose(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, tr("pnginfo.open"), "", IMAGE_FILTER)
        if path:
            self.load_path(Path(path))

    def load_path(self, path: Path) -> bool:
        """Show a picture and its parameters. False (with a message) when it carries none -- the picture is still shown."""
        self.path = path
        self._show_image(path)
        meta = png_info_meta(path)
        if not meta:
            self._fill("")
            self.status.setText(tr("pnginfo.none"))
            return False
        self._fill(meta["infotext"])
        self.status.setText(tr("pnginfo.loaded_from", name=path.name))
        return True

    def load_text(self, text: str) -> bool:
        """Take a copied infotext -- or any plain prompt, which then just gets split into tags -- from text."""
        text = text.strip()
        if not text:
            return False
        self.path = None
        self.preview.setPixmap(QPixmap())
        self.preview.setText(tr("pnginfo.drop_hint"))
        self._fill(text)
        self.status.clear()
        return True

    def _paste(self) -> None:
        if not self.load_text(QGuiApplication.clipboard().text()):
            self.status.setText(tr("pnginfo.no_text"))

    def _show_image(self, path: Path) -> None:
        image = decode_image(path)
        if image.isNull():
            self.preview.setPixmap(QPixmap())
            self.preview.setText(path.name)
            return
        size = self.preview.size().expandedTo(self.preview.minimumSize())
        pm = QPixmap.fromImage(image.scaled(size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        self.preview.setPixmap(pm)

    def _fill(self, infotext: str) -> None:
        self._infotext = infotext
        prompt, negative, settings = split_infotext(infotext) if infotext else ("", "", "")
        self.prompt.setPlainText(prompt)
        self.negative.setPlainText(negative)
        self.params.setPlainText(settings)
        self._refresh_tags()

    # --- tags ----------------------------------------------------------------------------------------------

    def _refresh_tags(self) -> None:
        self.tags.clear()
        self.tags.addItems(split_prompt(self.prompt.toPlainText()))
        self._update_buttons()

    def selected_tags(self) -> list[str]:
        return [item.text() for item in self.tags.selectedItems()]

    def _copy(self, tags: list[str]) -> None:
        if not tags:
            return
        text = ", ".join(tags)
        QGuiApplication.clipboard().setText(text)
        self.status.setText(tr("pnginfo.copied", text=text if len(text) <= 80 else text[:77] + "…"))

    def _send_tags(self, negative: bool) -> None:
        text = ", ".join(self.selected_tags())
        if text:
            (self.add_to_prompt.emit("", text) if negative else self.add_to_prompt.emit(text, ""))
            self.status.setText(tr("pnginfo.added"))

    def _update_buttons(self) -> None:
        picked = bool(self.tags.selectedItems())
        for b in (self.copy_btn, self.tags_prompt_btn, self.tags_negative_btn):
            b.setEnabled(picked)
        has_text = bool(self.prompt.toPlainText().strip() or self.negative.toPlainText().strip())
        for b in (self.insert_btn, self.replace_btn, self.send_btn):
            b.setEnabled(has_text)

    # --- sending to the Generate form ------------------------------------------------------------------------

    def _texts(self) -> tuple[str, str]:
        return self.prompt.toPlainText().strip(), self.negative.toPlainText().strip()

    def _insert(self) -> None:
        self.add_to_prompt.emit(*self._texts())
        self.status.setText(tr("pnginfo.added"))

    def _replace(self) -> None:
        self.replace_prompt.emit(*self._texts())
        self.status.setText(tr("pnginfo.added"))

    def _send_all(self) -> None:
        """The settings line as it stands in the (editable) box plus the edited prompts."""
        prompt, negative = self._texts()
        text = f"{prompt}\nNegative prompt: {negative}\n{self.params.toPlainText().strip()}"
        data = parse_infotext(text)
        data["prompt"], data["negative_prompt"] = prompt, negative
        self.load_params.emit(data)
        self.status.setText(tr("pnginfo.loaded"))

    # --- drag and drop ---------------------------------------------------------------------------------------

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls() and any(u.isLocalFile() for u in event.mimeData().urls()):
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        for url in event.mimeData().urls():
            if url.isLocalFile():
                self.load_path(Path(url.toLocalFile()))
                break
