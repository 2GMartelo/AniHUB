"""The "Train LoRA" tab: pick a few arts of one character/style, let the autotagger caption them, tweak the captions by
hand, name the LoRA and start training. AniHUB only assembles the dataset and drives sd-scripts (services/lora_train.py)
as a subprocess -- the actual training happens there, not in this process."""
from __future__ import annotations

import shutil
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout, QFrame, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
    QPlainTextEdit, QProgressBar, QPushButton, QScrollArea, QSpinBox, QSplitter, QToolButton, QVBoxLayout, QWidget,
)

from anihub.context import AppContext
from anihub.core.config import config_dir
from anihub.core.i18n import tr
from anihub.services import lora as lo
from anihub.services import lora_train as lt
from anihub.ui import style
from anihub.ui.manga_filters import FlowLayout
from anihub.ui.pagezoom import PageZoom
from anihub.ui.workers import run_async

THUMB = 88


class TagChip(QFrame):
    removed = Signal(str)

    def __init__(self, text: str):
        super().__init__()
        self.setObjectName("chip")
        self.text_value = text
        row = QHBoxLayout(self)
        row.setContentsMargins(7, 3, 4, 3)
        row.setSpacing(5)
        row.addWidget(QLabel(text))
        close_btn = QToolButton(text="×")
        close_btn.setProperty("tagbtn", True)
        close_btn.setFixedSize(16, 16)
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.clicked.connect(lambda: self.removed.emit(text))
        row.addWidget(close_btn)


class ImageRow(QFrame):
    """One picture of the dataset: its thumbnail and an editable, comma-tag caption (autotagged, then hand-fixed)."""
    removed = Signal(QWidget)
    changed = Signal()

    def __init__(self, path: Path, tags: list[str]):
        super().__init__()
        self.setObjectName("card")
        self.path = path
        self.tags = list(dict.fromkeys(t.strip() for t in tags if t.strip()))

        self._original_pixmap = QPixmap(str(path))
        self._thumb_label = QLabel()
        self._thumb_label.setObjectName("thumbHolder")
        self._name_label = style.role(QLabel(path.name), "dim")
        self._name_label.setWordWrap(True)
        self.remove_btn = style.ghost(QPushButton(tr("lt.remove_image")), "trash")
        self.set_thumb_size(THUMB)
        thumb, name = self._thumb_label, self._name_label

        left = QVBoxLayout()
        left.addWidget(thumb, 0, Qt.AlignmentFlag.AlignHCenter)
        left.addWidget(name)
        left.addWidget(self.remove_btn)
        left.addStretch(1)

        self.chip_area = QWidget()
        self.flow = FlowLayout(self.chip_area, spacing=6)
        self.add_line = QLineEdit(placeholderText=tr("lt.add_tag"))
        self.add_line.setMaximumWidth(220)
        self.add_line.setClearButtonEnabled(True)

        right = QVBoxLayout()
        right.addWidget(self.chip_area)
        right.addWidget(self.add_line)
        right.addStretch(1)

        row = QHBoxLayout(self)
        row.addLayout(left)
        row.addLayout(right, 1)

        self.remove_btn.clicked.connect(lambda: self.removed.emit(self))
        self.add_line.returnPressed.connect(self._add_tag)
        self._rebuild_chips()

    def set_thumb_size(self, size: int) -> None:
        self._thumb_label.setFixedSize(size, size)
        if not self._original_pixmap.isNull():
            self._thumb_label.setPixmap(self._original_pixmap.scaled(
                size, size, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation))
        self._name_label.setFixedWidth(size)

    def _rebuild_chips(self) -> None:
        while self.flow.count():
            item = self.flow.takeAt(0)
            if item.widget() is not None:
                item.widget().hide()
                item.widget().setParent(None)
                item.widget().deleteLater()
        for t in self.tags:
            chip = TagChip(t)
            chip.removed.connect(self._remove_tag)
            self.flow.addWidget(chip)
        self.chip_area.updateGeometry()

    def _remove_tag(self, text: str) -> None:
        if text in self.tags:
            self.tags.remove(text)
            self._rebuild_chips()
            self.changed.emit()

    def _add_tag(self) -> None:
        text = self.add_line.text().strip()
        if text and text not in self.tags:
            self.tags.append(text)
            self._rebuild_chips()
            self.add_line.clear()
            self.changed.emit()

    def set_tags(self, tags: list[str]) -> None:
        self.tags = list(dict.fromkeys(t.strip() for t in tags if t.strip()))
        self._rebuild_chips()
        self.changed.emit()

    def caption(self) -> str:
        return ", ".join(self.tags)


class LoraTrainPage(QWidget):
    def __init__(self, ctx: AppContext, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.rows: list[ImageRow] = []
        self.trainer: lt.Trainer | None = None
        self._checkpoint_paths: dict[str, Path] = {}
        self._checkpoint_path: Path | None = None
        self._trained_path: Path | None = None
        self._autotagging = False
        self._autotag_cancelled = False
        self._autotag_queue: list[ImageRow] = []
        self._autotag_total = 0
        self._autotag_done = 0

        # --- left: the dataset --------------------------------------------------------------------------------------
        self.add_btn = style.primary(QPushButton(tr("lt.add_images")), "upload")
        self.autotag_btn = style.secondary(QPushButton(tr("lt.autotag_all")), "tag")
        self.count_label = style.role(QLabel(), "dim")
        top_row = QHBoxLayout()
        top_row.addWidget(self.add_btn)
        top_row.addWidget(self.autotag_btn)
        top_row.addWidget(self.count_label)
        top_row.addStretch(1)

        self.empty_hint = style.role(QLabel(tr("lt.no_images")), "dim")
        self.empty_hint.setWordWrap(True)
        self.rows_area = QWidget()
        self.rows_layout = QVBoxLayout(self.rows_area)
        self.rows_layout.setSpacing(6)
        self.rows_layout.addWidget(self.empty_hint)
        self.rows_layout.addStretch(1)
        rows_scroll = QScrollArea()
        rows_scroll.setWidgetResizable(True)
        rows_scroll.setFrameShape(QFrame.Shape.NoFrame)
        rows_scroll.setWidget(self.rows_area)

        left_widget = QWidget()
        left = QVBoxLayout(left_widget)
        left.setContentsMargins(0, 0, 0, 0)
        left.addLayout(top_row)
        left.addWidget(rows_scroll, 1)
        left_widget.setMinimumWidth(280)

        # --- right: name, trigger, checkpoint, advanced params, start/log ------------------------------------------
        self.name_edit = QLineEdit(placeholderText=tr("lt.name_hint"))
        self.trigger_edit = QLineEdit(placeholderText=tr("lt.trigger_hint"))
        self.template_edit = QLineEdit(lo.DEFAULT_TEMPLATE, placeholderText=lo.DEFAULT_TEMPLATE)
        self.negative_edit = QLineEdit(placeholderText=tr("lora.negative_hint"))
        self.weight = QDoubleSpinBox(minimum=0.1, maximum=2.0, singleStep=0.05, decimals=2, value=0.8)

        self.checkpoint = QComboBox()
        self.checkpoint_browse = style.ghost(QPushButton(tr("wizard.browse")), "folder")
        cp_row = QHBoxLayout()
        cp_row.addWidget(self.checkpoint, 1)
        cp_row.addWidget(self.checkpoint_browse)
        self.sdxl_check = QCheckBox(tr("lt.sdxl"), checked=True)

        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        form.addRow(tr("lora.name"), self.name_edit)
        form.addRow(tr("lt.trigger"), self.trigger_edit)
        form.addRow(tr("lora.template"), self.template_edit)
        form.addRow(tr("lora.negative"), self.negative_edit)
        form.addRow(tr("lora.weight"), self.weight)
        form.addRow(tr("lt.checkpoint"), cp_row)
        form.addRow("", self.sdxl_check)

        d = lt.DEFAULT_TRAIN
        self.resolution = QSpinBox(minimum=512, maximum=2048, singleStep=64, value=d["resolution"])
        self.dim = QSpinBox(minimum=4, maximum=256, value=d["network_dim"])
        self.alpha = QSpinBox(minimum=1, maximum=256, value=d["network_alpha"])
        self.lr = QDoubleSpinBox(minimum=0.00001, maximum=0.01, singleStep=0.00005, decimals=5, value=d["learning_rate"])
        self.epochs = QSpinBox(minimum=1, maximum=200, value=d["epochs"])
        self.batch = QSpinBox(minimum=1, maximum=16, value=d["batch_size"])
        self.repeats = QSpinBox(minimum=1, maximum=100, value=d["repeats"])
        adv_form = QFormLayout()
        adv_form.addRow(tr("lt.resolution"), self.resolution)
        adv_form.addRow(tr("lt.dim"), self.dim)
        adv_form.addRow(tr("lt.alpha"), self.alpha)
        adv_form.addRow(tr("lt.lr"), self.lr)
        adv_form.addRow(tr("lt.epochs"), self.epochs)
        adv_form.addRow(tr("lt.batch"), self.batch)
        adv_form.addRow(tr("lt.repeats"), self.repeats)
        adv_box = QGroupBox(tr("lt.advanced"))
        adv_box.setLayout(adv_form)

        self.start_btn = style.primary(QPushButton(tr("lt.start")), "play")
        self.pause_btn = style.secondary(QPushButton(tr("lt.pause")), "pause")
        self.pause_btn.setEnabled(False)
        self.cancel_btn = style.secondary(QPushButton(tr("lt.cancel")), "stop")
        self.cancel_btn.setEnabled(False)
        run_row = QHBoxLayout()
        run_row.addWidget(self.start_btn)
        run_row.addWidget(self.pause_btn)
        run_row.addWidget(self.cancel_btn)
        run_row.addStretch(1)

        self.progress = QProgressBar(minimum=0, maximum=100)
        self.progress.setVisible(False)
        self.status_label = style.role(QLabel(), "dim")
        self.status_label.setWordWrap(True)
        self.log = QPlainTextEdit(readOnly=True)
        self.log.setMaximumBlockCount(4000)
        self.log.setVisible(False)
        self.log.setMinimumHeight(120)

        right_content = QWidget()
        rl = QVBoxLayout(right_content)
        rl.addLayout(form)
        rl.addWidget(adv_box)
        rl.addLayout(run_row)
        rl.addWidget(self.progress)
        rl.addWidget(self.status_label)
        rl.addWidget(self.log)
        rl.addStretch(1)
        right_scroll = QScrollArea()
        right_scroll.setWidgetResizable(True)
        right_scroll.setFrameShape(QFrame.Shape.NoFrame)
        right_scroll.setWidget(right_content)
        right_scroll.setMinimumWidth(360)

        split = QSplitter()
        split.addWidget(left_widget)
        split.addWidget(right_scroll)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        split.setSizes([600, 400])
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(split)

        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self._poll)

        self.add_btn.clicked.connect(self._add_images)
        self.autotag_btn.clicked.connect(self._autotag_all)
        self.checkpoint_browse.clicked.connect(self._browse_checkpoint)
        self.checkpoint.currentIndexChanged.connect(self._checkpoint_changed)
        self.start_btn.clicked.connect(self._start)
        self.pause_btn.clicked.connect(self._toggle_pause)
        self.cancel_btn.clicked.connect(self._cancel)

        self.reload_checkpoints()

        self._thumb_size = THUMB
        self.page_zoom = PageZoom(self, on_zoom=self._resize_rows)

    def _resize_rows(self, factor: float) -> None:
        self._thumb_size = max(50, round(THUMB * factor))
        for row in self.rows:
            row.set_thumb_size(self._thumb_size)

    # --- dataset ---------------------------------------------------------------------------------------------------

    def _update_count(self) -> None:
        self.empty_hint.setVisible(not self.rows)
        self.count_label.setText(tr("lt.image_count", n=len(self.rows)) if self.rows else "")

    def _add_images(self) -> None:
        exts = " ".join(f"*{e}" for e in lt.IMAGE_EXTS)
        files, _ = QFileDialog.getOpenFileNames(self, tr("lt.add_images"), "", f"{tr('lt.images')} ({exts})")
        existing = {row.path for row in self.rows}
        for f in files:
            path = Path(f)
            if path in existing:
                continue
            row = ImageRow(path, [])
            row.set_thumb_size(self._thumb_size)
            row.removed.connect(self._remove_row)
            self.rows.append(row)
            self.rows_layout.insertWidget(self.rows_layout.count() - 2, row)
        self._update_count()

    def _remove_row(self, row: ImageRow) -> None:
        if row in self.rows:
            self.rows.remove(row)
            if row in self._autotag_queue:
                self._autotag_queue.remove(row)
            row.hide()
            row.setParent(None)
            row.deleteLater()
            self._update_count()

    def _autotag_all(self) -> None:
        if self._autotagging:
            self._autotag_cancelled = True     # clicking again while running stops it after the current picture
            return
        if not self.rows:
            return
        if not self.ctx.autotagger.available:
            self.status_label.setText(tr("lt.no_autotagger"))
            return
        self._autotag_queue = [row for row in self.rows if not row.tags]
        if not self._autotag_queue:
            return
        self._autotagging = True
        self._autotag_cancelled = False
        self._autotag_total = len(self._autotag_queue)
        self._autotag_done = 0
        self.autotag_btn.setText(tr("lt.autotag_stop"))
        self._autotag_next()

    def _autotag_next(self) -> None:
        """One picture at a time, each its own background call: tagging every picture in a single big batch (the
        original design) froze the UI for however long the whole run took and only updated the screen once it was
        all done -- this way the app stays responsive and each row's chips appear as soon as that one picture is
        tagged, instead of everything landing in one burst at the end."""
        if self._autotag_cancelled or not self._autotag_queue:
            self._autotagging = False
            self.autotag_btn.setText(tr("lt.autotag_all"))
            if self._autotag_done:
                self.status_label.setText(tr("lt.autotagged", n=self._autotag_done))
            return
        row = self._autotag_queue.pop(0)
        self.status_label.setText(tr("lt.autotag_progress", done=self._autotag_done, total=self._autotag_total))

        def done(result) -> None:
            if result and row in self.rows:
                tags = [name.replace("_", " ") for name, _cat in result.tags]
                if tags:
                    row.set_tags(tags)
            self._autotag_done += 1
            self._autotag_next()

        def failed(_exc: Exception) -> None:
            self._autotag_done += 1
            self._autotag_next()

        run_async(lambda: self.ctx.autotagger.tag_file(row.path), on_done=done, on_error=failed)

    # --- checkpoint --------------------------------------------------------------------------------------------------

    def reload_checkpoints(self) -> None:
        self._checkpoint_paths.clear()
        self.checkpoint.blockSignals(True)
        self.checkpoint.clear()
        for path in lt.list_checkpoints(self.ctx.cfg):
            self._checkpoint_paths[path.stem] = path
            self.checkpoint.addItem(path.stem)
        self.checkpoint.blockSignals(False)
        self._checkpoint_changed()

    def _checkpoint_changed(self) -> None:
        stem = self.checkpoint.currentText()
        self._checkpoint_path = self._checkpoint_paths.get(stem)

    def _browse_checkpoint(self) -> None:
        exts = " ".join(f"*{e}" for e in lt.CHECKPOINT_EXTS)
        file, _ = QFileDialog.getOpenFileName(self, tr("lt.checkpoint"), "", f"{tr('lt.checkpoints')} ({exts})")
        if file:
            path = Path(file)
            self._checkpoint_paths[path.stem] = path
            if self.checkpoint.findText(path.stem) < 0:
                self.checkpoint.addItem(path.stem)
            self.checkpoint.setCurrentText(path.stem)
            self._checkpoint_path = path

    # --- training ------------------------------------------------------------------------------------------------------

    def _start(self) -> None:
        if self.trainer is not None and self.trainer.state == "running":
            return
        if len(self.rows) < 2:
            self.status_label.setText(tr("lt.need_images"))
            return
        name = self.name_edit.text().strip()
        if not name:
            self.status_label.setText(tr("lt.need_name"))
            return
        if self._checkpoint_path is None:
            self.status_label.setText(tr("lt.no_checkpoint"))
            return
        if not (self.ctx.cfg.get("lora.dir") or self.ctx.cfg.get("forge.path")):
            self.status_label.setText(tr("lt.no_lora_root"))
            return
        sd_scripts_dir = Path(self.ctx.cfg.get("lora_train.sd_scripts_path") or "")
        problem = lt.check_install(sd_scripts_dir)
        if problem:
            self.status_label.setText(tr(problem) + " — " + tr("nav.settings"))
            return
        script = lt.find_script(sd_scripts_dir, self.sdxl_check.isChecked())
        if script is None:
            self.status_label.setText(tr("lt.no_matching_script"))
            return
        python_exe = lt.find_python(sd_scripts_dir)

        cfg = lt.TrainConfig(name=name, trigger=self.trigger_edit.text().strip(), base_model=str(self._checkpoint_path),
                             sdxl=self.sdxl_check.isChecked(), resolution=self.resolution.value(), network_dim=self.dim.value(),
                             network_alpha=self.alpha.value(), learning_rate=self.lr.value(), epochs=self.epochs.value(),
                             batch_size=self.batch.value(), repeats=self.repeats.value(),
                             negative=self.negative_edit.text().strip(), template=self.template_edit.text().strip())
        self._pending_cfg = cfg
        job_dir = config_dir() / "lora_train_jobs" / lt.sanitize_name(name)
        images = [(row.path, lt.caption_text(cfg.trigger, row.caption())) for row in self.rows]
        try:
            train_dir = lt.build_dataset(images, job_dir, name, cfg.repeats)
            self._output_dir = job_dir / "out"
            self._output_file = self._output_dir / f"{lt.sanitize_name(name)}.safetensors"
            command = lt.build_command(python_exe, script, cfg, train_dir, self._output_dir)
            self.trainer = lt.Trainer(job_dir / "train.log")
            self.trainer.start(command, cwd=sd_scripts_dir)
        except OSError as exc:
            self.status_label.setText(tr("status.error", msg=str(exc)))
            return
        self.start_btn.setEnabled(False)
        self.pause_btn.setEnabled(True)
        self.pause_btn.setText(tr("lt.pause"))
        self.cancel_btn.setEnabled(True)
        self.progress.setVisible(True)
        self.progress.setValue(0)
        self.log.setVisible(True)
        self.log.clear()
        self.status_label.setText(tr("lt.running"))
        self.timer.start()

    def _cancel(self) -> None:
        if self.trainer is not None:
            self.trainer.cancel()

    def _toggle_pause(self) -> None:
        if self.trainer is None:
            return
        if self.trainer.paused:
            self.trainer.resume()
        else:
            self.trainer.pause()
        self.pause_btn.setText(tr("lt.resume") if self.trainer.paused else tr("lt.pause"))
        self.status_label.setText(tr("lt.paused") if self.trainer.paused else tr("lt.running"))

    def _poll(self) -> None:
        if self.trainer is None:
            return
        tail = self.trainer.log_tail()
        if tail != self.log.toPlainText():
            bar = self.log.verticalScrollBar()
            at_bottom = bar.value() >= bar.maximum() - 4
            self.log.setPlainText(tail)
            if at_bottom:
                bar.setValue(bar.maximum())
        prog = self.trainer.progress()
        if prog and not self.trainer.paused:
            self.progress.setValue(int(prog["frac"] * 100))
            text = tr("lt.progress", step=prog["step"], total=prog["total_steps"])
            if "epoch" in prog:
                text += f" · {tr('lt.epoch', epoch=prog['epoch'], total=prog['total_epochs'])}"
            self.status_label.setText(text)
        if self.trainer.state in ("done", "failed", "cancelled"):
            self.timer.stop()
            self.start_btn.setEnabled(True)
            self.pause_btn.setEnabled(False)
            self.cancel_btn.setEnabled(False)
            if self.trainer.state == "done":
                self._finish_success()
            elif self.trainer.state == "failed":
                self.status_label.setText(tr("lt.failed", msg=self.trainer.error))
            else:
                self.status_label.setText(tr("lt.cancelled"))

    def _finish_success(self) -> None:
        cfg = self._pending_cfg
        if not self._output_file.is_file():
            self.status_label.setText(tr("lt.no_output"))
            return
        try:
            dest_root = lo.root_dir(self.ctx.cfg)
            dest_root.mkdir(parents=True, exist_ok=True)
            stem = lt.sanitize_name(cfg.name)
            dest = dest_root / f"{stem}.safetensors"
            n = 2
            while dest.exists():
                dest = dest_root / f"{stem} ({n}).safetensors"
                n += 1
            shutil.move(str(self._output_file), str(dest))
            lora_obj = lo.Lora(dest, dest_root, keywords=cfg.trigger, weight=self.weight.value(), negative=cfg.negative,
                               template=cfg.template)
            lo.save(lora_obj)
        except (OSError, lo.LoraError) as exc:
            self.status_label.setText(tr("lt.save_failed", msg=str(exc), path=str(self._output_file)))
            return
        self._trained_path = dest
        self.status_label.setText(tr("lt.done", name=dest.stem))
