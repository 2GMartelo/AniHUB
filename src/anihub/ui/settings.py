from __future__ import annotations

import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout, QGroupBox, QProgressBar, QTableWidget,
    QTableWidgetItem, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QMessageBox, QPlainTextEdit, QScrollArea, QSpinBox, QVBoxLayout, QWidget,
)

from anihub.context import AppContext
from anihub.core import agemode
from anihub.core.i18n import tr
from anihub.services.autotag import download_model
from anihub.services.backends import gpu_list
from anihub.ui.workers import run_async
from anihub.ui import style
from anihub.ui.about_box import AboutBox
from anihub.ui.backup_box import BackupBox
from anihub.ui.theme import apply_theme


class SettingsPage(QWidget):
    saved = Signal()
    _tag_progress = Signal(str, int, int)  # emitted from the download worker thread

    def __init__(self, ctx: AppContext, parent=None, quit_app=lambda: None):
        super().__init__(parent)
        self.ctx = ctx
        cfg = ctx.cfg
        self.about = AboutBox(ctx, quit_app)
        self.cache_limit = QDoubleSpinBox(minimum=0.1, maximum=500, decimals=1, singleStep=0.5, suffix=" GB",
                                          value=float(cfg.get("library.cache_limit_gb", 1) or 1))
        self.backup = BackupBox(ctx)

        self.lang = QComboBox()
        self.lang.addItem("Русский", "ru")
        self.lang.addItem("English", "en")
        self.lang.setCurrentIndex(self.lang.findData(cfg.get("language")))
        self.theme = QComboBox()
        for key in ("system", "light", "dark"):
            self.theme.addItem(tr(f"settings.theme.{key}"), key)
        self.theme.setCurrentIndex(self.theme.findData(cfg.get("theme")))

        self.library = QLineEdit(cfg.get("library_path"), readOnly=True)
        open_btn = QPushButton(tr("settings.open_folder"))
        open_btn.clicked.connect(lambda: os.startfile(cfg.get("library_path")))
        library_row = QHBoxLayout()
        library_row.addWidget(self.library, 1)
        library_row.addWidget(open_btn)

        self.age_mode = QComboBox()
        for mode in agemode.MODES:
            self.age_mode.addItem(tr(f"age.m{mode}"), mode)
        self.age_mode.setCurrentIndex(self.age_mode.findData(agemode.mode_of(cfg)))
        self.locked_tags = QPlainTextEdit(readOnly=True)               # follows the mode; the user cannot edit it
        self.locked_tags.setMaximumHeight(120)
        self.custom_tags = QPlainTextEdit(" ".join(agemode.custom_tags(cfg)))
        self.custom_tags.setMaximumHeight(90)
        self.custom_tags.setPlaceholderText(tr("age.custom.hint"))
        self.age_mode.currentIndexChanged.connect(self._show_locked)
        self._show_locked()

        self.proxy = QLineEdit(cfg.get("network.proxy"))
        self.interval = QSpinBox(minimum=0, maximum=10000, singleStep=50, value=int(cfg.get("network.min_interval_ms")))
        self.parallel = QSpinBox(minimum=1, maximum=32, value=int(cfg.get("network.max_parallel")))

        # One field per credential a source declares: new sources appear here without touching this file.
        self.cred_fields: dict[str, QLineEdit] = {
            f"sources.{src.name}.{key}": QLineEdit(str(cfg.get(f"sources.{src.name}.{key}") or ""))
            for src in ctx.sources.values() for key, _ in src.credentials
        }

        self.forge_path = QLineEdit(str(cfg.get("forge.path") or ""))
        browse_forge = QPushButton(tr("wizard.browse"))
        browse_forge.clicked.connect(self._pick_forge)
        forge_row = QHBoxLayout()
        forge_row.addWidget(self.forge_path, 1)
        forge_row.addWidget(browse_forge)
        self.forge_port = QSpinBox(minimum=1024, maximum=65535, value=int(cfg.get("forge.port", 7860)))
        self.forge_nowebui = QCheckBox(tr("settings.forge_nowebui"), checked=bool(cfg.get("forge.nowebui")))
        self.forge_args = QLineEdit(str(cfg.get("forge.extra_args") or ""))
        self.forge_idle = QSpinBox(minimum=0, maximum=1440, value=int(cfg.get("forge.idle_minutes", 0) or 0))
        forge = QFormLayout()
        forge.addRow(tr("settings.forge_path"), forge_row)
        forge.addRow(tr("settings.forge_port"), self.forge_port)
        forge.addRow("", self.forge_nowebui)
        forge.addRow(tr("settings.forge_args"), self.forge_args)
        forge.addRow(tr("settings.forge_idle"), self.forge_idle)
        forge_box = QGroupBox("Stable Diffusion Forge")
        forge_box.setLayout(forge)

        # extra generation backends (multi-GPU)
        self.civitai_token = QLineEdit(str(cfg.get("civitai.token") or ""))
        self.civitai_token.setPlaceholderText(tr("settings.civitai_hint"))
        self.backend_table = QTableWidget(0, 4)
        self.backend_table.setHorizontalHeaderLabels([tr("settings.backend_on"), tr("settings.backend_name"),
                                                      tr("settings.backend_port"), tr("settings.backend_gpu")])
        self.backend_table.setMaximumHeight(140)
        self._gpus = gpu_list()
        for entry in cfg.get("forge.backends", []) or []:
            self._add_backend_row(entry)
        add_backend = QPushButton(tr("settings.backend_add"))
        remove_backend = QPushButton(tr("settings.backend_remove"))
        add_backend.clicked.connect(lambda: self._add_backend_row({"name": f"gpu{self.backend_table.rowCount() + 1}",
                                                                   "port": 7861 + self.backend_table.rowCount(), "gpu": None, "enabled": True}))
        remove_backend.clicked.connect(lambda: self.backend_table.removeRow(self.backend_table.currentRow()))
        backend_buttons = QHBoxLayout()
        backend_buttons.addWidget(add_backend)
        backend_buttons.addWidget(remove_backend)
        backend_buttons.addStretch(1)
        gen_form = QFormLayout()
        gen_form.addRow(QLabel(tr("settings.backends_hint")))
        gen_form.addRow(self.backend_table)
        gen_form.addRow(backend_buttons)
        gen_form.addRow(tr("settings.civitai_token"), self.civitai_token)
        gen_box = QGroupBox(tr("settings.gen_group"))
        gen_box.setLayout(gen_form)

        self.manga_port = QSpinBox(minimum=1024, maximum=65535, value=int(cfg.get("manga.port", 4567)))
        self.manga_poll = QSpinBox(minimum=1, maximum=1440, value=int(cfg.get("manga.poll_minutes", 30)))
        manga = QFormLayout()
        manga.addRow(tr("settings.manga_port"), self.manga_port)
        manga.addRow(tr("settings.manga_poll"), self.manga_poll)
        manga_box = QGroupBox(tr("nav.manga"))
        manga_box.setLayout(manga)

        # library: duplicates and trash
        self.near_mode = QComboBox()
        for key in ("warn", "skip", "off"):
            self.near_mode.addItem(tr(f"settings.near.{key}"), key)
        self.near_mode.setCurrentIndex(max(self.near_mode.findData(cfg.get("library.near_dedup", "warn")), 0))
        self.trash_days = QSpinBox(minimum=0, maximum=365, value=int(cfg.get("library.trash_days", 7) or 0))
        self.confirm_trash = QCheckBox(tr("settings.confirm_trash"), checked=bool(cfg.get("ui.confirm_trash", True)))
        lib = QFormLayout()
        lib.addRow(tr("settings.near_dedup"), self.near_mode)
        lib.addRow(tr("settings.trash_days"), self.trash_days)
        lib.addRow("", self.confirm_trash)
        lib_box = QGroupBox(tr("settings.library_group"))
        lib_box.setLayout(lib)

        # autotagger
        self.tag_enabled = QCheckBox(tr("settings.autotag_enable"), checked=bool(cfg.get("autotag.enabled")))
        self.tag_status = QLabel()
        self.tag_download = QPushButton(tr("settings.autotag_download"))
        self.tag_bar = QProgressBar()
        self.tag_bar.hide()
        self.tag_general = QDoubleSpinBox(minimum=0.05, maximum=0.95, singleStep=0.05, decimals=2,
                                          value=float(cfg.get("autotag.general_threshold", 0.35)))
        self.tag_char = QDoubleSpinBox(minimum=0.05, maximum=0.99, singleStep=0.05, decimals=2,
                                       value=float(cfg.get("autotag.character_threshold", 0.85)))
        tag = QFormLayout()
        tag.addRow("", self.tag_enabled)
        tag.addRow(tr("settings.autotag_model"), self.tag_status)
        tag.addRow("", self.tag_download)
        tag.addRow("", self.tag_bar)
        tag.addRow(tr("settings.autotag_general"), self.tag_general)
        tag.addRow(tr("settings.autotag_character"), self.tag_char)
        tag_box = QGroupBox(tr("settings.autotag_group"))
        tag_box.setLayout(tag)
        self.tag_download.clicked.connect(self._download_model)
        self._tag_progress.connect(self._on_tag_progress)
        self._refresh_tag_status()

        def form_box(title: str, *rows) -> QGroupBox:
            form = QFormLayout()
            form.setHorizontalSpacing(18)
            form.setVerticalSpacing(11)
            form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            for row in rows:
                form.addRow(*row)
            box = QGroupBox(title)
            box.setLayout(form)
            return box

        look_box = form_box(tr("settings.g_appearance"), (tr("settings.language"), self.lang), (tr("settings.theme"), self.theme))
        storage_box = form_box(tr("settings.g_storage"), (tr("settings.library"), library_row),
                               (tr("settings.cache_limit"), self.cache_limit))
        age_box = form_box(tr("age.title"), (tr("age.mode"), self.age_mode), (tr("age.locked"), self.locked_tags),
                           (tr("age.custom"), self.custom_tags))
        network_box = form_box(tr("settings.g_network"), (tr("settings.proxy"), self.proxy),
                               (tr("settings.interval"), self.interval), (tr("settings.parallel"), self.parallel))

        creds = QFormLayout()
        creds.setHorizontalSpacing(18)
        creds.setVerticalSpacing(11)
        creds.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        for src in ctx.sources.values():
            for key, label in src.credentials:
                creds.addRow(f"{src.title}: {label}", self.cred_fields[f"sources.{src.name}.{key}"])
        creds_box = QGroupBox(tr("settings.creds"))
        creds_box.setLayout(creds)
        for group in (forge_box, manga_box, gen_box, lib_box, tag_box):
            lay = group.layout()
            if isinstance(lay, QFormLayout):
                lay.setHorizontalSpacing(18)
                lay.setVerticalSpacing(11)
                lay.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        self.save_btn = style.primary(QPushButton(tr("settings.save")), "check")
        self.save_btn.setMinimumWidth(150)
        self.save_btn.clicked.connect(self._save)
        self.note = style.role(QLabel(), "dim")

        content = QWidget()
        content.setMaximumWidth(940)
        cl = QVBoxLayout(content)
        cl.setContentsMargins(0, 0, 8, 12)
        cl.setSpacing(6)
        for box in (look_box, age_box, storage_box, network_box, creds_box, forge_box, gen_box, manga_box, lib_box, tag_box, self.backup, self.about):
            cl.addWidget(box)
        cl.addStretch(1)
        holder = QWidget()
        hl = QHBoxLayout(holder)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.addWidget(content, 100)
        hl.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(holder)

        footer = QHBoxLayout()
        footer.addWidget(self.note, 1)
        footer.addWidget(self.save_btn)
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.addWidget(style.role(QLabel(tr("nav.settings")), "title"))
        layout.addWidget(scroll, 1)
        layout.addLayout(footer)

    def _add_backend_row(self, entry: dict) -> None:
        row = self.backend_table.rowCount()
        self.backend_table.insertRow(row)
        enabled = QCheckBox()
        enabled.setChecked(bool(entry.get("enabled", True)))
        port = QSpinBox(minimum=1024, maximum=65535, value=int(entry.get("port", 7861)))
        gpu = QComboBox()
        gpu.addItem(tr("queue.gpu_default"), None)
        for index, name, gb in self._gpus:
            gpu.addItem(f"GPU {index}: {name} ({gb:.0f} GB)", index)
        if entry.get("gpu") is not None and gpu.findData(entry["gpu"]) < 0:
            gpu.addItem(f"GPU {entry['gpu']}", entry["gpu"])
        gpu.setCurrentIndex(max(gpu.findData(entry.get("gpu")), 0))
        self.backend_table.setCellWidget(row, 0, enabled)
        self.backend_table.setItem(row, 1, QTableWidgetItem(str(entry.get("name", ""))))
        self.backend_table.setCellWidget(row, 2, port)
        self.backend_table.setCellWidget(row, 3, gpu)

    def _backend_entries(self) -> list[dict]:
        entries = []
        for row in range(self.backend_table.rowCount()):
            name = (self.backend_table.item(row, 1).text() if self.backend_table.item(row, 1) else "").strip()
            if name:
                entries.append({"name": name, "port": self.backend_table.cellWidget(row, 2).value(),
                                "gpu": self.backend_table.cellWidget(row, 3).currentData(),
                                "enabled": self.backend_table.cellWidget(row, 0).isChecked()})
        return entries

    def _refresh_tag_status(self) -> None:
        ready = self.ctx.autotagger.available
        self.tag_status.setText(tr("settings.autotag_ready") if ready else tr("settings.autotag_missing", mb=379))
        self.tag_download.setVisible(not ready)

    def _download_model(self) -> None:
        self.tag_download.setEnabled(False)
        self.tag_bar.show()
        self.tag_bar.setRange(0, 0)
        ctx = self.ctx

        def work() -> None:
            download_model(ctx.http, ctx.autotagger.model_dir,
                           progress=lambda name, done, total: self._tag_progress.emit(name, done, total))

        def done(_) -> None:
            self.tag_bar.hide()
            self.tag_download.setEnabled(True)
            ctx.refresh_tagger()
            self._refresh_tag_status()

        def failed(exc: Exception) -> None:
            self.tag_bar.hide()
            self.tag_download.setEnabled(True)
            self.tag_status.setText(tr("status.error", msg=str(exc)))

        run_async(work, on_done=done, on_error=failed)

    def _on_tag_progress(self, name: str, done: int, total: int) -> None:
        self.tag_bar.setRange(0, max(total, 1))
        self.tag_bar.setValue(done)

    def _show_locked(self) -> None:
        tags = agemode.locked_tags(self.age_mode.currentData())
        self.locked_tags.setPlainText(", ".join(tags) if tags else tr("age.locked.none"))

    def _confirm_adult(self) -> bool:
        return QMessageBox.question(self, "AniHUB", tr("age.confirm18")) == QMessageBox.StandardButton.Yes

    def _pick_forge(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, tr("settings.forge_path"), self.forge_path.text())
        if folder:
            self.forge_path.setText(os.path.normpath(folder))

    def _save(self) -> None:
        cfg = self.ctx.cfg
        cfg.set("language", self.lang.currentData(), save=False)
        cfg.set("theme", self.theme.currentData(), save=False)
        mode = self.age_mode.currentData()
        if mode == "18" and agemode.mode_of(cfg) != "18" and not self._confirm_adult():
            self.age_mode.setCurrentIndex(self.age_mode.findData(agemode.mode_of(cfg)))
            mode = agemode.mode_of(cfg)
        agemode.apply_mode(cfg, mode, save=False)
        cfg.set("filter.custom_tags", agemode.parse_tags(self.custom_tags.toPlainText()), save=False)
        cfg.set("network.proxy", self.proxy.text().strip(), save=False)
        cfg.set("network.min_interval_ms", self.interval.value(), save=False)
        cfg.set("network.max_parallel", self.parallel.value(), save=False)
        cfg.set("library.cache_limit_gb", self.cache_limit.value(), save=False)
        for key, field in self.cred_fields.items():
            cfg.set(key, field.text().strip(), save=False)
        cfg.set("forge.path", self.forge_path.text().strip(), save=False)
        cfg.set("forge.port", self.forge_port.value(), save=False)
        cfg.set("forge.nowebui", self.forge_nowebui.isChecked(), save=False)
        cfg.set("forge.extra_args", self.forge_args.text().strip(), save=False)
        cfg.set("forge.idle_minutes", self.forge_idle.value(), save=False)
        cfg.set("library.near_dedup", self.near_mode.currentData(), save=False)
        cfg.set("library.trash_days", self.trash_days.value(), save=False)
        cfg.set("ui.confirm_trash", self.confirm_trash.isChecked(), save=False)
        cfg.set("autotag.enabled", self.tag_enabled.isChecked(), save=False)
        cfg.set("autotag.general_threshold", self.tag_general.value(), save=False)
        cfg.set("autotag.character_threshold", self.tag_char.value(), save=False)
        cfg.set("civitai.token", self.civitai_token.text().strip(), save=False)
        cfg.set("forge.backends", self._backend_entries(), save=False)
        cfg.set("manga.port", self.manga_port.value(), save=False)
        cfg.set("manga.poll_minutes", self.manga_poll.value(), save=False)
        cfg.save()
        self.ctx.http.reconfigure()
        self.ctx.refresh_tagger()
        self.ctx.refresh_filter()
        self._refresh_tag_status()
        apply_theme(QApplication.instance(), cfg.get("theme"))
        self.note.setText(tr("settings.saved"))
        self.saved.emit()
