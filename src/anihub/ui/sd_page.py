"""Stable Diffusion section: Forge control bar, generation form, results, queue, history, CivitAI, saved generations."""
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QInputDialog,
    QLabel, QMenu, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QScrollArea, QSpinBox, QSplitter,
    QTabWidget, QVBoxLayout, QWidget,
)

from anihub.context import AppContext
from anihub.core.i18n import tr
from anihub.services.forge import ForgeState
from anihub.services.generation import (
    GenParams, GenResult, fit_size, params_from_dict, parse_infotext, progress_text, prompt_tags, read_png_text,
    record_history, run_generation, run_upscale)
from anihub.sources.base import RATINGS
from anihub.ui import style
from anihub.ui.forge_controller import ForgeController
from anihub.ui.style import StatusChip
from anihub.ui.grid import ThumbGrid, image_to_thumb
from anihub.ui.library_view import LibraryView
from anihub.ui.sd_civitai import CivitaiView
from anihub.ui.sd_dialogs import InsertDialog
from anihub.ui.sd_history import HistoryView
from anihub.ui.sd_queue import QueueController, QueueView
from anihub.ui.viewer import ViewItem, Viewer
from anihub.ui.workers import run_async

STATE_COLORS = {"stopped": "#8a8f94", "starting": "#f0a030", "running": "#3fb95a", "external": "#3fb95a",
                "failed": "#e0575a"}


class ForgeLogDialog(QDialog):
    def __init__(self, controller: ForgeController, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.setWindowTitle(tr("sd.log"))
        self.resize(900, 500)
        self.text = QPlainTextEdit(readOnly=True)
        self.text.setMaximumBlockCount(2000)
        QVBoxLayout(self).addWidget(self.text)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(1000)
        self.refresh()

    def refresh(self) -> None:
        tail = self.controller.manager.log_tail()
        if tail != self.text.toPlainText():
            bar = self.text.verticalScrollBar()
            at_bottom = bar.value() >= bar.maximum() - 4
            self.text.setPlainText(tail)
            if at_bottom:
                bar.setValue(bar.maximum())


def _set_combo(combo: QComboBox, value: str) -> None:
    idx = combo.findText(value, Qt.MatchFlag.MatchFixedString)
    if idx < 0:
        combo.addItem(value)
        idx = combo.count() - 1
    combo.setCurrentIndex(idx)


class GenerateView(QWidget):
    library_changed = Signal()
    history_changed = Signal()
    presets_changed = Signal()

    def __init__(self, ctx: AppContext, controller: ForgeController, queue: QueueController, parent=None):
        super().__init__(parent)
        self.ctx, self.controller, self.queue = ctx, controller, queue
        self._generating = False
        self._interrupting = False
        self._polling = False
        self._data_loaded = False
        self._viewers: list[Viewer] = []
        self.init_path: Path | None = None
        last = ctx.cfg.get("sd.last", {}) or {}
        d = GenParams()

        def val(key):
            return last.get(key, getattr(d, key))

        # --- presets / styles / tools row
        self.preset_box = QComboBox()
        self.preset_box.setMinimumWidth(160)
        self.preset_save = style.ghost(QPushButton(), "save")
        self.preset_save.setToolTip(tr("sd.preset_save"))
        self.preset_delete = style.ghost(QPushButton(), "trash")
        self.preset_delete.setToolTip(tr("sd.preset_delete"))
        self.styles_btn = QPushButton(tr("sd.styles") + " ▾")
        self.styles_menu = QMenu(self)
        self.styles_btn.setMenu(self.styles_menu)
        self.styles_menu.aboutToShow.connect(self._build_styles_menu)
        self.png_btn = style.secondary(QPushButton(tr("sd.from_image_short")), "image")
        self.png_btn.setToolTip(tr("sd.from_image"))
        self.lora_btn = style.secondary(QPushButton("LoRA"), "layers")
        self.embed_btn = style.secondary(QPushButton("Embeddings"), "tag")

        # --- prompts
        self.prompt = QPlainTextEdit(val("prompt"), placeholderText=tr("sd.prompt"))
        self.negative = QPlainTextEdit(val("negative_prompt"), placeholderText=tr("sd.negative"))
        self.prompt.setMinimumHeight(110)
        self.negative.setMaximumHeight(80)

        # --- img2img source
        self.init_thumb = QLabel(alignment=Qt.AlignmentFlag.AlignCenter)
        self.init_thumb.setFixedSize(72, 72)
        self.init_thumb.setObjectName("thumbHolder")
        self.init_thumb.setText("txt2img")
        self.init_choose = QPushButton(tr("sd.init_choose"))
        self.init_clear = QPushButton(tr("sd.init_clear"))
        self.init_clear.setEnabled(False)
        self.denoise = QDoubleSpinBox(minimum=0.0, maximum=1.0, singleStep=0.05, decimals=2, value=float(val("denoising_strength")))
        self.denoise.setEnabled(False)

        # --- main parameters
        self.model = QComboBox()
        self.model.setMinimumWidth(100)
        self.refresh_btn = style.ghost(QPushButton(), "refresh")
        self.refresh_btn.setFixedWidth(34)
        self.vae = QComboBox()
        self.vae.addItem(tr("sd.auto"), "")
        self.clip_skip = QSpinBox(minimum=0, maximum=12, value=int(val("clip_skip")))
        self.clip_skip.setSpecialValueText(tr("sd.keep"))
        self.sampler = QComboBox()
        self.sampler.addItem(val("sampler_name"))
        self.scheduler = QComboBox()
        self.scheduler.addItem(val("scheduler"))
        self.steps = QSpinBox(minimum=1, maximum=150, value=int(val("steps")))
        self.cfg_scale = QDoubleSpinBox(minimum=1, maximum=30, singleStep=0.5, decimals=1, value=float(val("cfg_scale")))
        self.width_ = QSpinBox(minimum=64, maximum=4096, singleStep=64, value=int(val("width")))
        self.height_ = QSpinBox(minimum=64, maximum=4096, singleStep=64, value=int(val("height")))
        self.seed = QSpinBox(minimum=-1, maximum=2147483647, value=int(val("seed")))
        self.n_iter = QSpinBox(minimum=1, maximum=100, value=int(val("n_iter")))
        self.batch_size = QSpinBox(minimum=1, maximum=16, value=int(val("batch_size")))
        if val("model"):
            self.model.addItem(val("model"), val("model"))

        # --- hires fix + variations
        self.hr_box = QGroupBox(tr("sd.hires"))
        self.hr_box.setCheckable(True)
        self.hr_box.setChecked(bool(val("enable_hr")))
        self.hr_scale = QDoubleSpinBox(minimum=1.0, maximum=4.0, singleStep=0.1, decimals=2, value=float(val("hr_scale")))
        self.hr_upscaler = QComboBox()
        self.hr_upscaler.setEditable(True)
        self.hr_upscaler.addItem(val("hr_upscaler"))
        self.hr_steps = QSpinBox(minimum=0, maximum=150, value=int(val("hr_steps")))
        self.hr_steps.setSpecialValueText(tr("sd.same_steps"))
        self.hr_denoise = QDoubleSpinBox(minimum=0.0, maximum=1.0, singleStep=0.05, decimals=2, value=float(val("hr_denoise")))
        hr = QFormLayout(self.hr_box)
        hr.addRow(tr("sd.hr_scale"), self.hr_scale)
        hr.addRow(tr("sd.hr_upscaler"), self.hr_upscaler)
        hr.addRow(tr("sd.hr_steps"), self.hr_steps)
        hr.addRow(tr("sd.hr_denoise"), self.hr_denoise)
        self.var_box = QGroupBox(tr("sd.variation"))
        self.var_box.setCheckable(True)
        self.var_box.setChecked(float(val("subseed_strength")) > 0)
        self.subseed = QSpinBox(minimum=-1, maximum=2147483647, value=int(val("subseed")))
        self.subseed_strength = QDoubleSpinBox(minimum=0.0, maximum=1.0, singleStep=0.05, decimals=2,
                                               value=float(val("subseed_strength")) or 0.3)
        var = QFormLayout(self.var_box)
        var.addRow(tr("sd.subseed"), self.subseed)
        var.addRow(tr("sd.subseed_strength"), self.subseed_strength)

        # --- actions
        self.generate_btn = style.primary(QPushButton(tr("sd.generate")), "zap")
        self.generate_btn.setMinimumHeight(38)
        self.stop_btn = style.danger(QPushButton(tr("sd.interrupt")), "stop")
        self.stop_btn.setMinimumHeight(38)
        self.stop_btn.setEnabled(False)
        self.queue_btn = style.secondary(QPushButton(tr("sd.to_queue")), "list")
        self.queue_count = QSpinBox(minimum=1, maximum=500, value=1)
        self.queue_count.setPrefix("×")
        self.queue_count.setToolTip(tr("sd.queue_count_hint"))
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress_text = style.role(QLabel(), "dim")
        self.message = style.role(QLabel(), "dim")
        self.message.setWordWrap(True)

        # --- layout of the left column
        top = QHBoxLayout()
        for w, s in ((self.preset_box, 1), (self.preset_save, 0), (self.preset_delete, 0), (self.styles_btn, 0)):
            top.addWidget(w, s)
        tools = QHBoxLayout()
        for w in (self.png_btn, self.lora_btn, self.embed_btn):
            tools.addWidget(w)
        tools.addStretch(1)
        model_row = QHBoxLayout()
        model_row.addWidget(self.model, 1)
        model_row.addWidget(self.refresh_btn)
        size_row = QHBoxLayout()
        size_row.addWidget(self.width_)
        size_row.addWidget(QLabel("×"))
        size_row.addWidget(self.height_)
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(9)
        form.addRow(tr("sd.model"), model_row)
        form.addRow("VAE / TE", self.vae)
        form.addRow(tr("sd.clip_skip"), self.clip_skip)
        form.addRow(tr("sd.sampler"), self.sampler)
        form.addRow(tr("sd.scheduler"), self.scheduler)
        form.addRow(tr("sd.steps"), self.steps)
        form.addRow("CFG", self.cfg_scale)
        form.addRow(tr("sd.size"), size_row)
        form.addRow(tr("sd.seed"), self.seed)
        form.addRow(tr("sd.batch_count"), self.n_iter)
        form.addRow(tr("sd.batch_size"), self.batch_size)
        init_box = QHBoxLayout()
        init_box.addWidget(self.init_thumb)
        init_col = QVBoxLayout()
        init_col.addWidget(QLabel(tr("sd.init_title")))
        btns = QHBoxLayout()
        btns.addWidget(self.init_choose)
        btns.addWidget(self.init_clear)
        init_col.addLayout(btns)
        dn = QHBoxLayout()
        dn.addWidget(QLabel(tr("sd.denoise")))
        dn.addWidget(self.denoise)
        init_col.addLayout(dn)
        init_box.addLayout(init_col, 1)
        actions = QHBoxLayout()
        actions.addWidget(self.generate_btn, 2)
        actions.addWidget(self.stop_btn, 1)
        queue_row = QHBoxLayout()
        queue_row.addWidget(self.queue_btn, 1)
        queue_row.addWidget(self.queue_count)

        inner = QWidget()
        lay = QVBoxLayout(inner)
        lay.addLayout(top)
        lay.addLayout(tools)
        lay.addWidget(QLabel(tr("sd.prompt")))
        lay.addWidget(self.prompt, 2)
        lay.addWidget(QLabel(tr("sd.negative")))
        lay.addWidget(self.negative)
        lay.addLayout(init_box)
        lay.addLayout(form)
        lay.addWidget(self.hr_box)
        lay.addWidget(self.var_box)
        lay.addLayout(actions)
        lay.addLayout(queue_row)
        lay.addWidget(self.progress)
        lay.addWidget(self.progress_text)
        lay.addWidget(self.message)
        lay.addStretch(1)
        left = QScrollArea()
        left.setWidgetResizable(True)
        left.setFrameShape(QScrollArea.Shape.NoFrame)
        left.setWidget(inner)
        left.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        left.setFixedWidth(470)

        # --- results
        self.grid = ThumbGrid(220)
        self.grid.set_empty("sparkles", tr("sd.results_empty"), tr("sd.results_hint"))
        self.rating = QComboBox()
        for r in RATINGS:
            self.rating.addItem(tr(f"rating.{r}"), r)
        self.add_btn = style.secondary(QPushButton(tr("action.save")), "save")
        self.add_btn.setEnabled(False)
        self.upscaler = QComboBox()
        self.upscaler.addItem("R-ESRGAN 4x+")
        self.up_scale = QDoubleSpinBox(minimum=1.0, maximum=8.0, singleStep=0.5, decimals=1, value=2.0)
        self.up_btn = style.secondary(QPushButton(tr("sd.upscale")), "arrow-up")
        self.up_btn.setEnabled(False)
        self.clear_btn = style.ghost(QPushButton(tr("sd.clear")), "x")
        bottom = QHBoxLayout()
        bottom.addWidget(QLabel(tr("sd.rating")))
        bottom.addWidget(self.rating)
        bottom.addWidget(self.add_btn)
        bottom.addSpacing(12)
        bottom.addWidget(self.upscaler)
        bottom.addWidget(self.up_scale)
        bottom.addWidget(self.up_btn)
        bottom.addStretch(1)
        bottom.addWidget(self.clear_btn)
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.addWidget(self.grid, 1)
        rl.addLayout(bottom)
        split = QSplitter()
        split.addWidget(left)
        split.addWidget(right)
        split.setStretchFactor(1, 1)
        QVBoxLayout(self).addWidget(split)

        # --- wiring
        self.generate_btn.clicked.connect(self.generate)
        self.stop_btn.clicked.connect(self.interrupt)
        self.queue_btn.clicked.connect(self._add_to_queue)
        self.init_choose.clicked.connect(self._choose_init)
        self.init_clear.clicked.connect(lambda: self.set_init_image(None))
        self.refresh_btn.clicked.connect(self.load_forge_data)
        self.add_btn.clicked.connect(self._add_selected)
        self.up_btn.clicked.connect(self._upscale_selected)
        self.clear_btn.clicked.connect(self.grid.clear_items)
        self.grid.itemDoubleClicked.connect(self._open_viewer)
        self.grid.itemSelectionChanged.connect(self._update_buttons)
        self.preset_box.activated.connect(self._apply_preset)
        self.preset_save.clicked.connect(self._save_preset)
        self.preset_delete.clicked.connect(self._delete_preset)
        self.png_btn.clicked.connect(self._load_from_image)
        self.lora_btn.clicked.connect(self._open_lora)
        self.embed_btn.clicked.connect(self._open_embeddings)
        self.progress_timer = QTimer(self)
        self.progress_timer.timeout.connect(self._poll_progress)
        controller.state_changed.connect(self._on_state)
        queue.running_changed.connect(lambda _r: self._update_buttons())
        self.refresh_presets()
        self._on_state(controller.state.value)

    # --- Forge state / lists -------------------------------------------------------------------------------

    def _on_state(self, state: str) -> None:
        if ForgeState(state).ready and not self._data_loaded:
            self.load_forge_data()
        if not ForgeState(state).ready:
            self._data_loaded = False
        self._update_buttons()

    def _update_buttons(self) -> None:
        ready = self.controller.state.ready
        queue_uses_main = self.queue.is_busy("main")
        self.generate_btn.setEnabled(ready and not self._generating and not queue_uses_main)
        self.stop_btn.setEnabled(self._generating)
        self.add_btn.setEnabled(bool(self.grid.selectedItems()))
        self.up_btn.setEnabled(bool(self.grid.selectedItems()) and ready and not self._generating)
        for b in (self.lora_btn, self.embed_btn):
            b.setEnabled(ready)
        if not ready and not self._generating:
            self.message.setText(tr("sd.need_forge"))
        elif self.message.text() == tr("sd.need_forge"):
            self.message.clear()

    def load_forge_data(self) -> None:
        api = self.controller.manager.api

        def fetch():
            def safe(fn, default):
                try:
                    return fn()
                except Exception:  # noqa: BLE001 - one missing list must not break the others
                    return default

            return (api.models(), api.samplers(), api.schedulers(), api.options().get("sd_model_checkpoint", ""),
                    safe(api.modules, []), safe(api.upscalers, []), safe(api.latent_modes, ["Latent"]))

        def done(result) -> None:
            models, samplers, schedulers, current, modules, upscalers, latent = result
            self._data_loaded = True
            wanted_model = self.model.currentData() or current
            self.model.clear()
            for m in models:
                self.model.addItem(m["model_name"], m["title"])
            idx = max(self.model.findData(wanted_model), self.model.findText(wanted_model.split(" [")[0]), 0)
            self.model.setCurrentIndex(idx)
            for combo, items in ((self.sampler, samplers), (self.scheduler, schedulers)):
                wanted = combo.currentText()
                combo.clear()
                combo.addItems(items)
                combo.setCurrentIndex(max(combo.findText(wanted), 0))
            wanted_vae = self.vae.currentData()
            self.vae.clear()
            self.vae.addItem(tr("sd.auto"), "")
            for m in modules:
                self.vae.addItem(m.get("model_name", m.get("filename", "")), m.get("filename", ""))
            self.vae.setCurrentIndex(max(self.vae.findData(wanted_vae), 0))
            wanted_hr = self.hr_upscaler.currentText()
            self.hr_upscaler.clear()
            self.hr_upscaler.addItems(list(dict.fromkeys(latent + upscalers)))
            _set_combo(self.hr_upscaler, wanted_hr)
            wanted_up = self.upscaler.currentText()
            self.upscaler.clear()
            self.upscaler.addItems(upscalers or [wanted_up])
            self.upscaler.setCurrentIndex(max(self.upscaler.findText(wanted_up), 0))

        run_async(fetch, on_done=done, on_error=lambda exc: self.message.setText(tr("status.error", msg=str(exc))))

    # --- parameters ------------------------------------------------------------------------------------------

    def _params(self) -> GenParams:
        return GenParams(
            prompt=self.prompt.toPlainText().strip(), negative_prompt=self.negative.toPlainText().strip(),
            model=self.model.currentData() or "", vae=self.vae.currentData() or "", clip_skip=self.clip_skip.value(),
            sampler_name=self.sampler.currentText(), scheduler=self.scheduler.currentText(), steps=self.steps.value(),
            cfg_scale=self.cfg_scale.value(), width=self.width_.value(), height=self.height_.value(),
            seed=self.seed.value(), subseed=self.subseed.value() if self.var_box.isChecked() else -1,
            subseed_strength=self.subseed_strength.value() if self.var_box.isChecked() else 0.0,
            n_iter=self.n_iter.value(), batch_size=self.batch_size.value(),
            enable_hr=self.hr_box.isChecked(), hr_scale=self.hr_scale.value(),
            hr_upscaler=self.hr_upscaler.currentText() or "Latent", hr_steps=self.hr_steps.value(),
            hr_denoise=self.hr_denoise.value(),
            init_image=str(self.init_path) if self.init_path else "", denoising_strength=self.denoise.value())

    def apply_params(self, data: dict) -> None:
        """Fill the whole form from a preset / history entry / PNG info (missing keys keep their defaults)."""
        p = params_from_dict(data)
        self.prompt.setPlainText(p.prompt)
        self.negative.setPlainText(p.negative_prompt)
        if p.model:
            self._set_model(p.model)
        idx = self.vae.findData(p.vae)
        self.vae.setCurrentIndex(max(idx, 0))
        self.clip_skip.setValue(p.clip_skip)
        _set_combo(self.sampler, p.sampler_name)
        _set_combo(self.scheduler, p.scheduler)
        self.steps.setValue(p.steps)
        self.cfg_scale.setValue(p.cfg_scale)
        self.width_.setValue(p.width)
        self.height_.setValue(p.height)
        self.seed.setValue(p.seed)
        self.n_iter.setValue(p.n_iter)
        self.batch_size.setValue(p.batch_size)
        self.hr_box.setChecked(p.enable_hr)
        self.hr_scale.setValue(p.hr_scale)
        _set_combo(self.hr_upscaler, p.hr_upscaler)
        self.hr_steps.setValue(p.hr_steps)
        self.hr_denoise.setValue(p.hr_denoise)
        self.var_box.setChecked(p.subseed_strength > 0)
        self.subseed.setValue(p.subseed)
        if p.subseed_strength > 0:
            self.subseed_strength.setValue(p.subseed_strength)
        self.denoise.setValue(p.denoising_strength)

    def _set_model(self, name: str) -> None:
        base = name.split(" [")[0].replace(".safetensors", "")
        for i in range(self.model.count()):
            title = str(self.model.itemData(i) or "")
            if title == name or self.model.itemText(i) == base or title.split(" [")[0].replace(".safetensors", "") == base:
                self.model.setCurrentIndex(i)
                return
        self.model.addItem(name, name)  # not installed here: keep it visible so the user notices
        self.model.setCurrentIndex(self.model.count() - 1)

    # --- presets, styles, PNG info -------------------------------------------------------------------------

    def refresh_presets(self) -> None:
        self.preset_box.clear()
        self.preset_box.addItem(tr("sd.preset_none"), None)
        for pid, name, data in self.ctx.db.presets("preset"):
            self.preset_box.addItem(name, (pid, data))

    def _apply_preset(self) -> None:
        entry = self.preset_box.currentData()
        if entry:
            self.apply_params(entry[1])
            self.message.setText(tr("sd.preset_applied", name=self.preset_box.currentText()))

    def _save_preset(self) -> None:
        name, ok = QInputDialog.getText(self, tr("sd.preset_save"), tr("lib.name"), text=self.preset_box.currentText()
                                        if self.preset_box.currentData() else "")
        name = name.strip()
        if ok and name:
            params = asdict(self._params())
            params.pop("init_image", None)  # a preset is about settings, not one particular source picture
            self.ctx.db.save_preset("preset", name, params)
            self.presets_changed.emit()
            self.refresh_presets()
            self.preset_box.setCurrentIndex(max(self.preset_box.findText(name), 0))
            self.message.setText(tr("hist.preset_saved", name=name))

    def _delete_preset(self) -> None:
        entry = self.preset_box.currentData()
        if entry and QMessageBox.question(self, tr("sd.preset_delete"), self.preset_box.currentText()) == QMessageBox.StandardButton.Yes:
            self.ctx.db.delete_preset(entry[0])
            self.presets_changed.emit()
            self.refresh_presets()

    def _build_styles_menu(self) -> None:
        menu = self.styles_menu
        menu.clear()
        for sid, name, data in self.ctx.db.presets("style"):
            menu.addAction(name, lambda d=data: self._apply_style(d))
        if not menu.isEmpty():
            menu.addSeparator()
        menu.addAction(tr("sd.style_save"), self._save_style)
        delete = menu.addMenu(tr("sd.style_delete"))
        for sid, name, _d in self.ctx.db.presets("style"):
            delete.addAction(name, lambda i=sid: self.ctx.db.delete_preset(i))
        delete.setEnabled(not delete.isEmpty())

    def _apply_style(self, data: dict) -> None:
        """A style is a prompt snippet: '{prompt}' in it is replaced by the current prompt, otherwise it is appended."""
        prompt, negative = self.prompt.toPlainText().strip(), self.negative.toPlainText().strip()
        text = data.get("prompt", "")
        self.prompt.setPlainText(text.replace("{prompt}", prompt) if "{prompt}" in text else ", ".join(p for p in (prompt, text) if p))
        extra = data.get("negative", "")
        self.negative.setPlainText(", ".join(p for p in (negative, extra) if p))

    def _save_style(self) -> None:
        name, ok = QInputDialog.getText(self, tr("sd.style_save"), tr("lib.name"))
        name = name.strip()
        if ok and name:
            self.ctx.db.save_preset("style", name, {"prompt": self.prompt.toPlainText().strip(),
                                                   "negative": self.negative.toPlainText().strip()})

    def _load_from_image(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, tr("sd.from_image"), "", "PNG (*.png)")
        if path:
            self.load_from_image(Path(path))

    def load_from_image(self, path: Path) -> bool:
        text = read_png_text(path).get("parameters", "")
        if not text:
            self.message.setText(tr("sd.no_png_info"))
            return False
        self.apply_params(parse_infotext(text))
        self.message.setText(tr("sd.png_loaded", name=path.name))
        return True

    # --- LoRA / embeddings ---------------------------------------------------------------------------------

    def _append_prompt(self, text: str) -> None:
        current = self.prompt.toPlainText().rstrip()
        self.prompt.setPlainText(f"{current}, {text}" if current else text)

    def _open_lora(self) -> None:
        api = self.controller.manager.api

        def load():
            return [(item.get("alias") or item["name"], item.get("alias") or item["name"]) for item in api.loras()]

        dlg = InsertDialog("LoRA", load, lambda name, w: f"<lora:{name}:{w:g}>", lambda: api.refresh("loras"),
                           with_weight=True, parent=self)
        dlg.inserted.connect(self._append_prompt)
        dlg.show()

    def _open_embeddings(self) -> None:
        api = self.controller.manager.api
        dlg = InsertDialog("Embeddings", lambda: [(n, n) for n in api.embeddings()], lambda name, _w: name,
                           lambda: api.refresh("embeddings"), parent=self)
        dlg.inserted.connect(self._append_prompt)
        dlg.show()

    # --- img2img source ----------------------------------------------------------------------------------------

    def _choose_init(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, tr("sd.init_choose"), "", "Images (*.png *.jpg *.jpeg *.webp *.bmp)")
        if path:
            self.set_init_image(Path(path), resize=True)

    def set_init_image(self, path: Path | None, resize: bool = False) -> None:
        self.init_path = path
        self.init_clear.setEnabled(path is not None)
        self.denoise.setEnabled(path is not None)
        self.generate_btn.setText(tr("sd.generate_img2img") if path else tr("sd.generate"))
        if path is None:
            self.init_thumb.setPixmap(QPixmap())
            self.init_thumb.setText("txt2img")
            return
        pm = QPixmap(str(path))
        if pm.isNull():
            self.init_thumb.setText("?")
            return
        self.init_thumb.setPixmap(pm.scaled(72, 72, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        if resize:
            w, h = fit_size(pm.width(), pm.height())
            self.width_.setValue(w)
            self.height_.setValue(h)

    def use_as_init(self, path: Path, prompt: str = "", negative: str = "") -> None:
        """Entry point of the library -> img2img bridge (ТЗ 5.3)."""
        self.set_init_image(path, resize=True)
        if prompt:
            self.prompt.setPlainText(prompt)
        if negative:
            self.negative.setPlainText(negative)
        self.message.setText(tr("sd.init_ready") if self.controller.state.ready else tr("sd.need_forge"))

    # --- generation ----------------------------------------------------------------------------------------------

    def _add_to_queue(self) -> None:
        params = self._params()
        if not params.prompt and not params.init_image:
            self.message.setText(tr("sd.need_prompt"))
            return
        self.queue.add(params, self.queue_count.value())
        self.message.setText(tr("sd.queued", n=self.queue_count.value()))

    def generate(self) -> None:
        if self._generating or not self.controller.state.ready or self.queue.is_busy("main"):
            return
        params = self._params()
        self.ctx.cfg.set("sd.last", asdict(params))
        self._generating = True
        self._interrupting = False
        self.controller.set_busy(True)
        self.queue.set_external_busy("main", True)
        self.progress.setValue(0)
        self.progress_text.setText(tr("status.loading"))
        self.message.clear()
        self._update_buttons()
        self.progress_timer.start(700)
        out_dir = self.ctx.paths.sd / "generated"
        api = self.controller.manager.api

        def work() -> list[GenResult]:
            results = run_generation(api, params, out_dir)
            record_history(self.ctx.db, self.ctx.paths.root, results, "main")
            return results

        def done(results: list[GenResult]) -> None:
            self._finish()
            self.add_results(results)
            self.message.setText(tr("sd.done", n=len(results)))
            self.history_changed.emit()

        def failed(exc: Exception) -> None:
            self._finish()
            self.message.setText(tr("status.error", msg=str(exc)))

        run_async(work, on_done=done, on_error=failed)

    def add_results(self, results: list[GenResult]) -> None:
        for res in results:
            self.grid.add_entry(res, self._tooltip(res), lambda r=res: image_to_thumb(r.path.read_bytes(), self.grid.thumb_size))
        self.grid.scrollToBottom()

    def _finish(self) -> None:
        self._generating = False
        self.progress_timer.stop()
        self.progress.setValue(0)
        self.progress_text.clear()
        self.controller.set_busy(False)
        self.queue.set_external_busy("main", False)
        self._update_buttons()

    def interrupt(self) -> None:
        self._interrupting = True
        self.stop_btn.setEnabled(False)
        self.progress_text.setText(tr("sd.interrupting"))
        run_async(self.controller.manager.api.interrupt,
                  on_error=lambda exc: self.message.setText(tr("status.error", msg=str(exc))))

    def _poll_progress(self) -> None:
        if self._polling or not self._generating:
            return
        self._polling = True

        def done(progress: dict) -> None:
            self._polling = False
            if self._generating and not self._interrupting:
                frac, text = progress_text(progress)
                self.progress.setValue(int(frac * 1000))
                self.progress_text.setText(text or tr("sd.preparing"))

        run_async(self.controller.manager.api.progress, on_done=done, on_error=lambda _e: setattr(self, "_polling", False))

    # --- results ---------------------------------------------------------------------------------------------------

    @staticmethod
    def _tooltip(res: GenResult) -> str:
        m = res.meta
        return f"seed {res.seed} · {m.get('width')}×{m.get('height')} · {m.get('steps')} steps\n{m.get('prompt', '')[:200]}"

    def _view_item(self, res: GenResult) -> ViewItem:
        info = res.meta.get("infotext") or json.dumps(res.meta, ensure_ascii=False)
        tags = [(t, "general") for t in prompt_tags(res.meta.get("prompt", ""))]
        return ViewItem(res.path.name, info, lambda: res.path, "", tags, res)

    def _open_viewer(self, item) -> None:
        viewer = Viewer([self._view_item(r) for r in self.grid.payloads()], self.grid.row(item), self._save_from_viewer)
        viewer.destroyed.connect(lambda: self._viewers.remove(viewer) if viewer in self._viewers else None)
        self._viewers.append(viewer)
        viewer.show()

    def _save_from_viewer(self, item: ViewItem) -> None:
        self._add([item.payload])

    def _add_selected(self) -> None:
        self._add(self.grid.selected_payloads())

    def _add(self, results: list[GenResult]) -> None:
        rating = self.rating.currentData()

        def work():
            counts = {"saved": 0, "duplicate": 0, "failed": 0}
            for res in results:
                counts[self.ctx.library.save_generation(res.path, res.meta, rating).status] += 1
            return counts

        def done(counts: dict) -> None:
            self.message.setText(tr("status.saved", saved=counts["saved"], dup=counts["duplicate"], failed=counts["failed"]))
            self.library_changed.emit()

        run_async(work, on_done=done, on_error=lambda exc: self.message.setText(tr("status.error", msg=str(exc))))

    def _upscale_selected(self) -> None:
        results = self.grid.selected_payloads()
        upscaler, scale = self.upscaler.currentText(), self.up_scale.value()
        api, out_dir = self.controller.manager.api, self.ctx.paths.sd / "generated"
        self.up_btn.setEnabled(False)
        self.message.setText(tr("sd.upscaling", n=len(results)))

        def work() -> list[GenResult]:
            out = [run_upscale(api, r.path, upscaler, scale, out_dir, r.meta) for r in results]
            record_history(self.ctx.db, self.ctx.paths.root, out, "main")
            return out

        def done(out: list[GenResult]) -> None:
            self.add_results(out)
            self.message.setText(tr("sd.upscaled", n=len(out)))
            self._update_buttons()
            self.history_changed.emit()

        def failed(exc: Exception) -> None:
            self.message.setText(tr("status.error", msg=str(exc)))
            self._update_buttons()

        run_async(work, on_done=done, on_error=failed)


class SDPage(QWidget):
    def __init__(self, ctx: AppContext, controller: ForgeController, controllers: dict | None = None, parent=None):
        super().__init__(parent)
        self.ctx, self.controller = ctx, controller
        self.controllers = controllers or {"main": controller}
        self.chip = StatusChip()
        self.dot, self.state_label = self.chip.dot, self.chip.text
        self.start_btn = style.primary(QPushButton(tr("sd.start")), "play")
        self.stop_btn = style.secondary(QPushButton(tr("sd.stop")), "stop")
        self.folder_btn = style.ghost(QPushButton(tr("sd.folder")), "folder")
        self.log_btn = style.ghost(QPushButton(tr("sd.log")), "list")
        self.error = style.role(QLabel(), "error")
        bar = QHBoxLayout()
        bar.setSpacing(8)
        for w in (self.chip, self.start_btn, self.stop_btn, self.folder_btn, self.log_btn):
            bar.addWidget(w)
        bar.addStretch(1)
        bar.addWidget(self.error)

        self.queue_ctrl = QueueController(ctx, self.controllers, parent=self)
        self.generate = GenerateView(ctx, controller, self.queue_ctrl)
        self.queue_view = QueueView(ctx, self.queue_ctrl)
        self.history = HistoryView(ctx)
        self.civitai = CivitaiView(ctx)
        self.saved = LibraryView(ctx, kind="sd")
        self.tabs = tabs = QTabWidget()
        tabs.addTab(self.generate, tr("sd.tab.generate"))
        tabs.addTab(self.queue_view, tr("sd.tab.queue"))
        tabs.addTab(self.history, tr("sd.tab.history"))
        tabs.addTab(self.civitai, "CivitAI")
        tabs.addTab(self.saved, tr("sd.tab.saved"))
        layout = QVBoxLayout(self)
        layout.addLayout(bar)
        layout.addWidget(tabs, 1)

        self.start_btn.clicked.connect(self._start)
        self.stop_btn.clicked.connect(controller.stop)
        self.folder_btn.clicked.connect(self._pick_folder)
        self.log_btn.clicked.connect(lambda: ForgeLogDialog(controller, self).show())
        controller.state_changed.connect(self._on_state)
        controller.error.connect(lambda msg: self.error.setText(msg))
        self.generate.library_changed.connect(self.saved.reload)
        self.generate.history_changed.connect(self.history.reload)
        self.generate.presets_changed.connect(lambda: None)
        self.history.load_params.connect(self._load_params)
        self.history.to_queue.connect(lambda d: self.queue_ctrl.add(params_from_dict(d)))
        self.history.to_img2img.connect(lambda path, p, n: (self.show_generate_tab(), self.generate.use_as_init(path, p, n)))
        self.history.presets_changed.connect(self.generate.refresh_presets)
        self.history.library_changed.connect(self.saved.reload)
        self.queue_ctrl.job_finished.connect(lambda results: (self.generate.add_results(results), self.history.reload()))
        # a freshly installed file is only visible to a running Forge (it was told to rescan already)
        self.civitai.installed.connect(lambda _t: self.generate.load_forge_data() if controller.state.ready else None)
        self._on_state(controller.state.value)

    def _load_params(self, data: dict) -> None:
        self.show_generate_tab()
        self.generate.apply_params(data)

    def show_generate_tab(self) -> None:
        self.tabs.setCurrentWidget(self.generate)

    def _start(self) -> None:
        self.error.clear()
        self.controller.start()

    def _pick_folder(self) -> None:
        start = self.ctx.cfg.get("forge.path") or ""
        folder = QFileDialog.getExistingDirectory(self, tr("sd.folder"), start)
        if folder:
            self.ctx.cfg.set("forge.path", folder.replace("/", "\\"))
            self.error.clear()

    def _on_state(self, state: str) -> None:
        s = ForgeState(state)
        self.chip.set_state(state, "Forge · " + tr(f"forge.state.{state}"))
        self.start_btn.setEnabled(s in (ForgeState.STOPPED, ForgeState.FAILED))
        self.stop_btn.setEnabled(s in (ForgeState.STARTING, ForgeState.RUNNING))
        self.stop_btn.setToolTip(tr("forge.external_hint") if s == ForgeState.EXTERNAL else "")
        if s == ForgeState.FAILED:
            self.error.setText(tr("forge.failed_hint"))
