"""Picking (or creating) a category and subcategory of the prompt builder's catalogue for a tag that comes from somewhere else —
right now, an art's own tags, added from the viewer's tag panel instead of typed by hand into the constructor."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMenu, QPushButton,
    QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from anihub.core.i18n import get_language, tr
from anihub.services import promptbook as pb
from anihub.services.promptbook import PromptBook
from anihub.ui import style

ROLE = Qt.ItemDataRole.UserRole


def _node_name(node: dict) -> str:
    return node["name_ru"] if get_language() == "ru" and node.get("name_ru") else node["name"]


class CatalogPickerDialog(QDialog):
    """`has_picture`: whether the caller can supply a picture for the new tag (offers a "use this picture" checkbox, checked
    by default). On accept, `chosen_node_id` holds the category the tag goes into."""

    def __init__(self, book: PromptBook, text: str, has_picture: bool = False, parent: QWidget | None = None):
        super().__init__(parent)
        self.book = book
        self.chosen_node_id: int | None = None
        self.setWindowTitle(tr("catpick.title"))
        self.resize(420, 500)

        self.text = QLineEdit(text.strip())
        self.label = QLineEdit(placeholderText=tr("pb.dlg.label_hint"))
        self.use_picture = QCheckBox(tr("catpick.use_picture"), checked=True)
        self.use_picture.setVisible(has_picture)

        form = QFormLayout()
        form.addRow(tr("pb.dlg.text"), self.text)
        form.addRow(tr("pb.dlg.label"), self.label)

        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.new_btn = style.ghost(QPushButton(tr("pb.tree.new_category")), "plus")
        pick_row = QHBoxLayout()
        pick_row.addWidget(QLabel(tr("catpick.pick")), 1)
        pick_row.addWidget(self.new_btn)

        hint = style.role(QLabel(tr("catpick.hint")), "dim")
        hint.setWordWrap(True)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.ok_btn = buttons.button(QDialogButtonBox.StandardButton.Ok)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.use_picture)
        layout.addWidget(hint)
        layout.addLayout(pick_row)
        layout.addWidget(self.tree, 1)
        layout.addWidget(buttons)

        self.tree.itemSelectionChanged.connect(self._update_ok)
        self.tree.customContextMenuRequested.connect(self._menu)
        self.new_btn.clicked.connect(lambda: self._new_category(None))
        self._fill_tree()
        self._update_ok()

    # --- the tree --------------------------------------------------------------------------------------------------------

    def _fill_tree(self, select: int | None = None) -> None:
        self.tree.clear()
        want_item = None
        for key in pb.SLOT_KEYS:
            top = QTreeWidgetItem([pb.slot_name(key, get_language())])
            top.setData(0, ROLE, ("slot", key))
            font = top.font(0)
            font.setBold(True)
            top.setFont(0, font)
            self.tree.addTopLevelItem(top)
            nodes = self.book.nodes(key)
            children: dict[int | None, list[dict]] = {}
            for n in nodes:
                children.setdefault(n["parent_id"], []).append(n)

            def add(parent_item: QTreeWidgetItem, parent_id: int | None) -> None:
                nonlocal want_item
                for n in children.get(parent_id, []):
                    item = QTreeWidgetItem([_node_name(n)])
                    item.setData(0, ROLE, ("node", n["id"]))
                    parent_item.addChild(item)
                    if select == n["id"]:
                        want_item = item
                    add(item, n["id"])

            add(top, None)
        if want_item is not None:
            self.tree.setCurrentItem(want_item)
            item = want_item
            while item is not None:
                item.setExpanded(True)
                item = item.parent()

    def _selection(self):
        item = self.tree.currentItem()
        return item.data(0, ROLE) if item is not None else None

    def _update_ok(self) -> None:
        sel = self._selection()
        self.ok_btn.setEnabled(sel is not None and sel[0] == "node")

    def _menu(self, pos) -> None:
        item = self.tree.itemAt(pos)
        if item is not None:
            self.tree.setCurrentItem(item)
        sel = self._selection()
        if sel is None:
            return
        menu = QMenu(self)
        menu.addAction(tr("pb.tree.new_category"), lambda: self._new_category(None))
        if sel[0] == "node":
            menu.addAction(tr("pb.tree.new_sub"), lambda: self._new_category(sel[1]))
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    def _new_category(self, parent_id: int | None) -> None:
        sel = self._selection()
        if sel is None:
            return
        slot = sel[1] if sel[0] == "slot" else self.book.node(sel[1])["slot"]
        name, ok = QInputDialog.getText(self, tr("pb.tree.new_category"), tr("pb.dlg.name"))
        if ok and name.strip():
            node_id = self.book.add_node(slot, name, parent_id)
            self._fill_tree(select=node_id)
            self._update_ok()

    def _accept(self) -> None:
        sel = self._selection()
        if not self.text.text().strip() or sel is None or sel[0] != "node":
            return
        self.chosen_node_id = sel[1]
        self.accept()
