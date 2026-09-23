"""Generation queue (ТЗ 5.7): a controller that feeds the backends, and its tab (queue, schedule, backends)."""
from __future__ import annotations

import json
import time
from dataclasses import asdict
from datetime import datetime

from PySide6.QtCore import QObject, Qt, QTime, QTimer, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QPushButton, QSpinBox,
    QTimeEdit, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from anihub.context import AppContext
from anihub.core.i18n import tr
from anihub.services.generation import GenParams, params_from_dict, record_history, run_generation
from anihub.services.procservice import ServiceState
from anihub.services.schedule import DEFAULT_SCHEDULE, next_run, schedule_due, system_idle_seconds
from anihub.ui import style, theme
from anihub.ui.forge_controller import ServiceController
from anihub.ui.workers import post_to_gui, run_async

def status_color(status: str) -> str:
    t = theme.current()
    return {"pending": t.muted, "running": t.accent_text, "done": t.success, "failed": t.danger,
            "cancelled": t.warning}.get(status, t.muted)


class QueueController(QObject):
    changed = Signal()
    message = Signal(str)
    running_changed = Signal(bool)
    job_finished = Signal(list)  # list[GenResult] of a finished job (the whole job, once it is fully done)
    partial_results = Signal(list)  # list[GenResult]: a piece of a still-running job, as soon as it is ready
    all_done = Signal()

    def __init__(self, ctx: AppContext, controllers: dict[str, ServiceController], run_job=run_generation,
                 parent=None):
        super().__init__(parent)
        self.ctx, self.controllers, self.run_job = ctx, controllers, run_job
        self.running = False
        self.active: dict[str, int] = {}      # backend name -> job id
        self.external_busy: set[str] = set()  # backends used by the manual Generate button
        self._cancelling = False
        self._scheduled = False
        self._started_by_schedule: list[str] = []
        self._awaiting_start: set[str] = set()
        self.now = datetime.now                # injectable for tests
        self.idle_seconds = system_idle_seconds
        ctx.db.queue_recover()                 # jobs interrupted by a previous exit become pending again
        for ctrl in controllers.values():
            ctrl.state_changed.connect(self._on_backend_state)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._check_schedule)
        self.timer.start(30_000)

    # --- queue editing ---------------------------------------------------------------------------------

    def add(self, params: GenParams, count: int = 1) -> list[int]:
        ids = []
        for i in range(max(1, count)):
            p = params if i == 0 or params.seed == -1 else GenParams(**{**asdict(params), "seed": -1})
            ids.append(self.ctx.db.queue_add(asdict(p), p.summary(80)))
        self.changed.emit()
        return ids

    def pending_count(self) -> int:
        return sum(1 for r in self.ctx.db.queue_list() if r["status"] == "pending")

    # --- running -----------------------------------------------------------------------------------------

    def start(self) -> None:
        if not self.running:
            self.running = True
            self.running_changed.emit(True)
        self._pump()

    def stop(self) -> None:
        """Let the running jobs finish, do not start new ones."""
        if self.running:
            self.running = False
            self.running_changed.emit(False)

    def cancel_current(self) -> None:
        self._cancelling = True
        self.stop()
        for name in list(self.active):
            api = self.controllers[name].manager.api
            run_async(api.interrupt, on_error=lambda exc: self.message.emit(str(exc)))

    def set_external_busy(self, name: str, busy: bool) -> None:
        (self.external_busy.add if busy else self.external_busy.discard)(name)
        if not busy:
            self._pump()

    def is_busy(self, name: str) -> bool:
        return name in self.active

    def _on_backend_state(self, _state: str) -> None:
        for name in list(self._awaiting_start):
            state = self.controllers[name].state
            if state.ready or state == ServiceState.FAILED:
                self._awaiting_start.discard(name)
        self._pump()

    def _pump(self) -> None:
        if not self.running:
            return
        for name, ctrl in self.controllers.items():
            if name in self.active or name in self.external_busy or not ctrl.state.ready:
                continue
            row = self.ctx.db.queue_claim(name)
            if row is None:
                break
            self._launch(name, ctrl, row)
        self._maybe_finish()

    def _backends_coming_up(self) -> bool:
        return bool(self._awaiting_start) or any(c.state == ServiceState.STARTING for c in self.controllers.values())

    def _maybe_finish(self) -> None:
        if self.active:
            return
        if self.pending_count() == 0:
            self.running = False
            self.running_changed.emit(False)
            self.all_done.emit()
            self._after_all_done()
        elif not self._backends_coming_up() and not any(c.state.ready for c in self.controllers.values()):
            self.running = False
            self.running_changed.emit(False)
            self.message.emit(tr("queue.no_backend"))
            self._after_all_done()

    def _launch(self, name: str, ctrl: ServiceController, row) -> None:
        job_id = row["id"]
        params = params_from_dict(json.loads(row["params"]))
        self.active[name] = job_id
        ctrl.set_busy(True)
        api, db, paths = ctrl.manager.api, self.ctx.db, self.ctx.paths

        wildcards = self.ctx.cfg.get("wildcards") or None

        def work():
            results = self.run_job(api, params, paths.sd / "generated",
                                   on_batch=lambda partial: post_to_gui(self.partial_results.emit, partial),
                                   should_stop=lambda: self._cancelling, wildcards=wildcards)
            record_history(db, paths.root, results, name)
            return results

        run_async(work, on_done=lambda results: self._finish_job(name, job_id, results, None),
                  on_error=lambda exc: self._finish_job(name, job_id, [], exc))
        self.changed.emit()

    def _finish_job(self, name: str, job_id: int, results: list, error: Exception | None) -> None:
        status = "cancelled" if self._cancelling else ("failed" if error else "done")
        self.ctx.db.queue_update(job_id, status=status, finished_at=time.time(), error=str(error) if error else None,
                                 result_count=len(results))
        self.active.pop(name, None)
        self.controllers[name].set_busy(False)
        if results:
            self.job_finished.emit(results)
        if self._cancelling and not self.active:
            self._cancelling = False
        self.changed.emit()
        self._pump()

    # --- schedule ----------------------------------------------------------------------------------------

    def schedule(self) -> dict:
        return {**DEFAULT_SCHEDULE, **(self.ctx.cfg.get("sd.schedule", {}) or {})}

    def save_schedule(self, **changes) -> None:
        self.ctx.cfg.set("sd.schedule", {**self.schedule(), **changes})

    def next_run(self) -> datetime | None:
        return next_run(self.now(), self.schedule())

    def _check_schedule(self) -> None:
        s = self.schedule()
        if self.running or not schedule_due(self.now(), s):
            return
        if s["idle_minutes"] and self.idle_seconds() < int(s["idle_minutes"]) * 60:
            return  # the PC is in use: check again in 30 s (until the window ends)
        self.save_schedule(last_run=self.now().date().isoformat(), enabled=s["enabled"] and s["repeat"] != "once")
        if self.pending_count() == 0:
            self.message.emit(tr("queue.schedule_empty"))
            return
        self._scheduled, self._started_by_schedule = True, []
        if s["start_forge"]:
            for name, ctrl in self.controllers.items():
                if not ctrl.state.ready and ctrl.state != ServiceState.STARTING:
                    self._started_by_schedule.append(name)
                    self._awaiting_start.add(name)
                    ctrl.start()
        self.message.emit(tr("queue.schedule_started"))
        self.start()

    def _after_all_done(self) -> None:
        if not self._scheduled:
            return
        self._scheduled = False
        if self.schedule()["stop_forge_after"]:
            for name in self._started_by_schedule:
                self.controllers[name].stop()  # only ever stops a backend AniHUB itself started
        self._started_by_schedule = []


class QueueView(QWidget):
    def __init__(self, ctx: AppContext, qc: QueueController, parent=None):
        super().__init__(parent)
        self.ctx, self.qc = ctx, qc
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["#", tr("queue.status"), tr("sd.prompt"), tr("sd.model"), tr("queue.params"),
                                   tr("queue.backend"), tr("queue.images")])
        self.tree.setRootIsDecorated(False)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        for i, w in enumerate((40, 90, 330, 160, 130, 80, 60)):
            self.tree.setColumnWidth(i, w)
        self.start_btn = QPushButton(tr("queue.start"))
        self.stop_btn = QPushButton(tr("queue.stop"))
        self.cancel_btn = QPushButton(tr("queue.cancel"))
        self.up_btn, self.down_btn = QPushButton("▲"), QPushButton("▼")
        self.dup_btn = QPushButton(tr("queue.duplicate"))
        self.remove_btn = QPushButton(tr("queue.remove"))
        self.clear_btn = QPushButton(tr("queue.clear_finished"))
        buttons = QHBoxLayout()
        for b in (self.start_btn, self.stop_btn, self.cancel_btn, self.up_btn, self.down_btn, self.dup_btn,
                  self.remove_btn, self.clear_btn):
            buttons.addWidget(b)
        buttons.addStretch(1)
        self.status = QLabel()
        self.status.setWordWrap(True)

        # schedule
        s = qc.schedule()
        self.sched_on = QCheckBox(tr("queue.schedule_on"), checked=bool(s["enabled"]))
        self.sched_time = QTimeEdit(QTime.fromString(s["time"], "HH:mm"))
        self.sched_time.setDisplayFormat("HH:mm")
        self.sched_repeat = QComboBox()
        self.sched_repeat.addItem(tr("queue.daily"), "daily")
        self.sched_repeat.addItem(tr("queue.once"), "once")
        self.sched_repeat.setCurrentIndex(max(self.sched_repeat.findData(s["repeat"]), 0))
        self.sched_start = QCheckBox(tr("queue.start_forge"), checked=bool(s["start_forge"]))
        self.sched_stop = QCheckBox(tr("queue.stop_forge_after"), checked=bool(s["stop_forge_after"]))
        self.sched_idle = QSpinBox(minimum=0, maximum=600, value=int(s["idle_minutes"]))
        self.next_label = QLabel()
        form = QFormLayout()
        row = QHBoxLayout()
        row.addWidget(self.sched_on)
        row.addWidget(self.sched_time)
        row.addWidget(self.sched_repeat)
        row.addStretch(1)
        form.addRow(row)
        form.addRow("", self.sched_start)
        form.addRow("", self.sched_stop)
        form.addRow(tr("queue.idle"), self.sched_idle)
        form.addRow("", self.next_label)
        sched_box = QGroupBox(tr("queue.schedule"))
        sched_box.setLayout(form)

        # backends
        self.backend_box = QGroupBox(tr("queue.backends"))
        self.backend_layout = QVBoxLayout(self.backend_box)
        self._backend_widgets: dict[str, tuple[QLabel, QPushButton, QPushButton]] = {}
        for backend in ctx.backends:
            dot, name = QLabel("●"), QLabel(f"{backend.name}  ·  " + (f"GPU {backend.gpu}" if backend.gpu is not None else tr("queue.gpu_default"))
                                            + f"  ·  :{backend.port}")
            start, stop = QPushButton(tr("sd.start")), QPushButton(tr("sd.stop"))
            row = QHBoxLayout()
            for w in (dot, name):
                row.addWidget(w)
            row.addStretch(1)
            row.addWidget(start)
            row.addWidget(stop)
            self.backend_layout.addLayout(row)
            self._backend_widgets[backend.name] = (dot, start, stop)
            start.clicked.connect(lambda _=False, n=backend.name: qc.controllers[n].start())
            stop.clicked.connect(lambda _=False, n=backend.name: qc.controllers[n].stop())

        layout = QVBoxLayout(self)
        layout.addWidget(self.tree, 1)
        layout.addLayout(buttons)
        layout.addWidget(self.status)
        lower = QHBoxLayout()
        lower.addWidget(sched_box, 1)
        lower.addWidget(self.backend_box, 1)
        layout.addLayout(lower)

        self.start_btn.clicked.connect(qc.start)
        self.stop_btn.clicked.connect(qc.stop)
        self.cancel_btn.clicked.connect(qc.cancel_current)
        self.up_btn.clicked.connect(lambda: self._move(-1))
        self.down_btn.clicked.connect(lambda: self._move(1))
        self.dup_btn.clicked.connect(self._duplicate)
        self.remove_btn.clicked.connect(self._remove)
        self.clear_btn.clicked.connect(lambda: (ctx.db.queue_clear_finished(), self.reload()))
        for w in (self.sched_on, self.sched_start, self.sched_stop):
            w.toggled.connect(self._save_schedule)
        self.sched_time.timeChanged.connect(self._save_schedule)
        self.sched_repeat.activated.connect(self._save_schedule)
        self.sched_idle.valueChanged.connect(self._save_schedule)
        qc.changed.connect(self.reload)
        qc.running_changed.connect(lambda _r: self._update_buttons())
        qc.message.connect(self.status.setText)
        self.refresh_timer = QTimer(self)
        self.refresh_timer.timeout.connect(self._refresh_backends)
        self.refresh_timer.start(2000)
        self.reload()
        self._refresh_backends()

    def _save_schedule(self, *_args) -> None:
        self.qc.save_schedule(enabled=self.sched_on.isChecked(), time=self.sched_time.time().toString("HH:mm"),
                              repeat=self.sched_repeat.currentData(), start_forge=self.sched_start.isChecked(),
                              stop_forge_after=self.sched_stop.isChecked(), idle_minutes=self.sched_idle.value(),
                              last_run="")  # a changed schedule may run today again
        self._update_next()

    def _update_next(self) -> None:
        nxt = self.qc.next_run()
        self.next_label.setText(tr("queue.next_run", when=nxt.strftime("%Y-%m-%d %H:%M")) if nxt else tr("queue.schedule_off"))

    def reload(self) -> None:
        selected = {it.data(0, Qt.ItemDataRole.UserRole) for it in self.tree.selectedItems()}
        self.tree.clear()
        for n, row in enumerate(self.ctx.db.queue_list(), 1):
            p = params_from_dict(json.loads(row["params"]))
            mode = ("inpaint" if p.mask_image else "img2img") if p.init_image else ("hires" if p.enable_hr else "txt2img")
            item = QTreeWidgetItem([str(n), tr(f"queue.st.{row['status']}"), row["label"] or p.summary(80),
                                    p.model.split(" [")[0], f"{mode} {p.width}×{p.height} · {p.steps}st ×{p.n_iter * p.batch_size}",
                                    row["backend"] or "", str(row["result_count"] or "")])
            item.setData(0, Qt.ItemDataRole.UserRole, row["id"])
            item.setForeground(1, QBrush(QColor(status_color(row["status"]))))
            if row["error"]:
                item.setToolTip(2, row["error"])
            self.tree.addTopLevelItem(item)
            item.setSelected(row["id"] in selected)
        self._update_buttons()
        self._update_next()

    def _update_buttons(self) -> None:
        running = self.qc.running
        self.start_btn.setEnabled(not running and self.qc.pending_count() > 0)
        self.stop_btn.setEnabled(running)
        self.cancel_btn.setEnabled(bool(self.qc.active))

    def _refresh_backends(self) -> None:
        for name, (dot, start, stop) in self._backend_widgets.items():
            state = self.qc.controllers[name].state
            dot.setStyleSheet(f"color: {style.state_color(state.value)}; font-size: 16px;")
            dot.setToolTip(tr(f"forge.state.{state.value}"))
            start.setEnabled(state in (ServiceState.STOPPED, ServiceState.FAILED))
            stop.setEnabled(state in (ServiceState.STARTING, ServiceState.RUNNING))

    def _ids(self) -> list[int]:
        return [it.data(0, Qt.ItemDataRole.UserRole) for it in self.tree.selectedItems()]

    def _move(self, delta: int) -> None:
        ids = self._ids()
        for job_id in (ids if delta < 0 else reversed(ids)):
            self.ctx.db.queue_move(job_id, delta)
        self.reload()

    def _duplicate(self) -> None:
        for job_id in self._ids():
            row = self.ctx.db.queue_get(job_id)
            if row:
                self.ctx.db.queue_add(json.loads(row["params"]), row["label"] or "")
        self.qc.changed.emit()

    def _remove(self) -> None:
        self.ctx.db.queue_remove(self._ids())
        self.reload()
