import threading
import time
from types import SimpleNamespace

import pytest

from anihub.core.config import Config
from anihub.net.http import BandwidthLimiter, HttpClient, HttpError
from anihub.services.downloads import CANCELLED, DONE, DUPLICATE, FAILED, QUEUED, DownloadManager
from anihub.sources.base import Post


def post(i, site="s"):
    return Post(site, str(i), f"https://x/{i}.png", "https://x/t.png")


def wait_for(cond, limit=5.0):
    end = time.time() + limit
    while time.time() < end and not cond():
        time.sleep(0.01)
    return cond()


class FakeLibrary:
    """save_post blocks on a gate so tests can look at the queue mid-flight."""

    def __init__(self, gated=False, outcomes=None):
        self.gate = threading.Event()
        if not gated:
            self.gate.set()
        self.saved, self.running, self.peak, self.lock = [], 0, 0, threading.Lock()
        self.outcomes = outcomes or {}

    def save_post(self, p):
        with self.lock:
            self.running += 1
            self.peak = max(self.peak, self.running)
        try:
            self.gate.wait(5)
            outcome = self.outcomes.get(p.id, "saved")
            if outcome == "boom":
                raise RuntimeError("boom")
            with self.lock:
                self.saved.append(p.id)
            return SimpleNamespace(status=outcome, error="HTTP 0: cancelled" if outcome == "failed-cancel" else "", item_id=1, similar=[])
        finally:
            with self.lock:
                self.running -= 1


class FakeHttpAbort:
    def __init__(self):
        self.aborts = 0

    def abort_downloads(self):
        self.aborts += 1


def manager(tmp_path, library, parallel=2):
    cfg = Config.load(tmp_path / "c.json")
    cfg.set("downloads.parallel", parallel, save=False)
    batches, changes = [], []
    m = DownloadManager(library, FakeHttpAbort(), cfg, on_change=lambda: changes.append(1), on_batch=batches.append)
    return m, batches, changes


def test_batch_runs_in_parallel_up_to_the_limit_and_reports_once(tmp_path):
    lib = FakeLibrary(gated=True)
    m, batches, changes = manager(tmp_path, lib, parallel=2)
    m.submit([post(i) for i in range(6)])
    assert wait_for(lambda: lib.running == 2)                    # two at a time, the rest wait
    assert m.counts() == {"running": 2, "queued": 4}
    lib.gate.set()
    assert wait_for(lambda: m.active == 0)
    assert lib.peak == 2 and sorted(lib.saved) == [str(i) for i in range(6)]
    assert wait_for(lambda: len(batches) == 1) and batches[0].counts == {DONE: 6} and batches[0].total == 6 and changes
    m.shutdown()


def test_pause_stops_new_downloads_and_resume_continues(tmp_path):
    lib = FakeLibrary()
    m, batches, _ = manager(tmp_path, lib, parallel=1)
    m.pause()
    m.submit([post(i) for i in range(3)])
    time.sleep(0.3)
    assert lib.saved == [] and m.counts() == {QUEUED: 3} and m.paused
    m.resume()
    assert wait_for(lambda: m.active == 0) and len(lib.saved) == 3 and not m.paused
    m.shutdown()


def test_cancel_queued_only_or_abort_running_too(tmp_path):
    lib = FakeLibrary(gated=True)
    m, batches, _ = manager(tmp_path, lib, parallel=1)
    m.submit([post(i) for i in range(4)])
    assert wait_for(lambda: lib.running == 1)
    ids = [j.id for j in m.jobs() if j.status == QUEUED][:1]
    assert m.cancel(set(ids)) == 1                                # one selected job
    assert m.cancel() == 2 and m.http.aborts == 0                 # the remaining queued ones; the running one is untouched
    assert m.cancel(abort_running=True) == 0 and m.http.aborts == 1
    lib.gate.set()
    assert wait_for(lambda: m.active == 0)
    counts = m.counts()
    assert counts[CANCELLED] == 3 and counts[DONE] == 1
    assert wait_for(lambda: len(batches) == 1)                    # the batch is reported exactly once
    time.sleep(0.2)
    assert len(batches) == 1
    m.shutdown()


def test_outcomes_failures_duplicates_and_retry(tmp_path):
    lib = FakeLibrary(outcomes={"1": "duplicate", "2": "failed", "3": "boom", "4": "failed-cancel"})
    m, batches, _ = manager(tmp_path, lib, parallel=1)
    m.submit([post(i) for i in range(5)])
    assert wait_for(lambda: m.active == 0)
    by_id = {j.post.id: j for j in m.jobs()}
    assert by_id["0"].status == DONE and by_id["1"].status == DUPLICATE and by_id["2"].status == FAILED
    assert by_id["3"].status == FAILED and by_id["3"].error == "boom"                # an exception never kills the worker
    assert by_id["4"].status == CANCELLED                                            # an aborted download is not a failure
    lib.outcomes = {}
    assert m.retry_failed() == 2
    assert wait_for(lambda: m.active == 0)
    assert {j.status for j in m.jobs() if j.post.id in ("2", "3")} == {DONE}
    assert wait_for(lambda: len(batches) == 2)                                       # finished again after the retry
    m.clear_finished()
    assert m.jobs() == []
    m.shutdown()


def test_separate_batches_are_reported_separately(tmp_path):
    m, batches, _ = manager(tmp_path, FakeLibrary(), parallel=2)
    a = m.submit([post(1), post(2)])
    b = m.submit([post(3)])
    assert wait_for(lambda: len(batches) == 2)
    assert {r.batch: r.total for r in batches} == {a: 2, b: 1}
    m.shutdown()


# --- the speed limit -------------------------------------------------------------------------------------------

def test_bandwidth_limiter_spaces_chunks_over_time():
    now = [100.0]
    slept = []

    def sleep(s):
        slept.append(round(s, 3))
        now[0] += s

    bw = BandwidthLimiter(clock=lambda: now[0], sleep=sleep)
    assert bw.consume(1000, 0) == 0 and bw.consume(0, 1000) == 0                     # unlimited / nothing to send
    assert bw.consume(1000, 1000) == 0                                               # the first second is free
    assert bw.consume(1000, 1000) == 1.0 and bw.consume(500, 1000) == 1.0 and slept == [1.0, 1.0]
    now[0] += 60                                                                     # a long pause does not bank bandwidth
    assert bw.consume(1000, 1000) == 0 and bw.consume(1000, 1000) == 1.0


def test_http_client_reads_the_speed_limit_and_aborts(tmp_path):
    cfg = Config.load(tmp_path / "c.json")
    http = HttpClient(cfg)
    assert http.speed_limit == 0
    cfg.set("network.speed_limit_mb", 2.5, save=False)
    assert http.speed_limit == 2.5 * 1_048_576
    cfg.set("network.speed_limit_mb", "junk", save=False)
    assert http.speed_limit == 0
    generation = http._abort_generation
    http.abort_downloads()
    assert http._abort_generation == generation + 1


def test_download_stops_when_aborted_and_applies_the_limit(tmp_path):
    """A real HttpClient.download against a stub stream: abort -> 'cancelled', limiter called for every chunk."""
    cfg = Config.load(tmp_path / "c.json")
    http = HttpClient(cfg)
    consumed = []
    http._bandwidth = SimpleNamespace(consume=lambda n, rate: consumed.append((n, rate)))
    cfg.set("network.speed_limit_mb", 1, save=False)

    class Resp:
        status_code = 200
        headers = {"Content-Length": "300"}

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def iter_bytes(self, n):
            for _ in range(3):
                yield b"a" * 100
                if len(consumed) == 2:
                    http.abort_downloads()

    http._client = SimpleNamespace(stream=lambda *a, **k: Resp())
    with pytest.raises(HttpError, match="cancelled"):
        http.download("https://x/a.bin", tmp_path / "a.bin")
    assert consumed == [(100, 1_048_576), (100, 1_048_576)]
    assert not (tmp_path / "a.bin").exists() and not (tmp_path / "a.bin.part").exists()


# --- UI -------------------------------------------------------------------------------------------------------

def dl_ctx(tmp_path, library):
    cfg = Config.load(tmp_path / "c.json")
    cfg.set("downloads.parallel", 1, save=False)
    m = DownloadManager(library, FakeHttpAbort(), cfg)
    return SimpleNamespace(cfg=cfg, downloads=m), m


def test_downloads_window_lists_jobs_and_controls_the_queue(qapp, tmp_path):
    from anihub.core.i18n import tr
    from anihub.ui.downloads_view import DownloadSignals, DownloadsButton, DownloadsDialog, summary_text

    lib = FakeLibrary(gated=True)
    ctx, m = dl_ctx(tmp_path, lib)
    signals = DownloadSignals()
    m.on_change = signals.changed.emit
    button = DownloadsButton(ctx, signals)
    dlg = DownloadsDialog(ctx, signals)
    assert button.isHidden() and dlg.tree.topLevelItemCount() == 0
    m.submit([post(i) for i in range(3)])
    assert wait_for(lambda: lib.running == 1)
    for _ in range(50):
        qapp.processEvents()
        time.sleep(0.01)
    dlg.refresh()
    assert dlg.tree.topLevelItemCount() == 3 and not button.isHidden() and "3" in button.text()
    dlg.pause_btn.click()
    assert m.paused and dlg.pause_btn.text() == tr("dl.resume")
    dlg.tree.topLevelItem(2).setSelected(True)
    dlg.cancel_btn.click()
    assert m.counts().get("cancelled") == 1
    dlg.speed.setValue(1.5)
    dlg.parallel.setValue(4)
    assert ctx.cfg.get("network.speed_limit_mb") == 1.5 and ctx.cfg.get("downloads.parallel") == 4
    dlg.pause_btn.click()
    lib.gate.set()
    assert wait_for(lambda: m.active == 0)
    dlg.refresh()
    assert dlg.retry_btn.isEnabled() is False
    assert summary_text({"done": 2, "failed": 1}) == "сохранено 2, ошибок 1" and summary_text({}) == "ничего"
    dlg.clear_btn.click()
    assert m.jobs() == []
    m.shutdown()
