r"""Dev tool: finds widgets whose text does not fit (clipped buttons, labels, combo boxes) in every section and tab of the main window.

    .venv\Scripts\python tools\text_audit.py [lang] [dark|light|custom] [width height]

Uses the real fonts (no offscreen platform), a temporary library and config.
"""
from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PySide6.QtWidgets import (
    QAbstractButton, QApplication, QCheckBox, QComboBox, QGroupBox, QLabel, QRadioButton, QTabBar, QTabWidget, QWidget,
)


def clipped(root: QWidget) -> list[str]:
    """Descriptions of the visible widgets under `root` that cannot show all of their text."""
    found = []
    for w in root.findChildren(QWidget):
        if not w.isVisibleTo(root) or w.width() <= 0 or w.height() <= 0:
            continue
        name = f"{type(w).__name__}"
        if isinstance(w, QAbstractButton) and w.text() and not isinstance(w, (QCheckBox, QRadioButton)):
            need = w.sizeHint().width()
            if w.width() < need - 2:
                found.append(f"{name} '{w.text()}' width {w.width()} < {need}")
        elif isinstance(w, (QCheckBox, QRadioButton)) and w.text():
            need = w.sizeHint().width()
            if w.width() < need - 2 and not w.property("wraps"):
                found.append(f"{name} '{w.text()[:40]}' width {w.width()} < {need}")
        elif isinstance(w, QLabel) and w.text() and not w.pixmap() and w.movie() is None:
            if w.wordWrap():
                if w.height() < w.heightForWidth(w.width()) - 2:
                    found.append(f"{name}(wrap) '{w.text()[:40]}' height {w.height()} < {w.heightForWidth(w.width())}")
            elif "<" not in w.text() and w.width() < w.sizeHint().width() - 2:
                found.append(f"{name} '{w.text()[:40]}' width {w.width()} < {w.sizeHint().width()}")
        elif isinstance(w, QComboBox) and w.currentText():
            inner = w.width() - 44                                        # frame, padding and the arrow
            if w.fontMetrics().horizontalAdvance(w.currentText()) > inner:
                found.append(f"{name} '{w.currentText()[:40]}' text {w.fontMetrics().horizontalAdvance(w.currentText())} > {inner}")
        elif isinstance(w, QGroupBox) and w.title():
            if w.fontMetrics().horizontalAdvance(w.title()) > w.width() - 40:
                found.append(f"{name} '{w.title()}' title too long")
        elif isinstance(w, QTabBar) and w.count():
            if w.usesScrollButtons() and any(b.isVisible() for b in w.findChildren(QAbstractButton) if b.width() < 30 and not b.text()):
                found.append(f"{name} tabs overflow: {[w.tabText(i) for i in range(w.count())]}")
    return found


def walk_tabs(widget: QWidget, app: QApplication, visit) -> None:
    """Visit `widget` with every combination of tab pages shown (one tab widget at a time)."""
    visit(widget)
    for tabs in widget.findChildren(QTabWidget):
        if not tabs.isVisibleTo(widget):
            continue
        original = tabs.currentIndex()
        for i in range(tabs.count()):
            if not tabs.isTabEnabled(i):
                continue
            tabs.setCurrentIndex(i)
            for _ in range(4):
                app.processEvents()
            walk_tabs(tabs.widget(i), app, visit)
        tabs.setCurrentIndex(original)


def audit_dialogs(app: QApplication, ctx, win, cfg) -> dict[str, list[str]]:
    """Open the dialogs that can be built without special data and check each one (and every wizard page)."""
    from anihub.ui.bugreport_dialog import BugReportDialog
    from anihub.ui.close_dialog import CloseDialog
    from anihub.ui.downloads_view import DownloadsDialog
    from anihub.ui.extensions_dialog import ExtensionsDialog, ReposDialog
    from anihub.ui.library_dialogs import DuplicatesDialog, TagManagerDialog
    from anihub.ui.music_radio import StationDialog
    from anihub.ui.rules_dialog import RulesDialog
    from anihub.ui.stats_dialog import StatsDialog
    from anihub.ui.wizard import SetupWizard

    factories = {
        "close": lambda: CloseDialog(), "bugreport": lambda: BugReportDialog(cfg), "station": lambda: StationDialog(),
        "repos": lambda: ReposDialog(ctx.extensions), "rules": lambda: RulesDialog(ctx), "stats": lambda: StatsDialog(ctx),
        "tags": lambda: TagManagerDialog(ctx), "duplicates": lambda: DuplicatesDialog(ctx),
        "downloads": lambda: DownloadsDialog(ctx, win.download_signals),
        "extensions": lambda: ExtensionsDialog(ctx, ctx.extensions, ("anime", "novel"), lambda: ctx.anime_sources),
    }
    found: dict[str, list[str]] = {}
    for name, make in factories.items():
        try:
            dlg = make()
        except Exception as exc:                                         # noqa: BLE001 - a dialog that needs data: report, go on
            print(f"  (skipped {name}: {exc})")
            continue
        dlg.show()
        for _ in range(8):
            app.processEvents()
            time.sleep(0.02)
        items: list[str] = []
        walk_tabs(dlg, app, lambda w: items.extend(clipped(w)))
        if items:
            found[f"dialog:{name}"] = list(dict.fromkeys(items))
        dlg.close()
    wizard = SetupWizard(cfg)
    wizard.show()
    for step in range(8):
        for _ in range(8):
            app.processEvents()
            time.sleep(0.02)
        items = clipped(wizard.currentPage())
        if items:
            found[f"wizard:{step}"] = list(dict.fromkeys(items))
        if not wizard.button(wizard.WizardButton.NextButton).isVisible():
            break
        wizard.next()
    wizard.close()
    return found


def main() -> int:
    lang = sys.argv[1] if len(sys.argv) > 1 else "ru"
    mode = sys.argv[2] if len(sys.argv) > 2 else "dark"
    size = (int(sys.argv[3]), int(sys.argv[4])) if len(sys.argv) > 4 else (1300, 800)
    from anihub.context import AppContext
    from anihub.core.config import Config
    from anihub.core.i18n import set_language
    from anihub.ui import theme
    from anihub.ui.main_window import MainWindow

    app = QApplication([])
    tmp = Path(tempfile.mkdtemp())
    cfg = Config.load(tmp / "config.json")
    cfg.set("library_path", str(tmp / "lib"), save=False)
    cfg.set("first_run_done", True, save=False)
    cfg.set("theme", mode, save=False)
    cfg.set("language", lang, save=False)
    set_language(lang)
    theme.apply_theme(app, mode, glass=False)
    ctx = AppContext.build(cfg)
    win = MainWindow(ctx)
    win.resize(*size)
    win.show()
    problems: dict[str, list[str]] = {}
    for name, row in win.rows.items():
        win.nav.setCurrentRow(row)
        for _ in range(6):
            app.processEvents()
            time.sleep(0.02)
        found: list[str] = []
        walk_tabs(win.pages.currentWidget(), app, lambda w: found.extend(clipped(w)))
        if found:
            problems[name] = list(dict.fromkeys(found))
    bar = clipped(win.statusBar())
    if bar:
        problems["statusbar"] = bar
    problems.update(audit_dialogs(app, ctx, win, cfg))
    for section, items in problems.items():
        print(f"[{section}]")
        for item in items:
            print("  ", item)
    print(f"{lang}/{mode}/{size[0]}x{size[1]}: {sum(len(v) for v in problems.values())} problem(s)")
    ctx.db.close()
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
