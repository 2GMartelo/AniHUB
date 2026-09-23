import threading
import time
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QObject, Signal

from anihub.core.config import Config
from anihub.core.db import Database
from anihub.core.paths import LibraryPaths
from anihub.services.generation import GenParams, GenResult
from anihub.services.procservice import ServiceState
from anihub.ui.sd_queue import QueueController


class FakeApi:
    def __init__(self):
        self.interrupted = False

    def interrupt(self):
        self.interrupted = True


class FakeController(QObject):
    state_changed = Signal(str)

    def __init__(self, ready=True, start_becomes_ready=True):
        super().__init__()
        self.state = ServiceState.RUNNING if ready else ServiceState.STOPPED
        self.manager = SimpleNamespace(api=FakeApi())
        self.busy = False
        self.started = self.stopped = 0
        self.start_becomes_ready = start_becomes_ready
        self.was_external = False

    def set_busy(self, busy):
        self.busy = busy

    def start(self):
        self.started += 1
        if self.start_becomes_ready:
            self.state = ServiceState.RUNNING
            self.state_changed.emit("running")

    def stop(self):
        self.stopped += 1
        self.state = ServiceState.STOPPED
        self.state_changed.emit("stopped")


def pump(qapp, cond, timeout=10):
    end = time.time() + timeout
    while time.time() < end:
        qapp.processEvents()
        if cond():
            return True
        time.sleep(0.01)
    return False


@pytest.fixture
def env(tmp_path, qapp):
    paths = LibraryPaths(tmp_path / "lib")
    paths.ensure()
    cfg = Config.load(tmp_path / "c.json")
    ctx = SimpleNamespace(db=Database(paths.db_file), paths=paths, cfg=cfg)
    return ctx, paths


def make_runner(paths, log, delay=0.05, fail_on=None):
    def run(api, params, out_dir, on_batch=None, should_stop=None):
        log.append((threading.current_thread().name, params.prompt, time.time()))
        time.sleep(delay)
        if fail_on and params.prompt == fail_on:
            raise RuntimeError("boom")
        if api.interrupted:
            time.sleep(0.01)
        img = out_dir / f"{params.prompt}.png"
        img.parent.mkdir(parents=True, exist_ok=True)
        img.write_bytes(b"x")
        result = [GenResult(img, 1, {"prompt": params.prompt, "model": "m"})]
        if on_batch is not None:
            on_batch(result)                                                  # a real run_job reports as it goes
        return result
    return run


def make_multi_batch_runner(paths, batches=3, delay=0.05):
    """A job that produces several pieces, like a real batch count above 1 -- used to check that `on_batch` reaches
    the GUI as `partial_results` for each piece, and that `should_stop` is actually consulted between them."""
    def run(api, params, out_dir, on_batch=None, should_stop=None):
        out_dir.mkdir(parents=True, exist_ok=True)
        produced = []
        for i in range(batches):
            if should_stop is not None and should_stop():
                break
            time.sleep(delay)
            img = out_dir / f"{params.prompt}_{i}.png"
            img.write_bytes(b"x")
            piece = [GenResult(img, i, {"prompt": params.prompt})]
            produced.extend(piece)
            if on_batch is not None:
                on_batch(piece)
        return produced
    return run


def statuses(ctx):
    return [r["status"] for r in ctx.db.queue_list()]


def test_two_backends_share_the_queue_without_double_runs(env, qapp):
    ctx, paths = env
    log = []
    ctrls = {"main": FakeController(), "gpu1": FakeController()}
    qc = QueueController(ctx, ctrls, run_job=make_runner(paths, log, delay=0.15))
    finished, done = [], []
    qc.job_finished.connect(finished.append)
    qc.all_done.connect(lambda: done.append(1))
    qc.add(GenParams(prompt="a"))
    qc.add(GenParams(prompt="b"))
    qc.add(GenParams(prompt="c"))
    qc.start()
    assert pump(qapp, lambda: bool(done))
    assert statuses(ctx) == ["done"] * 3
    assert sorted(p for _t, p, _s in log) == ["a", "b", "c"]                  # each job exactly once
    assert {r["backend"] for r in ctx.db.queue_list()} == {"main", "gpu1"}     # both backends were used
    assert len(finished) == 3 and ctx.db.history_count() == 3                  # results reported + logged in history
    assert not qc.running and not qc.active and not ctrls["main"].busy         # busy flag released


def test_failed_job_does_not_stop_the_queue(env, qapp):
    ctx, paths = env
    ctrls = {"main": FakeController()}
    qc = QueueController(ctx, ctrls, run_job=make_runner(paths, [], fail_on="bad"))
    done = []
    qc.all_done.connect(lambda: done.append(1))
    for p in ("ok1", "bad", "ok2"):
        qc.add(GenParams(prompt=p))
    qc.start()
    assert pump(qapp, lambda: bool(done))
    assert statuses(ctx) == ["done", "failed", "done"]
    assert "boom" in ctx.db.queue_list()[1]["error"]


def test_no_ready_backend_stops_with_a_message(env, qapp):
    ctx, paths = env
    qc = QueueController(ctx, {"main": FakeController(ready=False)}, run_job=make_runner(paths, []))
    messages = []
    qc.message.connect(messages.append)
    qc.add(GenParams(prompt="a"))
    qc.start()
    assert not qc.running and messages and statuses(ctx) == ["pending"]


def test_backend_that_becomes_ready_later_picks_the_queue_up(env, qapp):
    ctx, paths = env
    ctrl = FakeController(ready=False)
    ctrl.state = ServiceState.STARTING                                         # coming up: the queue must wait, not give up
    qc = QueueController(ctx, {"main": ctrl}, run_job=make_runner(paths, []))
    done = []
    qc.all_done.connect(lambda: done.append(1))
    qc.add(GenParams(prompt="a"))
    qc.start()
    assert qc.running and statuses(ctx) == ["pending"]
    ctrl.state = ServiceState.RUNNING
    ctrl.state_changed.emit("running")
    assert pump(qapp, lambda: bool(done)) and statuses(ctx) == ["done"]


def test_manual_generation_reserves_a_backend(env, qapp):
    ctx, paths = env
    log = []
    ctrls = {"main": FakeController(), "gpu1": FakeController()}
    qc = QueueController(ctx, ctrls, run_job=make_runner(paths, log))
    qc.set_external_busy("main", True)
    done = []
    qc.all_done.connect(lambda: done.append(1))
    qc.add(GenParams(prompt="a"), 2)
    qc.start()
    assert pump(qapp, lambda: bool(done))
    assert {r["backend"] for r in ctx.db.queue_list()} == {"gpu1"}             # main was busy with the Generate button


def test_cancel_interrupts_the_backend_and_marks_the_job(env, qapp):
    ctx, paths = env
    ctrl = FakeController()
    qc = QueueController(ctx, {"main": ctrl}, run_job=make_runner(paths, [], delay=0.3))
    qc.add(GenParams(prompt="a"))
    qc.add(GenParams(prompt="b"))
    qc.start()
    assert pump(qapp, lambda: qc.is_busy("main"))
    qc.cancel_current()
    assert pump(qapp, lambda: not qc.active)
    assert ctrl.manager.api.interrupted
    assert statuses(ctx) == ["cancelled", "pending"]                           # the next job stays queued


def test_partial_results_are_delivered_as_each_piece_of_a_job_finishes(env, qapp):
    ctx, paths = env
    qc = QueueController(ctx, {"main": FakeController()}, run_job=make_multi_batch_runner(paths, batches=3))
    seen = []
    qc.partial_results.connect(seen.append)
    finished = []
    qc.job_finished.connect(finished.append)
    qc.add(GenParams(prompt="a"))
    qc.start()
    assert pump(qapp, lambda: len(seen) >= 3)
    assert [p[0].seed for p in seen] == [0, 1, 2]                              # one signal per piece, in order
    assert pump(qapp, lambda: bool(finished))
    assert len(finished[0]) == 3                                               # job_finished still carries the whole job


def test_cancelling_a_multi_piece_job_stops_it_before_the_next_piece(env, qapp):
    ctx, paths = env
    ctrl = FakeController()
    qc = QueueController(ctx, {"main": ctrl}, run_job=make_multi_batch_runner(paths, batches=5, delay=0.1))
    qc.add(GenParams(prompt="a"))
    qc.start()
    assert pump(qapp, lambda: qc.is_busy("main"))
    time.sleep(0.15)                                                           # let one or two pieces land first
    qc.cancel_current()
    assert pump(qapp, lambda: not qc.active)
    assert statuses(ctx) == ["cancelled"]
    assert ctrl.manager.api.interrupted


def test_queue_add_with_count_randomises_seeds_of_the_copies(env, qapp):
    ctx, paths = env
    qc = QueueController(ctx, {"main": FakeController()}, run_job=make_runner(paths, []))
    qc.add(GenParams(prompt="a", seed=42), count=3)
    import json
    assert [json.loads(r["params"])["seed"] for r in ctx.db.queue_list()] == [42, -1, -1]


def test_stale_running_jobs_are_recovered_on_startup(env, qapp):
    ctx, paths = env
    job = ctx.db.queue_add({"prompt": "x"}, "x")
    ctx.db.queue_claim("main")                                                 # the app died while it was running
    QueueController(ctx, {"main": FakeController()}, run_job=make_runner(paths, []))
    assert ctx.db.queue_get(job)["status"] == "pending"


# --- schedule ----------------------------------------------------------------------------------------------

def scheduled(qc, **over):
    qc.save_schedule(enabled=True, time="02:00", repeat="daily", start_forge=True, stop_forge_after=True,
                     idle_minutes=0, last_run="", **over)
    qc.now = lambda: datetime(2026, 9, 20, 3, 0)


def test_schedule_starts_backends_runs_queue_and_stops_only_what_it_started(env, qapp):
    ctx, paths = env
    was_running, was_stopped = FakeController(ready=True), FakeController(ready=False)
    qc = QueueController(ctx, {"main": was_running, "gpu1": was_stopped}, run_job=make_runner(paths, []))
    scheduled(qc)
    qc.add(GenParams(prompt="a"))
    done = []
    qc.all_done.connect(lambda: done.append(1))
    qc._check_schedule()
    assert pump(qapp, lambda: bool(done))
    assert was_stopped.started == 1 and was_running.started == 0               # only the stopped one was started
    assert pump(qapp, lambda: was_stopped.stopped == 1)
    assert was_running.stopped == 0                                            # the user's own Forge is left alone
    assert qc.schedule()["last_run"] == "2026-09-20"
    qc._check_schedule()
    assert not qc.running                                                      # once per day


def test_schedule_respects_idle_requirement_and_disabling_for_once(env, qapp):
    ctx, paths = env
    ctrl = FakeController()
    qc = QueueController(ctx, {"main": ctrl}, run_job=make_runner(paths, []))
    scheduled(qc, )
    qc.save_schedule(idle_minutes=10)
    qc.idle_seconds = lambda: 60                                               # user active 1 minute ago
    qc.add(GenParams(prompt="a"))
    qc._check_schedule()
    assert not qc.running and statuses(ctx) == ["pending"]                     # waits for an idle PC
    qc.idle_seconds = lambda: 3600
    qc.save_schedule(repeat="once")
    qc._check_schedule()
    assert qc.running or statuses(ctx) != ["pending"]
    assert qc.schedule()["enabled"] is False                                   # a one-off run disables itself


def test_schedule_with_empty_queue_does_nothing_but_is_marked_as_used(env, qapp):
    ctx, paths = env
    ctrl = FakeController(ready=False)
    qc = QueueController(ctx, {"main": ctrl}, run_job=make_runner(paths, []))
    scheduled(qc)
    qc._check_schedule()
    assert ctrl.started == 0 and not qc.running and qc.schedule()["last_run"] == "2026-09-20"
