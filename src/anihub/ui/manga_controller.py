"""Manga module supervisor: install/start/stop Suwayomi, first-run bootstrap, new-chapter notifications."""
from __future__ import annotations

import logging
import time

from PySide6.QtCore import QObject, QTimer, Signal

from anihub.context import AppContext
from anihub.core.i18n import tr
from anihub.services.procservice import ServiceState
from anihub.services.suwayomi_install import install
from anihub.ui.forge_controller import ServiceController
from anihub.ui.workers import run_async

log = logging.getLogger(__name__)

UPDATE_EVERY_S = 6 * 3600  # how often we ask Suwayomi to refresh the library from the sources


class MangaController(QObject):
    state_changed = Signal(str)
    error = Signal(str)
    install_progress = Signal(str, int, int)  # stage, done, total (emitted from the worker thread)
    install_finished = Signal(str)            # version, or "" on failure
    bootstrapped = Signal()                   # store + categories are ready: views may load data
    new_chapters = Signal(list)               # chapters (dicts with manga{id,title}) found since the last check

    def __init__(self, ctx: AppContext, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.manager = ctx.suwayomi
        self.api = ctx.suwayomi.api
        self.service = ServiceController(self.manager, parent=self)
        self.service.state_changed.connect(self._on_state)
        self.service.state_changed.connect(self.state_changed)
        self.service.error.connect(self.error)
        self._installing = False
        self._cancel = False
        self._bootstrap_done = False
        self._checking = False
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.check_updates)
        self.timer.start(max(1, int(ctx.cfg.get("manga.poll_minutes", 30))) * 60_000)

    @property
    def state(self) -> ServiceState:
        return self.manager.state

    def is_installed(self) -> bool:
        return self.manager.installed() is not None

    # --- lifecycle ---------------------------------------------------------------------------------------

    def start(self) -> None:
        self.service.start()

    def stop(self) -> None:
        self._bootstrap_done = False
        self.service.stop()

    def stop_blocking(self) -> None:
        self.service.stop_blocking()

    def poll(self) -> None:
        self.service.poll()

    def autostart_if_enabled(self) -> None:
        if self.ctx.cfg.get("manga.autostart") and self.is_installed():
            self.start()

    # --- installation ------------------------------------------------------------------------------------

    @property
    def installing(self) -> bool:
        return self._installing

    def install(self) -> None:
        if self._installing:
            return
        self._installing, self._cancel = True, False

        def work() -> str:
            return install(self.ctx.http, self.manager.install_dir,
                           progress=lambda stage, done, total: self.install_progress.emit(stage, done, total),
                           cancelled=lambda: self._cancel)

        def done(version: str) -> None:
            self._installing = False
            self.install_finished.emit(version)

        def failed(exc: Exception) -> None:
            self._installing = False
            self.error.emit(str(exc))
            self.install_finished.emit("")

        run_async(work, on_done=done, on_error=failed)

    def cancel_install(self) -> None:
        self._cancel = True

    # --- first use ---------------------------------------------------------------------------------------

    def _on_state(self, state: str) -> None:
        if ServiceState(state).ready and not self._bootstrap_done:
            self._bootstrap_done = True
            self._bootstrap()
        elif not ServiceState(state).ready:
            self._bootstrap_done = False

    def _bootstrap(self) -> None:
        api = self.api

        def work() -> None:
            if api.ensure_default_store():
                api.refresh_extensions()
            cats = api.categories()
            if len(cats) <= 1:  # only Suwayomi's "Default": create the reading-status categories (ТЗ 4.5)
                for key in ("reading", "completed", "on_hold", "dropped", "plan"):
                    api.create_category(tr(f"manga.cat.{key}"))
            if int(self.ctx.cfg.get("manga.seen_chapter_id", -1)) < 0:  # baseline: do not announce old chapters
                self._baseline()

        run_async(work, on_done=lambda _: self.bootstrapped.emit(),
                  on_error=lambda exc: self.error.emit(str(exc)))

    # --- new chapters ------------------------------------------------------------------------------------
    # State (config): manga.seen_chapter_id = highest chapter id already examined; manga.known_ids = library titles
    # whose chapter list we have seen. Chapters of an unknown title are learned silently: otherwise adding a title
    # and letting Suwayomi fetch its whole chapter list would announce hundreds of "new" chapters.

    def _baseline(self) -> None:
        cfg = self.ctx.cfg
        cfg.set("manga.known_ids", [m["id"] for m in self.api.library()], save=False)
        cfg.set("manga.seen_chapter_id", self.api.max_chapter_id())

    def mark_known(self, manga_id: int) -> None:
        """Call when the user adds a title to the library (its current chapters are not 'new')."""
        known = set(self.ctx.cfg.get("manga.known_ids", []) or [])
        known.add(manga_id)
        self.ctx.cfg.set("manga.known_ids", sorted(known))

    def check_updates(self, force_refresh: bool = False) -> None:
        """Ask Suwayomi to refresh the library now and then, and report chapters that appeared since last time."""
        if self._checking or not self.manager.state.ready:
            return
        self._checking = True
        cfg, api = self.ctx.cfg, self.api

        def work() -> list[dict]:
            last = float(cfg.get("manga.last_update_ts", 0) or 0)
            if force_refresh or time.time() - last > UPDATE_EVERY_S:
                api.update_library()
                cfg.set("manga.last_update_ts", time.time(), save=False)
            seen = int(cfg.get("manga.seen_chapter_id", -1))
            if seen < 0:
                self._baseline()
                return []
            fresh = api.chapters_after(seen)
            if not fresh:
                return []
            known = set(cfg.get("manga.known_ids", []) or [])
            announce = [c for c in fresh if c["manga"]["id"] in known and not c["isRead"]]
            known.update(c["manga"]["id"] for c in fresh)
            cfg.set("manga.known_ids", sorted(known), save=False)
            cfg.set("manga.seen_chapter_id", max(c["id"] for c in fresh))
            return announce

        def done(chapters: list[dict]) -> None:
            self._checking = False
            if chapters:
                self.new_chapters.emit(chapters)

        def failed(exc: Exception) -> None:
            self._checking = False
            log.info("update check: %s", exc)

        run_async(work, on_done=done, on_error=failed)
