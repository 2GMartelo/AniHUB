"""Manga section: service bar (install / start / stop), tabs (library, browse, extensions, updates)."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QHBoxLayout, QLabel, QProgressBar, QPushButton, QStackedWidget, QTabWidget, QVBoxLayout, QWidget,
)

from anihub.context import AppContext
from anihub.core.i18n import tr
from anihub.services.procservice import ServiceState
from anihub.ui.manga_controller import MangaController
from anihub.ui.manga_detail import MangaDetail
from anihub.ui.manga_views import MangaBrowseTab, MangaExtensionsTab, MangaLibraryTab, MangaUpdatesTab
from anihub.ui import style
from anihub.ui.sd_page import ForgeLogDialog
from anihub.ui.style import EmptyState, StatusChip


class MangaPage(QWidget):
    def __init__(self, ctx: AppContext, ctrl: MangaController, parent=None):
        super().__init__(parent)
        self.ctx, self.ctrl = ctx, ctrl
        self._details: list[MangaDetail] = []
        self._new_count = 0

        # service bar
        self.chip = StatusChip()
        self.dot, self.state_label = self.chip.dot, self.chip.text
        self.start_btn = style.primary(QPushButton(tr("manga.start")), "play")
        self.stop_btn = style.secondary(QPushButton(tr("manga.stop")), "stop")
        self.log_btn = style.ghost(QPushButton(tr("sd.log")), "list")
        self.autostart = QCheckBox(tr("manga.autostart"), checked=bool(ctx.cfg.get("manga.autostart")))
        self.error = QLabel()
        style.role(self.error, "error")
        self.error.setWordWrap(True)
        bar = QHBoxLayout()
        bar.setSpacing(8)
        for w in (self.chip, self.start_btn, self.stop_btn, self.log_btn, self.autostart):
            bar.addWidget(w)
        bar.addStretch(1)

        # install panel
        self.install_text = QLabel(tr("manga.install_text"))
        self.install_text.setWordWrap(True)
        self.install_btn = style.primary(QPushButton(tr("manga.install")), "download")
        self.install_btn.setMinimumHeight(40)
        self.cancel_btn = QPushButton(tr("manga.install_cancel"))
        self.cancel_btn.hide()
        self.progress = QProgressBar()
        self.progress.hide()
        self.progress_text = QLabel()
        panel = QWidget()
        pl = QVBoxLayout(panel)
        pl.addStretch(1)
        for w in (self.install_text, self.install_btn, self.progress, self.progress_text, self.cancel_btn):
            pl.addWidget(w, 0, Qt.AlignmentFlag.AlignHCenter if isinstance(w, QPushButton) else Qt.AlignmentFlag.AlignLeft)
        pl.addStretch(2)
        panel.setMaximumWidth(700)
        holder = QWidget()
        QHBoxLayout(holder).addWidget(panel, 1, Qt.AlignmentFlag.AlignHCenter)

        # tabs
        self.library = MangaLibraryTab(ctx, ctrl)
        self.browse = MangaBrowseTab(ctx, ctrl)
        self.extensions = MangaExtensionsTab(ctx, ctrl)
        self.updates = MangaUpdatesTab(ctx, ctrl)
        self.tabs = QTabWidget()
        self.tabs.addTab(self.library, tr("manga.tab.library"))
        self.tabs.addTab(self.browse, tr("manga.tab.browse"))
        self.tabs.addTab(self.extensions, tr("manga.tab.extensions"))
        self.tabs.addTab(self.updates, tr("manga.tab.updates"))
        self.banner = EmptyState("book", tr("manga.stopped_title"), tr("manga.need_service"))
        content = QWidget()
        cl = QVBoxLayout(content)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.addWidget(self.banner)
        cl.addWidget(self.tabs, 1)
        self.stack = QStackedWidget()
        self.stack.addWidget(holder)
        self.stack.addWidget(content)

        layout = QVBoxLayout(self)
        layout.addLayout(bar)
        layout.addWidget(self.error)
        layout.addWidget(self.stack, 1)

        self.start_btn.clicked.connect(self._start)
        self.stop_btn.clicked.connect(ctrl.stop)
        self.log_btn.clicked.connect(lambda: ForgeLogDialog(ctrl, self).show())
        self.autostart.toggled.connect(lambda v: ctx.cfg.set("manga.autostart", v))
        self.install_btn.clicked.connect(self._install)
        self.cancel_btn.clicked.connect(ctrl.cancel_install)
        ctrl.state_changed.connect(self._on_state)
        ctrl.error.connect(lambda msg: self.error.setText(msg))
        ctrl.install_progress.connect(self._on_progress)
        ctrl.install_finished.connect(self._on_install_finished)
        ctrl.bootstrapped.connect(self.reload_all)
        ctrl.new_chapters.connect(self._on_new_chapters)
        self.library.open_manga.connect(self.open_manga)
        self.browse.open_manga.connect(self.open_manga)
        self.updates.open_chapter.connect(lambda mid, cid: self.open_manga(mid, cid))
        self.extensions.catalogue_changed.connect(self.browse.reload_sources)
        self.tabs.currentChanged.connect(self._on_tab)
        self._on_state(ctrl.state.value)

    # --- state -------------------------------------------------------------------------------------------

    def _on_state(self, state: str) -> None:
        s = ServiceState(state)
        installed = self.ctrl.is_installed()
        self.stack.setCurrentIndex(1 if installed else 0)
        self.chip.set_state(state, tr("nav.manga") + " · " + tr(f"forge.state.{state}"))
        self.start_btn.setEnabled(installed and s in (ServiceState.STOPPED, ServiceState.FAILED))
        self.stop_btn.setEnabled(s in (ServiceState.STARTING, ServiceState.RUNNING))
        self.stop_btn.setToolTip(tr("forge.external_hint") if s == ServiceState.EXTERNAL else "")
        self.banner.setVisible(not s.ready)
        self.tabs.setVisible(s.ready)
        if s == ServiceState.FAILED:
            self.error.setText(tr("forge.failed_hint"))
        elif s.ready:
            self.error.clear()

    def _start(self) -> None:
        self.error.clear()
        self.ctrl.start()

    # --- installation ------------------------------------------------------------------------------------

    def _install(self) -> None:
        self.error.clear()
        self.install_btn.setEnabled(False)
        self.progress.show()
        self.cancel_btn.show()
        self.progress.setRange(0, 0)
        self.progress_text.setText(tr("manga.install.release"))
        self.ctrl.install()

    def _on_progress(self, stage: str, done: int, total: int) -> None:
        if stage == "download":
            self.progress.setRange(0, max(total, 1))
            self.progress.setValue(done)
            self.progress_text.setText(tr("manga.install.download", done=done / 1e6, total=total / 1e6))
        else:
            self.progress.setRange(0, 0)
            self.progress_text.setText(tr(f"manga.install.{stage}"))

    def _on_install_finished(self, version: str) -> None:
        self.progress.hide()
        self.cancel_btn.hide()
        self.progress_text.clear()
        self.install_btn.setEnabled(True)
        if version:
            self._on_state(self.ctrl.state.value)
            self.ctrl.start()

    # --- data --------------------------------------------------------------------------------------------

    def reload_all(self) -> None:
        self.library.reload()
        self.browse.reload_sources()
        self.extensions.load()
        self.updates.reload()

    def _on_tab(self, index: int) -> None:
        if self.tabs.widget(index) is self.updates:
            self._new_count = 0
            self.tabs.setTabText(index, tr("manga.tab.updates"))
            self.updates.reload()
        elif self.tabs.widget(index) is self.library:
            self.library.reload()

    def _on_new_chapters(self, chapters: list) -> None:
        self._new_count += len(chapters)
        self.tabs.setTabText(self.tabs.indexOf(self.updates), f"{tr('manga.tab.updates')} ({self._new_count})")

    def open_manga(self, manga_id: int, start_chapter: int | None = None) -> None:
        detail = MangaDetail(self.ctx, self.ctrl, manga_id, start_chapter)
        detail.changed.connect(self.library.reload)
        detail.destroyed.connect(lambda: self._details.remove(detail) if detail in self._details else None)
        self._details.append(detail)
        detail.show()
