from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QCloseEvent, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QLabel, QListWidget, QMainWindow, QMenu, QMessageBox, QScrollArea, QStackedWidget, QSystemTrayIcon, QTabWidget,
    QToolButton, QWidget, QHBoxLayout, QVBoxLayout,
)

from anihub import APP_NAME
from anihub.context import AppContext
from anihub.core.i18n import tr
from anihub.ui.anime_page import AnimePage
from anihub.ui.browse import BrowseView
from anihub.ui.downloads_view import DownloadSignals, DownloadsButton, notify_text, summary_text
from anihub.ui.forge_controller import ForgeController
from anihub.ui.library_view import LibraryView
from anihub.ui.manga_controller import MangaController
from anihub.ui.manga_page import MangaPage
from anihub.ui.novels_online import NovelsHub
from anihub.ui.subscriptions_view import SubscriptionsView
from anihub.ui.sd_page import SDPage
from anihub.ui.settings import SettingsPage
from anihub.ui.navrail import NavRail
from anihub.ui import style
from anihub.ui.style import EmptyState, state_color
from anihub.ui.theme import apply_backdrop, is_glass, make_app_icon, paint_backdrop
from anihub.ui import cookie_import
from anihub.ui.close_dialog import CloseDialog
from anihub.ui.tutorial import Step, TutorialOverlay
from anihub.ui.workers import run_async


def _placeholder(icon_name: str = "tv", title: str = "") -> QWidget:
    return EmptyState(icon_name, title, tr("placeholder.soon"))


class MainWindow(QMainWindow):
    def __init__(self, ctx: AppContext):
        super().__init__()
        self.ctx = ctx
        self._quitting = False
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(make_app_icon())
        self.resize(1300, 850)
        self.setAcceptDrops(True)          # a cookies / logins file dropped on the window logs in to the sites in it

        self.browse = BrowseView(ctx)
        self.library = LibraryView(ctx)
        self.arts = arts = QTabWidget()
        arts.addTab(self.browse, tr("tab.browse"))
        arts.addTab(self.library, tr("tab.library"))
        self.subscriptions = SubscriptionsView(ctx)
        arts.addTab(self.subscriptions, tr("subs.tab"))
        self.browse.library_changed.connect(self.library.reload)
        self.browse.subscribed.connect(self.subscriptions.reload)
        self.subscriptions.changed.connect(self._update_subscription_badge)

        self.sd_enabled = ctx.sd_enabled
        self.forge = None
        self.sd_page = None
        self.forge_status = None
        self.sd_controllers: dict = {}
        if self.sd_enabled:
            self.forge = ForgeController(
                ctx.forge, idle_minutes=lambda: int(ctx.cfg.get("forge.idle_minutes", 0) or 0), parent=self)
            # one controller per backend: the primary Forge plus optional extra instances (multi-GPU)
            self.sd_controllers = {"main": self.forge}
            for backend in ctx.backends[1:]:
                self.sd_controllers[backend.name] = ForgeController(
                    backend, idle_minutes=lambda: int(ctx.cfg.get("forge.idle_minutes", 0) or 0), parent=self)
                self.sd_controllers[backend.name].poll()
            self.sd_page = SDPage(ctx, self.forge, self.sd_controllers)
            self.forge.state_changed.connect(self._on_forge_state)
            self.forge_status = QLabel()
            self.statusBar().addPermanentWidget(self.forge_status)
            self._on_forge_state(self.forge.state.value)
            self.forge.poll()  # attach to an already running Forge, if any

            # library -> img2img bridge (ТЗ 5.3)
            self.library.send_to_img2img.connect(self._to_img2img)
            self.sd_page.saved.send_to_img2img.connect(self._to_img2img)
        self.manga_ctrl = MangaController(ctx, parent=self)
        self.manga_page = MangaPage(ctx, self.manga_ctrl)
        self.manga_ctrl.new_chapters.connect(self._on_new_chapters)
        self.manga_ctrl.state_changed.connect(self._on_manga_state)
        self.manga_status = QLabel()
        self.statusBar().addPermanentWidget(self.manga_status)
        self._on_manga_state(self.manga_ctrl.state.value)
        self.manga_ctrl.poll()
        self.manga_ctrl.autostart_if_enabled()

        self.anime_page = AnimePage(ctx)
        self.novels_hub = NovelsHub(ctx)
        self.novels_page = self.novels_hub.shelf
        self.settings = SettingsPage(ctx, quit_app=self.quit_app)
        self.settings.saved.connect(self.library.reload)

        self.lora_train_enabled = ctx.lora_train_enabled
        self.lora_train_page = None
        if self.lora_train_enabled:
            from anihub.ui.lora_train_page import LoraTrainPage

            self.lora_train_page = LoraTrainPage(ctx)
            self.settings.saved.connect(self.lora_train_page.reload_checkpoints)

        self.pages = QStackedWidget()
        # (key, title, page, icon): manga, then light novels right under it; generation only where Forge can run
        sections = [("arts", tr("nav.arts"), arts, "image"), ("manga", tr("nav.manga"), self.manga_page, "book"),
                    ("novels", tr("nav.novels"), self.novels_hub, "file-text")]
        if self.sd_enabled:
            sections.append(("sd", tr("nav.sd"), self.sd_page, "sparkles"))
        if self.lora_train_enabled:
            sections.append(("lora_train", tr("nav.lora_train"), self.lora_train_page, "layers"))
        sections += [("anime", tr("nav.anime"), self.anime_page, "tv"), ("settings", tr("nav.settings"), self.settings, "sliders")]
        self.nav = NavRail()
        self.rows: dict[str, int] = {}
        for i, (key, title, page, icon_name) in enumerate(sections):
            self.rows[key] = i
            self.nav.add_item(title, icon_name, bottom=(key == "settings"))  # settings sit at the bottom
            self.pages.addWidget(page)
        self.nav.currentRowChanged.connect(self.pages.setCurrentIndex)
        self.nav.setCurrentRow(0)

        self.offline_banner = QLabel(tr("offline.banner"))
        self.offline_banner.setObjectName("offlineBanner")
        self.offline_banner.setWordWrap(True)
        content = QWidget()
        cl = QVBoxLayout(content)
        cl.setContentsMargins(10, 8, 10, 4)
        cl.addWidget(self.offline_banner)
        cl.addWidget(self.pages)
        central = QWidget()
        row = QHBoxLayout(central)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        row.addWidget(self.nav)
        row.addWidget(content, 1)
        self.setCentralWidget(central)

        apply_backdrop(self)                                       # Windows 11 Mica behind the translucent window, if enabled
        self.download_signals = DownloadSignals(self)
        ctx.downloads.on_change = self.download_signals.changed.emit
        ctx.downloads.on_batch = self.download_signals.batch.emit
        self.downloads_btn = DownloadsButton(ctx, self.download_signals)
        self.statusBar().insertPermanentWidget(0, self.downloads_btn)
        self.download_signals.batch.connect(self._batch_finished)

        self.update_btn = QToolButton()
        self.update_btn.setObjectName("updateNotice")
        self.update_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.update_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.update_btn.hide()
        self._pending_release = None
        self.update_btn.clicked.connect(self._show_update)
        self.statusBar().insertPermanentWidget(0, self.update_btn)
        self.settings.about.update_found.connect(self._update_found)
        self.settings.about.tutorial_requested.connect(self.start_tutorial)
        self._tutorial: TutorialOverlay | None = None
        QTimer.singleShot(6000, self._auto_check_updates)          # after startup, in the background
        QTimer.singleShot(20000, self._auto_backup)
        self._subs_timer = QTimer(self)
        self._subs_timer.timeout.connect(self._poll_subscriptions)
        self._subs_timer.start(5 * 60 * 1000)
        QTimer.singleShot(45000, self._poll_subscriptions)
        self._update_subscription_badge()
        QShortcut(QKeySequence("Ctrl+K"), self, activated=self.open_palette)
        self.error_btn = QToolButton()
        self.error_btn.setObjectName("updateNotice")
        self.error_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.error_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.error_btn.setText(tr("bug.notice"))
        style.bind_icon(self.error_btn, "zap", "danger", 16)
        self.error_btn.hide()
        self.error_btn.clicked.connect(self._report_error)
        self.statusBar().insertPermanentWidget(0, self.error_btn)
        self._error_timer = QTimer(self)
        self._error_timer.timeout.connect(self._check_errors)
        self._error_timer.start(2000)
        if ctx.cfg.get("backup.restored_notice", False):
            ctx.cfg.set("backup.restored_notice", False)
            QTimer.singleShot(1500, lambda: self.statusBar().showMessage(tr("backup.restored"), 15000))

        self.offline_btn = QToolButton()
        self.offline_btn.setObjectName("offlineToggle")
        self.offline_btn.setCheckable(True)
        self.offline_btn.setToolTip(tr("offline.tip"))
        self.offline_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.offline_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.statusBar().insertPermanentWidget(0, self.offline_btn)
        self.offline_btn.toggled.connect(self.set_offline)
        self.offline_btn.setChecked(bool(ctx.cfg.get("network.offline", False)))
        self.set_offline(self.offline_btn.isChecked())

        self._setup_tray()
        run_async(ctx.library.auto_purge, on_error=lambda exc: None)  # empty what sat in the trash past the grace period

    def _batch_finished(self, result) -> None:
        self.browse.on_batch(tr("dl.batch_status", details=summary_text(result.counts)))
        if result.total >= int(self.ctx.cfg.get("downloads.notify_min", 10)) and getattr(self, "tray", None) is not None:
            self.tray.showMessage(APP_NAME, notify_text(result), QSystemTrayIcon.MessageIcon.Information, 6000)

    def _update_subscription_badge(self) -> None:
        n = self.ctx.subscriptions.total_new()
        index = self.arts.indexOf(self.subscriptions)
        self.arts.setTabText(index, tr("subs.tab") + (f" ({n})" if n else ""))

    def _poll_subscriptions(self) -> None:
        """Every hour (setting): look for new posts of the followed searches; a notice when there are some."""
        svc = self.ctx.subscriptions
        if self.ctx.cfg.get("network.offline", False) or not svc.is_due() or not self.ctx.db.subscriptions():
            return
        self.ctx.cfg.set("subscriptions.last_poll", time.time())

        def done(results) -> None:
            self.subscriptions.reload()
            fresh = sum(len(r.new) for r in results if not r.saved)
            saved = sum(r.saved for r in results)
            if (fresh or saved) and getattr(self, "tray", None) is not None:
                self.tray.showMessage(APP_NAME, tr("subs.notice", fresh=fresh, saved=saved), QSystemTrayIcon.MessageIcon.Information, 6000)

        run_async(svc.check_all, on_done=done, on_error=lambda exc: None)

    def open_palette(self) -> None:
        """Ctrl+K: jump to a section, run an action, find a tag / book / show."""
        from anihub.ui.command_palette import CommandPalette
        from anihub.ui.palette_providers import build_providers

        dlg = CommandPalette(build_providers(self), self)
        dlg.move(self.geometry().center().x() - dlg.width() // 2, self.geometry().top() + 120)
        dlg.exec()

    def _check_errors(self) -> None:
        from anihub.services import bugreport

        if bugreport.take_unseen_error():
            self.error_btn.show()

    def _report_error(self) -> None:
        from anihub.ui.bugreport_dialog import BugReportDialog

        self.error_btn.hide()
        BugReportDialog(self.ctx.cfg, self).exec()

    def _auto_backup(self) -> None:
        from anihub.services import backup

        run_async(lambda: backup.run_if_due(self.ctx.paths, self.ctx.cfg), on_error=lambda exc: None)

    def _auto_check_updates(self) -> None:
        if self.ctx.cfg.get("network.offline", False):
            return
        run_async(self.ctx.updater.check, on_done=lambda r: r and self._update_found(r), on_error=lambda exc: None)

    def _update_found(self, release) -> None:
        self._pending_release = release
        style.bind_icon(self.update_btn, "download", "accent", 16)
        self.update_btn.setText(tr("update.notice", v=release.version))
        self.update_btn.show()
        if getattr(self, "tray", None) is not None and self.tray.isVisible():
            self.tray.showMessage(APP_NAME, tr("update.notice", v=release.version), QSystemTrayIcon.MessageIcon.Information, 6000)

    def _show_update(self) -> None:
        if self._pending_release is not None:
            from anihub.ui.update_dialog import UpdateDialog

            UpdateDialog(self.ctx.updater, self._pending_release, self.quit_app, self).exec()

    def set_offline(self, value: bool) -> None:
        """Offline mode (ТЗ 5.10): the HTTP layer refuses non-local requests, and everything that needs the internet
        is switched off in the UI. Local Forge, the library and already downloaded chapters keep working."""
        self.ctx.cfg.set("network.offline", bool(value))
        self.offline_banner.setVisible(bool(value))
        style.bind_icon(self.offline_btn, "wifi-off" if value else "wifi", "normal", 16)
        self.offline_btn.setText(tr("offline.offline" if value else "offline.online"))
        arts = self.arts
        arts.setTabEnabled(arts.indexOf(self.browse), not value)
        if value and arts.currentWidget() is self.browse:
            arts.setCurrentWidget(self.library)
        manga_tabs = self.manga_page.tabs
        for tab in (self.manga_page.browse, self.manga_page.extensions):
            manga_tabs.setTabEnabled(manga_tabs.indexOf(tab), not value)
        if value and manga_tabs.currentWidget() in (self.manga_page.browse, self.manga_page.extensions):
            manga_tabs.setCurrentWidget(self.manga_page.library)
        self.anime_page.set_offline(bool(value))
        if self.sd_page is not None:
            sd_tabs = self.sd_page.tabs
            sd_tabs.setTabEnabled(sd_tabs.indexOf(self.sd_page.civitai), not value)
            if value and sd_tabs.currentWidget() is self.sd_page.civitai:
                sd_tabs.setCurrentWidget(self.sd_page.generate)

    @staticmethod
    def _scrollable(widget: QWidget) -> QScrollArea:
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QScrollArea.Shape.NoFrame)
        area.setWidget(widget)
        return area

    def _setup_tray(self) -> None:
        self.tray = QSystemTrayIcon(make_app_icon(), self)
        menu = QMenu()
        show = QAction(tr("tray.show"), menu)
        show.triggered.connect(self._show_from_tray)
        quit_action = QAction(tr("tray.quit"), menu)
        quit_action.triggered.connect(self.quit_app)
        menu.addAction(show)
        menu.addAction(quit_action)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(
            lambda reason: self._show_from_tray() if reason == QSystemTrayIcon.ActivationReason.Trigger else None)
        self.tray.show()

    def _on_forge_state(self, state: str) -> None:
        self.forge_status.setText(f'<span style="color:{state_color(state)}">●</span>&nbsp; Forge: {tr(f"forge.state.{state}")}')

    def go(self, section: str) -> None:
        """Switch to a section by name ("arts", "manga", "novels", "sd", "anime", "settings"); a hidden one is ignored."""
        row = self.rows.get(section)
        if row is not None:
            self.nav.setCurrentRow(row)

    def open_music(self) -> None:
        """Jumps straight to Anime > Music (the "AniHUB Music" launcher's whole purpose)."""
        self.go("anime")
        self.anime_page.tabs.setCurrentWidget(self.anime_page.music_hub)

    def _to_img2img(self, row: dict) -> None:
        """Open the SD section with the chosen library picture as the img2img source."""
        from pathlib import Path
        from anihub.ui.library_view import row_prompt
        path = self.ctx.paths.root / (row["trash_path"] if row.get("trashed_at") and row.get("trash_path") else row["path"])
        prompt, negative = row_prompt(self.ctx, row)
        self.go("sd")
        self.sd_page.show_generate_tab()
        self.sd_page.generate.use_as_init(Path(path), prompt, negative)

    def _on_manga_state(self, state: str) -> None:
        self.manga_status.setText(f'<span style="color:{state_color(state)}">●</span>&nbsp; {tr("nav.manga")}: {tr(f"forge.state.{state}")}')

    def _on_new_chapters(self, chapters: list) -> None:
        titles = ", ".join(dict.fromkeys(c["manga"]["title"] for c in chapters))
        self.tray.showMessage(APP_NAME, tr("manga.new_chapters", n=len(chapters), titles=titles[:200]),
                              QSystemTrayIcon.MessageIcon.Information, 8000)

    def _show_from_tray(self) -> None:
        self.showNormal()
        self.activateWindow()

    def quit_app(self) -> None:
        self._quitting = True
        self.ctx.downloads.shutdown()
        for controller in self.sd_controllers.values():
            controller.stop_blocking()  # free the VRAM; only stops a Forge that AniHUB itself started
        self.manga_ctrl.stop_blocking()
        self.tray.hide()
        QApplication.quit()

    # --- first-run tutorial ---------------------------------------------------------------------------------

    def tutorial_steps(self) -> list[Step]:
        def section(name: str, tab: int | None = None):
            def go() -> None:
                self.go(name)
                if tab is not None:
                    self.arts.setCurrentIndex(tab)
            return go

        rail = lambda name: (lambda: self.nav._buttons[self.rows[name]])
        steps = [
            Step("welcome", None, section("arts", 0)),
            Step("nav_arts", rail("arts"), section("arts", 0)),
            Step("tabs", self.arts.tabBar, section("arts", 0)),
            Step("source", lambda: self.browse.source, section("arts", 0)),
            Step("search", lambda: self.browse.query, section("arts", 0)),
            Step("save", lambda: self.browse.save_btn, section("arts", 0)),
        ]
        if self.sd_enabled:
            steps.append(Step("tag_constructor", None, section("arts", 0)))
        steps += [
            Step("subscribe", lambda: self.browse.subscribe_btn, section("arts", 0)),
            Step("library2", lambda: self.library.side, section("arts", 1)),
            Step("downloads", lambda: self.downloads_btn, section("arts", 0)),
            Step("nav_manga", rail("manga"), section("manga")),
            Step("reader", None, section("manga")),
            Step("nav_novels", rail("novels"), section("novels")),
            Step("novels_tabs", self.novels_hub.tabBar, section("novels")),
        ]
        if self.sd_enabled:
            sd_tab = lambda index: (lambda: (self.go("sd"), self.sd_page.tabs.setCurrentIndex(index)))    # noqa: E731
            steps += [
                Step("nav_sd", rail("sd"), section("sd")),
                Step("sd_generate", lambda: self.sd_page.generate.generate_btn, sd_tab(0)),
                Step("sd_builder", self.sd_page.tabs.tabBar, sd_tab(self.sd_page.tabs.indexOf(self.sd_page.builder))),
                Step("sd_lora", self.sd_page.tabs.tabBar, sd_tab(self.sd_page.tabs.indexOf(self.sd_page.lora))),
                Step("sd_character", self.sd_page.tabs.tabBar, sd_tab(self.sd_page.tabs.indexOf(self.sd_page.character))),
            ]
        if self.lora_train_enabled:
            steps.append(Step("nav_lora_train", rail("lora_train"), section("lora_train")))
        steps += [
            Step("nav_anime", rail("anime"), section("anime")),
            Step("anime_tabs", self.anime_page.tabs.tabBar, section("anime")),
            Step("anime_shelf", lambda: self.anime_page.watch.source_box, lambda: (self.go("anime"), self.anime_page.tabs.setCurrentWidget(self.anime_page.watch))),
            Step("logins", lambda: self.settings.import_btn, section("settings")),
            Step("appearance", lambda: self.settings.theme, section("settings")),
            Step("age", lambda: self.settings.age_mode, section("settings")),
            Step("offline", lambda: self.offline_btn, section("settings")),
            Step("palette", None, section("arts", 0)),
            Step("close", None, section("arts", 0)),
            Step("finish", None, section("arts", 0)),
        ]
        return steps

    def maybe_install_forge(self) -> None:
        """The first-run wizard chose "download Forge": do it now (once), with a progress window."""
        dest = str(self.ctx.cfg.get("sd.install_pending") or "")
        if not dest or not self.sd_enabled or self._tutorial is not None:
            return
        from anihub.ui.forge_install_dialog import ForgeInstallDialog

        self.ctx.cfg.set("sd.install_pending", "")
        dlg = ForgeInstallDialog(self.ctx, Path(dest), self)
        dlg.exec()
        if dlg.installed is not None:
            self.settings.forge_path.setText(str(dlg.installed))

    def start_tutorial(self) -> None:
        """The guided tour (after the first run, or from Settings / the command palette)."""
        if self._tutorial is not None:
            return
        overlay = self._tutorial = TutorialOverlay(self, self.tutorial_steps())
        overlay.finished.connect(self._tutorial_done)
        overlay.start()

    def _tutorial_done(self, _completed: bool) -> None:
        self._tutorial = None
        self.ctx.cfg.set("tutorial.pending", False)
        self.go("arts")
        self.arts.setCurrentIndex(0)
        QTimer.singleShot(500, self.maybe_install_forge)

    def paintEvent(self, event) -> None:  # noqa: N802
        paint_backdrop(self)                                       # smooth gradient, glows and sparkles (translucent over Mica in glass mode)

    def _ask_close(self) -> tuple[str, bool] | None:
        """The first time the window is closed: quit for good or keep running in the tray? -> (action, remember) or None (cancel)."""
        dlg = CloseDialog(self)
        dlg.exec()
        return (dlg.choice, dlg.remember) if dlg.choice else None

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        urls = [u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]
        if urls and all(cookie_import.is_cookie_file(u) for u in urls):
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802
        for url in event.mimeData().urls():
            if url.isLocalFile() and cookie_import.is_cookie_file(url.toLocalFile()):
                cookie_import.import_path(self.ctx, Path(url.toLocalFile()), self)
        event.acceptProposedAction()

    def closeEvent(self, event: QCloseEvent) -> None:
        # The first time the user chooses between quitting and the tray (and may remember it); the tray keeps background
        # work (downloads, subscriptions, manga updates) running (ТЗ раздел 7).
        if self._quitting or not self.tray.isVisible():
            event.accept()
            return
        action = str(self.ctx.cfg.get("ui.close_action", "") or "")
        if action not in ("tray", "quit"):
            choice = self._ask_close()
            if choice is None:
                event.ignore()
                return
            action, remember = choice
            if remember:
                self.ctx.cfg.set("ui.close_action", action)
        if action == "quit":
            self.quit_app()
            event.accept()
            return
        event.ignore()
        self.hide()
        self.tray.showMessage(APP_NAME, tr("tray.msg"), QSystemTrayIcon.MessageIcon.Information, 3000)
