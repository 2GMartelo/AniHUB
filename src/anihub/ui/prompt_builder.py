"""The prompt builder: a catalogue of tags (categories, subcategories, a picture per tag) on the left and, on the right, the prompt as
paragraphs in the order Stable Diffusion likes: quality, style, who, character, appearance, expression, clothing, pose, camera,
background, light. A tag clicked in the catalogue goes into ITS paragraph, never just to the end of the text."""
from __future__ import annotations

import hashlib
import shutil
import tempfile
from pathlib import Path

from PySide6.QtCore import QPoint, QSize, Qt, Signal
from PySide6.QtGui import QAction, QBrush, QClipboard, QColor, QGuiApplication, QIcon, QImage, QLinearGradient, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QDialog, QFileDialog, QFormLayout, QFrame, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMenu, QMessageBox, QPlainTextEdit, QPushButton, QScrollArea, QSplitter, QToolButton, QTreeWidget,
    QTreeWidgetItem, QVBoxLayout, QWidget,
)

from anihub.context import AppContext
from anihub.core.i18n import get_language, tr
from anihub.services import promptbook as pb
from anihub.services.promptbook import Entry, PromptBook, PromptDoc
from anihub.ui import style, theme
from anihub.ui.manga_filters import FlowLayout
from anihub.ui.workers import run_async

TILE = 84                        # picture size of a tag tile
QUICK_QUALITY = ["masterpiece", "best quality", "highres"]
QUICK_NEGATIVE = {"neg_quality": ["lowres", "worst quality", "low quality", "jpeg artifacts", "blurry"],
                  "neg_anatomy": ["bad anatomy", "bad hands", "extra fingers", "missing fingers"],
                  "neg_artifacts": ["text", "watermark", "signature", "cropped"]}
IMAGE_FILTER = "Images (*.png *.jpg *.jpeg *.webp *.bmp *.gif)"


def display_label(row: dict) -> str:
    """The name shown on a tile: the Russian name in the Russian interface, otherwise the tag itself."""
    return row["label"] if get_language() == "ru" and row.get("label") else row["text"]


def node_name(node: dict) -> str:
    return node["name_ru"] if get_language() == "ru" and node.get("name_ru") else node["name"]


def placeholder_pixmap(text: str, size: int = TILE) -> QPixmap:
    """A picture for a tag that has none: a soft gradient picked from the text, with its first letters."""
    hue = int(hashlib.md5(text.encode("utf-8")).hexdigest()[:4], 16) % 360
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    g = QLinearGradient(0, 0, size, size)
    g.setColorAt(0, QColor.fromHsv(hue, 110, 175))
    g.setColorAt(1, QColor.fromHsv((hue + 35) % 360, 150, 95))
    p.setBrush(g)
    p.setPen(Qt.PenStyle.NoPen)
    p.drawRoundedRect(0, 0, size, size, 12, 12)
    p.setPen(QColor("white"))
    font = p.font()
    font.setBold(True)
    font.setPixelSize(int(size * 0.34))
    p.setFont(font)
    letters = "".join(w[0] for w in text.replace("_", " ").split()[:2]).upper() or text[:1].upper()
    p.drawText(pm.rect(), Qt.AlignmentFlag.AlignCenter, letters)
    p.end()
    return pm


def tile_icon(book: PromptBook, row: dict, active: bool, size: int = TILE) -> QIcon:
    path = book.image_path(row)
    pm = QPixmap(str(path)) if path and path.exists() else QPixmap()
    pm = pm.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation) if not pm.isNull() \
        else placeholder_pixmap(row["text"], size)
    out = QPixmap(size, size)
    out.fill(Qt.GlobalColor.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.drawPixmap(0, 0, pm)
    if active:                                                                    # the tag is in the prompt: accent ring and a check mark
        accent = theme.css_color(theme.current().accent)
        p.setPen(QPen(accent, 4))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(2, 2, size - 4, size - 4, 12, 12)
        p.setBrush(accent)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(size - 26, 5, 21, 21)
        p.setPen(QPen(QColor("white"), 3))
        p.drawLine(size - 20, 16, size - 16, 20)
        p.drawLine(size - 16, 20, size - 10, 11)
    p.end()
    return QIcon(out)


class TagDialog(QDialog):
    """Add or edit one tag: the text that goes into the prompt, its name in the list and an optional picture."""

    def __init__(self, text: str = "", label: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("pb.dlg.title"))
        self.picture: Path | None = None
        self.text = QLineEdit(text, placeholderText="blue hair")
        self.label = QLineEdit(label, placeholderText=tr("pb.dlg.label_hint"))
        self.pick = style.secondary(QPushButton(tr("pb.tile.picture_file")), "image")
        self.picture_label = style.role(QLabel(""), "dim")
        ok = style.primary(QPushButton(tr("settings.save")), "check")
        form = QFormLayout()
        form.addRow(tr("pb.dlg.text"), self.text)
        form.addRow(tr("pb.dlg.label"), self.label)
        row = QHBoxLayout()
        row.addWidget(self.pick)
        row.addWidget(self.picture_label, 1)
        form.addRow(tr("pb.dlg.picture"), row)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(ok, 0, Qt.AlignmentFlag.AlignRight)
        self.resize(460, 190)
        self.pick.clicked.connect(self._pick)
        ok.clicked.connect(self._accept)
        self.text.returnPressed.connect(self._accept)

    def _pick(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, tr("pb.tile.picture_file"), "", IMAGE_FILTER)
        if path:
            self.picture = Path(path)
            self.picture_label.setText(self.picture.name)

    def _accept(self) -> None:
        if self.text.text().strip():
            self.accept()


class TagGrid(QListWidget):
    """Tag tiles: picture over name. Dropping a picture file on a tile sets that tag's picture."""
    picture_dropped = Signal(int, str)

    def __init__(self):
        super().__init__()
        self.setObjectName("tagGrid")
        self.setViewMode(QListWidget.ViewMode.IconMode)
        self.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.setMovement(QListWidget.Movement.Static)
        self.setWrapping(True)
        self.setUniformItemSizes(True)
        self.setIconSize(QSize(TILE, TILE))
        self.setGridSize(QSize(TILE + 26, TILE + 46))
        self.setSpacing(4)
        self.setWordWrap(True)
        self.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.setAcceptDrops(True)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802
        item = self.itemAt(event.position().toPoint())
        urls = [u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]
        if item is not None and urls:
            self.picture_dropped.emit(item.data(Qt.ItemDataRole.UserRole)["id"], urls[0])
            event.acceptProposedAction()


class EntryChip(QFrame):
    """One tag of the prompt: small picture, text, weight, remove button. Ctrl + wheel changes the weight."""
    removed = Signal(str, str)
    weight_changed = Signal(str, str, float)
    menu_requested = Signal(str, str, QPoint)

    def __init__(self, slot: str, entry: Entry, icon: QPixmap | None, label: str):
        super().__init__()
        self.setObjectName("chip")
        self.slot, self.entry = slot, entry
        row = QHBoxLayout(self)
        row.setContentsMargins(6, 3, 4, 3)
        row.setSpacing(5)
        if icon is not None:
            pic = QLabel()
            pic.setPixmap(icon.scaled(20, 20, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation))
            row.addWidget(pic)
        self.text = QLabel(label)
        self.text.setToolTip(entry.text)
        row.addWidget(self.text)
        self.weight = style.role(QLabel(), "dim")
        row.addWidget(self.weight)
        self.close_btn = QToolButton(text="×")
        self.close_btn.setProperty("tagbtn", True)
        self.close_btn.setFixedSize(18, 18)
        self.close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.close_btn.clicked.connect(lambda: self.removed.emit(slot, entry.text))
        row.addWidget(self.close_btn)
        self.refresh_weight()

    def refresh_weight(self) -> None:
        w = self.entry.weight
        self.weight.setText("" if abs(w - 1.0) < 0.005 else f"×{w:g}")

    def wheelEvent(self, e) -> None:  # noqa: N802
        if e.modifiers() & Qt.KeyboardModifier.ControlModifier and e.angleDelta().y():
            step = pb.STEP_W if e.angleDelta().y() > 0 else -pb.STEP_W
            self.weight_changed.emit(self.slot, self.entry.text, self.entry.weight + step)
            e.accept()
        else:
            e.ignore()

    def contextMenuEvent(self, e) -> None:  # noqa: N802
        self.menu_requested.emit(self.slot, self.entry.text, e.globalPos())


class SlotCard(QFrame):
    """The paragraph of one slot: its title, the tags in it and a line to type an own tag."""
    own_tag = Signal(str, str)

    def __init__(self, slot: str):
        super().__init__()
        self.setObjectName("card")
        self.slot = slot
        self.title = QLabel()
        self.title.setStyleSheet("font-weight: 600;")
        self.count = style.role(QLabel(), "dim")
        self.add_line = QLineEdit(placeholderText=tr("pb.add_own"))
        self.add_line.setMaximumWidth(220)
        self.add_line.setClearButtonEnabled(True)
        head = QHBoxLayout()
        head.addWidget(self.title)
        head.addWidget(self.count)
        head.addStretch(1)
        head.addWidget(self.add_line)
        self.chips = QWidget()
        self.flow = FlowLayout(self.chips, spacing=6)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(6)
        layout.addLayout(head)
        layout.addWidget(self.chips)
        self.add_line.returnPressed.connect(self._add)
        self.set_title()

    def set_title(self) -> None:
        self.title.setText(pb.slot_name(self.slot, get_language()))

    def _add(self) -> None:
        text = self.add_line.text()
        if text.strip():
            self.own_tag.emit(self.slot, text)
            self.add_line.clear()

    def set_chips(self, chips: list[EntryChip]) -> None:
        while self.flow.count():
            item = self.flow.takeAt(0)
            if item.widget() is not None:
                item.widget().hide()
                item.widget().setParent(None)
                item.widget().deleteLater()
        for chip in chips:
            self.flow.addWidget(chip)
        self.chips.setVisible(bool(chips))
        self.count.setText(f"· {len(chips)}" if chips else "")
        self.chips.updateGeometry()


class PromptBuilder(QWidget):
    """`form` gives the builder access to the Generate form: `get() -> (prompt, negative)`, `set(prompt, negative)`,
    `api() -> ForgeApi | None` (a running Forge, for pictures)."""
    prompt_ready = Signal(str, str)                    # the assembled prompt and negative prompt
    _preview_progress = Signal(int, int, str)
    _preview_image = Signal(int, bytes)

    def __init__(self, ctx: AppContext, form=None, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.form = form
        self.book = PromptBook(ctx.db, ctx.paths.root)
        self.book.seed()
        self.doc = PromptDoc()
        self._last_pushed: tuple[str, str] | None = None
        self._dirty = False                                  # changes in the builder the form has not received yet
        self._cancel_previews = False
        self._rows: dict[int, dict] = {}

        # --- left: the catalogue -------------------------------------------------------------------------------
        self.search = QLineEdit(placeholderText=tr("pb.search"))
        self.search.setClearButtonEnabled(True)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setMinimumWidth(190)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.grid = TagGrid()
        self.status = style.role(QLabel(), "dim")
        self.status.setWordWrap(True)
        self.more_btn = style.ghost(QPushButton(tr("pb.more")), "more")
        catalog = QSplitter()
        catalog.addWidget(self.tree)
        catalog.addWidget(self.grid)
        catalog.setStretchFactor(1, 1)
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        top = QHBoxLayout()
        top.addWidget(self.search, 1)
        top.addWidget(self.more_btn)
        ll.addLayout(top)
        ll.addWidget(catalog, 1)
        ll.addWidget(self.status)

        # --- right: the prompt as paragraphs ------------------------------------------------------------------
        self.cards: dict[str, SlotCard] = {}
        content = QWidget()
        self.cards_layout = QVBoxLayout(content)
        self.cards_layout.setContentsMargins(0, 0, 6, 0)
        self.cards_layout.setSpacing(8)
        for key in pb.POSITIVE:
            self._add_card(key)
        self.negative_title = style.role(QLabel(tr("pb.negative_title")), "h2")
        self.cards_layout.addSpacing(6)
        self.cards_layout.addWidget(self.negative_title)
        for key in pb.NEGATIVE:
            self._add_card(key)
        self.cards_layout.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(content)
        self.positive_view = QPlainTextEdit(readOnly=True, placeholderText=tr("pb.preview.positive"))
        self.negative_view = QPlainTextEdit(readOnly=True, placeholderText=tr("pb.preview.negative"))
        for view in (self.positive_view, self.negative_view):
            view.setMaximumHeight(120)
        self.tokens = style.role(QLabel(), "dim")
        self.apply_btn = style.primary(QPushButton(tr("pb.apply")), "check")
        self.from_btn = style.secondary(QPushButton(tr("pb.from_form")), "download")
        self.quick_btn = style.secondary(QPushButton(tr("pb.quick")), "zap")
        self.copy_btn = style.ghost(QPushButton(tr("pb.copy")), "copy")
        self.clear_btn = style.ghost(QPushButton(tr("pb.clear")), "trash")
        self.sync = QCheckBox(tr("pb.sync"), checked=bool(ctx.cfg.get("promptbook.sync", True)))
        buttons = QWidget()                                                       # wraps to a second row in a narrow window
        flow = FlowLayout(buttons, spacing=8)
        for w in (self.quick_btn, self.from_btn, self.copy_btn, self.clear_btn, self.apply_btn):
            flow.addWidget(w)
        previews = QHBoxLayout()
        previews.addWidget(self.positive_view, 3)
        previews.addWidget(self.negative_view, 2)
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.addWidget(scroll, 1)
        rl.addLayout(previews)
        info = QHBoxLayout()
        info.addWidget(self.tokens, 1)
        info.addWidget(self.sync)
        rl.addLayout(info)
        rl.addWidget(buttons)

        split = QSplitter()
        split.addWidget(left)
        split.addWidget(right)
        split.setStretchFactor(0, 5)
        split.setStretchFactor(1, 4)
        split.setChildrenCollapsible(False)
        split.setSizes([620, 520])
        catalog.setChildrenCollapsible(False)
        catalog.setSizes([210, 410])
        self.tokens.setWordWrap(True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(split)

        quick = QMenu(self)
        quick.addAction(tr("pb.quick.quality"), self.quick_quality)
        quick.addAction(tr("pb.quick.negative"), self.quick_negative)
        quick.addAction(tr("pb.quick.safe"), self.quick_safe)
        self.quick_btn.setMenu(quick)

        self.search.textChanged.connect(self._refresh_grid)
        self.tree.currentItemChanged.connect(lambda *_: self._refresh_grid())
        self.tree.customContextMenuRequested.connect(self._tree_menu)
        self.grid.itemClicked.connect(self._tile_clicked)
        self.grid.customContextMenuRequested.connect(self._grid_menu)
        self.grid.picture_dropped.connect(self._picture_dropped)
        self.more_btn.clicked.connect(self._more_menu)
        self.apply_btn.clicked.connect(self.push)
        self.from_btn.clicked.connect(self.pull)
        self.copy_btn.clicked.connect(self._copy)
        self.clear_btn.clicked.connect(self._clear)
        self.sync.toggled.connect(lambda v: (ctx.cfg.set("promptbook.sync", bool(v)), v and self._doc_changed()))
        self._preview_progress.connect(self._on_preview_progress)
        self._preview_image.connect(self._on_preview_image)
        self._fill_tree()
        self._refresh_grid()
        self._refresh_doc()

    # --- helpers ---------------------------------------------------------------------------------------------------

    def _add_card(self, key: str) -> None:
        card = SlotCard(key)
        card.own_tag.connect(self._own_tag)
        self.cards[key] = card
        self.cards_layout.addWidget(card)

    def _allowed(self, row: dict) -> bool:
        """Positive tags obey the age mode and the user's hidden tags (negative ones are what the user does NOT want: never hidden)."""
        return row["slot"] in pb.NEGATIVE or not self.ctx.blocker.blocks(row["text"])

    def _visible_tags(self, rows: list[dict]) -> tuple[list[dict], int]:
        shown = [r for r in rows if self._allowed(r)]
        return shown, len(rows) - len(shown)

    # --- the catalogue tree -----------------------------------------------------------------------------------------

    def _fill_tree(self, keep: tuple | None = None) -> None:
        current = keep or self._selection()
        self.tree.blockSignals(True)
        self.tree.clear()
        wanted = None
        for key in pb.SLOT_KEYS:
            top = QTreeWidgetItem([pb.slot_name(key, get_language())])
            top.setData(0, Qt.ItemDataRole.UserRole, ("slot", key))
            font = top.font(0)
            font.setBold(True)
            top.setFont(0, font)
            self.tree.addTopLevelItem(top)
            nodes = self.book.nodes(key)
            children: dict[int | None, list[dict]] = {}
            for n in nodes:
                children.setdefault(n["parent_id"], []).append(n)

            def add(parent_item: QTreeWidgetItem, parent_id: int | None) -> None:
                for n in children.get(parent_id, []):
                    item = QTreeWidgetItem([node_name(n) + ("  ①" if n["exclusive"] else "")])
                    item.setData(0, Qt.ItemDataRole.UserRole, ("node", n["id"]))
                    parent_item.addChild(item)
                    if current == ("node", n["id"]):
                        nonlocal wanted
                        wanted = item
                    add(item, n["id"])

            add(top, None)
            if current == ("slot", key):
                wanted = top
        first = self.tree.topLevelItem(0)
        self.tree.setCurrentItem(wanted or first)
        for i in range(self.tree.topLevelItemCount()):
            self.tree.topLevelItem(i).setExpanded(False)
        item = self.tree.currentItem()
        while item is not None:
            item.setExpanded(True)
            item = item.parent()
        self.tree.blockSignals(False)

    def _selection(self) -> tuple | None:
        item = self.tree.currentItem()
        return item.data(0, Qt.ItemDataRole.UserRole) if item is not None else None

    def _current_slot(self) -> str:
        sel = self._selection()
        if sel is None:
            return pb.POSITIVE[0]
        if sel[0] == "slot":
            return sel[1]
        node = self.book.node(sel[1])
        return node["slot"] if node else pb.POSITIVE[0]

    # --- the tag grid ------------------------------------------------------------------------------------------------

    def _rows_for_view(self) -> list[dict]:
        query = self.search.text()
        if query.strip():
            return self.book.tags(query=query)
        sel = self._selection()
        if sel is None:
            return []
        if sel[0] == "slot":
            return self.book.tags(slot=sel[1])
        return self.book.tags(self.book.subtree_ids(sel[1]))

    def _refresh_grid(self) -> None:
        rows, hidden = self._visible_tags(self._rows_for_view())
        self._rows = {r["id"]: r for r in rows}
        self.grid.clear()
        for row in rows:
            item = QListWidgetItem(display_label(row))
            item.setData(Qt.ItemDataRole.UserRole, row)
            item.setToolTip(row["text"] + ("\n" + pb.slot_name(row["slot"], get_language())))
            item.setIcon(tile_icon(self.book, row, self.doc.has(row["slot"], row["text"])))
            item.setSizeHint(QSize(TILE + 22, TILE + 42))
            self.grid.addItem(item)
        note = tr("pb.hidden", n=hidden) if hidden else ""
        self.status.setText((tr("pb.count", n=len(rows)) + ("  ·  " + note if note else "")))

    def _refresh_tiles(self) -> None:
        """Only the ring/check marks: the tiles stay where they are."""
        for i in range(self.grid.count()):
            item = self.grid.item(i)
            row = item.data(Qt.ItemDataRole.UserRole)
            item.setIcon(tile_icon(self.book, row, self.doc.has(row["slot"], row["text"])))

    def _tile_clicked(self, item: QListWidgetItem) -> None:
        row = item.data(Qt.ItemDataRole.UserRole)
        self.doc.toggle(row["slot"], row["text"], group=str(row["group_id"]), exclusive=bool(row["exclusive"]), tag_id=row["id"])
        self._doc_changed()

    # --- the document ----------------------------------------------------------------------------------------------------

    def _own_tag(self, slot: str, text: str) -> None:
        for piece in pb.split_top_level(text):
            tag, weight = pb.parse_piece(piece)
            self.doc.add(slot, tag, weight=weight)
        self._doc_changed()

    def _doc_changed(self) -> None:
        self._refresh_doc()
        self._refresh_tiles()
        self._dirty = True
        if self.sync.isChecked():
            self.push()

    def _chip_for(self, slot: str, entry: Entry) -> EntryChip:
        row = self.book.tag(entry.tag_id) if entry.tag_id else None
        icon = None
        if row is not None and self.book.image_path(row):
            path = self.book.image_path(row)
            icon = QPixmap(str(path)) if path.exists() else None
        label = display_label(row) if row is not None and row["text"] == entry.text else entry.text
        chip = EntryChip(slot, entry, icon, label)
        chip.removed.connect(self._remove_entry)
        chip.weight_changed.connect(self._set_weight)
        chip.menu_requested.connect(self._chip_menu)
        return chip

    def _refresh_doc(self) -> None:
        for key, card in self.cards.items():
            card.set_chips([self._chip_for(key, e) for e in self.doc.entries(key)])
        positive, negative = self.doc.positive(), self.doc.negative()
        self.positive_view.setPlainText(positive)
        self.negative_view.setPlainText(negative)
        n = pb.estimate_tokens(positive)
        self.tokens.setText(tr("pb.tokens", n=n) + ("  ·  " + tr("pb.tokens_long") if n > 75 else ""))

    def _remove_entry(self, slot: str, text: str) -> None:
        self.doc.remove(slot, text)
        self._doc_changed()

    def _set_weight(self, slot: str, text: str, weight: float) -> None:
        self.doc.set_weight(slot, text, weight)
        self._doc_changed()

    def _chip_menu(self, slot: str, text: str, pos: QPoint) -> None:
        menu = QMenu(self)
        entry = self.doc.find(slot, text)
        menu.addAction(tr("pb.chip.weight_up"), lambda: self._set_weight(slot, text, entry.weight + pb.STEP_W))
        menu.addAction(tr("pb.chip.weight_down"), lambda: self._set_weight(slot, text, entry.weight - pb.STEP_W))
        menu.addAction(tr("pb.chip.weight_reset"), lambda: self._set_weight(slot, text, 1.0))
        menu.addSeparator()
        menu.addAction(tr("pb.chip.left"), lambda: (self.doc.move(slot, text, -1), self._doc_changed()))
        menu.addAction(tr("pb.chip.right"), lambda: (self.doc.move(slot, text, 1), self._doc_changed()))
        move = menu.addMenu(tr("pb.chip.move_to"))
        positive = slot in pb.POSITIVE
        for key in (pb.POSITIVE if positive else pb.NEGATIVE):
            if key != slot:
                move.addAction(pb.slot_name(key, get_language()), lambda k=key: (self.doc.move_to_slot(slot, text, k), self._doc_changed()))
        menu.addSeparator()
        menu.addAction(tr("pb.chip.remove"), lambda: self._remove_entry(slot, text))
        menu.exec(pos)

    # --- form <-> builder ------------------------------------------------------------------------------------------------

    def push(self) -> None:
        """Send the assembled prompt to the Generate form."""
        positive, negative = self.doc.positive(), self.doc.negative()
        self._last_pushed, self._dirty = (positive, negative), False
        if self.form is not None:
            self.form["set"](positive, negative)
        self.prompt_ready.emit(positive, negative)

    def pull(self) -> int:
        """Read the Generate form's prompt: its tags are sorted into the paragraphs (what the catalogue does not know goes to "extra")."""
        if self.form is None:
            return 0
        prompt, negative = self.form["get"]()
        lookup = self.book.lookup()
        doc = pb.parse_prompt(prompt, lookup)
        neg = pb.parse_prompt(negative, lookup, negative=True)
        for key in pb.NEGATIVE:
            doc.slots[key] = neg.slots.get(key, [])
        for entries in doc.slots.values():                                     # keep the catalogue pictures on the chips
            for e in entries:
                rows = self.book.tags(query=e.text)
                match = next((r for r in rows if pb.norm(r["text"]) == pb.norm(e.text)), None)
                if match:
                    e.tag_id = match["id"]
        self.doc = doc
        self._last_pushed, self._dirty = (doc.positive(), doc.negative()), False
        self._refresh_doc()
        self._refresh_tiles()
        return doc.count(pb.SLOT_KEYS)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        if self.form is None:
            return
        prompt, negative = self.form["get"]()
        known = self._last_pushed or ("", "")
        if (prompt.strip(), negative.strip()) != (known[0].strip(), known[1].strip()) and not self._dirty:
            self.pull()            # the form was edited by hand (or loaded from an image / history) since the builder last wrote to it

    def _copy(self) -> None:
        QGuiApplication.clipboard().setText(self.doc.positive() + ("\n\nNegative prompt: " + self.doc.negative() if self.doc.negative() else ""))
        self.status.setText(tr("pb.copied"))

    def _clear(self) -> None:
        self.doc.clear()
        self._doc_changed()

    def quick_quality(self) -> None:
        for tag in QUICK_QUALITY:
            self.doc.add("quality", tag)
        self._doc_changed()

    def quick_negative(self) -> None:
        for slot, tags in QUICK_NEGATIVE.items():
            for tag in tags:
                self.doc.add(slot, tag)
        self._doc_changed()

    def quick_safe(self) -> None:
        self.doc.add("neg_unwanted", "nsfw")
        self._doc_changed()

    # --- editing the catalogue -------------------------------------------------------------------------------------------

    def _selected_node(self) -> dict | None:
        sel = self._selection()
        return self.book.node(sel[1]) if sel and sel[0] == "node" else None

    def _more_menu(self) -> None:
        menu = QMenu(self)
        menu.addAction(tr("pb.tree.restore"), self._restore)
        menu.addSeparator()
        menu.addAction(tr("pb.pack.export"), self._export_pack)
        menu.addAction(tr("pb.pack.import"), self._import_pack)
        menu.exec(self.more_btn.mapToGlobal(QPoint(0, self.more_btn.height())))

    def _export_pack(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, tr("pb.pack.export"), "promptbook_pack.zip", "ZIP (*.zip)")
        if path:
            try:
                n = self.book.export_pack(Path(path))
            except OSError as exc:
                self.status.setText(tr("status.error", msg=str(exc)))
                return
            self.status.setText(tr("pb.pack.exported", n=n, path=path))

    def _import_pack(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, tr("pb.pack.import"), "", "ZIP (*.zip)")
        if path:
            n = self.book.apply_pack(Path(path), overwrite=True)
            self._refresh_grid()
            self._refresh_doc()
            self.status.setText(tr("pb.pack.imported", n=n))

    def _restore(self) -> None:
        self.book.restore_defaults()
        self._fill_tree()
        self._refresh_grid()

    def _tree_menu(self, pos: QPoint) -> None:
        item = self.tree.itemAt(pos)
        if item is not None:
            self.tree.setCurrentItem(item)
        sel = self._selection()
        if sel is None:
            return
        slot = self._current_slot()
        node = self._selected_node()
        menu = QMenu(self)
        menu.addAction(tr("pb.tree.new_category"), lambda: self._new_node(slot, None))
        if node is not None:
            menu.addAction(tr("pb.tree.new_sub"), lambda: self._new_node(slot, node["id"]))
            menu.addAction(tr("pb.tree.rename"), lambda: self._rename_node(node))
            exclusive = menu.addAction(tr("pb.tree.exclusive"))
            exclusive.setCheckable(True)
            exclusive.setChecked(bool(node["exclusive"]))
            exclusive.toggled.connect(lambda v: (self.book.set_exclusive(node["id"], v), self._fill_tree(), self._refresh_grid()))
            menu.addSeparator()
        if node is not None or sel[0] == "slot":
            menu.addAction(tr("pb.tree.previews"), self._previews_for_view)
        if node is not None:
            menu.addAction(tr("pb.tree.delete"), lambda: self._delete_node(node))
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    def _new_node(self, slot: str, parent_id: int | None) -> None:
        name, ok = QInputDialog.getText(self, tr("pb.tree.new_category"), tr("pb.dlg.name"))
        if ok and name.strip():
            node_id = self.book.add_node(slot, name, parent_id)
            self._fill_tree(("node", node_id))
            self._refresh_grid()

    def _rename_node(self, node: dict) -> None:
        name, ok = QInputDialog.getText(self, tr("pb.tree.rename"), tr("pb.dlg.name"), text=node_name(node))
        if ok and name.strip():
            self.book.rename_node(node["id"], name)
            self._fill_tree(("node", node["id"]))

    def _delete_node(self, node: dict) -> None:
        if QMessageBox.question(self, tr("pb.tree.delete"), tr("pb.confirm_delete", name=node_name(node))) == QMessageBox.StandardButton.Yes:
            self.book.delete_node(node["id"])
            self._fill_tree(("slot", node["slot"]))
            self._refresh_grid()

    def _grid_menu(self, pos: QPoint) -> None:
        item = self.grid.itemAt(pos)
        menu = QMenu(self)
        if item is not None:
            row = item.data(Qt.ItemDataRole.UserRole)
            menu.addAction(tr("pb.tile.picture_file"), lambda: self._pick_picture(row))
            menu.addAction(tr("pb.tile.paste"), lambda: self._paste_picture(row))
            menu.addAction(tr("pb.tile.generate"), lambda: self._generate_picture(row))
            if row["image"]:
                menu.addAction(tr("pb.tile.remove_picture"), lambda: (self.book.clear_image(row["id"]), self._refresh_grid()))
            menu.addSeparator()
            menu.addAction(tr("pb.tile.edit"), lambda: self._edit_tag(row))
            menu.addAction(tr("pb.tile.delete"), lambda: (self.book.delete_tag(row["id"]), self._refresh_grid()))
            menu.addSeparator()
        menu.addAction(tr("pb.tile.add"), self._add_tag)
        menu.exec(self.grid.viewport().mapToGlobal(pos))

    def _target_node(self) -> int | None:
        node = self._selected_node()
        if node is not None:
            return node["id"]
        sel = self._selection()
        if sel and sel[0] == "slot":                                            # a slot itself: its first category
            nodes = [n for n in self.book.nodes(sel[1]) if n["parent_id"] is None]
            return nodes[0]["id"] if nodes else self.book.add_node(sel[1], tr("pb.my_tags"))
        return None

    def _add_tag(self) -> None:
        node_id = self._target_node()
        if node_id is None:
            self.status.setText(tr("pb.select_category"))
            return
        dlg = TagDialog(parent=self)
        if dlg.exec():
            tag_id = self.book.add_tag(node_id, dlg.text.text(), dlg.label.text())
            if tag_id and dlg.picture is not None:
                self.book.set_image(tag_id, dlg.picture)
            self._refresh_grid()

    def _edit_tag(self, row: dict) -> None:
        dlg = TagDialog(row["text"], row["label"], self)
        if dlg.exec():
            self.book.edit_tag(row["id"], dlg.text.text(), dlg.label.text())
            if dlg.picture is not None:
                self.book.set_image(row["id"], dlg.picture)
            self._refresh_grid()

    # --- pictures --------------------------------------------------------------------------------------------------------

    def _pick_picture(self, row: dict) -> None:
        path, _ = QFileDialog.getOpenFileName(self, tr("pb.tile.picture_file"), "", IMAGE_FILTER)
        if path:
            self._picture_dropped(row["id"], path)

    def _picture_dropped(self, tag_id: int, path: str) -> None:
        if self.book.set_image(tag_id, Path(path)) is None:
            self.status.setText(tr("pb.bad_picture"))
            return
        self._refresh_grid()
        self._refresh_doc()

    def _paste_picture(self, row: dict) -> None:
        image = QGuiApplication.clipboard().image()
        if image.isNull() or self.book.set_image(row["id"], image) is None:
            self.status.setText(tr("pb.bad_picture"))
            return
        self._refresh_grid()
        self._refresh_doc()

    def _api(self):
        return self.form["api"]() if self.form is not None and self.form.get("api") else None

    def _generate_picture(self, row: dict) -> None:
        api = self._api()
        if api is None:
            self.status.setText(tr("pb.need_forge"))
            return
        self.status.setText(tr("pb.previews.working", n=1))
        self._run_previews(api, [row])

    def _previews_for_view(self) -> None:
        api = self._api()
        if api is None:
            self.status.setText(tr("pb.need_forge"))
            return
        rows = [r for r in self._rows.values() if not r["image"]]
        if not rows:
            self.status.setText(tr("pb.previews.none"))
            return
        if QMessageBox.question(self, tr("pb.tree.previews"), tr("pb.previews.confirm", n=len(rows))) != QMessageBox.StandardButton.Yes:
            return
        self._run_previews(api, rows)

    def _run_previews(self, api, rows: list[dict]) -> None:
        """Generate a picture per tag with the running Forge (one seed for all, so the tiles look alike), one after another."""
        from anihub.services.generation import GenParams, run_generation

        self._cancel_previews = False
        size = int(self.ctx.cfg.get("promptbook.preview_size", 768) or 768)

        def work() -> int:
            done = 0
            for i, row in enumerate(rows, 1):
                if self._cancel_previews:
                    break
                self._preview_progress.emit(i, len(rows), row["text"])
                prompt, negative = pb.preview_prompt(row["slot"], row["text"], (self.book.node(row["group_id"]) or {}).get("key") or "")
                tmp = Path(tempfile.mkdtemp(prefix="anihub_pb_"))
                try:
                    results = run_generation(api, GenParams(prompt=prompt, negative_prompt=negative, steps=20, width=size, height=size,
                                                             seed=12345, n_iter=1, batch_size=1), tmp)
                    if results:
                        self._preview_image.emit(row["id"], Path(results[0].path).read_bytes())
                        done += 1
                except Exception:  # noqa: BLE001 - one failed picture must not stop the rest
                    continue
                finally:
                    shutil.rmtree(tmp, ignore_errors=True)
            return done

        run_async(work, on_done=lambda n: self.status.setText(tr("pb.previews.done", n=n)),
                  on_error=lambda exc: self.status.setText(tr("status.error", msg=str(exc))))

    def _on_preview_progress(self, i: int, total: int, name: str) -> None:
        self.status.setText(tr("pb.previews.progress", i=i, total=total, name=name))

    def _on_preview_image(self, tag_id: int, data: bytes) -> None:
        self.book.set_image(tag_id, data)
        self._refresh_grid()
        self._refresh_doc()

    def cancel_previews(self) -> None:
        self._cancel_previews = True
