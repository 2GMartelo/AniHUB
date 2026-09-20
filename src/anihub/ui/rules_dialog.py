"""Editor for the automatic rules (ТЗ 6.4): conditions -> actions, applied to new items and, on demand, to the library."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QMessageBox, QPushButton, QVBoxLayout, QWidget,
)

from anihub.context import AppContext
from anihub.core.i18n import tr
from anihub.library.rules import describe_conditions, has_actions, has_conditions, parse_list
from anihub.sources.base import RATINGS
from anihub.ui import style
from anihub.ui.tag_widgets import tag_line_edit
from anihub.ui.workers import run_async

KINDS = ("art", "sd")


class RulesDialog(QDialog):
    changed = Signal()

    def __init__(self, ctx: AppContext, parent=None):
        super().__init__(parent)
        self.ctx, self.db = ctx, ctx.db
        self._rule_id: int | None = None
        self._loading = False
        self.setWindowTitle(tr("rules.title"))
        self.resize(880, 620)

        # left: the rules
        self.list = QListWidget()
        self.list.setMinimumWidth(240)
        self.new_btn = style.secondary(QPushButton(tr("rules.new")), "plus")
        self.del_btn = style.danger(QPushButton(tr("rules.delete")), "trash")
        self.up_btn = style.ghost(QPushButton(), "arrow-up")
        self.down_btn = style.ghost(QPushButton(), "arrow-down")
        for b in (self.up_btn, self.down_btn):
            b.setFixedWidth(34)
            b.setToolTip(tr("rules.order_tip"))
        left_buttons = QHBoxLayout()
        for w in (self.new_btn, self.del_btn, self.up_btn, self.down_btn):
            left_buttons.addWidget(w)
        left = QVBoxLayout()
        left.addWidget(self.list, 1)
        left.addLayout(left_buttons)

        # right: the editor
        self.name = QLineEdit(placeholderText=tr("rules.name"))
        self.tags_all = tag_line_edit(self.db, tr("rules.tags_all_ph"))
        self.tags_any = tag_line_edit(self.db, tr("rules.tags_any_ph"))
        self.tags_none = tag_line_edit(self.db, tr("rules.tags_none_ph"))
        self.authors = QLineEdit(placeholderText=tr("rules.authors_ph"))
        self.sites = QLineEdit(placeholderText=tr("rules.sites_ph"))
        self.ratings = {r: QCheckBox(tr(f"rating.{r}")) for r in RATINGS}
        self.kinds = {k: QCheckBox(tr(f"rules.kind.{k}")) for k in KINDS}
        cond_form = QFormLayout()
        cond_form.addRow(tr("rules.tags_all"), self.tags_all)
        cond_form.addRow(tr("rules.tags_any"), self.tags_any)
        cond_form.addRow(tr("rules.tags_none"), self.tags_none)
        cond_form.addRow(tr("rules.authors"), self.authors)
        cond_form.addRow(tr("rules.sites"), self.sites)
        cond_form.addRow(tr("rules.ratings"), self._row(*self.ratings.values()))
        cond_form.addRow(tr("rules.kinds"), self._row(*self.kinds.values()))
        cond_box = QGroupBox(tr("rules.when"))
        cond_box.setLayout(cond_form)

        self.collection = QComboBox()
        self.collection.addItem(tr("rules.none"), None)
        for kind in KINDS:
            for c in self.db.collections(kind):
                self.collection.addItem(c["name"], c["id"])
        self.category = QComboBox()
        self.category.addItem(tr("rules.none"), None)
        for kind in KINDS:
            for c in self.db.categories(kind):
                self.category.addItem(c["name"], c["id"])
        self.add_tags = tag_line_edit(self.db, tr("rules.add_tags_ph"))
        self.rating = QComboBox()
        self.rating.addItem(tr("rules.unchanged"), None)
        for r in RATINGS:
            self.rating.addItem(tr(f"rating.{r}"), r)
        self.favorite = QCheckBox(tr("rules.favorite"))
        self.stars = QComboBox()
        self.stars.addItem(tr("rules.unchanged"), None)
        for n in range(6):
            self.stars.addItem("★" * n if n else tr("viewer.no_stars"), n)
        act_form = QFormLayout()
        act_form.addRow(tr("rules.collection"), self.collection)
        act_form.addRow(tr("rules.category"), self.category)
        act_form.addRow(tr("rules.add_tags"), self.add_tags)
        act_form.addRow(tr("rules.rating"), self.rating)
        act_form.addRow(tr("rules.stars"), self.stars)
        act_form.addRow("", self.favorite)
        act_box = QGroupBox(tr("rules.then"))
        act_box.setLayout(act_form)

        self.save_btn = style.primary(QPushButton(tr("rules.save")), "check")
        self.apply_btn = style.secondary(QPushButton(tr("rules.apply_now")), "zap")
        self.auto = QCheckBox(tr("rules.auto"))
        self.auto.setChecked(bool(ctx.cfg.get("library.auto_rules", True)))
        self.status = QLabel()
        self.status.setWordWrap(True)
        style.role(self.status, "dim")
        buttons = QHBoxLayout()
        buttons.addWidget(self.save_btn)
        buttons.addWidget(self.apply_btn)
        buttons.addStretch(1)
        self.editor = QWidget()
        right = QVBoxLayout(self.editor)
        right.setContentsMargins(0, 0, 0, 0)
        right.addWidget(self.name)
        right.addWidget(cond_box)
        right.addWidget(act_box)
        right.addLayout(buttons)
        right.addStretch(1)

        hint = QLabel(tr("rules.hint"))
        hint.setWordWrap(True)
        style.role(hint, "dim")
        body = QHBoxLayout()
        body.addLayout(left, 0)
        body.addWidget(self.editor, 1)
        layout = QVBoxLayout(self)
        layout.addWidget(hint)
        layout.addLayout(body, 1)
        layout.addWidget(self.auto)
        layout.addWidget(self.status)

        self.list.currentRowChanged.connect(self._select)
        self.list.itemChanged.connect(self._toggled)
        self.new_btn.clicked.connect(self._new)
        self.del_btn.clicked.connect(self._delete)
        self.up_btn.clicked.connect(lambda: self._move(-1))
        self.down_btn.clicked.connect(lambda: self._move(1))
        self.save_btn.clicked.connect(self._save)
        self.apply_btn.clicked.connect(self._apply_now)
        self.auto.toggled.connect(lambda v: ctx.cfg.set("library.auto_rules", v))
        self.reload()

    @staticmethod
    def _row(*widgets: QWidget) -> QWidget:
        holder = QWidget()
        row = QHBoxLayout(holder)
        row.setContentsMargins(0, 0, 0, 0)
        for w in widgets:
            row.addWidget(w)
        row.addStretch(1)
        return holder

    # --- list ---------------------------------------------------------------------------------------

    def reload(self, select: int | None = None) -> None:
        rules = self.db.rules()
        self._loading = True
        self.list.clear()
        for rule in rules:
            item = QListWidgetItem(rule["name"])
            item.setData(Qt.ItemDataRole.UserRole, rule["id"])
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if rule["enabled"] else Qt.CheckState.Unchecked)
            item.setToolTip(describe_conditions(rule["conditions"]))
            self.list.addItem(item)
        self._loading = False
        row = 0
        if select is not None:
            row = next((i for i, r in enumerate(rules) if r["id"] == select), 0)
        if rules:
            self.list.setCurrentRow(row)
        else:
            self._select(-1)

    def _current(self) -> dict | None:
        item = self.list.currentItem()
        if item is None:
            return None
        rid = item.data(Qt.ItemDataRole.UserRole)
        return next((r for r in self.db.rules() if r["id"] == rid), None)

    def _select(self, _row: int) -> None:
        rule = self._current()
        self.editor.setEnabled(rule is not None)
        self.del_btn.setEnabled(rule is not None)
        self.up_btn.setEnabled(rule is not None)
        self.down_btn.setEnabled(rule is not None)
        self._fill(rule)

    def _fill(self, rule: dict | None) -> None:
        self._rule_id = rule["id"] if rule else None
        c, a = (rule["conditions"], rule["actions"]) if rule else ({}, {})
        self.name.setText(rule["name"] if rule else "")
        for edit, key in ((self.tags_all, "tags_all"), (self.tags_any, "tags_any"), (self.tags_none, "tags_none"),
                          (self.authors, "authors"), (self.sites, "sites")):
            edit.setText(" ".join(c.get(key, [])))
        for r, box in self.ratings.items():
            box.setChecked(r in c.get("ratings", []))
        for k, box in self.kinds.items():
            box.setChecked(k in c.get("kinds", []))
        self.collection.setCurrentIndex(max(self.collection.findData(a.get("collection_id")), 0))
        self.category.setCurrentIndex(max(self.category.findData(a.get("category_id")), 0))
        self.add_tags.setText(" ".join(a.get("add_tags", [])))
        self.rating.setCurrentIndex(max(self.rating.findData(a.get("rating")), 0))
        self.stars.setCurrentIndex(max(self.stars.findData(a.get("stars")), 0))
        self.favorite.setChecked(bool(a.get("favorite")))

    def _toggled(self, item: QListWidgetItem) -> None:
        if not self._loading:
            self.db.set_rule_enabled(item.data(Qt.ItemDataRole.UserRole), item.checkState() == Qt.CheckState.Checked)

    def _new(self) -> None:
        rid = self.db.save_rule(tr("rules.default_name"), {}, {})
        self.reload(select=rid)
        self.editor.setEnabled(True)
        self.name.setFocus()
        self.name.selectAll()
        self.status.setText(tr("rules.fill_in"))

    def _delete(self) -> None:
        rule = self._current()
        if rule and QMessageBox.question(self, tr("rules.delete"), tr("rules.delete_confirm", name=rule["name"])) \
                == QMessageBox.StandardButton.Yes:
            self.db.delete_rule(rule["id"])
            self.reload()

    def _move(self, delta: int) -> None:
        rule = self._current()
        if rule:
            self.db.move_rule(rule["id"], delta)
            self.reload(select=rule["id"])

    # --- editor -------------------------------------------------------------------------------------

    def _collect(self) -> tuple[dict, dict]:
        conditions = {
            "tags_all": parse_list(self.tags_all.text()), "tags_any": parse_list(self.tags_any.text()),
            "tags_none": parse_list(self.tags_none.text()), "authors": parse_list(self.authors.text()),
            "sites": parse_list(self.sites.text()),
            "ratings": [r for r, b in self.ratings.items() if b.isChecked()],
            "kinds": [k for k, b in self.kinds.items() if b.isChecked()],
        }
        conditions = {k: v for k, v in conditions.items() if v}
        actions: dict = {}
        if self.collection.currentData():
            actions["collection_id"] = self.collection.currentData()
        if self.category.currentData():
            actions["category_id"] = self.category.currentData()
        if parse_list(self.add_tags.text()):
            actions["add_tags"] = parse_list(self.add_tags.text())
        if self.rating.currentData():
            actions["rating"] = self.rating.currentData()
        if self.stars.currentData() is not None:
            actions["stars"] = self.stars.currentData()
        if self.favorite.isChecked():
            actions["favorite"] = True
        return conditions, actions

    def _save(self) -> None:
        if self._rule_id is None:
            return
        conditions, actions = self._collect()
        if not has_conditions(conditions) or not has_actions(actions):
            self.status.setText(tr("rules.incomplete"))
            return
        enabled = next((r["enabled"] for r in self.db.rules() if r["id"] == self._rule_id), True)
        self.db.save_rule(self.name.text().strip() or tr("rules.default_name"), conditions, actions, enabled, self._rule_id)
        self.status.setText(tr("rules.saved"))
        self.reload(select=self._rule_id)

    def _apply_now(self) -> None:
        if QMessageBox.question(self, tr("rules.apply_now"), tr("rules.apply_confirm")) != QMessageBox.StandardButton.Yes:
            return
        self.apply_btn.setEnabled(False)
        self.status.setText(tr("status.loading"))

        def done(result: dict) -> None:
            self.apply_btn.setEnabled(True)
            self.status.setText(tr("rules.applied", n=sum(result.values()), rules=len(result)))
            self.changed.emit()

        def failed(exc: Exception) -> None:
            self.apply_btn.setEnabled(True)
            self.status.setText(tr("status.error", msg=str(exc)))

        run_async(self.ctx.library.rules.apply_all, on_done=done, on_error=failed)
