"""Import of a cookies / logins text file (services/cookies.py): from Settings, by dropping the file on the window, or as a command line argument."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QFileDialog, QMessageBox, QWidget

from anihub.context import AppContext
from anihub.core.i18n import tr
from anihub.services import cookies

SUFFIXES = (".txt", ".json")


def known_settings(ctx: AppContext) -> set[str]:
    """The `site.key` names a text line may set: the credentials the sources declare (danbooru.login, gelbooru.api_key...)."""
    return {f"{src.name}.{key}" for src in ctx.sources.values() for key, _label in src.credentials}


def import_path(ctx: AppContext, path: Path, parent: QWidget | None = None, quiet: bool = False) -> cookies.Report | None:
    """Reads the file, puts its cookies / settings into the config and tells the user what happened (unless `quiet`)."""
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        if not quiet:
            QMessageBox.warning(parent, tr("cookies.title"), tr("status.error", msg=str(exc)))
        return None
    report = cookies.import_text(ctx.cfg, text, known_settings(ctx))
    if not quiet:
        show_report(parent, report)
    return report


def show_report(parent: QWidget | None, report: cookies.Report) -> None:
    if report.empty:
        QMessageBox.information(parent, tr("cookies.title"), tr("cookies.nothing"))
        return
    lines = [tr("cookies.done", n=report.cookies, sites=len(report.domains))]
    if report.domains:
        lines.append(", ".join(report.domains[:12]) + (" …" if len(report.domains) > 12 else ""))
    if report.filled:
        lines.append(tr("cookies.filled", what=", ".join(report.filled)))
    if report.skipped:
        lines.append(tr("cookies.skipped", n=report.skipped))
    QMessageBox.information(parent, tr("cookies.title"), "\n".join(lines))


def pick_and_import(ctx: AppContext, parent: QWidget | None = None) -> None:
    path, _ = QFileDialog.getOpenFileName(parent, tr("cookies.pick"), "", "Cookies (*.txt *.json);;*")
    if path:
        import_path(ctx, Path(path), parent)


def is_cookie_file(path: str) -> bool:
    return path.lower().endswith(SUFFIXES)
