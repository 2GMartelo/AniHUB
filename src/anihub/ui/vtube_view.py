"""VTube tab (Stage 3, ТЗ_rasshirenie_prilozheniya.md): turn one picture into a layered PSD via ComfyUI +
ComfyUI-See-through, ready to hand off to a Live2D rigger (Stretchy Studio / Cubism) or to touch up in Krita /
Photoshop first.

Runs ComfyUI as its own local service, the same lifecycle Forge already has (ui/forge_controller.ServiceController
wraps services/comfyui.ComfyManager exactly like it wraps ForgeManager). This is not automated end to end: the user
picks a picture, adjusts a few settings and clicks once; the actual decomposition can take anywhere from a few
minutes (a strong GPU, group_offload off) to tens of minutes (group_offload on, needed on a 10-12 GB card -- see
services/seethrough.py's own docstring for the real numbers measured on this project's own hardware)."""
from __future__ import annotations

import os
import time
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QDragEnterEvent, QDropEvent, QImage, QPainter, QPixmap
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QListWidget, QPushButton, QSpinBox,
    QSplitter, QVBoxLayout, QWidget,
)

from anihub.context import AppContext
from anihub.core.i18n import tr
from anihub.services import seethrough as st
from anihub.services.procservice import ServiceState
from anihub.ui import style
from anihub.ui.forge_controller import ServiceController
from anihub.ui.grid import decode_image
from anihub.ui.workers import run_async

RESOLUTIONS = (1024, 1280, 1536, 2048)
IMAGE_FILTER = "Images (*.png *.jpg *.jpeg *.webp)"


class VTubeView(QWidget):
    def __init__(self, ctx: AppContext, comfy: ServiceController, forge_controllers: dict[str, ServiceController],
                parent=None):
        super().__init__(parent)
        self.ctx, self.comfy, self.forge_controllers = ctx, comfy, forge_controllers
        self.setAcceptDrops(True)
        self.path: Path | None = None
        self.result: st.SeeThroughResult | None = None
        self._saved_to: Path | None = None
        self._running = False
        self._interrupting = False
        self._t0 = 0.0

        # --- top bar: the ComfyUI service, same shape as Forge's own in sd_page.py ---------------------------
        self.chip = style.StatusChip()
        self.start_btn = style.primary(QPushButton(tr("vtube.start")), "play")
        self.stop_btn = style.secondary(QPushButton(tr("vtube.stop")), "stop")
        self.log_btn = style.ghost(QPushButton(tr("vtube.log")), "list")
        bar = QHBoxLayout()
        for w in (self.chip, self.start_btn, self.stop_btn, self.log_btn):
            bar.addWidget(w)
        bar.addStretch(1)

        # --- left: source picture + settings -----------------------------------------------------------------
        self.preview = QLabel(tr("vtube.drop_hint"))
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setWordWrap(True)
        self.preview.setMinimumSize(240, 240)
        self.open_btn = style.secondary(QPushButton(tr("vtube.open_picture")), "image")

        self.resolution = QComboBox()
        for r in RESOLUTIONS:
            self.resolution.addItem(str(r), r)
        self.resolution.setCurrentIndex(RESOLUTIONS.index(1280))
        self.steps = QSpinBox(minimum=1, maximum=100, value=30)
        self.tblr_split = QCheckBox(tr("vtube.tblr_split"))
        self.tblr_split.setChecked(True)
        self.use_lama = QCheckBox(tr("vtube.use_lama"))
        self.use_lama.setChecked(True)
        self.group_offload = QCheckBox(tr("vtube.group_offload"))

        form = QFormLayout()
        form.addRow(tr("vtube.resolution"), self.resolution)
        form.addRow(tr("vtube.steps"), self.steps)
        form.addRow("", self.tblr_split)
        form.addRow("", self.use_lama)
        form.addRow("", self.group_offload)

        self.generate_btn = style.primary(QPushButton(tr("vtube.generate")), "layers")
        self.cancel_btn = style.secondary(QPushButton(tr("vtube.cancel")))
        self.cancel_btn.hide()
        gen_row = QHBoxLayout()
        gen_row.addWidget(self.generate_btn)
        gen_row.addWidget(self.cancel_btn)
        gen_row.addStretch(1)
        self.status = QLabel()
        self.status.setWordWrap(True)

        left = QVBoxLayout()
        left.addWidget(self.preview, 1)
        left.addWidget(self.open_btn)
        left.addLayout(form)
        left.addLayout(gen_row)
        left.addWidget(self.status)
        left_box = QWidget()
        left_box.setLayout(left)

        # --- right: results ------------------------------------------------------------------------------------
        self.result_preview = QLabel()
        self.result_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.result_preview.setMinimumSize(240, 240)
        self.layer_list = QListWidget()
        self.save_btn = style.secondary(QPushButton(tr("vtube.save_as")))
        self.save_btn.setEnabled(False)
        self.reveal_btn = style.ghost(QPushButton(tr("vtube.reveal")))
        self.reveal_btn.setEnabled(False)
        save_row = QHBoxLayout()
        save_row.addWidget(self.save_btn)
        save_row.addWidget(self.reveal_btn)
        save_row.addStretch(1)

        right = QVBoxLayout()
        right.addWidget(self.result_preview, 1)
        right.addWidget(QLabel(tr("vtube.layers")))
        right.addWidget(self.layer_list, 1)
        right.addLayout(save_row)
        right_box = QWidget()
        right_box.setLayout(right)

        split = QSplitter(Qt.Orientation.Horizontal)
        split.addWidget(left_box)
        split.addWidget(right_box)
        split.setSizes([420, 420])

        layout = QVBoxLayout(self)
        layout.addLayout(bar)
        layout.addWidget(split, 1)

        self.start_btn.clicked.connect(self.comfy.start)
        self.stop_btn.clicked.connect(self.comfy.stop)
        self.log_btn.clicked.connect(self._show_log)
        self.comfy.state_changed.connect(self._on_state)
        self.open_btn.clicked.connect(self._choose)
        self.generate_btn.clicked.connect(self._generate)
        self.cancel_btn.clicked.connect(self._cancel)
        self.save_btn.clicked.connect(self._save_as)
        self.reveal_btn.clicked.connect(self._reveal)
        self._elapsed_timer = QTimer(self)
        self._elapsed_timer.timeout.connect(self._tick)
        self._on_state(self.comfy.state.value)
        self.comfy.poll()  # attach to an already running ComfyUI, if any

    # --- service status --------------------------------------------------------------------------------------

    def _on_state(self, state: str) -> None:
        s = ServiceState(state)
        self.chip.set_state(state, "ComfyUI · " + tr(f"forge.state.{state}"))
        self.start_btn.setEnabled(s in (ServiceState.STOPPED, ServiceState.FAILED))
        self.stop_btn.setEnabled(s in (ServiceState.STARTING, ServiceState.RUNNING))
        self._update_buttons()

    def _show_log(self) -> None:
        from anihub.ui.sd_page import ForgeLogDialog

        ForgeLogDialog(self.comfy, self, title="ComfyUI").show()

    def _update_buttons(self) -> None:
        if not self._running:
            self.generate_btn.setEnabled(self.comfy.state.ready and self.path is not None)

    # --- picking a picture -------------------------------------------------------------------------------------

    def _choose(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, tr("vtube.open_picture"), "", IMAGE_FILTER)
        if path:
            self.load_path(Path(path))

    def load_path(self, path: Path) -> None:
        self.path = path
        image = decode_image(path)
        if not image.isNull():
            pm = QPixmap.fromImage(image.scaled(self.preview.size(), Qt.AspectRatioMode.KeepAspectRatio,
                                                Qt.TransformationMode.SmoothTransformation))
            self.preview.setPixmap(pm)
        else:
            self.preview.setPixmap(QPixmap())
            self.preview.setText(path.name)
        self.status.clear()
        self._update_buttons()

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls() and any(u.isLocalFile() for u in event.mimeData().urls()):
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        for url in event.mimeData().urls():
            if url.isLocalFile():
                self.load_path(Path(url.toLocalFile()))
                break

    # --- running -------------------------------------------------------------------------------------------------

    def settings(self) -> st.SeeThroughSettings:
        return st.SeeThroughSettings(resolution=self.resolution.currentData(), steps=self.steps.value(),
                                     tblr_split=self.tblr_split.isChecked(), use_lama=self.use_lama.isChecked(),
                                     group_offload=self.group_offload.isChecked())

    def _default_psd_path(self) -> Path:
        folder = self.ctx.paths.vtube_out
        folder.mkdir(parents=True, exist_ok=True)
        stem = self.path.stem if self.path is not None else "result"
        return folder / f"{stem}.psd"

    def _free_forge(self) -> None:
        """Called from the worker thread, before the ComfyUI job is submitted: synchronously (this is *not* the GUI
        thread) unloads every ready Forge backend's checkpoint, so its VRAM is actually free before See-through's
        own model starts loading -- not just "the GpuScheduler slot is ours", the real memory too."""
        for ctrl in self.forge_controllers.values():
            if ctrl.state.ready:
                try:
                    ctrl.manager.api.unload_checkpoint()
                except Exception:  # noqa: BLE001 - best-effort; a generation still starts even if this fails
                    pass

    def _generate(self) -> None:
        if self.path is None:
            self.status.setText(tr("vtube.no_picture"))
            return
        api = self.comfy.manager.api
        if not st.is_installed(api):
            self.status.setText(tr("vtube.not_installed"))
            return
        save_path, _ = QFileDialog.getSaveFileName(self, tr("vtube.save_as"), str(self._default_psd_path()),
                                                    "PSD (*.psd)")
        if not save_path:
            return
        psd_path = Path(save_path)
        settings = self.settings()
        image_path = self.path
        output_dir = self.comfy.manager.comfy_dir / "output"
        scheduler = self.ctx.gpu_scheduler

        self._running = True
        self._interrupting = False
        self._t0 = time.time()
        self.status.setText(tr("vtube.running"))
        self.generate_btn.hide()
        self.cancel_btn.show()
        self._elapsed_timer.start(1000)
        self._update_buttons()

        def work() -> st.SeeThroughResult:
            return st.run(api, output_dir, image_path, psd_path, settings=settings,
                          should_stop=lambda: self._interrupting, scheduler=scheduler, gpu=0,
                          free_others=self._free_forge)

        def done(result: st.SeeThroughResult) -> None:
            self._finish()
            self.result = result
            self._saved_to = psd_path
            self.status.setText(tr("vtube.done", n=len(result.tags)))
            self.layer_list.clear()
            self.layer_list.addItems(result.tags)
            self._show_composite(result)
            self.save_btn.setEnabled(True)
            self.reveal_btn.setEnabled(True)

        def failed(exc: Exception) -> None:
            self._finish()
            self.status.setText(tr("vtube.cancelled") if self._interrupting else tr("status.error", msg=str(exc)))

        run_async(work, on_done=done, on_error=failed)

    def _cancel(self) -> None:
        self._interrupting = True
        self.cancel_btn.setEnabled(False)

    def _finish(self) -> None:
        self._running = False
        self._elapsed_timer.stop()
        self.generate_btn.show()
        self.cancel_btn.setEnabled(True)
        self.cancel_btn.hide()
        self._update_buttons()

    def _tick(self) -> None:
        elapsed = int(time.time() - self._t0)
        self.status.setText(f"{tr('vtube.running')} — {tr('vtube.elapsed', m=elapsed // 60, s=elapsed % 60)}")

    # --- results ---------------------------------------------------------------------------------------------------

    def _show_composite(self, result: st.SeeThroughResult) -> None:
        canvas = QImage(result.width, result.height, QImage.Format.Format_ARGB32_Premultiplied)
        canvas.fill(QColor(232, 232, 232))
        painter = QPainter(canvas)
        for layer in reversed(result.layers):  # PsdLayer: index 0 = topmost -> paint back to front
            h, w = layer.image.shape[:2]
            picture = QImage(layer.image.data, w, h, w * 4, QImage.Format.Format_RGBA8888)
            painter.drawImage(layer.x, layer.y, picture)
        painter.end()
        pm = QPixmap.fromImage(canvas.scaled(self.result_preview.size(), Qt.AspectRatioMode.KeepAspectRatio,
                                             Qt.TransformationMode.SmoothTransformation))
        self.result_preview.setPixmap(pm)

    def _save_as(self) -> None:
        if self.result is None:
            return
        default = str(self._saved_to) if self._saved_to else str(self._default_psd_path())
        path, _ = QFileDialog.getSaveFileName(self, tr("vtube.save_as"), default, "PSD (*.psd)")
        if not path:
            return
        from anihub.services.psd_writer import write_psd

        write_psd(Path(path), self.result.layers, self.result.width, self.result.height)
        self._saved_to = Path(path)
        self.status.setText(tr("vtube.saved", name=self._saved_to.name))

    def _reveal(self) -> None:
        if self._saved_to is not None and self._saved_to.exists():
            os.startfile(str(self._saved_to.parent))  # noqa: S606 - Windows-only app, same idiom as settings.py
