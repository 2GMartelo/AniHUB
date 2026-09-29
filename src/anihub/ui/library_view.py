"""Library manager: sidebar (categories, collections, smart tags, trash), search with tag autocomplete, sorting,
star ratings, bulk actions, hover preview and the bridge to img2img."""
from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor, QIcon, QImage, QPixmap
from PySide6.QtWidgets import (
    QComboBox, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidgetItem, QMenu, QMessageBox, QPushButton, QSplitter,
    QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from anihub.context import AppContext
from anihub.core.db import SORTS
from anihub.core.i18n import tr
from anihub.sources.base import RATINGS, VIDEO_EXTS, badge_for_ext
from anihub.ui import icons, style, theme
from anihub.ui.grid import PAYLOAD, ThumbGrid, image_to_thumb
from anihub.ui.library_dialogs import DuplicatesDialog, ImportDialog, TagEditDialog, TagManagerDialog
from anihub.ui.compare import CompareDialog
from anihub.ui.integrity_dialog import IntegrityDialog
from anihub.ui.rules_dialog import RulesDialog
from anihub.ui.stats_dialog import StatsDialog
from anihub.ui.tag_widgets import tag_line_edit
from anihub.ui.tagquery import apply_tag
from anihub.ui.viewer import ViewItem, Viewer
from anihub.ui.workers import run_async, run_status

PAGE = 200
ROLE = Qt.ItemDataRole.UserRole


def split_query(text: str) -> tuple[list[str], list[str]]:
    include = [t.lower() for t in text.split() if not t.startswith("-")]
    exclude = [t[1:].lower() for t in text.split() if t.startswith("-") and len(t) > 1]
    return include, exclude


def row_prompt(ctx: AppContext, row: sqlite3.Row | dict) -> tuple[str, str]:
    """(prompt, negative prompt) to prefill img2img from a library item."""
    if row["meta"]:
        meta = json.loads(row["meta"])
        if meta.get("prompt"):
            return meta["prompt"], meta.get("negative_prompt", "")
    tags = [n.replace("_", " ") for n, cat in ctx.db.item_tags_categorized(row["id"]) if cat != "meta"]
    return ", ".join(tags[:60]), ""


class LibraryView(QWidget):
    send_to_img2img = Signal(dict)  # the library row of the chosen item
    send_to_vtube = Signal(Path)
    changed = Signal()

    def __init__(self, ctx: AppContext, kind: str = "art", parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.kind = kind  # art | sd | manga: each content type has its own section
        self.mode: tuple[str, object] = ("all", None)  # all | favorites | category | collection | smart | trash
        self._gen = 0
        self._offset = 0
        self._loading = False
        self._exhausted = False
        self._total = 0
        self._viewers: list[Viewer] = []
        cfg = ctx.cfg

        # --- sidebar
        self.side = QTreeWidget()
        self.side.setHeaderHidden(True)
        self.side.setMinimumWidth(190)
        self.side.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)

        # --- toolbar
        self.query = tag_line_edit(ctx.db, tr("search.placeholder"))
        self.search_btn = QPushButton(tr("search.button"))
        self.sort = QComboBox()
        for key in SORTS:
            self.sort.addItem(tr(f"sort.{key}"), key)
        self.sort.setCurrentIndex(max(self.sort.findData(cfg.get("library.sort", "added")), 0))
        self.order_btn = QPushButton("↓" if cfg.get("library.desc", True) else "↑")
        self.order_btn.setFixedWidth(44)
        self.order_btn.setToolTip(tr("sort.order"))
        self.stars_filter = QComboBox()
        self.stars_filter.addItem(tr("lib.any_stars"), 0)
        for n in range(1, 6):
            self.stars_filter.addItem("★" * n + "+", n)
        self.import_btn = QPushButton(tr("lib.import"))
        self.import_btn.setVisible(kind == "art")
        self.tools_btn = QPushButton(tr("lib.tools"))
        self.actions_btn = QPushButton(tr("lib.actions"))
        self.selection_label = QLabel()
        style.primary(self.search_btn, "search")
        style.secondary(self.import_btn, "upload")
        style.secondary(self.tools_btn, "wrench")
        style.secondary(self.actions_btn, "more")
        self.tools_btn.setText(self.tools_btn.text() + "  ▾")
        self.actions_btn.setText(self.actions_btn.text() + "  ▾")
        style.role(self.selection_label, "dim")
        self.query.addAction(icons.icon("search", size=16), QLineEdit.ActionPosition.LeadingPosition)
        self.side.setObjectName("sideTree")
        top = QHBoxLayout()
        top.setSpacing(8)
        for w, s in ((self.query, 1), (self.search_btn, 0), (self.sort, 0), (self.order_btn, 0), (self.stars_filter, 0),
                     (self.import_btn, 0), (self.tools_btn, 0)):
            top.addWidget(w, s)
        second = QHBoxLayout()
        second.addWidget(self.actions_btn)
        second.addWidget(self.selection_label, 1)

        self.grid = ThumbGrid(cfg.get("ui.thumb_size", 180))
        self.grid.hover_loader = self._hover_loader
        self.status = style.role(QLabel(), "dim")
        self.grid.set_empty("image", tr("lib.empty_title"), tr("lib.empty_hint"))
        main = QWidget()
        ml = QVBoxLayout(main)
        ml.setContentsMargins(0, 0, 0, 0)
        ml.addLayout(top)
        ml.addLayout(second)
        ml.addWidget(self.grid, 1)
        ml.addWidget(self.status)
        split = QSplitter()
        split.addWidget(self.side)
        split.addWidget(main)
        split.setStretchFactor(1, 1)
        split.setSizes([210, 900])
        QVBoxLayout(self).addWidget(split)
        self.tools_menu = QMenu(self)
        self.tools_btn.setMenu(self.tools_menu)
        self.tools_menu.aboutToShow.connect(self._build_tools_menu)
        self.actions_menu = QMenu(self)
        self.actions_btn.setMenu(self.actions_menu)
        self.actions_menu.aboutToShow.connect(lambda: self._fill_menu(self.actions_menu))

        self.search_btn.clicked.connect(self.reload)
        self.query.returnPressed.connect(self.reload)
        self.sort.activated.connect(self._sort_changed)
        self.order_btn.clicked.connect(self._toggle_order)
        self.stars_filter.activated.connect(self.reload)
        self.import_btn.clicked.connect(self._import)
        self.grid.need_more.connect(self._load_page)
        self.grid.itemDoubleClicked.connect(self._open_viewer)
        self.grid.itemSelectionChanged.connect(self._selection_changed)
        self.grid.context_requested.connect(self._grid_context)
        self.grid.delete_pressed.connect(self._delete_key)
        self.side.currentItemChanged.connect(self._sidebar_selected)
        self.side.customContextMenuRequested.connect(self._sidebar_menu)
        self.refresh_sidebar()
        self.reload()

    # --- sidebar ---------------------------------------------------------------------------------------

    def _add_side(self, parent, text: str, key: tuple, bold: bool = False) -> QTreeWidgetItem:
        item = QTreeWidgetItem([text])
        item.setData(0, ROLE, key)
        if bold:  # section headers: small, quiet
            font = item.font(0)
            font.setBold(True)
            font.setPointSizeF(font.pointSizeF() - 1)
            item.setFont(0, font)
            item.setForeground(0, QBrush(QColor(theme.current().dim)))
        (parent.addChild if parent is not None else self.side.addTopLevelItem)(item)
        return item

    def refresh_sidebar(self) -> None:
        db, kind = self.ctx.db, self.kind
        self.side.blockSignals(True)
        self.side.clear()
        self._add_side(None, f"{tr('lib.all')} ({db.count_items(kind)})", ("all", None))
        self._add_side(None, "♥ " + tr("lib.favorites"), ("favorites", None))
        cats = self._add_side(None, tr("lib.categories"), ("header", "category"), bold=True)
        counts = db.category_counts(kind)
        for c in db.categories(kind):
            label = f"{c['name']} ({counts.get(c['id'], 0)})" + (f"  · {tr('lib.default')}" if c["is_default"] else "")
            self._add_side(cats, label, ("category", c["id"]))
        cols = self._add_side(None, tr("lib.collections"), ("header", "collection"), bold=True)
        counts = db.collection_counts(kind)
        for c in db.collections(kind):
            self._add_side(cols, f"{c['name']} ({counts.get(c['id'], 0)})", ("collection", c["id"]))
        smart = self._add_side(None, tr("lib.smart"), ("header", "smart"), bold=True)
        for _sid, name, _tags in db.smart_tags():
            self._add_side(smart, f"@{name}", ("smart", name))
        self._add_side(None, f"🗑 {tr('lib.trash')} ({db.count_search(kind=kind, trashed=True)})", ("trash", None))
        self.side.expandAll()
        self.side.blockSignals(False)
        self._select_current_in_sidebar()

    def _select_current_in_sidebar(self) -> None:
        def walk(item):
            if item.data(0, ROLE) == self.mode:
                return item
            for i in range(item.childCount()):
                found = walk(item.child(i))
                if found:
                    return found
            return None

        for i in range(self.side.topLevelItemCount()):
            found = walk(self.side.topLevelItem(i))
            if found:
                self.side.blockSignals(True)
                self.side.setCurrentItem(found)
                self.side.blockSignals(False)
                return

    def _sidebar_selected(self, item: QTreeWidgetItem | None) -> None:
        if item is None:
            return
        key = item.data(0, ROLE)
        if key[0] == "header":
            return
        self.mode = key
        self.reload()

    def _sidebar_menu(self, pos) -> None:
        item = self.side.itemAt(pos)
        if item is None:
            return
        kind_, value = item.data(0, ROLE)
        menu = QMenu(self)
        db = self.ctx.db
        if kind_ == "header" and value == "category":
            menu.addAction(tr("lib.new_category"), lambda: self._new_named("category"))
        elif kind_ == "header" and value == "collection":
            menu.addAction(tr("lib.new_collection"), lambda: self._new_named("collection"))
        elif kind_ == "header" and value == "smart":
            menu.addAction(tr("tags.manager") + "...", self._tag_manager)
        elif kind_ == "category":
            menu.addAction(tr("lib.rename"), lambda: self._rename_named("category", value))
            is_default = db.default_category(self.kind) == value
            menu.addAction(tr("lib.unset_default") if is_default else tr("lib.set_default"),
                           lambda: (db.set_default_category(None if is_default else value, self.kind), self.refresh_sidebar()))
            menu.addAction(tr("lib.move_up"), lambda: self._move_category(value, -1))
            menu.addAction(tr("lib.move_down"), lambda: self._move_category(value, 1))
            menu.addAction(tr("lib.delete"), lambda: self._delete_named("category", value))
        elif kind_ == "collection":
            menu.addAction(tr("lib.rename"), lambda: self._rename_named("collection", value))
            menu.addAction(tr("export.collection"), lambda: self._export_collection(value))
            menu.addAction(tr("lib.delete"), lambda: self._delete_named("collection", value))
        elif kind_ == "smart":
            menu.addAction(tr("tags.manager") + "...", self._tag_manager)
        elif kind_ == "trash":
            menu.addAction(tr("lib.empty_trash"), self._empty_trash)
        if not menu.isEmpty():
            menu.exec(self.side.viewport().mapToGlobal(pos))

    def _new_named(self, what: str) -> None:
        name, ok = QInputDialog.getText(self, tr(f"lib.new_{what}"), tr("lib.name"))
        name = name.strip()
        if ok and name:
            try:
                (self.ctx.db.create_category if what == "category" else self.ctx.db.create_collection)(name, self.kind)
            except sqlite3.IntegrityError:
                QMessageBox.information(self, tr(f"lib.new_{what}"), tr("lib.name_exists"))
            self.refresh_sidebar()

    def _rename_named(self, what: str, ident: int) -> None:
        name, ok = QInputDialog.getText(self, tr("lib.rename"), tr("lib.name"))
        name = name.strip()
        if ok and name:
            try:
                (self.ctx.db.rename_category if what == "category" else self.ctx.db.rename_collection)(ident, name)
            except sqlite3.IntegrityError:
                QMessageBox.information(self, tr("lib.rename"), tr("lib.name_exists"))
            self.refresh_sidebar()

    def _delete_named(self, what: str, ident: int) -> None:
        if QMessageBox.question(self, tr("lib.delete"), tr(f"lib.delete_{what}_confirm")) != QMessageBox.StandardButton.Yes:
            return
        (self.ctx.db.delete_category if what == "category" else self.ctx.db.delete_collection)(ident)
        if self.mode == (what, ident):
            self.mode = ("all", None)
        self.refresh_sidebar()
        self.reload()

    def _move_category(self, ident: int, delta: int) -> None:
        ids = [c["id"] for c in self.ctx.db.categories(self.kind)]
        i = ids.index(ident)
        j = i + delta
        if 0 <= j < len(ids):
            ids[i], ids[j] = ids[j], ids[i]
            self.ctx.db.reorder_categories(ids)
            self.refresh_sidebar()

    # --- toolbar ---------------------------------------------------------------------------------------

    def _sort_changed(self) -> None:
        self.ctx.cfg.set("library.sort", self.sort.currentData())
        self.reload()

    def _toggle_order(self) -> None:
        desc = self.order_btn.text() != "↓"
        self.order_btn.setText("↓" if desc else "↑")
        self.ctx.cfg.set("library.desc", desc)
        self.reload()

    def _build_tools_menu(self) -> None:
        m = self.tools_menu
        m.clear()
        m.addAction(tr("tags.manager") + "...", self._tag_manager)
        m.addAction(tr("rules.title") + "...", self._rules)
        if self.kind == "art":
            m.addAction(tr("dup.title") + "...", self._duplicates)
        m.addAction(tr("lib.autotag_all"), self._autotag_untagged)
        m.addAction(tr("integrity.title") + "...", self._integrity)
        m.addAction(tr("stats.title") + "...", self._stats)
        m.addAction(tr("export.import_pack"), self._import_pack)
        m.addSeparator()
        m.addAction(tr("lib.empty_trash"), self._empty_trash)

    def _tag_manager(self) -> None:
        dlg = TagManagerDialog(self.ctx, self)
        dlg.changed.connect(lambda: (self.refresh_sidebar(), self.reload()))
        dlg.exec()
        self.refresh_sidebar()

    # --- export / share (п. 6.16, 6.18) ---------------------------------------------------------------------

    def _export_collection(self, collection_id: int) -> None:
        rows = self.ctx.db.search_items(kind=self.kind, collection_id=collection_id, limit=100000)
        name = next((c["name"] for c in self.ctx.db.collections(self.kind) if c["id"] == collection_id), "collection")
        self._export([r["id"] for r in rows], "pack", name)

    def _export(self, ids: list[int], how: str, name: str = "") -> None:
        from PySide6.QtWidgets import QFileDialog

        from anihub.services import export

        title = name or tr("export.default_name")
        path, _ = QFileDialog.getSaveFileName(self, tr("export.menu"), f"{title}.zip", "ZIP (*.zip)")
        if not path:
            return
        db, paths = self.ctx.db, self.ctx.paths
        fn = export.export_pack if how == "pack" else export.export_html
        self.status.setText(tr("status.loading"))
        run_status(lambda: fn(db, paths, ids, Path(path), title),
                  on_done=lambda n: self.status.setText(tr("export.done", n=n, path=path)), status=self.status)

    def _import_pack(self) -> None:
        from PySide6.QtWidgets import QFileDialog

        from anihub.services import export

        path, _ = QFileDialog.getOpenFileName(self, tr("export.import_pack"), "", "ZIP (*.zip)")
        if not path:
            return
        self.status.setText(tr("status.loading"))

        def done(result: dict) -> None:
            self.status.setText(tr("export.imported", name=result["name"], saved=result["saved"], dup=result["duplicate"], failed=result["failed"]))
            self.refresh_sidebar()
            self.reload()
            self.changed.emit()

        run_status(lambda: export.import_pack(self.ctx.db, self.ctx.library, Path(path)), on_done=done, status=self.status)

    def _stats(self) -> None:
        StatsDialog(self.ctx, self).exec()

    def _integrity(self) -> None:
        dlg = IntegrityDialog(self.ctx, self)
        dlg.changed.connect(lambda: (self.refresh_sidebar(), self.reload(), self.changed.emit()))
        dlg.exec()

    def _rules(self) -> None:
        dlg = RulesDialog(self.ctx, self)
        dlg.changed.connect(lambda: (self.refresh_sidebar(), self.reload(), self.changed.emit()))
        dlg.exec()
        self.refresh_sidebar()

    def _duplicates(self) -> None:
        dlg = DuplicatesDialog(self.ctx, self.kind, self)
        dlg.changed.connect(lambda: (self.refresh_sidebar(), self.reload(), self.changed.emit()))
        dlg.exec()

    def _import(self) -> None:
        dlg = ImportDialog(self.ctx, self)
        dlg.imported.connect(lambda: (self.refresh_sidebar(), self.reload(), self.changed.emit()))
        dlg.exec()

    def _autotag_untagged(self) -> None:
        if self.ctx.library.tagger is None:
            QMessageBox.information(self, tr("lib.autotag_all"), tr("import.autotag_off"))
            return
        ids = [r["id"] for r in self.ctx.db.conn.execute(
            "SELECT i.id FROM items i WHERE i.kind=? AND i.trashed_at IS NULL AND i.ext NOT IN ('mp4','webm','mkv','mov','zip') "
            "AND NOT EXISTS (SELECT 1 FROM item_tags it WHERE it.item_id=i.id)", (self.kind,))]
        self._run_autotag(ids)

    # --- loading ---------------------------------------------------------------------------------------

    def _search_args(self) -> dict:
        include, exclude = split_query(self.query.text())
        mode, value = self.mode
        args = dict(include=include, exclude=exclude, kind=self.kind, sort=self.sort.currentData(),
                    desc=self.order_btn.text() == "↓", min_stars=self.stars_filter.currentData(),
                    ratings=None if mode == "trash" else self.ctx.allowed_ratings())
        if mode == "favorites":
            args["favorites"] = True
        elif mode == "category":
            args["category_id"] = value
        elif mode == "collection":
            args["collection_id"] = value
        elif mode == "smart":
            args["include"] = include + [f"@{value}"]
        elif mode == "trash":
            args["trashed"] = True
        return args

    def reload(self) -> None:
        self._gen += 1
        self.grid.clear_items()
        self._offset, self._loading, self._exhausted = 0, False, False
        self._load_page()

    def _load_page(self) -> None:
        if self._loading or self._exhausted:
            return
        self._loading = True
        gen, offset, args = self._gen, self._offset, self._search_args()

        def work():
            db = self.ctx.db
            rows = db.search_items(limit=PAGE, offset=offset, **args)
            total = db.count_search(**{k: v for k, v in args.items() if k not in ("sort", "desc")}) if offset == 0 else None
            return rows, total

        def done(result) -> None:
            if gen != self._gen:
                return
            rows, total = result
            if total is not None:
                self._total = total
            self._loading = False
            self._offset += len(rows)
            self._exhausted = len(rows) < PAGE
            for row in rows:
                self.grid.add_entry(row, self._tooltip(row), lambda r=row: self._thumb(r))
            self._update_status()
            if rows and not self._exhausted:
                self.grid.request_fill()

        def failed(exc: Exception) -> None:
            if gen == self._gen:
                self._loading = False
                self.status.setText(tr("status.error", msg=str(exc)))

        run_async(work, on_done=done, on_error=failed)

    def _update_status(self) -> None:
        text = tr("lib.count", shown=self.grid.count(), total=self._total)
        if self.mode[0] == "trash":
            text += "  ·  " + tr("lib.trash_hint", days=int(self.ctx.cfg.get("library.trash_days", 7) or 0))
        self.status.setText(text)

    def _file_of(self, row: sqlite3.Row):
        return self.ctx.paths.root / (row["trash_path"] if row["trashed_at"] and row["trash_path"] else row["path"])

    @staticmethod
    def _mark(row: sqlite3.Row) -> str:
        return ("♥ " if row["favorite"] else "") + (f"★{row['stars']}" if row["stars"] else "")

    def _thumb(self, row: sqlite3.Row):
        size, badge, mark = self.grid.thumb_size, badge_for_ext(row["ext"]), self._mark(row)
        cache = self.ctx.paths.thumbs / f"{row['id']}_{size}.jpg"
        if cache.exists():
            return image_to_thumb(cache, size, badge, mark)
        # Videos have no still frame Qt can read: use the site preview saved together with the item.
        source = self.ctx.paths.preview_file(row["id"]) if row["ext"] in VIDEO_EXTS else self._file_of(row)
        if not source.exists():
            return None
        img = image_to_thumb(source, size)  # cache the clean thumbnail, stamp the marks on top
        if img is None:
            return None
        img.save(str(cache), "JPG", 85)
        return image_to_thumb(cache, size, badge, mark)

    def _hover_loader(self, row: sqlite3.Row):
        source = self.ctx.paths.preview_file(row["id"]) if row["ext"] in VIDEO_EXTS else self._file_of(row)

        def load() -> QImage | None:
            image = QImage(str(source))
            return None if image.isNull() else image

        return load

    @staticmethod
    def _tooltip(row: sqlite3.Row) -> str:
        if row["source_site"] == "forge" or row["meta"]:       # generated here, or its PNG carried the parameters
            meta = json.loads(row["meta"] or "{}")
            return f"seed {meta.get('seed')} · {row['rating']}\n{meta.get('prompt', '')[:200]}"
        return f"#{row['source_post_id']}  {row['rating']}  {row['width'] or '?'}×{row['height'] or '?'}\n{row['author'] or ''}"

    # --- selection & actions -------------------------------------------------------------------------

    def _selected(self) -> list[sqlite3.Row]:
        return self.grid.selected_payloads()

    def _selection_changed(self) -> None:
        n = len(self._selected())
        self.selection_label.setText(tr("lib.selected", n=n) if n else "")

    def _grid_context(self, pos) -> None:
        if not self._selected():
            return
        menu = QMenu(self)
        self._fill_menu(menu)
        menu.exec(pos)

    def _delete_key(self) -> None:
        rows = self._selected()
        if rows:
            (self._purge if self.mode[0] == "trash" else self._trash)([r["id"] for r in rows])

    def _fill_menu(self, menu: QMenu) -> None:
        menu.clear()
        rows = self._selected()
        if not rows:
            menu.addAction(tr("lib.select_first")).setEnabled(False)
            return
        ids = [r["id"] for r in rows]
        db, kind = self.ctx.db, self.kind
        if self.mode[0] == "trash":
            menu.addAction(tr("lib.restore"), lambda: self._restore(ids))
            menu.addAction(tr("lib.purge"), lambda: self._purge(ids))
            return
        menu.addAction(tr("lib.edit_tags"), lambda: self._edit_tags(ids))
        if self.ctx.library.tagger is not None:
            menu.addAction(tr("lib.autotag"), lambda: self._run_autotag(ids))
        cols = menu.addMenu(tr("lib.to_collection"))
        for c in db.collections(kind):
            cols.addAction(c["name"], lambda cid=c["id"]: self._to_collection(ids, cid))
        cols.addSeparator()
        cols.addAction(tr("lib.new_collection") + "...", lambda: self._to_new_collection(ids))
        if self.mode[0] == "collection":
            menu.addAction(tr("lib.remove_from_collection"),
                           lambda: (db.remove_from_collection(ids, self.mode[1]), self._after(True)))
        cats = menu.addMenu(tr("lib.to_category"))
        for c in db.categories(kind):
            cats.addAction(c["name"], lambda cid=c["id"]: (db.set_item_categories(ids, add=[cid]),
                                                           self._after(self.mode[0] == "category", ids)))
        if self.mode[0] == "category":
            menu.addAction(tr("lib.remove_from_category"),
                           lambda: (db.set_item_categories(ids, remove=[self.mode[1]]), self._after(True)))
        rating = menu.addMenu(tr("lib.content_rating"))
        for r in RATINGS:
            rating.addAction(tr(f"rating.{r}"), lambda r=r: (db.set_field(ids, "rating", r), self._after(True)))
        stars = menu.addMenu(tr("lib.stars"))
        for n in range(0, 6):
            stars.addAction("★" * n if n else tr("lib.no_stars"),
                            lambda n=n: (db.set_field(ids, "stars", n), self._after(self.stars_filter.currentData() > 0, ids)))
        all_fav = all(r["favorite"] for r in rows)
        menu.addAction(tr("lib.unfavorite") if all_fav else tr("lib.favorite"),
                       lambda: (db.set_field(ids, "favorite", 0 if all_fav else 1),
                                self._after(self.mode[0] == "favorites", ids)))
        if len(rows) == 2 and all(r["ext"] not in ("mp4", "webm", "mkv", "mov") for r in rows):
            menu.addAction(tr("compare.action"), lambda: self._compare(rows))
        export = menu.addMenu(tr("export.menu"))
        export.addAction(tr("export.pack"), lambda: self._export(ids, "pack"))
        export.addAction(tr("export.html"), lambda: self._export(ids, "html"))
        if len(rows) == 1:
            if self.ctx.sd_enabled:                                     # no generation on this computer: no img2img
                menu.addAction(tr("lib.to_img2img"), lambda: self.send_to_img2img.emit(dict(rows[0])))
            if self.ctx.vtube_enabled:
                menu.addAction(tr("vtube.send"), lambda: self.send_to_vtube.emit(self._file_of(rows[0])))
            menu.addAction(tr("lib.show_folder"), lambda: os.startfile(self._file_of(rows[0]).parent))
            if rows[0]["ext"] not in VIDEO_EXTS:
                menu.addAction(tr("lib.upload_rule34"), lambda: self._upload_rule34(rows[0]))
        menu.addSeparator()
        menu.addAction(tr("lib.trash_action"), lambda: self._trash(ids))

    def _compare(self, rows: list[sqlite3.Row]) -> None:
        first, second = sorted(rows, key=lambda r: (r["added_at"], r["id"]))  # the older one is the "before"
        dlg = CompareDialog((self._file_of(first), first["path"].rsplit("/", 1)[-1]),
                            (self._file_of(second), second["path"].rsplit("/", 1)[-1]), self)
        dlg.exec()

    def _after(self, affects_filter: bool, ids: list[int] | None = None) -> None:
        """Refresh after a change: in place (keeps the scroll position) unless it can alter what is listed."""
        self.changed.emit()
        if affects_filter or ids is None:
            self.refresh_sidebar()
            self.reload()
            return
        wanted = set(ids)
        for i in range(self.grid.count()):
            item = self.grid.item(i)
            row = item.data(PAYLOAD)
            if row["id"] in wanted:
                fresh = self.ctx.db.get_item(row["id"])
                item.setData(PAYLOAD, fresh)
                self._rethumb(item, fresh)
        self.refresh_sidebar()

    def _rethumb(self, item: QListWidgetItem, row: sqlite3.Row) -> None:
        run_async(lambda: self._thumb(row),
                  on_done=lambda img: img is not None and item.setIcon(QIcon(QPixmap.fromImage(img))))

    def _edit_tags(self, ids: list[int]) -> None:
        if TagEditDialog(self.ctx, ids, self).exec():
            self._after(bool(self.query.text().strip()) or self.mode[0] == "smart", ids)

    def _to_collection(self, ids: list[int], cid: int) -> None:
        self.ctx.db.add_to_collection(ids, cid)
        self._after(self.mode[0] == "collection", ids)

    def _to_new_collection(self, ids: list[int]) -> None:
        name, ok = QInputDialog.getText(self, tr("lib.new_collection"), tr("lib.name"))
        name = name.strip()
        if not (ok and name):
            return
        try:
            cid = self.ctx.db.create_collection(name, self.kind)
        except sqlite3.IntegrityError:  # already exists: just add to it
            cid = next(c["id"] for c in self.ctx.db.collections(self.kind) if c["name"] == name)
        self._to_collection(ids, cid)

    def _upload_rule34(self, row: sqlite3.Row) -> None:
        from anihub.ui.rule34_upload_dialog import Rule34UploadDialog

        Rule34UploadDialog(self.ctx, self._file_of(row), self).exec()

    def _run_autotag(self, ids: list[int]) -> None:
        self.status.setText(tr("lib.autotagging", n=len(ids)))
        run_status(lambda: self.ctx.library.autotag_items(ids, set_rating=False),
                  on_done=lambda n: (self.status.setText(tr("lib.autotagged", n=n)), self.reload()), status=self.status)

    # --- trash ---------------------------------------------------------------------------------------

    def _confirm_trash(self, n: int) -> bool:
        if not self.ctx.cfg.get("ui.confirm_trash", True):
            return True
        box = QMessageBox(self)
        box.setWindowTitle(tr("lib.trash_action"))
        box.setText(tr("lib.trash_confirm", n=n))
        yes = box.addButton(tr("lib.yes"), QMessageBox.ButtonRole.YesRole)
        always = box.addButton(tr("lib.yes_always"), QMessageBox.ButtonRole.YesRole)
        box.addButton(tr("lib.no"), QMessageBox.ButtonRole.NoRole)
        box.exec()
        clicked = box.clickedButton()
        if clicked is always:
            self.ctx.cfg.set("ui.confirm_trash", False)
        return clicked in (yes, always)

    def _trash(self, ids: list[int]) -> None:
        if ids and self._confirm_trash(len(ids)):
            self._file_op(lambda: self.ctx.library.trash(ids),
                          undo=(tr("lib.trash_action"), lambda: self.ctx.library.restore(ids), lambda: self.ctx.library.trash(ids)))

    def _restore(self, ids: list[int]) -> None:
        self._file_op(lambda: self.ctx.library.restore(ids),
                      undo=(tr("lib.restore"), lambda: self.ctx.library.trash(ids), lambda: self.ctx.library.restore(ids)))

    def _purge(self, ids: list[int]) -> None:
        if QMessageBox.question(self, tr("lib.purge"), tr("lib.purge_confirm", n=len(ids))) == QMessageBox.StandardButton.Yes:
            self._file_op(lambda: self.ctx.library.purge(ids))  # permanent: nothing to undo

    def _empty_trash(self) -> None:
        n = self.ctx.db.count_search(kind=self.kind, trashed=True)
        if n and QMessageBox.question(self, tr("lib.empty_trash"), tr("lib.purge_confirm", n=n)) == QMessageBox.StandardButton.Yes:
            self._file_op(lambda: self.ctx.library.empty_trash(self.kind))  # permanent: nothing to undo

    def _file_op(self, fn, undo: tuple[str, object, object] | None = None) -> None:
        def done(_n) -> None:
            self.refresh_sidebar()
            self.reload()
            self.changed.emit()
            if undo is not None:
                label, undo_fn, redo_fn = undo
                self.ctx.undo.push(label, lambda: self._run_silently(undo_fn), lambda: self._run_silently(redo_fn))

        run_status(fn, on_done=done, status=self.status)

    def _run_silently(self, fn) -> None:
        """Re-apply an undo/redo step (already confirmed once, by the action that pushed it) and refresh the view."""
        run_status(fn, on_done=lambda _n: (self.refresh_sidebar(), self.reload(), self.changed.emit()), status=self.status)

    # --- viewer ----------------------------------------------------------------------------------------

    def _view_item(self, row: sqlite3.Row) -> ViewItem:
        path = self._file_of(row)
        tags = self.ctx.db.item_tags_categorized(row["id"])
        if row["source_site"] == "forge" or row["meta"]:
            meta = json.loads(row["meta"] or "{}")
            info = meta.get("infotext") or json.dumps(meta, ensure_ascii=False)
        else:
            info = (f"{row['source_site']} #{row['source_post_id']} · {row['rating']}"
                    + (f" · {row['author']}" if row["author"] else "") + (f" · ★{row['stars']}" if row["stars"] else ""))
        return ViewItem(path.name, info, lambda: path, row["page_url"] or "", tags, row,
                        favorite=bool(row["favorite"]), stars=int(row["stars"] or 0))

    def _open_viewer(self, item: QListWidgetItem) -> None:
        rows = self.grid.payloads()
        dirty = []

        def favorite(view_item: ViewItem, value: bool) -> None:
            self.ctx.db.set_field([view_item.payload["id"]], "favorite", int(value))
            dirty.append(1)

        def stars(view_item: ViewItem, value: int) -> None:
            self.ctx.db.set_field([view_item.payload["id"]], "stars", value)
            dirty.append(1)

        viewer = Viewer([self._view_item(r) for r in rows], self.grid.row(item), on_favorite=favorite, on_stars=stars, ctx=self.ctx)
        viewer.tag_action.connect(lambda tag, mode: self._tag_from_viewer(viewer, tag, mode))
        viewer.destroyed.connect(lambda: self._viewer_closed(viewer, bool(dirty)))
        self._viewers.append(viewer)
        viewer.show()

    def _viewer_closed(self, viewer: Viewer, changed: bool) -> None:
        if viewer in self._viewers:
            self._viewers.remove(viewer)
        if changed:
            self.refresh_sidebar()
            self.reload()
            self.changed.emit()

    def _tag_from_viewer(self, viewer: Viewer, tag: str, mode: str) -> None:
        self.query.setText(apply_tag(self.query.text(), tag, mode))
        if mode == "search":
            viewer.close()
            self.window().activateWindow()
        self.reload()
