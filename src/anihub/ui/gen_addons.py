"""The "Addons" section of the Generate form: one place for every optional generation extra (ADetailer, OpenPose,
Forge Couple, wildcards, and whatever comes next) instead of scattering a checkbox for each wherever it happens to
fit. Each addon shows either its controls or an install button, depending on what services/addons.py's detection
found the last time `refresh()` ran -- which only happens once Forge is confirmed up, since that is the only time
the detection can actually mean anything."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFrame, QGroupBox, QHBoxLayout, QLabel, QPushButton, QVBoxLayout,
)

from anihub.context import AppContext
from anihub.core.i18n import tr
from anihub.services import addons
from anihub.services.forge import ForgeApi
from anihub.services.generation import GenParams
from anihub.ui import style
from anihub.ui.prompt_builder import IMAGE_FILTER, placeholder_pixmap
from anihub.ui.workers import run_async

THUMB = 64


class GenAddonsPanel(QGroupBox):
    def __init__(self, ctx: AppContext, parent=None):
        super().__init__(tr("sd.addons"), parent)
        self.ctx = ctx
        self._openpose_path: Path | None = None
        self._openpose_module = ""
        self._openpose_model = ""

        # --- ADetailer -------------------------------------------------------------------------------------------
        self.adetailer_check = QCheckBox(tr("sd.adetailer"))
        self.adetailer_install_btn = style.ghost(QPushButton(tr("sd.adetailer_install")), "download")
        self.adetailer_check.hide()
        self.adetailer_install_btn.hide()

        # --- OpenPose (ControlNet, built into Forge) --------------------------------------------------------------
        self.openpose_check = QCheckBox(tr("sd.openpose"))
        self.openpose_check.setEnabled(False)
        self.openpose_thumb = QLabel()
        self.openpose_thumb.setObjectName("thumbHolder")
        self.openpose_thumb.setFixedSize(THUMB, THUMB)
        self.openpose_choose_btn = style.ghost(QPushButton(tr("sd.openpose_choose")), "image")
        self.openpose_clear_btn = style.ghost(QPushButton(tr("sd.openpose_clear")), "x")
        self.openpose_clear_btn.setEnabled(False)
        self.openpose_weight = QDoubleSpinBox(minimum=0.0, maximum=2.0, singleStep=0.05, decimals=2, value=1.0)
        self.openpose_no_model_hint = style.role(QLabel(tr("sd.openpose_no_model")), "dim")
        self.openpose_no_model_hint.setWordWrap(True)
        self.openpose_no_model_hint.hide()
        pose_row = QHBoxLayout()
        pose_row.addWidget(self.openpose_thumb)
        pose_buttons = QVBoxLayout()
        pose_buttons.addWidget(self.openpose_choose_btn)
        pose_buttons.addWidget(self.openpose_clear_btn)
        pose_row.addLayout(pose_buttons)
        pose_row.addWidget(QLabel(tr("sd.openpose_weight")))
        pose_row.addWidget(self.openpose_weight)
        pose_row.addStretch(1)

        # --- Forge Couple ------------------------------------------------------------------------------------------
        self.couple_check = QCheckBox(tr("sd.couple"))
        self.couple_install_btn = style.ghost(QPushButton(tr("sd.couple_install")), "download")
        self.couple_check.hide()
        self.couple_install_btn.hide()
        self.couple_direction = QComboBox()
        self.couple_direction.addItem(tr("sd.couple_horizontal"), "Horizontal")
        self.couple_direction.addItem(tr("sd.couple_vertical"), "Vertical")
        self.couple_hint = style.role(QLabel(tr("sd.couple_hint")), "dim")
        self.couple_hint.setWordWrap(True)
        couple_row = QHBoxLayout()
        couple_row.addWidget(self.couple_check)
        couple_row.addWidget(self.couple_install_btn)
        couple_row.addWidget(self.couple_direction)
        couple_row.addStretch(1)

        # --- Wildcards (no Forge extension: resolved by AniHUB itself) ---------------------------------------------
        self.wildcards_btn = style.ghost(QPushButton(tr("wildcards.manage")), "list")
        wc_row = QHBoxLayout()
        wc_row.addWidget(self.wildcards_btn)
        wc_row.addWidget(style.role(QLabel(tr("wildcards.syntax_hint")), "dim"), 1)

        adetailer_row = QHBoxLayout()
        adetailer_row.addWidget(self.adetailer_check)
        adetailer_row.addWidget(self.adetailer_install_btn)
        adetailer_row.addStretch(1)

        layout = QVBoxLayout(self)
        layout.addLayout(adetailer_row)
        layout.addWidget(_separator())
        layout.addWidget(self.openpose_check)
        layout.addLayout(pose_row)
        layout.addWidget(self.openpose_no_model_hint)
        layout.addWidget(_separator())
        layout.addLayout(couple_row)
        layout.addWidget(self.couple_hint)
        layout.addWidget(_separator())
        layout.addLayout(wc_row)

        self.openpose_choose_btn.clicked.connect(self._choose_openpose)
        self.openpose_clear_btn.clicked.connect(self._clear_openpose)
        self.adetailer_install_btn.clicked.connect(lambda: self._install("adetailer", self.adetailer_check, self.adetailer_install_btn))
        self.couple_install_btn.clicked.connect(lambda: self._install("forge_couple", self.couple_check, self.couple_install_btn))
        self.wildcards_btn.clicked.connect(self._open_wildcards)

    # --- detection ---------------------------------------------------------------------------------------------------

    def refresh(self, api: ForgeApi) -> None:
        """Call once Forge is confirmed ready. Everything here is a network round-trip, so it runs off the GUI thread."""
        def fetch():
            return (addons.is_installed(api, "adetailer"), addons.is_installed(api, "forge_couple"),
                    api.controlnet_model_for("OpenPose"))

        def done(result: tuple) -> None:
            adetailer_ok, couple_ok, (module, model) = result
            self.adetailer_check.setVisible(adetailer_ok)
            self.adetailer_install_btn.setVisible(not adetailer_ok)
            self.couple_check.setVisible(couple_ok)
            self.couple_direction.setVisible(couple_ok)
            self.couple_hint.setVisible(couple_ok)
            self.couple_install_btn.setVisible(not couple_ok)
            self._openpose_module, self._openpose_model = module, model
            has_model = bool(model)
            self.openpose_check.setEnabled(has_model)
            self.openpose_no_model_hint.setVisible(not has_model)

        run_async(fetch, on_done=done, on_error=lambda _e: None)

    def _install(self, key: str, checkbox, install_btn) -> None:
        forge_dir = self.ctx.cfg.get("forge.path") or ""
        if not forge_dir:
            return
        from anihub.ui.addon_install_dialog import AddonInstallDialog

        dlg = AddonInstallDialog(self.ctx, Path(forge_dir), key, self)
        dlg.exec()
        if dlg.installed is not None:
            checkbox.show()
            install_btn.hide()

    # --- OpenPose reference image -------------------------------------------------------------------------------------

    def _choose_openpose(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, tr("sd.openpose_choose"), "", IMAGE_FILTER)
        if path:
            self._set_openpose_image(Path(path))

    def _set_openpose_image(self, path: Path) -> None:
        self._openpose_path = path
        pm = QPixmap(str(path))
        self.openpose_thumb.setPixmap((pm if not pm.isNull() else placeholder_pixmap(path.name, THUMB)).scaled(
            THUMB, THUMB, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation))
        self.openpose_clear_btn.setEnabled(True)
        self.openpose_check.setChecked(True)

    def _clear_openpose(self) -> None:
        self._openpose_path = None
        self.openpose_thumb.setPixmap(QPixmap())
        self.openpose_clear_btn.setEnabled(False)
        self.openpose_check.setChecked(False)

    def _open_wildcards(self) -> None:
        from anihub.ui.wildcards_dialog import WildcardsDialog

        WildcardsDialog(self.ctx, self).exec()

    # --- GenParams round-trip ---------------------------------------------------------------------------------------

    def params_kwargs(self) -> dict:
        pose_on = self.openpose_check.isChecked() and self._openpose_path is not None
        couple_on = self.couple_check.isChecked() and not self.couple_check.isHidden()
        return dict(
            adetailer=self.adetailer_check.isChecked() and not self.adetailer_check.isHidden(),
            openpose_image=str(self._openpose_path) if pose_on else "",
            openpose_module=self._openpose_module, openpose_model=self._openpose_model,
            openpose_weight=self.openpose_weight.value(),
            couple_enabled=couple_on, couple_direction=self.couple_direction.currentData() or "Horizontal")

    def apply(self, p: GenParams) -> None:
        self.adetailer_check.setChecked(p.adetailer)
        if p.openpose_image:
            self._set_openpose_image(Path(p.openpose_image))
        else:
            self._clear_openpose()
        self.openpose_weight.setValue(p.openpose_weight or 1.0)
        self.couple_check.setChecked(p.couple_enabled)
        self.couple_direction.setCurrentIndex(max(self.couple_direction.findData(p.couple_direction), 0))


def _separator() -> QFrame:
    line = QFrame()
    line.setFrameShape(QFrame.Shape.HLine)
    line.setFrameShadow(QFrame.Shadow.Sunken)
    return line
