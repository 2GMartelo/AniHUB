"""The LoRA editor: cards of the LoRA files in Forge's folder, and for the chosen one its file name, description, keywords, picture and how it
is written into a prompt. The data lives beside the model file (see services/lora.py), so Forge shows the same card."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QGuiApplication, QIcon, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDoubleSpinBox, QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QMenu, QMessageBox, QPlainTextEdit, QPushButton, QScrollArea, QSplitter, QVBoxLayout, QWidget,
)

from anihub.context import AppContext
from anihub.core.i18n import tr
from anihub.services import lora as lo
from anihub.services.lora import Lora, LoraError
from anihub.ui import style
from anihub.ui.manga_filters import FlowLayout
from anihub.ui.prompt_builder import IMAGE_FILTER, placeholder_pixmap
from anihub.ui.workers import run_async

CARD = 96
PICTURE = 230
BASES = ["", "SD 1.5", "SD 2.x", "SDXL", "Pony", "Illustrious", "NoobAI", "Flux"]


class PictureBox(QLabel):
    """The picture of the card; a picture file dropped on it becomes the new one."""
    dropped = Signal(str)

    def __init__(self):
        super().__init__(tr("lora.picture_drop"))
        self.setObjectName("loraPicture")
        self.setFixedSize(PICTURE, PICTURE)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setWordWrap(True)
        self.setAcceptDrops(True)
        self.setProperty("role", "dim")

    def show_picture(self, path: Path | None) -> None:
        pm = QPixmap(str(path)) if path else QPixmap()
        if pm.isNull():
            self.setPixmap(QPixmap())
            self.setText(tr("lora.picture_drop"))
            return
        self.setPixmap(pm.scaled(PICTURE, PICTURE, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasUrls() or event.mimeData().hasImage():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802
        urls = [u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]
        if urls:
            self.dropped.emit(urls[0])
            event.acceptProposedAction()


class LoraEditor(QWidget):
    """`hooks`: `insert(prompt: str, negative: str) -> bool` puts text into the Generate form (False = it was already there),
    `refresh()` makes a running Forge rescan its LoRA list."""

    def __init__(self, ctx: AppContext, hooks: dict | None = None, parent=None):
        super().__init__(parent)
        self.ctx, self.hooks = ctx, hooks or {}
        self.items: dict[Path, QListWidgetItem] = {}
        self.current: Lora | None = None
        self._loading = False
        self._dirty = False
        self._picture_pending: object = None          # a new picture chosen but not saved yet: Path | QImage | "clear"
        self._thumbs: list[Path] = []
        self._timer = QTimer(self, interval=15)
        self._timer.timeout.connect(self._load_thumbs)

        # --- left: the cards ---------------------------------------------------------------------------------------------------
        self.search = QLineEdit(placeholderText=tr("lora.search"))
        self.search.setClearButtonEnabled(True)
        self.folder_btn = style.ghost(QPushButton(tr("lora.folder")), "folder")
        self.reload_btn = style.ghost(QPushButton(), "refresh")
        self.reload_btn.setFixedWidth(34)
        self.grid = QListWidget()
        self.grid.setViewMode(QListWidget.ViewMode.IconMode)
        self.grid.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.grid.setMovement(QListWidget.Movement.Static)
        self.grid.setUniformItemSizes(True)
        self.grid.setIconSize(QSize(CARD, CARD))
        self.grid.setGridSize(QSize(CARD + 30, CARD + 50))
        self.grid.setSpacing(4)
        self.grid.setWordWrap(True)
        self.grid.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.status = style.role(QLabel(), "dim")
        self.status.setWordWrap(True)
        top = QHBoxLayout()
        top.addWidget(self.search, 1)
        top.addWidget(self.folder_btn)
        top.addWidget(self.reload_btn)
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.addLayout(top)
        ll.addWidget(self.grid, 1)
        ll.addWidget(self.status)

        # --- right: the editor -------------------------------------------------------------------------------------------------
        self.picture = PictureBox()
        self.pic_file = style.secondary(QPushButton(tr("lora.picture_file")), "image")
        self.pic_paste = style.ghost(QPushButton(tr("lora.picture_paste")), "copy")
        self.pic_clear = style.ghost(QPushButton(tr("lora.picture_clear")), "trash")
        pic_buttons = QWidget()
        pf = FlowLayout(pic_buttons, spacing=6)
        for b in (self.pic_file, self.pic_paste, self.pic_clear):
            pf.addWidget(b)
        self.name = QLineEdit()
        self.ext = style.role(QLabel(), "dim")
        self.where = style.role(QLabel(), "dim")
        self.where.setWordWrap(True)
        self.description = QPlainTextEdit(placeholderText=tr("lora.description"))
        self.description.setFixedHeight(84)
        self.keywords = QPlainTextEdit(placeholderText=tr("lora.keywords_hint"))
        self.keywords.setFixedHeight(70)
        self.suggest_btn = style.ghost(QPushButton(tr("lora.suggest")), "zap")
        self.weight = QDoubleSpinBox(minimum=-2.0, maximum=2.0, singleStep=0.1, decimals=2, value=0.8)
        self.base = QComboBox(editable=True)
        self.base.addItems(BASES)
        self.negative = QLineEdit(placeholderText=tr("lora.negative_hint"))
        self.template = QLineEdit(placeholderText=lo.DEFAULT_TEMPLATE)
        self.template_reset = style.ghost(QPushButton(tr("lora.template_reset")), "refresh")
        self.result = QLabel()
        self.result.setWordWrap(True)
        self.result.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.result.setObjectName("loraResult")
        self.save_btn = style.primary(QPushButton(tr("lora.save")), "check")
        self.revert_btn = style.secondary(QPushButton(tr("lora.revert")), "rotate")
        self.insert_btn = style.secondary(QPushButton(tr("lora.insert")), "plus")
        self.open_btn = style.ghost(QPushButton(tr("lora.open_folder")), "folder")
        self.message = style.role(QLabel(), "dim")
        self.message.setWordWrap(True)

        def field(text: str, widget: QWidget, hint: str = "") -> QWidget:
            box = QWidget()
            v = QVBoxLayout(box)
            v.setContentsMargins(0, 0, 0, 0)
            v.setSpacing(3)
            label = QLabel(text)
            label.setStyleSheet("font-weight: 600;")
            v.addWidget(label)
            v.addWidget(widget)
            if hint:
                note = style.role(QLabel(hint), "dim")
                note.setWordWrap(True)
                v.addWidget(note)
            return box

        name_row = QWidget()
        nr = QHBoxLayout(name_row)
        nr.setContentsMargins(0, 0, 0, 0)
        nr.addWidget(self.name, 1)
        nr.addWidget(self.ext)
        kw_row = QWidget()
        kr = QVBoxLayout(kw_row)
        kr.setContentsMargins(0, 0, 0, 0)
        kr.addWidget(self.keywords)
        kr.addWidget(self.suggest_btn, 0, Qt.AlignmentFlag.AlignLeft)
        wb = QWidget()
        wl = QHBoxLayout(wb)
        wl.setContentsMargins(0, 0, 0, 0)
        wl.addWidget(field(tr("lora.weight"), self.weight))
        wl.addWidget(field(tr("lora.base"), self.base), 1)
        tpl = QWidget()
        tl = QHBoxLayout(tpl)
        tl.setContentsMargins(0, 0, 0, 0)
        tl.addWidget(self.template, 1)
        tl.addWidget(self.template_reset)
        actions = QWidget()
        af = FlowLayout(actions, spacing=8)
        for b in (self.save_btn, self.revert_btn, self.insert_btn, self.open_btn):
            af.addWidget(b)

        self.form = QWidget()
        fl = QVBoxLayout(self.form)
        fl.setContentsMargins(0, 0, 8, 0)
        fl.setSpacing(10)
        head = QHBoxLayout()
        head.addWidget(self.picture, 0, Qt.AlignmentFlag.AlignTop)
        side = QVBoxLayout()
        side.addWidget(style.role(QLabel(tr("lora.picture")), "h2"))
        side.addWidget(pic_buttons)
        side.addWidget(self.where)
        side.addStretch(1)
        head.addLayout(side, 1)
        fl.addLayout(head)
        fl.addWidget(field(tr("lora.name"), name_row, tr("lora.name_hint")))
        fl.addWidget(field(tr("lora.description"), self.description))
        fl.addWidget(field(tr("lora.keywords"), kw_row))
        fl.addWidget(wb)
        fl.addWidget(field(tr("lora.negative"), self.negative))
        fl.addWidget(field(tr("lora.template"), tpl, tr("lora.template_hint")))
        fl.addWidget(self.result)
        fl.addWidget(actions)
        fl.addWidget(self.message)
        fl.addStretch(1)
        self.empty = style.role(QLabel(tr("lora.pick"), alignment=Qt.AlignmentFlag.AlignCenter), "dim")
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(self.form)
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.addWidget(self.empty, 1)
        rl.addWidget(scroll, 1)
        self._scroll = scroll
        split = QSplitter()
        split.addWidget(left)
        split.addWidget(right)
        split.setChildrenCollapsible(False)
        split.setStretchFactor(0, 5)
        split.setStretchFactor(1, 4)
        split.setSizes([520, 560])
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(split)

        self.search.textChanged.connect(self._apply_filter)
        self.folder_btn.clicked.connect(self._pick_folder)
        self.reload_btn.clicked.connect(self.reload)
        self.grid.currentItemChanged.connect(self._selection_changed)
        self.grid.itemDoubleClicked.connect(lambda _i: self.insert_saved())
        self.pic_file.clicked.connect(self._pick_picture)
        self.pic_paste.clicked.connect(self._paste_picture)
        self.pic_clear.clicked.connect(self._clear_picture)
        self.picture.dropped.connect(lambda p: self._set_picture(Path(p)))
        for edit in (self.name, self.negative, self.template):
            edit.textChanged.connect(self._edited)
        for edit in (self.description, self.keywords):
            edit.textChanged.connect(self._edited)
        self.weight.valueChanged.connect(self._edited)
        self.base.editTextChanged.connect(self._edited)
        self.template_reset.clicked.connect(lambda: self.template.setText(""))
        self.suggest_btn.clicked.connect(self._suggest_menu)
        self.save_btn.clicked.connect(self.save)
        self.revert_btn.clicked.connect(self._revert)
        self.insert_btn.clicked.connect(self.insert_current)
        self.open_btn.clicked.connect(self._open_folder)
        self._show_form(False)
        self.reload()

    # --- the folder and the cards ---------------------------------------------------------------------------------------------

    def root(self) -> Path:
        custom = self.ctx.cfg.get("lora.dir") or ""
        if custom:
            return Path(custom)
        forge = self.ctx.cfg.get("forge.path") or ""
        return Path(forge) / "models" / "Lora" if forge else Path()

    def _pick_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, tr("lora.folder"), str(self.root()) if self.root().is_dir() else "")
        if folder:
            self.ctx.cfg.set("lora.dir", folder.replace("/", "\\"))
            self.reload()

    def _show_form(self, on: bool) -> None:
        self._scroll.setVisible(on)
        self.empty.setVisible(not on)

    def reload(self, select: Path | None = None) -> None:
        keep = select or (self.current.path if self.current else None)
        root = self.root()
        self._timer.stop()
        self.grid.blockSignals(True)
        self.grid.clear()
        self.items.clear()
        self.grid.blockSignals(False)
        models = lo.scan(root)
        if not models:
            self.status.setText(tr("lora.no_folder", path=str(root)) if not root.is_dir() else tr("lora.count", n=0))
        else:
            self.status.setText(tr("lora.count", n=len(models)))
        self._thumbs = []
        for path in models:
            item = QListWidgetItem(path.stem)
            item.setData(Qt.ItemDataRole.UserRole, path)
            item.setToolTip(path.relative_to(root).as_posix())
            item.setIcon(QIcon(placeholder_pixmap(path.stem, CARD)))
            item.setSizeHint(QSize(CARD + 26, CARD + 46))
            self.grid.addItem(item)
            self.items[path] = item
            self._thumbs.append(path)
        self._apply_filter()
        self._timer.start()                                                    # pictures are loaded a few per tick: a big folder must not freeze
        if keep in self.items:
            self.grid.setCurrentItem(self.items[keep])
        else:
            self.current = None
            self._show_form(False)

    def _load_thumbs(self) -> None:
        for _ in range(12):
            if not self._thumbs:
                self._timer.stop()
                return
            path = self._thumbs.pop(0)
            item = self.items.get(path)
            preview = lo.find_preview(path)
            if item is not None and preview is not None:
                pm = QPixmap(str(preview))
                if not pm.isNull():
                    item.setIcon(QIcon(pm.scaled(CARD, CARD, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
                                       .copy(0, 0, CARD, CARD)))

    def _set_card_icon(self, path: Path) -> None:
        item = self.items.get(path)
        if item is None:
            return
        preview = lo.find_preview(path)
        pm = QPixmap(str(preview)) if preview else QPixmap()
        item.setIcon(QIcon(pm.scaled(CARD, CARD, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
                           .copy(0, 0, CARD, CARD)) if not pm.isNull() else QIcon(placeholder_pixmap(path.stem, CARD)))

    def _apply_filter(self) -> None:
        needle = self.search.text().strip().lower()
        for path, item in self.items.items():
            item.setHidden(bool(needle) and needle not in path.stem.lower() and needle not in item.toolTip().lower())

    # --- selecting one -----------------------------------------------------------------------------------------------------------

    def _selection_changed(self, item: QListWidgetItem | None, previous: QListWidgetItem | None) -> None:
        if self._loading:
            return
        if self._dirty and self.current is not None and previous is not None:
            answer = QMessageBox.question(self, tr("lora.save"), tr("lora.ask_save", name=self.current.name),
                                          QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel)
            if answer == QMessageBox.StandardButton.Cancel:
                self._loading = True
                self.grid.setCurrentItem(previous)
                self._loading = False
                return
            if answer == QMessageBox.StandardButton.Save and not self.save():
                self._loading = True
                self.grid.setCurrentItem(previous)
                self._loading = False
                return
        if item is None:
            self.current = None
            self._show_form(False)
            return
        self.open_lora(item.data(Qt.ItemDataRole.UserRole))

    def open_lora(self, path: Path) -> None:
        lora = lo.load(path, self.root())
        self.current = lora
        self._loading = True
        try:
            self.name.setText(lora.name)
            self.ext.setText(path.suffix)
            self.where.setText(tr("lora.where", folder=lora.folder or "/", size=f"{lora.size / 1048576:.0f}"))
            self.description.setPlainText(lora.description)
            self.keywords.setPlainText(lora.keywords)
            self.weight.setValue(lora.weight)
            self.base.setEditText(lora.base)
            self.base.lineEdit().setPlaceholderText(lo.base_from_header(path))
            self.negative.setText(lora.negative)
            self.template.setText(lora.template)
            self.picture.show_picture(lora.preview())
        finally:
            self._loading = False
        self._picture_pending = None
        self._dirty = False
        self.message.clear()
        self._update_result()
        self._show_form(True)
        self._scroll.verticalScrollBar().setValue(0)

    def _edited(self, *_args) -> None:
        if self._loading:
            return
        self._dirty = True
        self._update_result()

    def _fields(self) -> Lora:
        """The lora as the form shows it now (not saved)."""
        base = self.current
        lora = Lora(base.path, base.root, extra=base.extra)
        lora.description = self.description.toPlainText()
        lora.keywords = lo.clean_keywords(self.keywords.toPlainText())
        lora.weight = self.weight.value()
        lora.negative = self.negative.text()
        lora.base = self.base.currentText()
        lora.template = self.template.text()
        return lora

    def _update_result(self) -> None:
        if self.current is None:
            return
        lora = self._fields()
        stem = self.name.text().strip() or self.current.name
        text = lo.render_template(lora.template or lo.DEFAULT_TEMPLATE, stem, lora.weight, lora.keywords)
        self.result.setText(text)

    # --- the picture -------------------------------------------------------------------------------------------------------------

    def _pick_picture(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, tr("lora.picture_file"), "", IMAGE_FILTER)
        if path:
            self._set_picture(Path(path))

    def _paste_picture(self) -> None:
        image = QGuiApplication.clipboard().image()
        if image.isNull():
            self.message.setText(tr("lora.err.picture"))
            return
        self._set_picture(image)

    def _clear_picture(self) -> None:
        if self.current is None:
            return
        self._picture_pending = "clear"
        self.picture.show_picture(None)
        self._edited()

    def _set_picture(self, image) -> None:
        if self.current is None:
            return
        from PySide6.QtGui import QImage
        probe = QImage(str(image)) if isinstance(image, Path) else image
        if probe.isNull():
            self.message.setText(tr("lora.err.picture"))
            return
        self._picture_pending = image
        self.picture.setText("")
        self.picture.setPixmap(QPixmap.fromImage(probe).scaled(PICTURE, PICTURE, Qt.AspectRatioMode.KeepAspectRatio,
                                                                Qt.TransformationMode.SmoothTransformation))
        self._edited()

    # --- keywords ------------------------------------------------------------------------------------------------------------------

    def _suggest_menu(self) -> None:
        if self.current is None:
            return
        words = lo.suggested_keywords(self.current.path)
        menu = QMenu(self)
        if not words:
            menu.addAction(tr("lora.suggest_none")).setEnabled(False)
        else:
            have = {w.lower() for w in lo.clean_keywords(self.keywords.toPlainText()).split(", ") if w}
            menu.addAction(tr("lora.suggest_all"), lambda: self._add_keywords(words))
            menu.addSeparator()
            for w in words:
                action = menu.addAction(w, lambda w=w: self._add_keywords([w]))
                action.setEnabled(w.lower() not in have)
        menu.exec(self.suggest_btn.mapToGlobal(self.suggest_btn.rect().bottomLeft()))

    def _add_keywords(self, words: list[str]) -> None:
        current = self.keywords.toPlainText().strip().rstrip(",")
        self.keywords.setPlainText(lo.clean_keywords(", ".join([current] + words) if current else ", ".join(words)))

    # --- saving -------------------------------------------------------------------------------------------------------------------

    def _error_text(self, exc: LoraError) -> str:
        code = str(exc)
        return tr(f"lora.err.{code}") if code in ("empty", "chars", "exists", "picture") else tr("status.error", msg=code)

    def save(self) -> bool:
        """Writes the card; renames the file when the name was changed. True when everything was done."""
        if self.current is None:
            return False
        lora = self._fields()
        old = self.current.path
        try:
            new_path = lo.rename(old, self.name.text()) if self.name.text().strip() != old.stem else old
            renamed = new_path != old
            lora.path = new_path
            lo.save(lora)
            if self._picture_pending == "clear":
                lo.clear_preview(new_path)
            elif self._picture_pending is not None:
                lo.set_preview(new_path, self._picture_pending)
        except LoraError as exc:
            self.message.setText(self._error_text(exc))
            return False
        self._picture_pending = None
        self._dirty = False
        if renamed:
            self.reload(select=new_path)
        else:
            self._set_card_icon(new_path)
            self.current = lo.load(new_path, self.root())
        self.message.setText(tr("lora.renamed", name=new_path.stem) if renamed else tr("lora.saved"))
        refresh = self.hooks.get("refresh")
        if refresh is not None:
            run_async(refresh)                                                   # a running Forge rescans; a stopped one is not started
        return True

    def _revert(self) -> None:
        if self.current is not None:
            self.open_lora(self.current.path)

    # --- using it ------------------------------------------------------------------------------------------------------------------

    def insert_current(self) -> None:
        if self.current is None or (self._dirty and not self.save()):        # the prompt must carry the name the file really has
            return
        self._insert(lo.load(self.current.path, self.root()))

    def insert_saved(self) -> None:
        item = self.grid.currentItem()
        if item is not None and not self._dirty:
            self._insert(lo.load(item.data(Qt.ItemDataRole.UserRole), self.root()))

    def _insert(self, lora: Lora) -> None:
        insert = self.hooks.get("insert")
        if insert is None:
            return
        added = insert(lora.prompt_text(), lora.negative.strip(), lora.name)
        self.message.setText(tr("lora.inserted") if added else tr("lora.already"))

    def _open_folder(self) -> None:
        if self.current is not None:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.current.path.parent)))
