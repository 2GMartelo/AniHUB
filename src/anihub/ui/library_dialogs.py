"""Library dialogs: tag editor, tag manager (hierarchy + smart tags), folder import, duplicate finder."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor, QIcon, QPixmap
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMessageBox, QProgressBar, QPushButton, QTabWidget, QTreeWidget, QTreeWidgetItem,
    QVBoxLayout, QWidget,
)

from anihub.context import AppContext
from anihub.core.i18n import tr
from anihub.library.service import collect_image_files
from anihub.sources.base import RATINGS
from anihub.ui.tag_widgets import tag_line_edit
from anihub.ui.workers import run_async, run_status

CATEGORY_COLORS = {"artist": "#e0575a", "copyright": "#d070d6", "character": "#3fb95a", "meta": "#f0a030"}
TAG_CATEGORIES = ("general", "character", "artist", "copyright", "meta")


def normalize_tag(text: str) -> str:
    return "_".join(text.strip().lower().split())


class TagEditDialog(QDialog):
    """Edit the tags of one or many items. Tick = the tag is on the item(s); a partly ticked box (many items)
    means only some of them carry it: leave it as is, tick to add to all, untick to remove from all."""

    def __init__(self, ctx: AppContext, item_ids: list[int], parent=None):
        super().__init__(parent)
        self.ctx, self.item_ids = ctx, item_ids
        self.setWindowTitle(tr("tags.edit_title", n=len(item_ids)))
        self.resize(460, 560)
        n = len(item_ids)
        self._original: dict[str, Qt.CheckState] = {}
        self._new_category: dict[str, str] = {}

        self.list = QListWidget()
        for name, category, count in ctx.db.tags_of_items(item_ids):
            state = Qt.CheckState.Checked if count == n else Qt.CheckState.PartiallyChecked
            self._original[name] = state
            self._add_row(name, category, state, count if count != n else None)
        self.edit = tag_line_edit(ctx.db, tr("tags.add_placeholder"), multi=False)
        self.category = QComboBox()
        for c in TAG_CATEGORIES:
            self.category.addItem(tr(f"tagcat.{c}"), c)
        add = QPushButton(tr("tags.add"))
        row = QHBoxLayout()
        row.addWidget(self.edit, 1)
        row.addWidget(self.category)
        row.addWidget(add)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(tr("tags.hint_multi") if n > 1 else tr("tags.hint_single")))
        layout.addWidget(self.list, 1)
        layout.addLayout(row)
        layout.addWidget(buttons)
        add.clicked.connect(self._add_from_edit)
        self.edit.returnPressed.connect(self._add_from_edit)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

    def _add_row(self, name: str, category: str, state: Qt.CheckState, partial_count: int | None = None) -> None:
        text = name + (f"   ({partial_count}/{len(self.item_ids)})" if partial_count else "")
        item = QListWidgetItem(text)
        item.setData(Qt.ItemDataRole.UserRole, name)
        flags = item.flags() | Qt.ItemFlag.ItemIsUserCheckable
        if state == Qt.CheckState.PartiallyChecked:
            flags |= Qt.ItemFlag.ItemIsUserTristate
        item.setFlags(flags)
        item.setCheckState(state)
        if category in CATEGORY_COLORS:
            item.setForeground(QBrush(QColor(CATEGORY_COLORS[category])))
        self.list.addItem(item)

    def _add_from_edit(self) -> None:
        name = normalize_tag(self.edit.text())
        self.edit.clear()
        if not name:
            return
        for i in range(self.list.count()):
            item = self.list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == name:
                item.setCheckState(Qt.CheckState.Checked)
                self.list.scrollToItem(item)
                return
        category = self.category.currentData()
        existing = self.ctx.db.tag_id(name)
        if existing is not None:  # keep the category the tag already has
            row = self.ctx.db.conn.execute("SELECT category FROM tags WHERE id=?", (existing,)).fetchone()
            category = row[0]
        self._new_category[name] = category
        self._add_row(name, category, Qt.CheckState.Checked)
        self.list.scrollToBottom()

    def changes(self) -> tuple[list[tuple[str, str]], list[str]]:
        add, remove = [], []
        for i in range(self.list.count()):
            item = self.list.item(i)
            name, state = item.data(Qt.ItemDataRole.UserRole), item.checkState()
            original = self._original.get(name)
            if state == Qt.CheckState.Checked and original != Qt.CheckState.Checked:
                add.append((name, self._new_category.get(name, "general")))
            elif state == Qt.CheckState.Unchecked and original is not None:
                remove.append(name)
        return add, remove

    def accept(self) -> None:
        self._add_from_edit()  # a half-typed tag is not lost
        add, remove = self.changes()
        if add:
            self.ctx.db.add_tags(self.item_ids, add)
        if remove:
            self.ctx.db.remove_tags(self.item_ids, remove)
        super().accept()


class TagManagerDialog(QDialog):
    changed = Signal()

    def __init__(self, ctx: AppContext, parent=None):
        super().__init__(parent)
        self.ctx, self.db = ctx, ctx.db
        self.setWindowTitle(tr("tags.manager"))
        self.resize(760, 600)
        tabs = QTabWidget()
        tabs.addTab(self._build_hierarchy(), tr("tags.hierarchy"))
        tabs.addTab(self._build_smart(), tr("tags.smart"))
        QVBoxLayout(self).addWidget(tabs)
        self.reload_tree()
        self.reload_smart()

    # --- hierarchy -----------------------------------------------------------------------------

    def _build_hierarchy(self) -> QWidget:
        w = QWidget()
        self.filter = QLineEdit(placeholderText=tr("tags.filter"))
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels([tr("tags.tag"), tr("tags.items")])
        self.tree.setColumnWidth(0, 360)
        self.tag_edit = tag_line_edit(self.db, tr("tags.tag"), multi=False)
        self.parent_edit = tag_line_edit(self.db, tr("tags.parent"), multi=False)
        set_btn = QPushButton(tr("tags.set_parent"))
        unset_btn = QPushButton(tr("tags.unset_parent"))
        rename_btn = QPushButton(tr("tags.rename"))
        delete_btn = QPushButton(tr("tags.delete"))
        self.tree_status = QLabel()
        form = QHBoxLayout()
        form.addWidget(self.tag_edit, 1)
        form.addWidget(QLabel("→"))
        form.addWidget(self.parent_edit, 1)
        form.addWidget(set_btn)
        actions = QHBoxLayout()
        for b in (unset_btn, rename_btn, delete_btn):
            actions.addWidget(b)
        actions.addStretch(1)
        layout = QVBoxLayout(w)
        layout.addWidget(QLabel(tr("tags.hierarchy_hint")))
        layout.addWidget(self.filter)
        layout.addWidget(self.tree, 1)
        layout.addLayout(form)
        layout.addLayout(actions)
        layout.addWidget(self.tree_status)
        self.filter.textChanged.connect(self.reload_tree)
        self.tree.itemSelectionChanged.connect(self._tree_selected)
        set_btn.clicked.connect(self._set_parent)
        unset_btn.clicked.connect(self._unset_parent)
        rename_btn.clicked.connect(self._rename)
        delete_btn.clicked.connect(self._delete)
        return w

    def reload_tree(self) -> None:
        rows = self.db.tag_tree(self.filter.text().strip().lower())
        self.tree.clear()
        items: dict[int, QTreeWidgetItem] = {}
        for r in rows:
            item = QTreeWidgetItem([r["name"], str(r["n"])])
            item.setData(0, Qt.ItemDataRole.UserRole, (r["name"], r["parent_id"]))
            items[r["id"]] = item
        for r in rows:
            parent = items.get(r["parent_id"])
            (parent.addChild if parent else self.tree.addTopLevelItem)(items[r["id"]])
        self.tree.expandAll()
        self.tree_status.setText(tr("tags.tree_count", n=len(rows)))

    def _tree_selected(self) -> None:
        items = self.tree.selectedItems()
        if not items:
            return
        name, _ = items[0].data(0, Qt.ItemDataRole.UserRole)
        parent = items[0].parent()
        self.tag_edit.setText(name)
        self.parent_edit.setText(parent.data(0, Qt.ItemDataRole.UserRole)[0] if parent else "")

    def _set_parent(self) -> None:
        name, parent = normalize_tag(self.tag_edit.text()), normalize_tag(self.parent_edit.text())
        if not name or not parent:
            return
        try:
            self.db.set_tag_parent(name, parent)
        except ValueError as exc:
            QMessageBox.warning(self, tr("tags.manager"), str(exc))
            return
        self.reload_tree()
        self.changed.emit()

    def _unset_parent(self) -> None:
        name = normalize_tag(self.tag_edit.text())
        if name:
            self.db.set_tag_parent(name, None)
            self.reload_tree()
            self.changed.emit()

    def _rename(self) -> None:
        old = normalize_tag(self.tag_edit.text())
        if not old or self.db.tag_id(old) is None:
            return
        new, ok = QInputDialog.getText(self, tr("tags.rename"), tr("tags.rename_prompt"), text=old)
        new = normalize_tag(new)
        if ok and new and new != old:
            self.db.rename_tag(old, new)
            self.tag_edit.setText(new)
            self.reload_tree()
            self.changed.emit()

    def _delete(self) -> None:
        name = normalize_tag(self.tag_edit.text())
        if name and self.db.tag_id(name) is not None and QMessageBox.question(
                self, tr("tags.delete"), tr("tags.delete_confirm", name=name)) == QMessageBox.StandardButton.Yes:
            self.db.delete_tag(name)
            self.tag_edit.clear()
            self.reload_tree()
            self.changed.emit()

    # --- smart tags ------------------------------------------------------------------------------

    def _build_smart(self) -> QWidget:
        w = QWidget()
        self.smart_list = QListWidget()
        self.smart_list.setMaximumWidth(220)
        self.smart_name = QLineEdit(placeholderText=tr("tags.smart_name"))
        self.members = QListWidget()
        self.member_edit = tag_line_edit(self.db, tr("tags.smart_add"), multi=False)
        add_btn = QPushButton(tr("tags.add"))
        remove_btn = QPushButton(tr("tags.smart_remove_member"))
        new_btn = QPushButton(tr("tags.smart_new"))
        save_btn = QPushButton(tr("tags.smart_save"))
        del_btn = QPushButton(tr("tags.smart_delete"))
        self._smart_id: int | None = None
        row = QHBoxLayout()
        row.addWidget(self.member_edit, 1)
        row.addWidget(add_btn)
        row.addWidget(remove_btn)
        buttons = QHBoxLayout()
        for b in (new_btn, save_btn, del_btn):
            buttons.addWidget(b)
        buttons.addStretch(1)
        right = QVBoxLayout()
        right.addWidget(QLabel(tr("tags.smart_hint")))
        right.addWidget(self.smart_name)
        right.addWidget(self.members, 1)
        right.addLayout(row)
        right.addLayout(buttons)
        layout = QHBoxLayout(w)
        layout.addWidget(self.smart_list)
        layout.addLayout(right, 1)
        self.smart_list.currentRowChanged.connect(self._smart_selected)
        add_btn.clicked.connect(self._smart_add_member)
        self.member_edit.returnPressed.connect(self._smart_add_member)
        remove_btn.clicked.connect(lambda: [self.members.takeItem(self.members.row(i)) for i in self.members.selectedItems()])
        new_btn.clicked.connect(self._smart_new)
        save_btn.clicked.connect(self._smart_save)
        del_btn.clicked.connect(self._smart_delete)
        return w

    def reload_smart(self, select: int | None = None) -> None:
        self.smart_list.blockSignals(True)
        self.smart_list.clear()
        self._smart = self.db.smart_tags()
        for sid, name, _ in self._smart:
            self.smart_list.addItem(f"@{name}")
        self.smart_list.blockSignals(False)
        row = next((i for i, s in enumerate(self._smart) if s[0] == select), -1)
        self.smart_list.setCurrentRow(row)
        if row < 0:
            self._smart_new()

    def _smart_selected(self, row: int) -> None:
        if 0 <= row < len(self._smart):
            sid, name, tags = self._smart[row]
            self._smart_id = sid
            self.smart_name.setText(name)
            self.members.clear()
            self.members.addItems(tags)

    def _smart_new(self) -> None:
        self._smart_id = None
        self.smart_list.blockSignals(True)
        self.smart_list.setCurrentRow(-1)
        self.smart_list.blockSignals(False)
        self.smart_name.clear()
        self.members.clear()

    def _smart_add_member(self) -> None:
        name = normalize_tag(self.member_edit.text())
        self.member_edit.clear()
        if name and not self.members.findItems(name, Qt.MatchFlag.MatchExactly):
            self.members.addItem(name)

    def _smart_save(self) -> None:
        self._smart_add_member()
        name = normalize_tag(self.smart_name.text())
        tags = [self.members.item(i).text() for i in range(self.members.count())]
        if not name or not tags:
            QMessageBox.information(self, tr("tags.smart"), tr("tags.smart_need"))
            return
        try:
            sid = self.db.save_smart_tag(name, tags, self._smart_id)
        except Exception as exc:  # noqa: BLE001 - e.g. duplicate name
            QMessageBox.warning(self, tr("tags.smart"), str(exc))
            return
        self.reload_smart(select=sid)
        self.changed.emit()

    def _smart_delete(self) -> None:
        if self._smart_id is not None:
            self.db.delete_smart_tag(self._smart_id)
            self.reload_smart()
            self.changed.emit()


class ImportDialog(QDialog):
    """Import local images/folders: copies them into the library, dedups, hashes and (optionally) autotags."""
    progress = Signal(int, int)
    imported = Signal()

    def __init__(self, ctx: AppContext, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self._paths: list[Path] = []
        self._cancel = False
        self._running = False
        self.setWindowTitle(tr("import.title"))
        self.resize(560, 380)
        self.list = QListWidget()
        add_dir = QPushButton(tr("import.add_folder"))
        add_files = QPushButton(tr("import.add_files"))
        clear = QPushButton(tr("import.clear"))
        top = QHBoxLayout()
        for b in (add_dir, add_files, clear):
            top.addWidget(b)
        top.addStretch(1)
        self.rating = QComboBox()
        for r in RATINGS:
            self.rating.addItem(tr(f"rating.{r}"), r)
        self.category = QComboBox()
        self.category.addItem(tr("import.default_category"), None)
        for c in ctx.db.categories("art"):
            self.category.addItem(c["name"], c["id"])
        self.use_tagger = QCheckBox(tr("import.autotag"))
        available = ctx.library.tagger is not None
        self.use_tagger.setChecked(available)
        self.use_tagger.setEnabled(available)
        if not available:
            self.use_tagger.setToolTip(tr("import.autotag_off"))
        opts = QHBoxLayout()
        opts.addWidget(QLabel(tr("import.rating")))
        opts.addWidget(self.rating)
        opts.addWidget(QLabel(tr("import.category")))
        opts.addWidget(self.category)
        opts.addStretch(1)
        self.bar = QProgressBar()
        self.result = QLabel()
        self.result.setWordWrap(True)
        self.start_btn = QPushButton(tr("import.start"))
        self.cancel_btn = QPushButton(tr("action.close"))
        bottom = QHBoxLayout()
        bottom.addStretch(1)
        bottom.addWidget(self.start_btn)
        bottom.addWidget(self.cancel_btn)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(tr("import.hint")))
        layout.addLayout(top)
        layout.addWidget(self.list, 1)
        layout.addLayout(opts)
        layout.addWidget(self.use_tagger)
        layout.addWidget(self.bar)
        layout.addWidget(self.result)
        layout.addLayout(bottom)
        add_dir.clicked.connect(self._add_folder)
        add_files.clicked.connect(self._add_files)
        clear.clicked.connect(lambda: (self._paths.clear(), self.list.clear()))
        self.start_btn.clicked.connect(self._start)
        self.cancel_btn.clicked.connect(self._cancel_or_close)
        self.progress.connect(lambda d, t: (self.bar.setRange(0, t), self.bar.setValue(d)))

    def _add(self, paths: list[Path]) -> None:
        for p in paths:
            if p not in self._paths:
                self._paths.append(p)
                self.list.addItem(str(p))

    def _add_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, tr("import.add_folder"))
        if folder:
            self._add([Path(folder)])

    def _add_files(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(self, tr("import.add_files"), "", "Images (*.png *.jpg *.jpeg *.webp *.gif *.bmp *.tif *.tiff)")
        self._add([Path(f) for f in files])

    def _start(self) -> None:
        if not self._paths or self._running:
            return
        self._running, self._cancel = True, False
        self.start_btn.setEnabled(False)
        self.cancel_btn.setText(tr("import.cancel"))
        self.result.setText(tr("status.loading"))
        opts = dict(rating=self.rating.currentData(), use_tagger=self.use_tagger.isChecked(),
                    category_id=self.category.currentData())
        paths = list(self._paths)

        def work() -> dict:
            files = collect_image_files(paths)
            return self.ctx.library.import_files(files, progress=lambda d, t: self.progress.emit(d, t),
                                                 cancelled=lambda: self._cancel, **opts)

        def done(counts: dict) -> None:
            self._running = False
            self.start_btn.setEnabled(True)
            self.cancel_btn.setText(tr("action.close"))
            self.result.setText(tr("import.done", **counts))
            self.imported.emit()

        def failed(exc: Exception) -> None:
            self._running = False
            self.start_btn.setEnabled(True)
            self.cancel_btn.setText(tr("action.close"))
            self.result.setText(tr("status.error", msg=str(exc)))

        run_async(work, on_done=done, on_error=failed)

    def _cancel_or_close(self) -> None:
        if self._running:
            self._cancel = True
        else:
            self.close()


class DuplicatesDialog(QDialog):
    changed = Signal()

    def __init__(self, ctx: AppContext, kind: str = "art", parent=None):
        super().__init__(parent)
        self.ctx, self.kind = ctx, kind
        self.setWindowTitle(tr("dup.title"))
        self.resize(760, 600)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels([tr("dup.file"), tr("dup.size"), tr("dup.dims"), tr("dup.rating")])
        self.tree.setColumnWidth(0, 360)
        self.tree.setIconSize(self.tree.iconSize() * 2)
        self.status = QLabel(tr("dup.scanning"))
        keep_btn = QPushButton(tr("dup.select_smaller"))
        trash_btn = QPushButton(tr("dup.trash_checked"))
        close_btn = QPushButton(tr("action.close"))
        row = QHBoxLayout()
        row.addWidget(keep_btn)
        row.addWidget(trash_btn)
        row.addStretch(1)
        row.addWidget(close_btn)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(tr("dup.hint")))
        layout.addWidget(self.tree, 1)
        layout.addWidget(self.status)
        layout.addLayout(row)
        keep_btn.clicked.connect(self._check_all_but_largest)
        trash_btn.clicked.connect(self._trash_checked)
        close_btn.clicked.connect(self.close)
        threshold = int(ctx.cfg.get("library.near_threshold", 6))
        run_status(lambda: ctx.library.duplicate_groups(kind, threshold), on_done=self._fill, status=self.status)

    def _fill(self, groups: list) -> None:
        self.tree.clear()
        for n, rows in enumerate(groups, 1):
            head = QTreeWidgetItem([tr("dup.group", n=n, k=len(rows))])
            self.tree.addTopLevelItem(head)
            for r in rows:
                path = self.ctx.paths.root / r["path"]
                item = QTreeWidgetItem([r["path"], f"{(r['size'] or 0) / 1024:.0f} KB",
                                        f"{r['width'] or '?'}×{r['height'] or '?'}", r["rating"]])
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(0, Qt.CheckState.Unchecked)
                item.setData(0, Qt.ItemDataRole.UserRole, r["id"])
                pm = QPixmap(str(path))
                if not pm.isNull():
                    item.setIcon(0, QIcon(pm.scaled(64, 64, Qt.AspectRatioMode.KeepAspectRatio,
                                                   Qt.TransformationMode.SmoothTransformation)))
                head.addChild(item)
            head.setExpanded(True)
        self.status.setText(tr("dup.found", n=len(groups)) if groups else tr("dup.none"))

    def _children(self):
        for i in range(self.tree.topLevelItemCount()):
            head = self.tree.topLevelItem(i)
            yield [head.child(k) for k in range(head.childCount())]

    def _check_all_but_largest(self) -> None:
        for kids in self._children():
            for k, item in enumerate(kids):  # rows arrive largest-file first
                item.setCheckState(0, Qt.CheckState.Unchecked if k == 0 else Qt.CheckState.Checked)

    def _trash_checked(self) -> None:
        ids = [item.data(0, Qt.ItemDataRole.UserRole) for kids in self._children() for item in kids
               if item.checkState(0) == Qt.CheckState.Checked]
        if not ids:
            return
        run_async(lambda: self.ctx.library.trash(ids), on_done=lambda n: (
            self.status.setText(tr("dup.trashed", n=n)), self.changed.emit(),
            [i.setDisabled(True) for kids in self._children() for i in kids if i.data(0, Qt.ItemDataRole.UserRole) in ids]))
