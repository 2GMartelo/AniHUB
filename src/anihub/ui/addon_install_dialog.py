"""Downloads a generation addon (see services/addons.py) straight into Forge's own extensions/ folder, with a
progress bar; Forge itself still needs a restart afterwards to actually load it -- installing an extension while
it is running is not something Forge supports, same as doing it by hand."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QDialog, QLabel, QProgressBar, QPushButton, QVBoxLayout

from anihub.context import AppContext
from anihub.core.i18n import tr
from anihub.services import addons
from anihub.ui import style
from anihub.ui.workers import run_async


class AddonInstallDialog(QDialog):
    _progress = Signal(int, int)                       # from the worker thread

    def __init__(self, ctx: AppContext, forge_dir: Path, key: str, parent=None):
        super().__init__(parent)
        self.ctx, self.forge_dir, self.key = ctx, Path(forge_dir), key
        self.installed: Path | None = None
        self._cancel = False
        self._paused = False
        self.setWindowTitle(tr("addon.install.title", name=addons.ADDONS[key].script_name))
        self.setModal(True)
        self.setMinimumWidth(480)
        self.info = QLabel(tr("addon.install.text", dest=str(Path(forge_dir) / "extensions" / key)))
        self.info.setWordWrap(True)
        self.state = style.role(QLabel(tr("status.loading")), "dim")
        self.state.setWordWrap(True)
        self.bar = QProgressBar()
        self.bar.setRange(0, 0)
        self.pause_btn = style.secondary(QPushButton(tr("forge.install.pause")), "pause")
        self.cancel_btn = style.secondary(QPushButton(tr("close.cancel")), "x")
        self.close_btn = style.primary(QPushButton(tr("forge.install.close")), "check")
        self.close_btn.hide()
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        for w in (self.info, self.bar, self.state):
            layout.addWidget(w)
        layout.addWidget(self.pause_btn, 0, Qt.AlignmentFlag.AlignRight)
        layout.addWidget(self.cancel_btn, 0, Qt.AlignmentFlag.AlignRight)
        layout.addWidget(self.close_btn, 0, Qt.AlignmentFlag.AlignRight)
        self._progress.connect(self._on_progress)
        self.pause_btn.clicked.connect(self._toggle_pause)
        self.cancel_btn.clicked.connect(self._on_cancel)
        self.close_btn.clicked.connect(self.accept)
        run_async(self._work, on_done=self._done, on_error=self._failed)

    def _work(self) -> Path | None:
        return addons.install(self.ctx.http, self.forge_dir, self.key, lambda d, t: self._progress.emit(d, t),
                              lambda: self._cancel, lambda: self._paused)

    def _on_progress(self, done: int, total: int) -> None:
        if total:
            self.bar.setRange(0, 1000)
            self.bar.setValue(int(done / total * 1000))
            self.state.setText(tr("forge.install.download", done=f"{done / 1024**2:.0f}", total=f"{total / 1024**2:.0f}"))

    def _toggle_pause(self) -> None:
        self._paused = not self._paused
        self.pause_btn.setText(tr("forge.install.resume") if self._paused else tr("forge.install.pause"))

    def _done(self, path: Path | None) -> None:
        if path is None:  # paused mid-download: reopening this dialog resumes it
            self.bar.setRange(0, 1)
            self.bar.setValue(0)
            self.state.setText(tr("forge.install.paused"))
            self.pause_btn.hide()
            self.cancel_btn.hide()
            self.close_btn.show()
            return
        self.installed = path
        self.bar.setRange(0, 1)
        self.bar.setValue(1)
        self.state.setText(tr("addon.install.done"))
        self.pause_btn.hide()
        self.cancel_btn.hide()
        self.close_btn.show()

    def _failed(self, exc: Exception) -> None:
        self.bar.setRange(0, 1)
        self.bar.setValue(0)
        self.state.setText(tr("forge.install.failed", msg=str(exc)))
        self.pause_btn.hide()
        self.cancel_btn.hide()
        self.close_btn.show()

    def _on_cancel(self) -> None:
        self._cancel = True
        self.ctx.http.abort_downloads()
        self.cancel_btn.setEnabled(False)

    def reject(self) -> None:
        if self.close_btn.isVisible():
            super().reject()
        else:
            self._on_cancel()
