"""Downloads sd-scripts and builds its own venv (torch, xformers, its requirements) with a progress bar; the result becomes
`lora_train.sd_scripts_path`. Mirrors ForgeInstallDialog -- same shape, its own stages (this one has several slow ones, not
just a single download)."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QDialog, QLabel, QProgressBar, QPushButton, QVBoxLayout

from anihub.context import AppContext
from anihub.core.i18n import tr
from anihub.services import lora_train_install as ti
from anihub.ui import style
from anihub.ui.workers import run_async

TEXT_STAGES = ("preflight", "extract", "venv", "pip", "torch", "requirements", "accelerate")


class LoraTrainInstallDialog(QDialog):
    _progress = Signal(str, int, int)                 # from the worker thread

    def __init__(self, ctx: AppContext, dest: Path, parent=None):
        super().__init__(parent)
        self.ctx, self.dest = ctx, Path(dest)
        self.installed: Path | None = None
        self._cancel = False
        self.setWindowTitle(tr("train_install.title"))
        self.setModal(True)
        self.setMinimumWidth(520)
        self.info = QLabel(tr("train_install.text", dest=str(dest)))
        self.info.setWordWrap(True)
        self.state = style.role(QLabel(tr("status.loading")), "dim")
        self.state.setWordWrap(True)
        self.bar = QProgressBar()
        self.bar.setRange(0, 0)
        self.cancel_btn = style.secondary(QPushButton(tr("close.cancel")), "x")
        self.close_btn = style.primary(QPushButton(tr("forge.install.close")), "check")
        self.close_btn.hide()
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        for w in (self.info, self.bar, self.state):
            layout.addWidget(w)
        layout.addWidget(self.cancel_btn, 0, Qt.AlignmentFlag.AlignRight)
        layout.addWidget(self.close_btn, 0, Qt.AlignmentFlag.AlignRight)
        self._progress.connect(self._on_progress)
        self.cancel_btn.clicked.connect(self._on_cancel)
        self.close_btn.clicked.connect(self.accept)
        run_async(self._work, on_done=self._done, on_error=self._failed)

    def _work(self) -> Path:
        return ti.install(self.ctx.http, self.dest, lambda s, d, t: self._progress.emit(s, d, t), lambda: self._cancel)

    def _on_progress(self, stage: str, done: int, total: int) -> None:
        if stage == "download" and total:
            self.bar.setRange(0, 1000)
            self.bar.setValue(int(done / total * 1000))
            self.state.setText(tr("train_install.download", done=f"{done / 1024**2:.0f}", total=f"{total / 1024**2:.0f}"))
        else:
            self.bar.setRange(0, 0)
            self.state.setText(tr(f"train_install.{stage}") if stage in TEXT_STAGES else tr("status.loading"))

    def _done(self, path: Path) -> None:
        self.installed = path
        self.ctx.cfg.set("lora_train.sd_scripts_path", str(path))
        self.bar.setRange(0, 1)
        self.bar.setValue(1)
        self.state.setText(tr("train_install.done", path=str(path)))
        self.cancel_btn.hide()
        self.close_btn.show()

    def _failed(self, exc: Exception) -> None:
        self.bar.setRange(0, 1)
        self.bar.setValue(0)
        self.state.setText(tr("forge.install.failed", msg=str(exc)))
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
