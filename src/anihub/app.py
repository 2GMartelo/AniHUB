from __future__ import annotations

import sys
import threading

from PySide6.QtCore import QThreadPool, QTimer
from PySide6.QtWidgets import QApplication

from anihub import APP_NAME
from anihub.core.config import Config
from anihub.core.i18n import set_language, tr
from anihub.core.logging_setup import setup_logging
from anihub.ui.theme import apply_theme, make_app_icon, set_custom_colors


def set_taskbar_identity() -> None:
    """Windows groups taskbar buttons and pinned shortcuts by "AppUserModelID", not by window icon. Without setting
    one explicitly, a window launched via python.exe (a dev run) or even the packaged .exe can end up grouped under
    python.exe's own identity/icon instead of AniHUB's -- this makes the running window's identity match the desktop
    shortcut regardless of how it was started. Must run before QApplication() creates the first window."""
    if sys.platform != "win32":
        return
    import ctypes

    aumid = "AniHUB.Music" if "--music" in sys.argv else "AniHUB.App"
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(aumid)
    except (AttributeError, OSError):
        pass


def make_splash(text: str):
    """A small window shown the moment the process has a QApplication, before the (slow) import of the whole UI and the
    construction of every page -- the app used to show nothing at all for several seconds after a click on its icon."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor, QFont, QPainter, QPixmap
    from PySide6.QtWidgets import QSplashScreen

    pm = QPixmap(360, 200)
    pm.fill(QColor("#1b1426"))
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.drawPixmap(20, 44, make_app_icon().pixmap(96, 96))
    painter.setPen(QColor("white"))
    font = QFont("Segoe UI")
    font.setPixelSize(30)
    font.setBold(True)
    painter.setFont(font)
    painter.drawText(136, 96, APP_NAME)
    font.setPixelSize(14)
    font.setBold(False)
    painter.setFont(font)
    painter.setPen(QColor("#b9a9d6"))
    painter.drawText(138, 124, text)
    painter.end()
    splash = QSplashScreen(pm, Qt.WindowType.WindowStaysOnTopHint)
    splash.show()
    return splash


def main() -> int:
    setup_logging()
    set_taskbar_identity()
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setWindowIcon(make_app_icon())
    app.setQuitOnLastWindowClosed(False)  # the main window hides to the tray instead of quitting
    cfg = Config.load()
    set_language(cfg.get("language"))
    splash = make_splash(tr("status.loading"))
    app.processEvents()

    from anihub.services.backends import gpu_list

    threading.Thread(target=gpu_list, daemon=True).start()       # nvidia-smi takes ~0.6 s; Settings reads the cached answer
    from anihub.context import AppContext
    from anihub.ui import smoothscroll
    from anihub.ui.main_window import MainWindow
    from anihub.ui.wizard import SetupWizard

    set_custom_colors(cfg.get("theme_custom"))
    smoothscroll.install(app, bool(cfg.get("ui.smooth_scroll", True)))
    apply_theme(app, cfg.get("theme"))

    if not cfg.get("first_run_done") or not cfg.get("library_path"):
        splash.hide()
        wizard = SetupWizard(cfg)
        if not wizard.exec():
            return 0
    apply_theme(app, cfg.get("theme"), glass=bool(cfg.get("ui.glass", True)))     # the wizard is opaque; the main window may be glass

    from pathlib import Path

    from anihub.core.paths import LibraryPaths
    from anihub.services.backup import apply_pending_restore

    if apply_pending_restore(LibraryPaths(Path(cfg.get("library_path")))):      # a restore chosen in Settings; must run before the DB opens
        cfg.set("backup.restored_notice", True)
    ctx = AppContext.build(cfg)
    window = MainWindow(ctx)
    window.show()
    splash.finish(window)
    from pathlib import Path

    from anihub.ui import cookie_import

    for arg in sys.argv[1:]:                                        # a cookies / logins file given to the program (drag it onto the exe, "open with")
        if cookie_import.is_cookie_file(arg) and Path(arg).is_file():
            QTimer.singleShot(600, lambda a=arg: cookie_import.import_path(ctx, Path(a), window))
    if "--music" in sys.argv[1:]:                                   # launched from the "AniHUB Music" shortcut/exe
        QTimer.singleShot(0, window.open_music)
    if cfg.get("tutorial.pending"):                                 # set by the setup wizard: show the tour once
        QTimer.singleShot(900, window.start_tutorial)
    code = app.exec()
    from anihub.ui.workers import thumb_pool

    thumb_pool().waitForDone(1000)
    QThreadPool.globalInstance().waitForDone(3000)  # let running workers finish before Qt objects go away
    return code
