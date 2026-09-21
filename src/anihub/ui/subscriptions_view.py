"""Subscriptions tab (ТЗ 3.8): followed searches, their new posts, saving them."""
from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMessageBox, QPushButton, QSplitter, QVBoxLayout, QWidget,
)

from anihub.context import AppContext
from anihub.core.i18n import tr
from anihub.services.subscriptions import CheckResult
from anihub.ui import style
from anihub.ui.grid import ThumbGrid, image_to_thumb
from anihub.ui.viewer import Viewer, ViewItem
from anihub.ui.workers import run_async


class SubscriptionsView(QWidget):
    changed = Signal()                        # the number of new posts changed (tab badge)

    def __init__(self, ctx: AppContext, parent=None):
        super().__init__(parent)
        self.ctx, self.service = ctx, ctx.subscriptions
        self.current: int | None = None
        self._gen = 0
        self._viewers: list[Viewer] = []
        self.list = QListWidget()
        self.list.setMinimumWidth(240)
        self.check_all_btn = style.secondary(QPushButton(tr("subs.check_all")), "refresh")
        self.empty = style.EmptyState("tag", tr("subs.empty_title"), tr("subs.empty_text"))
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.addWidget(self.list, 1)
        ll.addWidget(self.check_all_btn)

        self.title = QLabel()
        self.title.setStyleSheet("font-size: 16px; font-weight: 600;")
        self.info = QLabel()
        style.role(self.info, "dim")
        self.info.setWordWrap(True)
        self.enabled = QCheckBox(tr("subs.enabled"))
        self.auto = QCheckBox(tr("subs.auto_save"))
        self.check_btn = style.secondary(QPushButton(tr("subs.check")), "refresh")
        self.save_btn = style.primary(QPushButton(tr("subs.save_new")), "download")
        self.seen_btn = style.secondary(QPushButton(tr("subs.mark_seen")), "check")
        self.delete_btn = style.danger(QPushButton(tr("subs.delete")), "trash")
        self.grid = ThumbGrid(ctx.cfg.get("ui.thumb_size", 180) + 20)
        self.status = QLabel()
        style.role(self.status, "dim")
        row = QHBoxLayout()
        for w in (self.check_btn, self.save_btn, self.seen_btn, self.delete_btn):
            row.addWidget(w)
        row.addStretch(1)
        toggles = QHBoxLayout()
        toggles.addWidget(self.enabled)
        toggles.addWidget(self.auto)
        toggles.addStretch(1)
        self.details = QWidget()
        dl = QVBoxLayout(self.details)
        dl.setContentsMargins(0, 0, 0, 0)
        for w in (self.title, self.info):
            dl.addWidget(w)
        dl.addLayout(toggles)
        dl.addLayout(row)
        dl.addWidget(self.grid, 1)
        dl.addWidget(self.status)
        self.details.hide()
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.addWidget(self.empty, 1)
        rl.addWidget(self.details, 1)
        split = QSplitter()
        split.addWidget(left)
        split.addWidget(right)
        split.setStretchFactor(1, 1)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(split)

        self.list.currentRowChanged.connect(self._select)
        self.check_all_btn.clicked.connect(self.check_all)
        self.check_btn.clicked.connect(self.check_current)
        self.save_btn.clicked.connect(self._save_new)
        self.seen_btn.clicked.connect(self._mark_seen)
        self.delete_btn.clicked.connect(self._delete)
        self.enabled.toggled.connect(lambda v: self._set(enabled=int(v)))
        self.auto.toggled.connect(lambda v: self._set(auto_save=int(v)))
        self.grid.itemDoubleClicked.connect(self._open_viewer)
        self.reload()

    # --- list ---------------------------------------------------------------------------------------------

    def reload(self, select: int | None = None) -> None:
        keep = select if select is not None else self.current
        rows = self.ctx.db.subscriptions()
        self.list.blockSignals(True)
        self.list.clear()
        for r in rows:
            src = self.ctx.sources.get(r["source"])
            item = QListWidgetItem(f"{r['name']}  ·  {src.title if src else r['source']}" + (f"   ●{r['new_count']}" if r["new_count"] else ""))
            item.setData(Qt.ItemDataRole.UserRole, r["id"])
            if not r["enabled"]:
                item.setForeground(Qt.GlobalColor.gray)
            self.list.addItem(item)
        self.list.blockSignals(False)
        self.empty.setVisible(not rows)
        self.details.setVisible(bool(rows))
        row = next((i for i, r in enumerate(rows) if r["id"] == keep), 0)
        if rows:
            self.list.setCurrentRow(row)
            self._select(row)
        else:
            self.current = None
        self.changed.emit()

    def _row(self):
        return self.ctx.db.subscription(self.current) if self.current is not None else None

    def _select(self, index: int) -> None:
        item = self.list.item(index)
        self.current = item.data(Qt.ItemDataRole.UserRole) if item else None
        row = self._row()
        if row is None:
            return
        self.title.setText(row["name"])
        when = tr("subs.never") if not row["last_check"] else datetime.fromtimestamp(row["last_check"]).strftime("%Y-%m-%d %H:%M")
        self.info.setText(tr("subs.info", query=row["query"] or "—", source=self.ctx.sources[row["source"]].title
                             if row["source"] in self.ctx.sources else row["source"], when=when)
                          + (f"\n{tr('status.error', msg=row['last_error'])}" if row["last_error"] else ""))
        for box, value in ((self.enabled, row["enabled"]), (self.auto, row["auto_save"])):
            box.blockSignals(True)
            box.setChecked(bool(value))
            box.blockSignals(False)
        self.load_new()

    def _set(self, **fields) -> None:
        if self.current is not None:
            self.ctx.db.update_subscription(self.current, **fields)
            self.reload(self.current)

    # --- new posts --------------------------------------------------------------------------------------------

    def load_new(self) -> None:
        """Fetches the posts that are new for the selected subscription and shows them."""
        row = self._row()
        if row is None:
            return
        self._gen += 1
        gen, sub_id = self._gen, row["id"]
        self.grid.clear_items()
        if row["source"] not in self.ctx.sources or self.ctx.cfg.get("network.offline", False):
            self.status.setText(tr("subs.offline") if self.ctx.cfg.get("network.offline", False) else tr("subs.no_source"))
            return
        self.status.setText(tr("status.loading"))
        source, service = self.ctx.sources[row["source"]], self.service

        def work():
            return service._fetch_new(source, row["query"], row["last_seen_id"])

        def done(posts) -> None:
            if gen != self._gen:
                return
            for post in posts:
                self.grid.add_entry(post, f"#{post.id}  {post.rating}  ★{post.score}",
                                    lambda p=post: image_to_thumb(self.ctx.http.get_bytes(p.preview_url), self.grid.thumb_size, p.badge))
            self.status.setText(tr("subs.new_count", n=len(posts)))
            self.ctx.db.update_subscription(sub_id, new_count=len(posts))
            self.save_btn.setEnabled(bool(posts))
            self.changed.emit()

        run_async(work, on_done=done, on_error=lambda exc: gen == self._gen and self.status.setText(tr("status.error", msg=str(exc))))

    def _posts(self) -> list:
        return self.grid.payloads()

    def _save_new(self) -> None:
        posts = self.grid.selected_payloads() or self._posts()
        if not posts:
            return
        self.ctx.downloads.submit(posts)
        self.status.setText(tr("dl.queued", n=len(posts)))
        if len(posts) == len(self._posts()):
            self._mark_seen(silent=True)

    def _mark_seen(self, silent: bool = False) -> None:
        if self.current is None:
            return
        posts = self._posts()
        self.service.mark_seen(self.current, posts)
        if not silent:
            self.status.setText(tr("subs.marked"))
        self.reload(self.current)

    def _open_viewer(self, item) -> None:
        posts = self._posts()
        items = [ViewItem(f"{p.site} #{p.id}", f"{p.site} #{p.id} · {p.rating}", (lambda p=p: self.ctx.media.get(p.display_url())),
                          p.page_url, p.tags, p) for p in posts]
        viewer = Viewer(items, self.grid.row(item), lambda it: self.ctx.downloads.submit([it.payload]))
        viewer.destroyed.connect(lambda: self._viewers.remove(viewer) if viewer in self._viewers else None)
        self._viewers.append(viewer)
        viewer.show()

    # --- checking ---------------------------------------------------------------------------------------------

    def check_current(self) -> None:
        if self.current is None:
            return
        sub_id = self.current
        self.check_btn.setEnabled(False)
        self.status.setText(tr("status.loading"))

        def done(result: CheckResult) -> None:
            self.check_btn.setEnabled(True)
            self.reload(sub_id)

        run_async(lambda: self.service.check(sub_id), on_done=done,
                  on_error=lambda exc: (self.check_btn.setEnabled(True), self.status.setText(tr("status.error", msg=str(exc)))))

    def check_all(self) -> None:
        self.check_all_btn.setEnabled(False)

        def done(results: list[CheckResult]) -> None:
            self.check_all_btn.setEnabled(True)
            self.reload()

        run_async(self.service.check_all, on_done=done, on_error=lambda exc: self.check_all_btn.setEnabled(True))

    def _delete(self) -> None:
        row = self._row()
        if row and QMessageBox.question(self, tr("subs.delete"), tr("subs.delete_confirm", name=row["name"])) == QMessageBox.StandardButton.Yes:
            self.ctx.db.delete_subscription(row["id"])
            self.current = None
            self.reload()
