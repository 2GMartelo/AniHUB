"""X/Y grid dialog (ТЗ 5.8): pick what varies along X (and Y), generate, look at the table, keep it."""
from __future__ import annotations

import time
from pathlib import Path
from typing import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction, QImage, QPixmap
from PySide6.QtWidgets import (
    QComboBox, QDialog, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QMenu, QProgressBar, QPushButton,
    QScrollArea, QVBoxLayout, QWidget,
)

from anihub.context import AppContext
from anihub.core.i18n import tr
from anihub.services.generation import GenParams, GenResult
from anihub.services.xyplot import AXES, MAX_CELLS, XYPlan, build_plan, compose_grid, parse_values, run_xy
from anihub.ui import style, theme
from anihub.ui.workers import run_async


class XYDialog(QDialog):
    """`begin()` / `end()` bracket a run: they mark Forge busy (so the queue and the Generate button stay out of the way);
    `begin` returns False when Forge is not free. `options(axis)` lists the names to pick from for list-like axes."""

    progress_changed = Signal(int)          # emitted from the worker thread, delivered in the GUI thread

    def __init__(self, ctx: AppContext, api, base: Callable[[], GenParams], begin: Callable[[], bool],
                 end: Callable[[], None], options: Callable[[str], list[str]], parent=None):
        super().__init__(parent)
        self.ctx, self.api, self._base, self._begin, self._end, self._options = ctx, api, base, begin, end, options
        self._running = False
        self._cancel = False
        self._plan: XYPlan | None = None
        self._grid: QImage | None = None
        self._grid_path: Path | None = None
        self.setWindowTitle(tr("xy.title"))
        self.resize(1100, 820)

        self.x_axis = self._axis_combo(include_none=False)
        self.y_axis = self._axis_combo(include_none=True)
        self.x_values = QLineEdit(placeholderText=tr("xy.values_ph"))
        self.y_values = QLineEdit(placeholderText=tr("xy.values_ph"))
        self.x_pick = self._pick_button(self.x_axis, self.x_values)
        self.y_pick = self._pick_button(self.y_axis, self.y_values)
        form = QFormLayout()
        form.addRow(tr("xy.x"), self._row(self.x_axis, self.x_values, self.x_pick))
        form.addRow(tr("xy.y"), self._row(self.y_axis, self.y_values, self.y_pick))
        self.x_axis.setCurrentIndex(self.x_axis.findData("steps"))
        self.x_values.setText("20, 28, 36")
        self.count = QLabel()
        style.role(self.count, "dim")
        self.message = QLabel()
        self.message.setWordWrap(True)
        self.progress = QProgressBar()
        self.progress.setTextVisible(True)
        self.start_btn = style.primary(QPushButton(tr("xy.start")), "zap")
        self.stop_btn = style.danger(QPushButton(tr("sd.interrupt")), "stop")
        self.stop_btn.setEnabled(False)
        self.save_btn = style.secondary(QPushButton(tr("xy.save_as")), "save")
        self.lib_btn = style.secondary(QPushButton(tr("xy.to_library")), "folder")
        self.save_btn.setEnabled(False)
        self.lib_btn.setEnabled(False)
        hint = QLabel(tr("xy.hint"))
        hint.setWordWrap(True)
        style.role(hint, "muted")
        buttons = QHBoxLayout()
        for w in (self.start_btn, self.stop_btn, self.save_btn, self.lib_btn):
            buttons.addWidget(w)
        buttons.addStretch(1)
        self.view = QLabel(alignment=Qt.AlignmentFlag.AlignCenter)
        self.view.setText(tr("xy.empty"))
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setWidget(self.view)
        layout = QVBoxLayout(self)
        layout.addWidget(hint)
        layout.addLayout(form)
        layout.addWidget(self.count)
        layout.addLayout(buttons)
        layout.addWidget(self.progress)
        layout.addWidget(self.message)
        layout.addWidget(self.scroll, 1)

        for w in (self.x_axis, self.y_axis):
            w.currentIndexChanged.connect(self._axis_changed)
        for w in (self.x_values, self.y_values):
            w.textChanged.connect(self._update_count)
        self.progress_changed.connect(self.progress.setValue)
        self.start_btn.clicked.connect(self.start)
        self.stop_btn.clicked.connect(self.stop)
        self.save_btn.clicked.connect(self._save_as)
        self.lib_btn.clicked.connect(self._to_library)
        self._axis_changed()

    # --- widgets ------------------------------------------------------------------------------------

    def _axis_combo(self, include_none: bool) -> QComboBox:
        box = QComboBox()
        if include_none:
            box.addItem(tr("xy.none"), None)
        for axis in AXES:
            box.addItem(tr(f"xy.axis.{axis}"), axis)
        return box

    def _pick_button(self, axis_box: QComboBox, edit: QLineEdit) -> QPushButton:
        button = style.secondary(QPushButton(tr("xy.pick")), "list")
        menu = QMenu(button)
        menu.aboutToShow.connect(lambda: self._fill_menu(menu, axis_box, edit))
        button.setMenu(menu)
        return button

    def _fill_menu(self, menu: QMenu, axis_box: QComboBox, edit: QLineEdit) -> None:
        menu.clear()
        chosen = {t.strip() for t in edit.text().split(",")}
        for name in self._options(axis_box.currentData() or "")[:200]:
            action = QAction(name, menu)
            action.setCheckable(True)
            action.setChecked(name in chosen)
            action.toggled.connect(lambda on, n=name: self._toggle_name(edit, n, on))
            menu.addAction(action)

    @staticmethod
    def _toggle_name(edit: QLineEdit, name: str, on: bool) -> None:
        names = [t.strip() for t in edit.text().split(",") if t.strip()]
        if on and name not in names:
            names.append(name)
        elif not on and name in names:
            names.remove(name)
        edit.setText(", ".join(names))

    @staticmethod
    def _row(*widgets: QWidget) -> QWidget:
        holder = QWidget()
        row = QHBoxLayout(holder)
        row.setContentsMargins(0, 0, 0, 0)
        for i, w in enumerate(widgets):
            row.addWidget(w, 1 if isinstance(w, QLineEdit) else 0)
        return holder

    def _axis_changed(self) -> None:
        for axis_box, values, pick in ((self.x_axis, self.x_values, self.x_pick), (self.y_axis, self.y_values, self.y_pick)):
            axis = axis_box.currentData()
            values.setEnabled(axis is not None)
            pick.setVisible(axis in ("sampler_name", "scheduler", "model"))
            if axis == "prompt_sr":
                values.setPlaceholderText(tr("xy.sr_ph"))
            else:
                values.setPlaceholderText(tr("xy.values_ph"))
        self._update_count()

    # --- planning ------------------------------------------------------------------------------------

    def make_plan(self) -> XYPlan:
        """Raises ValueError with a readable message when the input is not usable."""
        x_axis = self.x_axis.currentData()
        y_axis = self.y_axis.currentData()
        x_values = parse_values(x_axis, self.x_values.text())
        y_values = parse_values(y_axis, self.y_values.text()) if y_axis else []
        return build_plan(self._base(), x_axis, x_values, y_axis, y_values)

    def _update_count(self) -> None:
        try:
            x = len(parse_values(self.x_axis.currentData(), self.x_values.text()))
            y_axis = self.y_axis.currentData()
            y = len(parse_values(y_axis, self.y_values.text())) if y_axis else 1
            total = x * y
            self.count.setText(tr("xy.count", x=x, y=y, n=total) if total <= MAX_CELLS else tr("xy.too_many", n=total, max=MAX_CELLS))
            self.start_btn.setEnabled(not self._running and total <= MAX_CELLS)
        except ValueError as exc:
            self.count.setText(str(exc))
            self.start_btn.setEnabled(False)

    # --- running -------------------------------------------------------------------------------------

    def start(self) -> None:
        if self._running:
            return
        try:
            plan = self.make_plan()
        except ValueError as exc:
            self.message.setText(tr("status.error", msg=str(exc)))
            return
        if not self._begin():
            self.message.setText(tr("xy.busy"))
            return
        self._plan, self._running, self._cancel = plan, True, False
        self._grid = None
        self._toggle_running(True)
        self.progress.setRange(0, len(plan.cells))
        self.progress.setValue(0)
        self.message.setText(tr("xy.running"))
        out_dir = self.ctx.paths.sd / "generated"
        api = self.api

        def work():
            done_cells = run_xy(api, plan, out_dir, progress=lambda i, n: self.progress_changed.emit(i),
                                cancelled=lambda: self._cancel)
            from anihub.services.generation import record_history

            record_history(self.ctx.db, self.ctx.paths.root, list(done_cells.values()), "main")
            return done_cells

        run_async(work, on_done=self._finished, on_error=self._failed)

    def stop(self) -> None:
        self._cancel = True
        self.stop_btn.setEnabled(False)
        self.message.setText(tr("sd.interrupting"))
        run_async(self.api.interrupt, on_error=lambda exc: None)

    def _toggle_running(self, running: bool) -> None:
        self.start_btn.setEnabled(not running)
        self.stop_btn.setEnabled(running)
        for w in (self.x_axis, self.y_axis, self.x_values, self.y_values):
            w.setEnabled(not running)
        if not running:
            self._axis_changed()

    def _failed(self, exc: Exception) -> None:
        self._running = False
        self._end()
        self._toggle_running(False)
        self.message.setText(tr("status.error", msg=str(exc)))

    def _finished(self, made: dict[tuple[int, int], GenResult]) -> None:
        self._running = False
        self._end()
        self._toggle_running(False)
        plan = self._plan
        if not made or plan is None:
            self.message.setText(tr("xy.nothing"))
            return
        images = {pos: QImage(str(res.path)) for pos, res in made.items()}
        self._grid = compose_grid(plan, images, dark=theme.current().dark)
        folder = self.ctx.paths.sd / "xy"
        folder.mkdir(parents=True, exist_ok=True)
        self._grid_path = folder / f"xy_{int(time.time())}.png"
        self._grid.save(str(self._grid_path), "PNG")
        self._show_grid()
        self.save_btn.setEnabled(True)
        self.lib_btn.setEnabled(True)
        partial = len(made) < len(plan.cells)
        self.message.setText(tr("xy.partial", n=len(made), total=len(plan.cells)) if partial else tr("xy.done", n=len(made)))

    def _show_grid(self) -> None:
        if self._grid is None:
            return
        width = max(self.scroll.viewport().width() - 4, 400)
        pm = QPixmap.fromImage(self._grid)
        if pm.width() > width:
            pm = pm.scaledToWidth(width, Qt.TransformationMode.SmoothTransformation)
        self.view.setPixmap(pm)

    def resizeEvent(self, e) -> None:  # noqa: N802
        super().resizeEvent(e)
        self._show_grid()

    # --- keeping the result --------------------------------------------------------------------------

    def _save_as(self) -> None:
        if self._grid is None:
            return
        path, _ = QFileDialog.getSaveFileName(self, tr("xy.save_as"), str(self._grid_path or ""), "PNG (*.png)")
        if path:
            self._grid.save(path, "PNG")

    def _to_library(self) -> None:
        if self._grid_path is None or self._plan is None:
            return
        base = self._base()
        meta = {"prompt": base.prompt, "negative_prompt": base.negative_prompt, "model": base.model,
                "width": self._grid.width(), "height": self._grid.height(),
                "xy": {"x": self._plan.x_axis, "x_values": [str(v) for v in self._plan.x_values],
                       "y": self._plan.y_axis, "y_values": [str(v) for v in self._plan.y_values]}}
        result = self.ctx.library.save_generation(self._grid_path, meta)
        self.message.setText(tr("xy.saved") if result.status == "saved" else tr("xy.already"))

    def closeEvent(self, event) -> None:  # noqa: N802
        if self._running:
            event.ignore()                    # let the run finish (or press Stop) so Forge is released properly
            self.message.setText(tr("xy.wait"))
            return
        super().closeEvent(event)

    def reject(self) -> None:
        if self._running:
            self.message.setText(tr("xy.wait"))
            return
        super().reject()
