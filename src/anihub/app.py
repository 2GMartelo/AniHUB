from __future__ import annotations

import sys

from PySide6.QtCore import QThreadPool
from PySide6.QtWidgets import QApplication

from anihub import APP_NAME
from anihub.context import AppContext
from anihub.core.config import Config
from anihub.core.i18n import set_language
from anihub.core.logging_setup import setup_logging
from anihub.ui.main_window import MainWindow
from anihub.ui.theme import apply_theme, make_app_icon
from anihub.ui.wizard import SetupWizard


def main() -> int:
    setup_logging()
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setWindowIcon(make_app_icon())
    app.setQuitOnLastWindowClosed(False)  # the main window hides to the tray instead of quitting

    cfg = Config.load()
    set_language(cfg.get("language"))
    apply_theme(app, cfg.get("theme"))

    if not cfg.get("first_run_done") or not cfg.get("library_path"):
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
    code = app.exec()
    QThreadPool.globalInstance().waitForDone(3000)  # let running workers finish before Qt objects go away
    return code
