"""Browse a folder on disk directly, without importing it into the library first: add a folder once (remembered
in config as "library.external_folders"), and its pictures show up here without ever being copied. This is for a
folder of photos the user already has somewhere on the computer and just wants to look at -- "Add to library"
copies a picture in explicitly, on request, the same anihub.library.service.LibraryService.import_files() an
ordinary folder import already uses; nothing here goes through the items table."""
from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QImage
from PySide6.QtWidgets import (
    QFileDialog, QHBoxLayout, QInputDialog, QLabel, QMenu, QMessageBox, QPushButton, QSplitter, QTreeWidget,
    QTreeWidgetItem, QVBoxLayout, QWidget,
)

from anihub.context import AppContext
from anihub.core.i18n import tr
from anihub.library.service import IMAGE_EXTS, VIDEO_EXTS
from anihub.ui import style
from anihub.ui.grid import PAYLOAD, ThumbGrid, image_to_thumb
from anihub.ui.image_context_menu import show_image_menu
from anihub.ui.viewer import ViewItem, Viewer
from anihub.ui.workers import run_async

ROLE = Qt.ItemDataRole.UserRole
MEDIA_EXTS = IMAGE_EXTS | VIDEO_EXTS


def list_media(folder: Path) -> list[Path]:
    """Direct children only (like a real file browser's folder view; subfolders are navigated via the tree)."""
    try:
        entries = sorted(folder.iterdir(), key=lambda p: p.name.lower())
    except OSError:
        return []
    return [p for p in entries if p.is_file() and p.suffix.lower().lstrip(".") in MEDIA_EXTS]


def has_subfolder(folder: Path) -> bool:
    try:
        return any(p.is_dir() for p in folder.iterdir())
    except OSError:
        return False


class ExternalFoldersView(QWidget):
    def __init__(self, ctx: AppContext, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.current: Path | None = None
        self._gen = 0

        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setMinimumWidth(220)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.add_btn = style.secondary(QPushButton(tr("extfolders.add")), "plus")
        side = QWidget()
        side_layout = QVBoxLayout(side)
        side_layout.setContentsMargins(0, 0, 0, 0)
        side_layout.addWidget(self.tree, 1)
        side_layout.addWidget(self.add_btn)

        self.path_label = style.role(QLabel(), "dim")
        self.path_label.setWordWrap(True)
        self.grid = ThumbGrid(170)
        self.add_to_library_btn = style.secondary(QPushButton(tr("extfolders.to_library")), "download")
        self.add_to_library_btn.setEnabled(False)
        top = QHBoxLayout()
        top.addWidget(self.path_label, 1)
        top.addWidget(self.add_to_library_btn)
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.addLayout(top)
        right_layout.addWidget(self.grid, 1)

        split = QSplitter()
        split.addWidget(side)
        split.addWidget(right)
        split.setStretchFactor(1, 1)
        split.setChildrenCollapsible(False)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(split)

        self.add_btn.clicked.connect(self._add_root)
        self.tree.itemExpanded.connect(self._populate_children)
        self.tree.currentItemChanged.connect(self._on_selected)
        self.tree.customContextMenuRequested.connect(self._tree_menu)
        self.grid.context_requested.connect(self._grid_menu)
        self.grid.itemDoubleClicked.connect(self._open_viewer)
        self.grid.itemSelectionChanged.connect(self._update_buttons)
        self.add_to_library_btn.clicked.connect(self._add_selected_to_library)
        self.grid.set_empty("folder", tr("extfolders.empty_title"), tr("extfolders.empty_hint"))
        self.reload_roots()

    # --- the tree of added folders ------------------------------------------------------------------------

    def roots(self) -> list[dict]:
        return list(self.ctx.cfg.get("library.external_folders", []) or [])

    def reload_roots(self) -> None:
        current = self.current
        self.tree.clear()
        for entry in self.roots():
            path = Path(entry["path"])
            item = QTreeWidgetItem([entry.get("label") or path.name or str(path)])
            item.setData(0, ROLE, ("root", path))
            self.tree.addTopLevelItem(item)
            self._add_placeholder_if_needed(item, path)
        if current is not None:
            self._select_path(current)

    def _add_placeholder_if_needed(self, item: QTreeWidgetItem, path: Path) -> None:
        if has_subfolder(path):
            placeholder = QTreeWidgetItem(["…"])
            placeholder.setData(0, ROLE, ("placeholder", None))
            item.addChild(placeholder)

    def _populate_children(self, item: QTreeWidgetItem) -> None:
        if item.childCount() == 1 and item.child(0).data(0, ROLE)[0] == "placeholder":
            item.takeChildren()
            _, path = item.data(0, ROLE)
            try:
                subfolders = sorted((p for p in path.iterdir() if p.is_dir()), key=lambda p: p.name.lower())
            except OSError:
                subfolders = []
            for sub in subfolders:
                child = QTreeWidgetItem([sub.name])
                child.setData(0, ROLE, ("folder", sub))
                item.addChild(child)
                self._add_placeholder_if_needed(child, sub)

    def _select_path(self, path: Path) -> None:
        stack = [self.tree.topLevelItem(i) for i in range(self.tree.topLevelItemCount())]
        while stack:
            item = stack.pop()
            data = item.data(0, ROLE)
            if data[0] != "placeholder" and data[1] == path:
                self.tree.setCurrentItem(item)
                return
            stack += [item.child(i) for i in range(item.childCount())]

    def _on_selected(self, item: QTreeWidgetItem | None) -> None:
        if item is None:
            return
        kind, path = item.data(0, ROLE)
        if kind == "placeholder":
            return
        self.current = path
        self.load_current()

    # --- adding / removing roots ---------------------------------------------------------------------------

    def _add_root(self) -> None:
        path = QFileDialog.getExistingDirectory(self, tr("extfolders.add"), str(Path.home()))
        if not path:
            return
        label, ok = QInputDialog.getText(self, tr("extfolders.add"), tr("extfolders.label"), text=Path(path).name)
        if not ok:
            return
        roots = self.roots()
        roots.append({"path": path, "label": label.strip() or Path(path).name})
        self.ctx.cfg.set("library.external_folders", roots)
        self.reload_roots()

    def _remove_root(self, path: Path) -> None:
        roots = [r for r in self.roots() if Path(r["path"]) != path]
        self.ctx.cfg.set("library.external_folders", roots)
        if self.current == path:
            self.current = None
            self.grid.clear_items()
            self.path_label.clear()
        self.reload_roots()

    def _tree_menu(self, pos) -> None:
        item = self.tree.itemAt(pos)
        if item is None:
            return
        kind, path = item.data(0, ROLE)
        if kind != "root":
            return
        menu = QMenu(self)
        menu.addAction(tr("lib.show_folder"), lambda: os.startfile(path))
        menu.addAction(tr("extfolders.remove"), lambda: self._remove_root(path))
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    # --- the grid of the current folder ---------------------------------------------------------------------

    def load_current(self) -> None:
        if self.current is None:
            return
        self._gen += 1
        gen = self._gen
        self.grid.clear_items()
        self.path_label.setText(str(self.current))
        folder = self.current

        def work() -> list[Path]:
            return list_media(folder)

        def done(files: list[Path]) -> None:
            if gen != self._gen:
                return
            for f in files:
                self.grid.add_entry(f, f.name, lambda p=f: image_to_thumb(p, self.grid.thumb_size))

        run_async(work, on_done=done)

    def _update_buttons(self) -> None:
        self.add_to_library_btn.setEnabled(bool(self.grid.selected_payloads()))

    def _add_selected_to_library(self) -> None:
        files = self.grid.selected_payloads()
        if not files:
            return

        def work() -> dict:
            return self.ctx.library.import_files(files)

        def done(counts: dict) -> None:
            self.path_label.setText(tr("extfolders.imported", saved=counts["saved"], dup=counts["duplicate"], failed=counts["failed"]))

        run_async(work, on_done=done)

    def _open_viewer(self, item) -> None:
        files = self.grid.payloads()
        index = self.grid.row(item)
        items = [ViewItem(f.name, "", (lambda p=f: p)) for f in files]
        viewer = Viewer(items, index, ctx=self.ctx)
        viewer.show()

    def _grid_menu(self, pos) -> None:
        item = self.grid.itemAt(self.grid.viewport().mapFromGlobal(pos))
        if item is None:
            return
        path: Path = item.data(PAYLOAD)
        show_image_menu(self, pos, path=path, suggested_name=path.name)
