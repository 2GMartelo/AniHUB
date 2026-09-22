"""Generation history (ТЗ 5.6): a journal of every image Forge produced, separate from the library."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QUrl, Signal
from PySide6.QtGui import QDesktopServices, QImage
from PySide6.QtWidgets import (
    QComboBox, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMenu, QMessageBox, QPushButton, QVBoxLayout, QWidget,
)

from anihub.context import AppContext
from anihub.core.i18n import tr
from anihub.ui import style
from anihub.services.generation import GenResult, prompt_tags
from anihub.sources.base import RATINGS
from anihub.ui.grid import PAYLOAD, ThumbGrid, image_to_thumb
from anihub.ui.viewer import ViewItem, Viewer
from anihub.ui.workers import run_async

PAGE = 200


class HistoryView(QWidget):
    load_params = Signal(dict)          # parameters of the chosen entry -> the Generate form
    to_queue = Signal(dict)
    to_img2img = Signal(Path, str, str)  # image, prompt, negative
    presets_changed = Signal()
    library_changed = Signal()

    def __init__(self, ctx: AppContext, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self._gen = 0
        self._offset = 0
        self._loading = False
        self._exhausted = False
        self._viewers: list[Viewer] = []
        self.search = QLineEdit(placeholderText=tr("hist.search"))
        self.reload_btn = style.ghost(QPushButton(), "refresh")
        self.reload_btn.setFixedWidth(34)
        self.grid = ThumbGrid(170)
        self.grid.hover_loader = self._hover
        self.open_btn = style.secondary(QPushButton(tr("hist.open")), "image")
        self.load_btn = QPushButton(tr("hist.load"))
        self.preset_btn = QPushButton(tr("hist.save_preset"))
        self.repeat_btn = QPushButton(tr("hist.repeat"))
        self.i2i_btn = QPushButton(tr("lib.to_img2img"))
        self.rating = QComboBox()
        for r in RATINGS:
            self.rating.addItem(tr(f"rating.{r}"), r)
        self.add_btn = QPushButton(tr("action.save"))
        self.delete_btn = QPushButton(tr("hist.delete"))
        self.clear_btn = QPushButton(tr("hist.clear"))
        self.status = QLabel()
        top = QHBoxLayout()
        top.addWidget(self.search, 1)
        top.addWidget(self.reload_btn)
        buttons = QHBoxLayout()
        for w in (self.open_btn, self.load_btn, self.preset_btn, self.repeat_btn, self.i2i_btn):
            buttons.addWidget(w)
        buttons.addSpacing(16)
        buttons.addWidget(self.rating)
        buttons.addWidget(self.add_btn)
        buttons.addStretch(1)
        buttons.addWidget(self.delete_btn)
        buttons.addWidget(self.clear_btn)
        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(self.grid, 1)
        layout.addLayout(buttons)
        layout.addWidget(self.status)

        self.search.returnPressed.connect(self.reload)
        self.reload_btn.clicked.connect(self.reload)
        self.grid.need_more.connect(self._load_page)
        self.grid.itemSelectionChanged.connect(self._update_buttons)
        self.grid.itemDoubleClicked.connect(self._open)               # a double click shows the picture; "Load parameters" is a button
        self.grid.context_requested.connect(self._menu)
        self.open_btn.clicked.connect(lambda: self._open(self.grid.currentItem()))
        self.load_btn.clicked.connect(self._load)
        self.preset_btn.clicked.connect(self._save_preset)
        self.repeat_btn.clicked.connect(self._repeat)
        self.i2i_btn.clicked.connect(self._img2img)
        self.add_btn.clicked.connect(self._add_to_library)
        self.delete_btn.clicked.connect(self._delete)
        self.clear_btn.clicked.connect(self._clear)
        self._update_buttons()
        self.reload()

    # --- loading -----------------------------------------------------------------------------------------

    def reload(self) -> None:
        self._gen += 1
        self.grid.clear_items()
        self._offset, self._loading, self._exhausted = 0, False, False
        self._load_page()

    def _load_page(self) -> None:
        if self._loading or self._exhausted:
            return
        self._loading = True
        gen, offset, query = self._gen, self._offset, self.search.text().strip()

        def work():
            return self.ctx.db.history(query, PAGE, offset), self.ctx.db.history_count(query)

        def done(result) -> None:
            if gen != self._gen:
                return
            rows, total = result
            self._loading = False
            self._offset += len(rows)
            self._exhausted = len(rows) < PAGE
            for row in rows:
                self.grid.add_entry(row, self._tooltip(row), lambda r=row: self._thumb(r))
            self.status.setText(tr("hist.count", shown=self.grid.count(), total=total))
            if rows and not self._exhausted:
                self.grid.request_fill()

        run_async(work, on_done=done, on_error=lambda exc: self.status.setText(tr("status.error", msg=str(exc))))

    def _file(self, row: sqlite3.Row) -> Path:
        path = Path(row["path"])
        return path if path.is_absolute() else self.ctx.paths.root / path

    def _thumb(self, row: sqlite3.Row):
        file = self._file(row)
        return image_to_thumb(file.read_bytes(), self.grid.thumb_size) if file.exists() else None

    def _hover(self, row: sqlite3.Row):
        file = self._file(row)
        return (lambda: QImage(str(file))) if file.exists() else None

    @staticmethod
    def _tooltip(row: sqlite3.Row) -> str:
        when = datetime.fromtimestamp(row["created_at"]).strftime("%Y-%m-%d %H:%M")
        return f"{when} · seed {row['seed']} · {row['backend'] or ''}\n{(row['prompt'] or '')[:200]}"

    # --- actions -------------------------------------------------------------------------------------------

    def _selected(self) -> list[sqlite3.Row]:
        return self.grid.selected_payloads()

    def _first(self) -> sqlite3.Row | None:
        rows = self._selected()
        return rows[0] if rows else None

    def _update_buttons(self) -> None:
        n = len(self._selected())
        for b in (self.open_btn, self.load_btn, self.preset_btn, self.repeat_btn, self.i2i_btn):
            b.setEnabled(n >= 1)
        self.add_btn.setEnabled(n >= 1)
        self.delete_btn.setEnabled(n >= 1)

    def _view_item(self, row: sqlite3.Row) -> ViewItem:
        file = self._file(row)
        info = (json.loads(row["params"]).get("infotext") if row["params"] else "") or f"seed {row['seed']}\n{row['prompt'] or ''}"
        tags = [(t, "general") for t in prompt_tags(row["prompt"] or "")]
        return ViewItem(file.name, info, lambda: file, "", tags, row)

    def _open(self, item) -> None:
        """Shows the picture in the viewer (arrow keys go through the whole history); a picture whose file is gone is said so."""
        if item is None:
            return
        rows = self.grid.payloads()
        index = self.grid.row(item)
        if not self._file(rows[index]).exists():
            self.status.setText(tr("hist.file_missing", name=self._file(rows[index]).name))
            return
        viewer = Viewer([self._view_item(r) for r in rows], index, self._save_from_viewer, ctx=self.ctx)
        viewer.destroyed.connect(lambda: self._viewers.remove(viewer) if viewer in self._viewers else None)
        self._viewers.append(viewer)
        viewer.show()

    def _save_from_viewer(self, item: ViewItem) -> None:
        row = item.payload
        rating = self.rating.currentData()

        def work():
            return self.ctx.library.save_generation(self._file(row), self._params(row), rating).status

        run_async(work, on_done=lambda st: (self.status.setText(tr("status.saved", saved=int(st == "saved"), dup=int(st == "duplicate"),
                                                                    failed=int(st == "failed"))), self.library_changed.emit()),
                  on_error=lambda exc: self.status.setText(tr("status.error", msg=str(exc))))

    def _menu(self, pos) -> None:
        row = self._first()
        if row is None:
            return
        menu = QMenu(self)
        menu.addAction(tr("hist.open"), lambda: self._open(self.grid.currentItem()))
        menu.addAction(tr("hist.load"), self._load)
        menu.addAction(tr("lib.to_img2img"), self._img2img)
        menu.addAction(tr("hist.repeat"), self._repeat)
        menu.addSeparator()
        menu.addAction(tr("hist.show_folder"), lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._file(row).parent))))
        menu.exec(pos)

    def _params(self, row: sqlite3.Row) -> dict:
        params = json.loads(row["params"])
        params.pop("infotext", None)  # not a generation parameter
        return params

    def _load(self) -> None:
        row = self._first()
        if row:
            self.load_params.emit(self._params(row))

    def _save_preset(self) -> None:
        row = self._first()
        if not row:
            return
        name, ok = QInputDialog.getText(self, tr("hist.save_preset"), tr("lib.name"))
        name = name.strip()
        if ok and name:
            params = self._params(row)
            params.pop("init_image", None)  # a preset is about settings, not one particular source picture
            params.pop("mask_image", None)
            params["seed"] = -1 if not params.get("keep_seed") else params["seed"]
            self.ctx.db.save_preset("preset", name, params)
            self.presets_changed.emit()
            self.status.setText(tr("hist.preset_saved", name=name))

    def _repeat(self) -> None:
        for row in self._selected():
            params = self._params(row)
            params["seed"] = -1  # a repeat is a new roll of the dice; use "Load parameters" to keep the seed
            self.to_queue.emit(params)
        self.status.setText(tr("hist.queued", n=len(self._selected())))

    def _img2img(self) -> None:
        row = self._first()
        if row and self._file(row).exists():
            self.to_img2img.emit(self._file(row), row["prompt"] or "", row["negative"] or "")

    def _add_to_library(self) -> None:
        rows = [r for r in self._selected() if self._file(r).exists()]
        rating = self.rating.currentData()

        def work():
            counts = {"saved": 0, "duplicate": 0, "failed": 0}
            for r in rows:
                counts[self.ctx.library.save_generation(self._file(r), self._params(r), rating).status] += 1
            return counts

        def done(c: dict) -> None:
            self.status.setText(tr("status.saved", saved=c["saved"], dup=c["duplicate"], failed=c["failed"]))
            self.library_changed.emit()

        run_async(work, on_done=done, on_error=lambda exc: self.status.setText(tr("status.error", msg=str(exc))))

    def _delete(self) -> None:
        ids = [r["id"] for r in self._selected()]
        self.ctx.db.delete_history(ids)  # only the journal entries: the image files stay where they are
        self.reload()

    def _clear(self) -> None:
        if QMessageBox.question(self, tr("hist.clear"), tr("hist.clear_confirm")) == QMessageBox.StandardButton.Yes:
            self.ctx.db.clear_history()
            self.reload()
