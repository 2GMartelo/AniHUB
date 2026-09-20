from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QCloseEvent
from PySide6.QtWidgets import (
    QApplication, QLabel, QListWidget, QMainWindow, QMenu, QScrollArea, QStackedWidget, QSystemTrayIcon, QTabWidget,
    QWidget, QHBoxLayout, QVBoxLayout,
)

from anihub import APP_NAME
from anihub.context import AppContext
from anihub.core.i18n import tr
from anihub.ui.browse import BrowseView
from anihub.ui.forge_controller import ForgeController
from anihub.ui.library_view import LibraryView
from anihub.ui.manga_controller import MangaController
from anihub.ui.manga_page import MangaPage
from anihub.ui.sd_page import SDPage
from anihub.ui.settings import SettingsPage
from anihub.ui.navrail import NavRail
from anihub.ui.style import EmptyState, state_color
from anihub.ui.theme import make_app_icon
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

        self.browse = BrowseView(ctx)
        self.library = LibraryView(ctx)
        arts = QTabWidget()
        arts.addTab(self.browse, tr("tab.browse"))
        arts.addTab(self.library, tr("tab.library"))
        self.browse.library_changed.connect(self.library.reload)

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

        self.settings = SettingsPage(ctx)
        self.settings.saved.connect(self.library.reload)

        self.pages = QStackedWidget()
        sections = [
            (tr("nav.arts"), arts), (tr("nav.manga"), self.manga_page), (tr("nav.sd"), self.sd_page),
            (tr("nav.anime"), _placeholder("tv", tr("nav.anime"))), (tr("nav.settings"), self.settings),
        ]
        self.nav = NavRail()
        nav_icons = ["image", "book", "sparkles", "tv", "sliders"]
        for i, ((title, page), icon_name) in enumerate(zip(sections, nav_icons)):
            self.nav.add_item(title, icon_name, bottom=(i == len(sections) - 1))  # settings sit at the bottom
            self.pages.addWidget(page)
        self.nav.currentRowChanged.connect(self.pages.setCurrentIndex)
        self.nav.setCurrentRow(0)

        content = QWidget()
        cl = QVBoxLayout(content)
        cl.setContentsMargins(10, 8, 10, 4)
        cl.addWidget(self.pages)
        central = QWidget()
        row = QHBoxLayout(central)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        row.addWidget(self.nav)
        row.addWidget(content, 1)
        self.setCentralWidget(central)

        self._setup_tray()
        run_async(ctx.library.auto_purge, on_error=lambda exc: None)  # empty what sat in the trash past the grace period

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

    def _to_img2img(self, row: dict) -> None:
        """Open the SD section with the chosen library picture as the img2img source."""
        from pathlib import Path
        from anihub.ui.library_view import row_prompt
        path = self.ctx.paths.root / (row["trash_path"] if row.get("trashed_at") and row.get("trash_path") else row["path"])
        prompt, negative = row_prompt(self.ctx, row)
        self.nav.setCurrentRow(2)
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
        for controller in self.sd_controllers.values():
            controller.stop_blocking()  # free the VRAM; only stops a Forge that AniHUB itself started
        self.manga_ctrl.stop_blocking()
        self.tray.hide()
        QApplication.quit()

    def closeEvent(self, event: QCloseEvent) -> None:
        # Closing the window minimises to the tray so background work is not interrupted (ТЗ раздел 7).
        if self._quitting or not self.tray.isVisible():
            event.accept()
            return
        event.ignore()
        self.hide()
        self.tray.showMessage(APP_NAME, tr("tray.msg"), QSystemTrayIcon.MessageIcon.Information, 3000)
