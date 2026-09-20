"""Download manager (раздел 14): a queue of posts to save, several at once, pause / resume, cancel, one notification per batch.

Workers are plain threads calling LibraryService.save_post (which downloads through the shared HttpClient, so the proxy,
per-host rate limit, offline switch and speed limit all apply). The manager knows nothing about Qt: it reports through
callbacks, which the UI turns into signals.
"""
from __future__ import annotations

import itertools
import logging
import threading
from dataclasses import dataclass, field
from typing import Callable

from anihub.sources.base import Post

log = logging.getLogger(__name__)

QUEUED, RUNNING, DONE, DUPLICATE, FAILED, CANCELLED = "queued", "running", "done", "duplicate", "failed", "cancelled"
FINISHED = (DONE, DUPLICATE, FAILED, CANCELLED)


@dataclass
class Job:
    id: int
    batch: int
    post: Post
    status: str = QUEUED
    error: str = ""
    item_id: int | None = None
    similar: int = 0

    @property
    def title(self) -> str:
        return f"{self.post.site} #{self.post.id}" + (f" · {self.post.title}" if self.post.title else "")


@dataclass
class BatchResult:
    batch: int
    counts: dict[str, int] = field(default_factory=dict)

    @property
    def total(self) -> int:
        return sum(self.counts.values())


class DownloadManager:
    def __init__(self, library, http, cfg, on_change: Callable[[], None] | None = None,
                 on_batch: Callable[[BatchResult], None] | None = None):
        self.library, self.http, self.cfg = library, http, cfg
        self.on_change, self.on_batch = on_change, on_batch
        self._cond = threading.Condition()
        self._jobs: list[Job] = []
        self._ids, self._batches = itertools.count(1), itertools.count(1)
        self._paused = False
        self._threads: list[threading.Thread] = []
        self._stopping = False
        self._notified: set[int] = set()

    # --- settings ---------------------------------------------------------------------------------------

    @property
    def parallel(self) -> int:
        try:
            return max(1, min(int(self.cfg.get("downloads.parallel", 3)), 16))
        except (TypeError, ValueError):
            return 3

    # --- queue ------------------------------------------------------------------------------------------

    def submit(self, posts: list[Post]) -> int:
        """Queue posts for saving; returns the batch number."""
        batch = next(self._batches)
        with self._cond:
            for post in posts:
                self._jobs.append(Job(next(self._ids), batch, post))
            self._ensure_workers()
            self._cond.notify_all()
        self._changed()
        return batch

    def jobs(self) -> list[Job]:
        with self._cond:
            return list(self._jobs)

    def counts(self) -> dict[str, int]:
        with self._cond:
            out: dict[str, int] = {}
            for j in self._jobs:
                out[j.status] = out.get(j.status, 0) + 1
            return out

    @property
    def active(self) -> int:
        c = self.counts()
        return c.get(QUEUED, 0) + c.get(RUNNING, 0)

    @property
    def paused(self) -> bool:
        return self._paused

    def pause(self) -> None:
        """Running downloads finish; nothing new starts until resume()."""
        with self._cond:
            self._paused = True
        self._changed()

    def resume(self) -> None:
        with self._cond:
            self._paused = False
            self._cond.notify_all()
        self._changed()

    def cancel(self, job_ids: set[int] | None = None, abort_running: bool = False) -> int:
        """Cancel queued jobs (all, or the given ids). With abort_running the downloads in progress are stopped as well."""
        finished_batches: set[int] = set()
        with self._cond:
            n = 0
            for j in self._jobs:
                if j.status == QUEUED and (job_ids is None or j.id in job_ids):
                    j.status = CANCELLED
                    finished_batches.add(j.batch)
                    n += 1
            self._cond.notify_all()
        if abort_running:
            self.http.abort_downloads()
        for batch in finished_batches:
            self._maybe_finish(batch)
        self._changed()
        return n

    def clear_finished(self) -> None:
        with self._cond:
            self._jobs = [j for j in self._jobs if j.status not in FINISHED]
        self._changed()

    def retry_failed(self) -> int:
        n = 0
        with self._cond:
            for j in self._jobs:
                if j.status == FAILED:
                    j.status, j.error = QUEUED, ""
                    n += 1
            for b in {j.batch for j in self._jobs if j.status == QUEUED}:
                self._notified.discard(b)
            self._ensure_workers()
            self._cond.notify_all()
        self._changed()
        return n

    def shutdown(self) -> None:
        with self._cond:
            self._stopping = True
            self._cond.notify_all()
        self.http.abort_downloads()

    # --- workers ----------------------------------------------------------------------------------------

    def _ensure_workers(self) -> None:
        self._threads = [t for t in self._threads if t.is_alive()]
        while len(self._threads) < self.parallel:
            t = threading.Thread(target=self._work, name=f"downloads-{len(self._threads)}", daemon=True)
            self._threads.append(t)
            t.start()

    def _next_job(self) -> Job | None:
        with self._cond:
            while not self._stopping:
                if not self._paused:
                    for j in self._jobs:
                        if j.status == QUEUED:
                            j.status = RUNNING
                            return j
                if len(self._threads) > self.parallel:       # the setting was lowered: surplus workers retire
                    self._threads = [t for t in self._threads if t is not threading.current_thread()]
                    return None
                self._cond.wait(1.0)
        return None

    def _work(self) -> None:
        while True:
            job = self._next_job()
            if job is None:
                return
            self._changed()
            try:
                result = self.library.save_post(job.post)
                with self._cond:
                    job.status = {"saved": DONE, "duplicate": DUPLICATE}.get(result.status, FAILED)
                    if job.status == FAILED and "cancelled" in (result.error or ""):
                        job.status = CANCELLED
                    job.error, job.item_id, job.similar = result.error, result.item_id, len(result.similar or [])
            except Exception as exc:  # noqa: BLE001 - one bad post must not kill the worker
                log.warning("download of %s failed: %s", job.title, exc)
                with self._cond:
                    job.status = CANCELLED if "cancelled" in str(exc) else FAILED
                    job.error = str(exc)
            self._changed()
            self._maybe_finish(job.batch)

    def _maybe_finish(self, batch: int) -> None:
        with self._cond:
            mine = [j for j in self._jobs if j.batch == batch]
            if not mine or batch in self._notified or any(j.status in (QUEUED, RUNNING) for j in mine):
                return
            self._notified.add(batch)
            counts: dict[str, int] = {}
            for j in mine:
                counts[j.status] = counts.get(j.status, 0) + 1
        if self.on_batch:
            try:
                self.on_batch(BatchResult(batch, counts))
            except Exception:  # noqa: BLE001
                log.exception("batch callback failed")

    def _changed(self) -> None:
        if self.on_change:
            try:
                self.on_change()
            except Exception:  # noqa: BLE001
                log.exception("change callback failed")
