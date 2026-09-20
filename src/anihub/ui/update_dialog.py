"""Update dialogs: one release with its changelog, and the list of all versions (also the way back to an older one)."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QProgressBar, QPushButton, QSplitter, QTextBrowser,
    QVBoxLayout, QWidget,
)

from anihub import __version__
from anihub.core.config import config_dir
from anihub.core.i18n import tr
from anihub.services.updater import Release, Updater, UpdateError, is_newer
from anihub.ui import style
from anihub.ui.workers import run_async


def downloads_dir() -> Path:
    return config_dir() / "updates"


class ReleasePanel(QWidget):
    """Changelog + install button for one release. `quit_app` is called right after the installer has been started."""

    progress_signal = Signal(int, int)             # emitted from the download thread

    def __init__(self, updater: Updater, quit_app, parent=None):
        super().__init__(parent)
        self.updater, self.quit_app = updater, quit_app
        self.release: Release | None = None
        self._cancel = False
        self._busy = False
        self.title = QLabel()
        self.title.setStyleSheet("font-size: 16px; font-weight: 600;")
        self.title.setWordWrap(True)
        self.meta = QLabel()
        style.role(self.meta, "dim")
        self.notes = QTextBrowser()
        self.notes.setOpenExternalLinks(True)
        self.progress = QProgressBar()
        self.progress.hide()
        self.message = QLabel()
        self.message.setWordWrap(True)
        style.role(self.message, "dim")
        self.install_btn = style.primary(QPushButton(tr("update.install")), "download")
        self.cancel_btn = style.secondary(QPushButton(tr("action.close")), "x")
        self.cancel_btn.hide()
        self.page_btn = style.ghost(QPushButton(tr("update.page")), "external")
        row = QHBoxLayout()
        for w in (self.install_btn, self.cancel_btn, self.page_btn):
            row.addWidget(w)
        row.addStretch(1)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        for w in (self.title, self.meta):
            layout.addWidget(w)
        layout.addWidget(self.notes, 1)
        layout.addWidget(self.progress)
        layout.addWidget(self.message)
        layout.addLayout(row)
        self.install_btn.clicked.connect(self._install)
        self.cancel_btn.clicked.connect(self._cancel_download)
        self.page_btn.clicked.connect(self._open_page)
        self.progress_signal.connect(self._progress)

    def show_release(self, release: Release | None) -> None:
        self.release = release
        self.message.clear()
        self.progress.hide()
        if release is None:
            self.title.setText("")
            self.meta.setText("")
            self.notes.clear()
            self.install_btn.setEnabled(False)
            self.page_btn.setEnabled(False)
            return
        newer = is_newer(release.version, self.updater.current)
        same = release.version == self.updater.current
        self.title.setText(f"AniHUB {release.version}" + (f"  ·  {tr('update.current')}" if same else ""))
        self.meta.setText("  ·  ".join(x for x in (release.published, tr("update.prerelease") if release.prerelease else "",
                                                     f"{release.asset_size / 1048576:.0f} MB" if release.asset_size else "") if x))
        self.notes.setMarkdown(release.notes or tr("update.no_notes"))
        self.install_btn.setText(tr("update.install") if newer else tr("update.reinstall") if same else tr("update.rollback"))
        self.install_btn.setEnabled(release.installable and not self._busy)
        self.page_btn.setEnabled(bool(release.page))
        if not release.installable:
            self.message.setText(tr("update.no_installer"))

    def _open_page(self) -> None:
        if self.release and self.release.page:
            from PySide6.QtCore import QUrl
            from PySide6.QtGui import QDesktopServices

            QDesktopServices.openUrl(QUrl(self.release.page))

    def _progress(self, done: int, total: int) -> None:
        self.progress.setRange(0, total or 0)
        self.progress.setValue(done)

    def _cancel_download(self) -> None:
        self._cancel = True

    def _install(self) -> None:
        release = self.release
        if release is None or self._busy:
            return
        self._busy, self._cancel = True, False
        self.install_btn.setEnabled(False)
        self.cancel_btn.setText(tr("wizard.cancel"))
        self.cancel_btn.show()
        self.progress.show()
        self.progress.setRange(0, 0)
        self.message.setText(tr("update.downloading"))

        def work() -> Path:
            return self.updater.download(release, downloads_dir(), progress=lambda d, t: self.progress_signal.emit(d, t),
                                         cancelled=lambda: self._cancel)

        def done(path: Path) -> None:
            self._busy = False
            self.cancel_btn.hide()
            self.message.setText(tr("update.starting"))
            try:
                self.updater.launch(path)
            except OSError as exc:
                self.message.setText(tr("status.error", msg=str(exc)))
                self.install_btn.setEnabled(True)
                return
            self.quit_app()

        def failed(exc: Exception) -> None:
            self._busy = False
            self.cancel_btn.hide()
            self.progress.hide()
            self.install_btn.setEnabled(True)
            cancelled = "cancelled" in str(exc)
            self.message.setText(tr("update.cancelled") if cancelled else tr("status.error", msg=str(exc)))

        run_async(work, on_done=done, on_error=failed)


class UpdateDialog(QDialog):
    """A new version is available."""

    def __init__(self, updater: Updater, release: Release, quit_app, parent=None):
        super().__init__(parent)
        self.updater, self.release = updater, release
        self.setWindowTitle(tr("update.title"))
        self.resize(640, 520)
        intro = QLabel(tr("update.available", new=release.version, old=updater.current))
        intro.setWordWrap(True)
        self.panel = ReleasePanel(updater, quit_app)
        self.panel.show_release(release)
        self.later_btn = style.secondary(QPushButton(tr("update.later")), "clock")
        self.skip_btn = style.ghost(QPushButton(tr("update.skip")), "x")
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(self.skip_btn)
        row.addWidget(self.later_btn)
        layout = QVBoxLayout(self)
        layout.addWidget(intro)
        layout.addWidget(self.panel, 1)
        layout.addLayout(row)
        self.later_btn.clicked.connect(self.reject)
        self.skip_btn.clicked.connect(self._skip)

    def _skip(self) -> None:
        self.updater.skip(self.release)
        self.reject()


class VersionsDialog(QDialog):
    """Every published release: read what changed, install any of them (newer, the same, or an older one to roll back)."""

    def __init__(self, updater: Updater, quit_app, parent=None):
        super().__init__(parent)
        self.updater = updater
        self.releases: list[Release] = []
        self.setWindowTitle(tr("update.versions"))
        self.resize(900, 560)
        self.list = QListWidget()
        self.list.setMinimumWidth(180)
        self.status = QLabel(tr("status.loading"))
        style.role(self.status, "dim")
        self.panel = ReleasePanel(updater, quit_app)
        self.panel.show_release(None)
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.addWidget(self.list, 1)
        ll.addWidget(self.status)
        split = QSplitter()
        split.addWidget(left)
        split.addWidget(self.panel)
        split.setStretchFactor(1, 1)
        layout = QVBoxLayout(self)
        layout.addWidget(split)
        self.list.currentRowChanged.connect(self._select)
        run_async(updater.releases, on_done=self._loaded, on_error=lambda exc: self.status.setText(tr("status.error", msg=str(exc))))

    def _loaded(self, releases: list[Release]) -> None:
        self.releases = releases
        self.status.setText(tr("update.versions_n", n=len(releases)))
        for r in releases:
            mark = " ●" if r.version == self.updater.current else ""
            item = QListWidgetItem(f"{r.version}{mark}" + (f"  ({tr('update.prerelease')})" if r.prerelease else ""))
            self.list.addItem(item)
        if releases:
            self.list.setCurrentRow(0)

    def _select(self, row: int) -> None:
        self.panel.show_release(self.releases[row] if 0 <= row < len(self.releases) else None)
