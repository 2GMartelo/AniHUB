"""The prompt builder: a catalogue of tags (categories, subcategories, a picture per tag) on the left and, on the right, the prompt as
paragraphs in the order Stable Diffusion likes: quality, style, who, character, appearance, expression, clothing, pose, camera,
background, light. A tag clicked in the catalogue goes into ITS paragraph, never just to the end of the text."""
from __future__ import annotations

import hashlib
from pathlib import Path

from PySide6.QtCore import QPoint, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QBrush, QClipboard, QColor, QGuiApplication, QIcon, QImage, QLinearGradient, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView, QButtonGroup, QCheckBox, QDialog, QFileDialog, QFormLayout, QFrame, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMenu, QMessageBox, QPlainTextEdit, QPushButton, QScrollArea, QSpinBox, QSplitter, QToolButton, QTreeWidget,
    QTreeWidgetItem, QVBoxLayout, QWidget,
)

from anihub.context import AppContext
from anihub.core.i18n import get_language, tr
from anihub.services import lora as lo
from anihub.services import promptbook as pb
from anihub.services.tagpictures import PictureMaker
from anihub.services.promptbook import Entry, PromptBook, PromptDoc
from anihub.ui import builder_lora as bl
from anihub.ui import style, theme
from anihub.ui.builder_dnd import LORA_MIME, NODE_MIME, ROLE, TAG_MIME, CatalogTree, DragGrid
from anihub.ui.manga_filters import FlowLayout
from anihub.ui.pagezoom import PageZoom
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
    if row.get("lora"):
        return decorate_icon(bl.lora_pixmap(row["path"], size) or placeholder_pixmap(row["text"], size), active, size)
    path = book.image_path(row)
    pm = QPixmap(str(path)) if path and path.exists() else QPixmap()
    pm = pm.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation) if not pm.isNull() \
        else placeholder_pixmap(row["text"], size)
    return decorate_icon(pm, active, size)


def decorate_icon(pm: QPixmap, active: bool, size: int = TILE) -> QIcon:
    """The tile picture, with the accent ring and check mark when the tag / LoRA is in the prompt."""
    out = QPixmap(size, size)
    out.fill(Qt.GlobalColor.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.drawPixmap(0, 0, pm)
    if active:                                                                    # the tag is in the prompt: accent ring and a check mark
        k = size / TILE                                                           # the marks grow with the tile (Ctrl + wheel zoom)

        def r(v: float) -> int:
            return round(v * k)

        accent = theme.css_color(theme.current().accent)
        p.setPen(QPen(accent, 4 * k))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(r(2), r(2), size - r(4), size - r(4), r(12), r(12))
        p.setBrush(accent)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(size - r(26), r(5), r(21), r(21))
        p.setPen(QPen(QColor("white"), 3 * k))
        p.drawLine(size - r(20), r(16), size - r(16), r(20))
        p.drawLine(size - r(16), r(20), size - r(10), r(11))
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


class SlotEditDialog(QDialog):
    """A section (top-level category/slot): rename it (built-ins keep their name -- the field is disabled, not
    hidden, so it is still obvious what is being edited) and toggle "belongs to a character"."""

    def __init__(self, name: str, character: bool, editable_name: bool, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("pb.edit_section.title"))
        self.name_edit = QLineEdit(name)
        self.name_edit.setEnabled(editable_name)
        self.character_box = QCheckBox(tr("pb.edit_section.character"), checked=character)
        ok = style.primary(QPushButton(tr("settings.save")), "check")
        form = QFormLayout()
        form.addRow(tr("pb.edit_section.name"), self.name_edit)
        form.addRow("", self.character_box)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(ok, 0, Qt.AlignmentFlag.AlignRight)
        ok.clicked.connect(self.accept)


class NodeEditDialog(QDialog):
    """A category/subcategory: rename it and toggle whether several of its tags can be active at once ("одновременный
    выбор") -- the same thing as the existing exclusive flag, just worded from the other side and reachable from one
    consolidated Edit dialog instead of only the tree's own checkable menu item."""

    def __init__(self, name: str, multi: bool, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("pb.edit_category.title"))
        self.name_edit = QLineEdit(name)
        self.multi_box = QCheckBox(tr("pb.edit_category.multi"), checked=multi)
        ok = style.primary(QPushButton(tr("settings.save")), "check")
        form = QFormLayout()
        form.addRow(tr("pb.edit_category.name"), self.name_edit)
        form.addRow("", self.multi_box)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(ok, 0, Qt.AlignmentFlag.AlignRight)
        ok.clicked.connect(self.accept)


class TagGrid(DragGrid):
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
        self.set_tile(TILE)
        self.setSpacing(4)
        self.setWordWrap(True)
        self.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.setAcceptDrops(True)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)

    def set_tile(self, size: int) -> None:
        self.setIconSize(QSize(size, size))
        self.setGridSize(QSize(size + 26, size + 60))

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
    """The paragraph of one slot: its title, a line to type an own tag, and its tags grouped by subcategory
    (each subcategory gets its own sub-header, a bit apart from the next; entries with no catalogue subcategory
    -- typed in by hand -- fall into a trailing, unlabelled group). Still just one paragraph in the compiled
    prompt: the grouping here is visual only, ui/prompt_builder.py's PromptDoc.paragraphs() is unaffected."""
    own_tag = Signal(str, str)

    def __init__(self, slot: str, title: str | None = None):
        super().__init__()
        self.setObjectName("card")
        self.slot = slot
        self._title_override = title
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
        self.groups_area = QWidget()
        self.groups_layout = QVBoxLayout(self.groups_area)
        self.groups_layout.setContentsMargins(0, 0, 0, 0)
        self.groups_layout.setSpacing(12)                # "чуть отдалённо друг от друга" between subcategories
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(6)
        layout.addLayout(head)
        layout.addWidget(self.groups_area)
        self.add_line.returnPressed.connect(self._add)
        self.set_title()

    def set_title(self) -> None:
        self.title.setText(self._title_override or pb.slot_name(self.slot, get_language()))

    def _add(self) -> None:
        text = self.add_line.text()
        if text.strip():
            self.own_tag.emit(self.slot, text)
            self.add_line.clear()

    def set_groups(self, groups: list[tuple[str, list[EntryChip]]]) -> None:
        """`groups`: [(subcategory label, chips), ...], already in catalogue order; label "" (only ever the last
        group) gets no sub-header, for hand-typed tags that belong to no subcategory."""
        while self.groups_layout.count():
            item = self.groups_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()
        total = 0
        for label, chips in groups:
            if not chips:
                continue
            total += len(chips)
            box = QWidget()
            box_layout = QVBoxLayout(box)
            box_layout.setContentsMargins(0, 0, 0, 0)
            box_layout.setSpacing(4)
            if label:
                box_layout.addWidget(style.role(QLabel(label), "h3"))
            row = QWidget()
            flow = FlowLayout(row, spacing=6)
            for chip in chips:
                flow.addWidget(chip)
            box_layout.addWidget(row)
            self.groups_layout.addWidget(box)
        self.groups_area.setVisible(total > 0)
        self.count.setText(f"· {total}" if total else "")
        self.groups_area.updateGeometry()

    def all_chips(self) -> list[EntryChip]:
        """Every chip across every subcategory group, in display order -- for callers that just want "the chips
        of this slot" without caring how they are grouped (e.g. a test, or the token/paragraph preview)."""
        chips: list[EntryChip] = []
        for i in range(self.groups_layout.count()):
            box = self.groups_layout.itemAt(i).widget()
            if box is None or box.layout() is None:
                continue
            row = box.layout().itemAt(box.layout().count() - 1).widget()
            flow = row.layout() if row is not None else None
            if flow is None:
                continue
            for j in range(flow.count()):
                widget = flow.itemAt(j).widget()
                if isinstance(widget, EntryChip):
                    chips.append(widget)
        return chips


class PromptBuilder(QWidget):
    """`form` gives the builder access to the Generate form: `get() -> (prompt, negative)`, `set(prompt, negative)`,
    `api() -> ForgeApi | None` (a running Forge, for pictures)."""
    prompt_ready = Signal(str, str)                    # the assembled prompt and negative prompt
    _preview_progress = Signal(int, int, str)
    _preview_image = Signal(int, bytes)

    def __init__(self, ctx: AppContext, form=None, parent=None):
        super().__init__(parent)
        pb.apply_custom_slots(ctx.cfg)          # keeps pb.SLOT_KEYS/POSITIVE/NEGATIVE in sync even when the
        self.ctx = ctx                          # caller built its own ctx by hand instead of AppContext.build()
        self.form = form
        self.book = PromptBook(ctx.db, ctx.paths.root)
        self.book.seed()
        self.doc = PromptDoc()
        if not ctx.cfg.get("promptbuilder.default_character_seeded", False):
            self.book.seed_default_character(self.doc)
            ctx.cfg.set("promptbuilder.default_character_seeded", True)
        self.character_count = max(1, min(4, int(ctx.cfg.get("promptbuilder.character_count", 1) or 1)))
        self.active_character = 1
        self._last_pushed: tuple[str, str] | None = None
        self._dirty = False                                  # changes in the builder the form has not received yet
        self._cancel_previews = False
        self.drawing = False
        self._rows: dict[int, dict] = {}
        self._lora_queue: list = []
        self.tile = TILE                                     # current tile picture size (Ctrl + wheel zoom)
        self._lora_timer = QTimer(self, interval=15)
        self._lora_timer.timeout.connect(self._load_lora_thumbs)

        # --- left: the catalogue -------------------------------------------------------------------------------
        self.search = QLineEdit(placeholderText=tr("pb.search"))
        self.search.setClearButtonEnabled(True)
        self.tree = CatalogTree()
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
            self._add_cards_for(key)
        self.negative_title = style.role(QLabel(tr("pb.negative_title")), "h2")
        self.cards_layout.addSpacing(6)
        self.cards_layout.addWidget(self.negative_title)
        for key in pb.NEGATIVE:
            self._add_cards_for(key)
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
        self.character_spin = QSpinBox(minimum=1, maximum=4, value=self.character_count)
        self.character_switch_group = QButtonGroup(self)
        self.character_switch_group.setExclusive(True)
        self.character_buttons: list[QToolButton] = []
        character_row = QHBoxLayout()
        character_row.addWidget(QLabel(tr("pb.characters_label")))
        character_row.addWidget(self.character_spin)
        character_row.addSpacing(10)
        for i in range(1, 5):
            btn = QToolButton(text=str(i), checkable=True)
            btn.setToolTip(tr("pb.character_switch_tip"))
            btn.setChecked(i == self.active_character)
            self.character_switch_group.addButton(btn, i)
            character_row.addWidget(btn)
            self.character_buttons.append(btn)
        character_row.addStretch(1)
        self.character_spin.valueChanged.connect(self._set_character_count)
        self.character_switch_group.idClicked.connect(self._set_active_character)

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.addLayout(character_row)
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
        self.tree.tags_dropped.connect(self._tags_dropped)
        self.tree.node_dropped.connect(self._node_dropped)
        self.tree.loras_dropped.connect(self._loras_dropped)
        self.tree.slot_dropped.connect(self._slot_dropped)
        self._fill_tree()
        self._refresh_grid()
        self._refresh_doc()
        self._update_character_buttons()
        self.page_zoom = PageZoom(self, on_zoom=self._zoom_tiles)
        saved = ctx.cfg.get("ui.builder_zoom")
        if isinstance(saved, (int, float)) and saved != 1.0:
            self.page_zoom.set_factor(float(saved))

    def _zoom_tiles(self, factor: float) -> None:
        """Ctrl + wheel: bigger or smaller tag pictures (and buttons), remembered for the next start."""
        self.tile = max(40, round(TILE * factor))
        self.grid.set_tile(self.tile)
        self._refresh_grid()
        self.ctx.cfg.set("ui.builder_zoom", factor)

    # --- helpers ---------------------------------------------------------------------------------------------------

    def _add_card(self, key: str, title: str | None = None) -> None:
        card = SlotCard(key, title)
        card.own_tag.connect(self._own_tag)
        self.cards[key] = card
        self.cards_layout.addWidget(card)

    def _add_cards_for(self, slot: str) -> None:
        """One card, or with more than one active character and a character slot, one card per character
        (ui/prompt_builder.py's character switcher only decides which of these a catalogue click lands in --
        every character's card is always shown at once, per the ТЗ's own example layout)."""
        if self.character_count > 1 and pb.is_character_slot(slot):
            name = pb.slot_name(slot, get_language())
            for i in range(1, self.character_count + 1):
                self._add_card(pb.character_key(slot, i), tr("pb.character_card_title", n=i, name=name))
        else:
            self._add_card(slot)

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
        lora_top = QTreeWidgetItem(["LoRA"])                        # a fixed tab: cannot be renamed or deleted, no tags are created in it
        lora_top.setData(0, ROLE, ("lora", None))
        font = lora_top.font(0)
        font.setBold(True)
        lora_top.setFont(0, font)
        self.tree.addTopLevelItem(lora_top)
        if current == ("lora", None):
            wanted = lora_top
        for group in ("", *bl.GROUPS):
            sub = QTreeWidgetItem([bl.group_name(group)])
            sub.setData(0, ROLE, ("lora", group))
            lora_top.addChild(sub)
            if current == ("lora", group):
                wanted = sub
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
        first = self.tree.topLevelItem(1)                       # the first paragraph ("quality"); item 0 is the LoRA tab
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
        if sel[0] == "lora":
            return "extra"
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

    def _lora_root(self) -> Path:
        return lo.root_dir(self.ctx.cfg)

    def _refresh_lora_grid(self, group: str | None) -> None:
        """The LoRA tab: the tiles of the LoRA files of one group (their card pictures load a few at a time, big folders must not freeze)."""
        rows = bl.lora_rows(self._lora_root(), group)
        needle = self.search.text().strip().lower()
        if needle:
            rows = [r for r in rows if needle in r["text"].lower()]
        self._rows = {}
        self.grid.clear()
        self._lora_queue = []
        for row in rows:
            item = QListWidgetItem(row["text"])
            item.setData(Qt.ItemDataRole.UserRole, row)
            item.setData(ROLE + 1, (LORA_MIME, [str(row["path"])]))
            item.setToolTip(row["text"] + ("\n" + row["folder"] if row["folder"] else "") + ("\n" + row["description"][:200] if row["description"] else ""))
            item.setIcon(QIcon(placeholder_pixmap(row["text"], self.tile)))
            item.setSizeHint(QSize(self.tile + 22, self.tile + 56))
            self.grid.addItem(item)
            self._lora_queue.append(item)
        root = self._lora_root()
        self.status.setText(tr("lora.count", n=len(rows)) if root.is_dir() else tr("lora.no_folder", path=str(root)))
        self._lora_timer.start()

    def _load_lora_thumbs(self) -> None:
        for _ in range(10):
            if not self._lora_queue:
                self._lora_timer.stop()
                return
            item = self._lora_queue.pop(0)
            try:
                row = item.data(Qt.ItemDataRole.UserRole)
                item.setIcon(tile_icon(self.book, row, self._lora_active(row["text"]), self.tile))
            except RuntimeError:                                       # the tile is gone (the view was refilled)
                continue

    def _lora_active(self, name: str) -> bool:
        group = bl.group_of_entry(name)
        return any(e.group == group for e in self.doc.entries("extra"))

    def _toggle_lora(self, row: dict) -> None:
        """A LoRA tile: the LoRA (as its card says: name, weight, keywords) goes into the "extra" paragraph, its negative text into the
        negative prompt; a second click takes both out."""
        group = bl.group_of_entry(row["text"])
        if self._lora_active(row["text"]):
            for slot in ("extra", "neg_unwanted"):
                self.doc.slots[slot] = [e for e in self.doc.entries(slot) if e.group != group]
        else:
            card = lo.load(row["path"], self._lora_root())
            self.doc.add("extra", card.prompt_text(), group=group)
            if card.negative.strip():
                self.doc.add("neg_unwanted", card.negative.strip(), group=group)
        self._doc_changed()

    def _refresh_grid(self) -> None:
        sel = self._selection()
        if sel is not None and sel[0] == "lora":
            self._refresh_lora_grid(sel[1])
            return
        rows, hidden = self._visible_tags(self._rows_for_view())
        self._rows = {r["id"]: r for r in rows}
        self.grid.clear()
        for row in rows:
            item = QListWidgetItem(display_label(row))
            item.setData(Qt.ItemDataRole.UserRole, row)
            item.setData(ROLE + 1, (TAG_MIME, [row["id"]]))
            item.setToolTip(row["text"] + ("\n" + pb.slot_name(row["slot"], get_language())))
            item.setIcon(tile_icon(self.book, row, self.doc.has(self._target_key(row["slot"]), row["text"]), self.tile))
            item.setSizeHint(QSize(self.tile + 22, self.tile + 56))
            self.grid.addItem(item)
        note = tr("pb.hidden", n=hidden) if hidden else ""
        self.status.setText((tr("pb.count", n=len(rows)) + ("  ·  " + note if note else "")))

    def _refresh_tiles(self) -> None:
        """Only the ring/check marks: the tiles stay where they are."""
        for i in range(self.grid.count()):
            item = self.grid.item(i)
            row = item.data(Qt.ItemDataRole.UserRole)
            if row.get("lora") and item in self._lora_queue:                 # its picture is not loaded yet: the loader will draw the mark
                continue
            active = self._lora_active(row["text"]) if row.get("lora") else self.doc.has(self._target_key(row["slot"]), row["text"])
            item.setIcon(tile_icon(self.book, row, active, self.tile))

    def _target_key(self, slot: str) -> str:
        """Where a click in the catalogue actually lands: the active character's own instance of a character slot
        (ui/prompt_builder.py's character switcher) once more than one is active, otherwise the slot itself."""
        if self.character_count > 1 and pb.is_character_slot(slot):
            return pb.character_key(slot, self.active_character)
        return slot

    def _tile_clicked(self, item: QListWidgetItem) -> None:
        row = item.data(Qt.ItemDataRole.UserRole)
        if row.get("lora"):
            self._toggle_lora(row)
            return
        key = self._target_key(row["slot"])
        self.doc.toggle(key, row["text"], group=str(row["group_id"]), exclusive=bool(row["exclusive"]), tag_id=row["id"])
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

    def _grouped_chips(self, slot: str) -> list[tuple[str, list[EntryChip]]]:
        """Entries of `slot` (a plain key, or a character's own composite key -- character_key()), grouped by
        subcategory (Entry.group is already the catalogue node's own id, as a string -- set for every
        catalogue-sourced entry when it is toggled/added; empty for a hand-typed one) and ordered the way the
        subcategories themselves appear in the tree. The catalogue itself only knows the BASE slot name -- a
        composite key has no pb_nodes rows of its own."""
        buckets: dict[str, list[Entry]] = {}
        for e in self.doc.entries(slot):
            buckets.setdefault(e.group, []).append(e)
        nodes = self.book.nodes(slot.split("::", 1)[0])
        seen = set()
        groups = []
        for n in nodes:
            gid = str(n["id"])
            if gid in buckets:
                groups.append((node_name(n), [self._chip_for(slot, e) for e in buckets[gid]]))
                seen.add(gid)
        other = [e for gid, es in buckets.items() if gid not in seen for e in es]
        if other:
            groups.append(("", [self._chip_for(slot, e) for e in other]))
        return groups

    def _refresh_doc(self) -> None:
        for key, card in self.cards.items():
            card.set_groups(self._grouped_chips(key))
        positive, negative = self.doc.positive(self.character_count), self.doc.negative(self.character_count)
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
        base = slot.split("::", 1)[0]                     # a character slot's own composite key is not itself a POSITIVE/NEGATIVE entry
        positive = base in pb.POSITIVE
        for key in (pb.POSITIVE if positive else pb.NEGATIVE):
            if key != base and key != slot:
                move.addAction(pb.slot_name(key, get_language()), lambda k=key: (self.doc.move_to_slot(slot, text, k), self._doc_changed()))
        menu.addSeparator()
        menu.addAction(tr("pb.chip.remove"), lambda: self._remove_entry(slot, text))
        menu.exec(pos)

    # --- form <-> builder ------------------------------------------------------------------------------------------------

    def push(self) -> None:
        """Send the assembled prompt to the Generate form."""
        positive, negative = self.doc.positive(self.character_count), self.doc.negative(self.character_count)
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
        self._last_pushed, self._dirty = (doc.positive(self.character_count), doc.negative(self.character_count)), False
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
        n = self.character_count
        positive, negative = self.doc.positive(n), self.doc.negative(n)
        QGuiApplication.clipboard().setText(positive + (f"\n\nNegative prompt: {negative}" if negative else ""))
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
        menu.addAction(tr("pb.regen_all"), self.regenerate_all)
        stop = menu.addAction(tr("pb.stop_drawing"), self.cancel_previews)
        stop.setEnabled(self.drawing)
        menu.addSeparator()
        menu.addAction(tr("pb.pack.export"), self._export_pack)
        menu.addAction(tr("pb.pack.import"), self._import_pack)
        menu.addSeparator()
        menu.addAction(tr("pb.catalog.export"), self._export_catalog)
        menu.addAction(tr("pb.catalog.import"), self._import_catalog)
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

    def _export_catalog(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, tr("pb.catalog.export"), "promptbook_catalog.zip", "ZIP (*.zip)")
        if not path:
            return
        try:
            n = self.book.export_catalog(self.ctx.cfg, Path(path))
        except OSError as exc:
            self.status.setText(tr("status.error", msg=str(exc)))
            return
        self.status.setText(tr("pb.catalog.exported", n=n, path=path))

    def _import_catalog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, tr("pb.catalog.import"), "", "ZIP (*.zip)")
        if not path:
            return
        try:
            counts = self.book.import_catalog(self.ctx.cfg, Path(path))
        except (pb.CatalogPackError, OSError) as exc:
            self.status.setText(tr("status.error", msg=str(exc)))
            return
        self.character_count = max(1, min(4, int(self.ctx.cfg.get("promptbuilder.character_count", 1) or 1)))
        self.active_character = min(self.active_character, self.character_count)
        self.character_spin.setValue(self.character_count)
        self._update_character_buttons()
        self._fill_tree()
        self._rebuild_cards()
        self._refresh_grid()
        self.status.setText(tr("pb.catalog.imported", nodes=counts["nodes"], tags=counts["tags"], images=counts["images"]))

    def _restore(self) -> None:
        self.book.restore_defaults()
        self._fill_tree()
        self._refresh_grid()

    def _tree_menu(self, pos: QPoint) -> None:
        item = self.tree.itemAt(pos)
        if item is not None:
            self.tree.setCurrentItem(item)
        sel = self._selection()
        if sel is None or sel[0] == "lora":                        # the LoRA tab has no menu: nothing in it can be created or deleted
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
            menu.addAction(tr("pb.edit_category"), lambda: self._edit_node(node))
            menu.addSeparator()
        if node is not None or sel[0] == "slot":
            menu.addAction(tr("pb.tree.previews"), self._previews_for_view)
            menu.addAction(tr("pb.tree.regen_view"), self._regenerate_view)
        if node is not None:
            menu.addAction(tr("pb.tree.delete"), lambda: self._delete_node(node))
        menu.addSeparator()
        menu.addAction(tr("pb.tree.new_section"), self._new_slot)
        menu.addAction(tr("pb.edit_section"), lambda: self._edit_slot(slot))
        if sel[0] == "slot" and pb.is_custom_slot(sel[1]):
            menu.addAction(tr("pb.tree.rename_section"), lambda: self._rename_slot(sel[1]))
            menu.addAction(tr("pb.tree.delete_section"), lambda: self._delete_slot(sel[1]))
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    def _edit_node(self, node: dict) -> None:
        dlg = NodeEditDialog(node_name(node), not bool(node["exclusive"]), self)
        if dlg.exec():
            name = dlg.name_edit.text().strip()
            if name:
                self.book.rename_node(node["id"], name)
            self.book.set_exclusive(node["id"], not dlg.multi_box.isChecked())
            self._fill_tree(("node", node["id"]))
            self._refresh_grid()

    def _edit_slot(self, key: str) -> None:
        is_custom = pb.is_custom_slot(key)
        dlg = SlotEditDialog(pb.slot_name(key, get_language()), pb.is_character_slot(key), is_custom, self)
        if dlg.exec():
            if is_custom:
                new_name = dlg.name_edit.text().strip()
                if new_name:
                    pb.rename_custom_slot(self.ctx.cfg, key, new_name)
            pb.set_character_flag(self.ctx.cfg, key, dlg.character_box.isChecked())
            self._rebuild_cards()
            self._fill_tree(("slot", key))
            self._refresh_grid()

    def _rebuild_cards(self) -> None:
        """Re-derives the right-side paragraph panel from pb.POSITIVE/pb.NEGATIVE (after a section was added,
        renamed, deleted or reordered, or the character count/a character flag changed) without losing what is
        already in negative_title (reused, not recreated)."""
        while self.cards_layout.count():
            item = self.cards_layout.takeAt(0)
            widget = item.widget()
            if widget is None:
                continue
            widget.setParent(None)
            if widget is not self.negative_title:
                widget.deleteLater()
        self.cards.clear()
        for key in pb.POSITIVE:
            self._add_cards_for(key)
        self.cards_layout.addSpacing(6)
        self.cards_layout.addWidget(self.negative_title)
        for key in pb.NEGATIVE:
            self._add_cards_for(key)
        self.cards_layout.addStretch(1)
        self._refresh_doc()

    def _set_character_count(self, value: int) -> None:
        self.character_count = max(1, min(4, int(value)))
        self.ctx.cfg.set("promptbuilder.character_count", self.character_count)
        if self.active_character > self.character_count:
            self._set_active_character(1)
        self._update_character_buttons()
        self._rebuild_cards()

    def _set_active_character(self, character: int) -> None:
        self.active_character = character
        self._update_character_buttons()

    def _update_character_buttons(self) -> None:
        for i, btn in enumerate(self.character_buttons, start=1):
            btn.setVisible(i <= self.character_count)
            block = btn.blockSignals(True)
            btn.setChecked(i == self.active_character)
            btn.blockSignals(block)

    def _new_slot(self) -> None:
        negative = self._current_slot() in pb.NEGATIVE
        name, ok = QInputDialog.getText(self, tr("pb.tree.new_section"), tr("pb.dlg.name"))
        name = name.strip()
        if ok and name:
            key = pb.add_custom_slot(self.ctx.cfg, name, negative)
            self._rebuild_cards()
            self._fill_tree(("slot", key))
            self._refresh_grid()

    def _rename_slot(self, key: str) -> None:
        name, ok = QInputDialog.getText(self, tr("pb.tree.rename_section"), tr("pb.dlg.name"),
                                        text=pb.slot_name(key, get_language()))
        name = name.strip()
        if ok and name:
            pb.rename_custom_slot(self.ctx.cfg, key, name)
            self._rebuild_cards()
            self._fill_tree(("slot", key))

    def _delete_slot(self, key: str) -> None:
        name = pb.slot_name(key, get_language())
        if QMessageBox.question(self, tr("pb.tree.delete_section"), tr("pb.confirm_delete", name=name)) == QMessageBox.StandardButton.Yes:
            pb.delete_custom_slot(self.ctx.cfg, key, self.doc)
            self._rebuild_cards()
            self._fill_tree()
            self._refresh_grid()

    def _slot_dropped(self, key: str, target) -> None:
        before = target[1] if target[0] == "slot" else None
        pb.reorder_slot(self.ctx.cfg, key, before)
        self._rebuild_cards()
        self._fill_tree(("slot", key))
        self._refresh_grid()

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
        sel = self._selection()
        if sel is not None and sel[0] == "lora":                   # a LoRA can only be sorted into a group (or opened in the LoRA editor)
            if item is not None:
                row = item.data(Qt.ItemDataRole.UserRole)
                move = menu.addMenu(tr("lora.category"))
                for group in ("", *bl.GROUPS):
                    action = move.addAction(bl.group_name(group), lambda g=group, r=row: self._set_lora_group([str(r["path"])], g))
                    action.setCheckable(True)
                    action.setChecked((row["category"] or "") == group)
                if self.form is not None and self.form.get("open_lora"):
                    menu.addAction(tr("pb.lora.open"), lambda r=row: self.form["open_lora"](r["path"]))
                menu.exec(self.grid.viewport().mapToGlobal(pos))
            return
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

    # --- moving things by dragging -------------------------------------------------------------------------------------

    def _tags_dropped(self, ids: list, target) -> None:
        moved = sum(1 for tag_id in ids if self.book.move_tag(int(tag_id), target[1]))
        self._refresh_grid()
        node = self.book.node(target[1])
        self.status.setText(tr("pb.moved", n=moved, name=node_name(node) if node else "") if moved else tr("pb.move_none"))

    def _node_dropped(self, node_id: int, target) -> None:
        ok = self.book.move_node(int(node_id), target[1], None) if target[0] == "node" else self.book.move_node(int(node_id), None, target[1])
        self._fill_tree(("node", int(node_id)) if ok else None)
        self._refresh_grid()
        if not ok:
            self.status.setText(tr("pb.move_none"))

    def _set_lora_group(self, paths: list, group: str) -> None:
        root = self._lora_root()
        for path in paths:
            try:
                lo.set_category(Path(path), root, group)
            except lo.LoraError as exc:
                self.status.setText(tr("status.error", msg=str(exc)))
                return
        self._refresh_grid()
        self.status.setText(tr("pb.moved", n=len(paths), name=bl.group_name(group)))

    def _loras_dropped(self, paths: list, target) -> None:
        self._set_lora_group(paths, target[1])

    # --- the standard character and the pictures of the tags -------------------------------------------------------------

    def character(self) -> dict:
        """The standard character every tag picture is drawn on (edited in the "Standard character" tab)."""
        return pb.character_from(self.ctx.cfg.get("promptbook.character"))

    def _api(self):
        return self.form["api"]() if self.form is not None and self.form.get("api") else None

    def _with_forge(self, action) -> None:
        """Runs `action(api)` with a running Forge: at once if there is one, else after asking to start it (and waiting until it answers)."""
        api = self._api()
        if api is not None:
            action(api)
            return
        start = self.form.get("start") if self.form is not None else None
        if start is None:
            self.status.setText(tr("pb.need_forge"))
            return
        if QMessageBox.question(self, tr("pb.start_forge_title"), tr("pb.start_forge")) != QMessageBox.StandardButton.Yes:
            return
        self.status.setText(tr("pb.forge_starting"))
        start()
        waited = {"n": 0}
        timer = QTimer(self, interval=2000)

        def check() -> None:
            waited["n"] += 1
            api = self._api()
            if api is not None:
                timer.stop()
                action(api)
            elif waited["n"] > 300:                                  # ten minutes
                timer.stop()
                self.status.setText(tr("pb.need_forge"))

        timer.timeout.connect(check)
        timer.start()

    def _generate_picture(self, row: dict) -> None:
        self._with_forge(lambda api: self._run_previews(api, [row]))

    def _previews_for_view(self) -> None:
        rows = [r for r in self._rows.values() if not r["image"]]
        if not rows:
            self.status.setText(tr("pb.previews.none"))
            return
        if QMessageBox.question(self, tr("pb.tree.previews"), tr("pb.previews.confirm", n=len(rows))) != QMessageBox.StandardButton.Yes:
            return
        self._with_forge(lambda api: self._run_previews(api, rows))

    def regenerate_all(self) -> None:
        """One click: every tag of the catalogue gets a new picture drawn on the standard character (the old ones are replaced)."""
        rows = [r for r in self.book.tags() if r["text"] not in pb.NO_PICTURE_TAGS]
        if QMessageBox.question(self, tr("pb.regen_all"), tr("pb.regen_confirm", n=len(rows))) != QMessageBox.StandardButton.Yes:
            return
        self._with_forge(lambda api: self._run_previews(api, rows))

    def _regenerate_view(self) -> None:
        """Like regenerate_all(), but only the tags of whichever group/subgroup is open in the tree right now get a
        new picture (the old ones are replaced) -- for touching up one category without waiting through the whole
        catalogue."""
        rows = [r for r in self._rows.values() if r["text"] not in pb.NO_PICTURE_TAGS]
        if not rows:
            self.status.setText(tr("pb.regen_view.empty"))
            return
        if QMessageBox.question(self, tr("pb.tree.regen_view"), tr("pb.regen_confirm", n=len(rows))) != QMessageBox.StandardButton.Yes:
            return
        self._with_forge(lambda api: self._run_previews(api, rows))

    def _run_previews(self, api, rows: list[dict]) -> None:
        """Draws a picture per tag with the running Forge on the standard character, one after another (Stop: "More" > Stop drawing)."""
        self._cancel_previews = False
        keys = {n["id"]: n["key"] or "" for n in self.book.nodes(include_hidden=True)}
        maker = PictureMaker(api, self.character())

        def work() -> int:
            done = 0
            for i, row in enumerate(rows, 1):
                if self._cancel_previews:
                    break
                self._preview_progress.emit(i, len(rows), row["text"])
                try:
                    self._preview_image.emit(row["id"], maker.draw(row, keys.get(row["group_id"], "")))
                    done += 1
                except ValueError:                                     # the configured checkpoint does not exist: nothing can be drawn
                    raise
                except Exception:  # noqa: BLE001 - one failed picture must not stop the rest
                    continue
            return done

        self.drawing = True
        run_async(work, on_done=lambda n: (setattr(self, "drawing", False), self.status.setText(tr("pb.previews.done", n=n))),
                  on_error=lambda exc: (setattr(self, "drawing", False), self.status.setText(tr("status.error", msg=str(exc)))))

    def _on_preview_progress(self, i: int, total: int, name: str) -> None:
        self.status.setText(tr("pb.previews.progress", i=i, total=total, name=name))

    def _on_preview_image(self, tag_id: int, data: bytes) -> None:
        self.book.set_image(tag_id, data)
        for i in range(self.grid.count()):                              # only that tile is redrawn: 600 pictures must not refill the grid 600 times
            item = self.grid.item(i)
            row = item.data(Qt.ItemDataRole.UserRole)
            if not row.get("lora") and row["id"] == tag_id:
                row["image"] = self.book.tag(tag_id)["image"]
                item.setIcon(tile_icon(self.book, row, self.doc.has(self._target_key(row["slot"]), row["text"]), self.tile))
                break
        self._refresh_doc()

    def cancel_previews(self) -> None:
        self._cancel_previews = True
