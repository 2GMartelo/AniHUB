from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout, QGroupBox, QKeySequenceEdit, QProgressBar,
    QTableWidget, QTableWidgetItem, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QMessageBox, QPlainTextEdit, QScrollArea, QSpinBox, QTabWidget, QToolButton, QVBoxLayout, QWidget,
)

from anihub.context import AppContext
from anihub.core import agemode, keymap
from anihub.core.i18n import LANGUAGES, tr
from anihub.services.autotag import download_model
from anihub.services.backends import gpu_list
from anihub.ui.workers import run_async
from anihub.ui import cookie_import, style
from anihub.ui.about_box import AboutBox
from anihub.ui.backup_box import BackupBox
from anihub.ui import smoothscroll
from anihub.ui import theme as theme_module
from anihub.ui.color_button import ColorButton
from anihub.ui.theme import apply_theme, glass_supported


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
        for code, name in LANGUAGES.items():
            self.lang.addItem(name, code)
        self.lang.setCurrentIndex(self.lang.findData(cfg.get("language")))
        self.theme = QComboBox()
        for key in ("system", "light", "dark", "custom"):
            self.theme.addItem(tr(f"settings.theme.{key}"), key)
        self.theme.setCurrentIndex(self.theme.findData(cfg.get("theme")))
        # the custom theme: four colours, the rest is derived and kept readable
        theme_module.set_custom_colors(cfg.get("theme_custom"))
        self.custom_buttons: dict[str, ColorButton] = {}
        self.custom_row = QWidget()
        custom_layout = QHBoxLayout(self.custom_row)
        custom_layout.setContentsMargins(0, 0, 0, 0)
        for key in ("bg", "panel", "text", "accent"):
            button = ColorButton(tr(f"settings.custom.{key}"), theme_module.custom_colors()[key])
            button.changed.connect(self._custom_changed)
            self.custom_buttons[key] = button
            custom_layout.addWidget(button)
        self.custom_reset = style.ghost(QPushButton(tr("settings.custom.reset")), "refresh")
        self.custom_reset.clicked.connect(self._custom_reset)
        custom_layout.addWidget(self.custom_reset)
        custom_layout.addStretch(1)
        self.theme.currentIndexChanged.connect(self._theme_changed)
        self.custom_row.setVisible(self.theme.currentData() == "custom")
        self.smooth = QCheckBox(tr("settings.smooth"))
        self.smooth.setChecked(bool(cfg.get("ui.smooth_scroll", True)))
        self.smooth.toggled.connect(smoothscroll.set_enabled)
        self.close_action = QComboBox()
        for key in ("", "tray", "quit"):
            self.close_action.addItem(tr(f"settings.close.{key or 'ask'}"), key)
        self.close_action.setCurrentIndex(max(self.close_action.findData(str(cfg.get("ui.close_action", "") or "")), 0))
        self.glass = QCheckBox(tr("settings.glass"))
        self.glass.setChecked(bool(cfg.get("ui.glass", True)) and glass_supported())
        self.glass.setEnabled(glass_supported())
        self.glass.setToolTip(tr("settings.glass.tip"))

        self.library = QLineEdit(cfg.get("library_path"), readOnly=True)
        open_btn = QPushButton(tr("settings.open_folder"))
        open_btn.clicked.connect(lambda: os.startfile(cfg.get("library_path")))
        library_row = QHBoxLayout()
        library_row.addWidget(self.library, 1)
        library_row.addWidget(open_btn)

        self.folder_fields: dict[str, QLineEdit] = {}
        folder_defaults = {"generations": str(ctx.paths.sd / "generated"), "vtube": str(ctx.paths.root / "vtube"),
                           "music": str(ctx.paths.root / "music")}
        folder_labels = {"generations": tr("settings.folder_generations"), "vtube": tr("settings.folder_vtube"),
                         "music": tr("settings.folder_music")}
        folder_rows = []
        for key in ("generations", "vtube", "music"):
            edit = QLineEdit(str(cfg.get(f"paths.{key}", "") or ""))
            edit.setPlaceholderText(folder_defaults[key])
            browse_btn = style.secondary(QPushButton(tr("settings.browse")), "folder")
            browse_btn.clicked.connect(lambda _=False, e=edit: self._pick_folder(e))
            reset_btn = style.ghost(QToolButton(), "refresh")
            reset_btn.setToolTip(tr("settings.hotkey_reset"))
            reset_btn.clicked.connect(lambda _=False, e=edit: e.clear())
            row_widget = QWidget()
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.addWidget(edit, 1)
            row_layout.addWidget(browse_btn)
            row_layout.addWidget(reset_btn)
            self.folder_fields[key] = edit
            folder_rows.append((folder_labels[key], row_widget))

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

        # training your own LoRA (services/lora_train.py): off by default, needs a separate sd-scripts install
        self.train_enabled = QCheckBox(tr("train.enable"), checked=bool(cfg.get("lora_train.enabled", False)))
        self.train_enabled.toggled.connect(self._on_train_toggled)
        self.train_path = QLineEdit(str(cfg.get("lora_train.sd_scripts_path") or ""))
        browse_train = QPushButton(tr("wizard.browse"))
        browse_train.clicked.connect(self._pick_train_path)
        train_row = QHBoxLayout()
        train_row.addWidget(self.train_path, 1)
        train_row.addWidget(browse_train)
        train_hint = style.role(QLabel(tr("train.hint")), "dim")
        train_hint.setWordWrap(True)
        self.train_status = style.role(QLabel(), "dim")
        self.train_status.setWordWrap(True)
        self.train_check_btn = style.secondary(QPushButton(tr("train.check")), "refresh")
        self.train_check_btn.clicked.connect(self._recheck_train)
        self.train_download_btn = style.secondary(QPushButton(tr("train.install")), "download")
        self.train_download_btn.clicked.connect(self._download_train_scripts)
        train_btn_row = QHBoxLayout()
        train_btn_row.addWidget(self.train_check_btn)
        train_btn_row.addWidget(self.train_download_btn)
        train_form = QFormLayout()
        train_form.addRow("", self.train_enabled)
        train_form.addRow(train_hint)
        train_form.addRow(tr("train.path"), train_row)
        train_form.addRow(train_btn_row)
        train_form.addRow(self.train_status)
        self.train_box = QGroupBox(tr("train.group"))
        self.train_box.setLayout(train_form)

        # ComfyUI (video/sound/2D-VTube, ТЗ_rasshirenie_prilozheniya.md): its own local service, same shape as Forge
        self.comfyui_path = QLineEdit(str(cfg.get("comfyui.path") or ""))
        browse_comfyui = QPushButton(tr("wizard.browse"))
        browse_comfyui.clicked.connect(self._pick_comfyui)
        comfyui_row = QHBoxLayout()
        comfyui_row.addWidget(self.comfyui_path, 1)
        comfyui_row.addWidget(browse_comfyui)
        self.comfyui_download_btn = style.secondary(QPushButton(tr("comfyui.download.button")), "download")
        self.comfyui_download_btn.clicked.connect(self._download_comfyui)
        self.comfyui_port = QSpinBox(minimum=1024, maximum=65535, value=int(cfg.get("comfyui.port", 8188)))
        self.comfyui_idle = QSpinBox(minimum=0, maximum=1440, value=int(cfg.get("comfyui.idle_minutes", 0) or 0))
        comfyui_form = QFormLayout()
        comfyui_form.addRow(tr("settings.comfyui_path"), comfyui_row)
        comfyui_form.addRow("", self.comfyui_download_btn)
        comfyui_form.addRow(tr("settings.comfyui_port"), self.comfyui_port)
        comfyui_form.addRow(tr("settings.forge_idle"), self.comfyui_idle)
        self.comfyui_box = QGroupBox("ComfyUI")
        self.comfyui_box.setLayout(comfyui_form)

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
        self.tag_pause_btn = QPushButton(tr("settings.autotag_pause"))
        self.tag_pause_btn.hide()
        self.tag_bar = QProgressBar()
        self.tag_bar.hide()
        self._tag_paused = False
        self.tag_general = QDoubleSpinBox(minimum=0.05, maximum=0.95, singleStep=0.05, decimals=2,
                                          value=float(cfg.get("autotag.general_threshold", 0.35)))
        self.tag_char = QDoubleSpinBox(minimum=0.05, maximum=0.99, singleStep=0.05, decimals=2,
                                       value=float(cfg.get("autotag.character_threshold", 0.85)))
        tag_dl_row = QHBoxLayout()
        tag_dl_row.addWidget(self.tag_download)
        tag_dl_row.addWidget(self.tag_pause_btn)
        tag_dl_row.addStretch(1)
        tag = QFormLayout()
        tag.addRow("", self.tag_enabled)
        tag.addRow(tr("settings.autotag_model"), self.tag_status)
        tag.addRow("", tag_dl_row)
        tag.addRow("", self.tag_bar)
        tag.addRow(tr("settings.autotag_general"), self.tag_general)
        tag.addRow(tr("settings.autotag_character"), self.tag_char)
        tag_box = QGroupBox(tr("settings.autotag_group"))
        tag_box.setLayout(tag)
        self.tag_download.clicked.connect(self._download_model)
        self.tag_pause_btn.clicked.connect(self._toggle_tag_pause)
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

        self.hotkey_edits: dict[str, QKeySequenceEdit] = {}
        hotkey_rows = []
        for action in keymap.ACTIONS:
            edit = QKeySequenceEdit(QKeySequence(keymap.key_for(cfg, action.id)))
            reset_btn = style.ghost(QToolButton(), "refresh")
            reset_btn.setToolTip(tr("settings.hotkey_reset"))
            reset_btn.clicked.connect(lambda _=False, a=action, e=edit: e.setKeySequence(QKeySequence(a.default)))
            row_widget = QWidget()
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.addWidget(edit, 1)
            row_layout.addWidget(reset_btn)
            self.hotkey_edits[action.id] = edit
            hotkey_rows.append((tr(action.label_key), row_widget))

        look_box = form_box(tr("settings.g_appearance"), (tr("settings.language"), self.lang), (tr("settings.theme"), self.theme), ("", self.custom_row),
                            ("", self.glass), ("", self.smooth), (tr("settings.close"), self.close_action))
        storage_box = form_box(tr("settings.g_storage"), (tr("settings.library"), library_row),
                               (tr("settings.cache_limit"), self.cache_limit))
        folders_box = form_box(tr("settings.folders_title"), *folder_rows)
        age_box = form_box(tr("age.title"), (tr("age.mode"), self.age_mode), (tr("age.locked"), self.locked_tags),
                           (tr("age.custom"), self.custom_tags))
        network_box = form_box(tr("settings.g_network"), (tr("settings.proxy"), self.proxy),
                               (tr("settings.interval"), self.interval), (tr("settings.parallel"), self.parallel))
        hotkeys_box = form_box(tr("settings.hotkeys_title"), *hotkey_rows)

        self.discord_enabled = QCheckBox(tr("settings.discord_enabled"))
        self.discord_enabled.setChecked(bool(cfg.get("discord.enabled", False)))
        self.discord_client_id = QLineEdit(str(cfg.get("discord.client_id", "") or ""))
        self.discord_client_id.setPlaceholderText(tr("settings.discord_client_id_hint"))
        discord_box = form_box(tr("settings.discord_title"), ("", self.discord_enabled),
                               (tr("settings.discord_client_id"), self.discord_client_id))

        creds = QFormLayout()
        creds.setHorizontalSpacing(18)
        creds.setVerticalSpacing(11)
        creds.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        for src in ctx.sources.values():
            for key, label in src.credentials:
                creds.addRow(f"{src.title}: {label}", self.cred_fields[f"sources.{src.name}.{key}"])
            help_text = tr(f"cred.{src.name}.help")
            if help_text != f"cred.{src.name}.help":                # a source may explain where its credential comes from
                hint = style.role(QLabel(help_text), "dim")
                hint.setWordWrap(True)
                creds.addRow("", hint)
        self.import_btn = import_btn = style.secondary(QPushButton(tr("cookies.import")), "upload")
        import_btn.clicked.connect(lambda: cookie_import.pick_and_import(ctx, self))
        forget_btn = style.ghost(QPushButton(tr("cookies.clear")), "trash")
        forget_btn.clicked.connect(lambda: cfg.set("cookie.jar", {}))
        import_hint = style.role(QLabel(tr("cookies.hint")), "dim")
        import_hint.setWordWrap(True)
        import_row = QHBoxLayout()
        import_row.addWidget(import_btn)
        import_row.addWidget(forget_btn)
        import_row.addStretch(1)
        creds.addRow(import_row)
        creds.addRow(import_hint)
        creds_box = QGroupBox(tr("settings.creds"))
        creds_box.setLayout(creds)
        for group in (forge_box, manga_box, gen_box, self.train_box, self.comfyui_box, lib_box, tag_box):
            lay = group.layout()
            if isinstance(lay, QFormLayout):
                lay.setHorizontalSpacing(18)
                lay.setVerticalSpacing(11)
                lay.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        self.save_btn = style.primary(QPushButton(tr("settings.save")), "check")
        self.save_btn.setMinimumWidth(150)
        self.save_btn.clicked.connect(self._save)
        self.note = style.role(QLabel(), "dim")

        self.sd_box = self._build_sd_box()

        # Categorised into tabs (was one long scroll of a dozen-plus group boxes -- hard to find anything in).
        gen_boxes = [self.sd_box]
        if ctx.sd_enabled:
            gen_boxes += [forge_box, gen_box, self.train_box, self.comfyui_box]  # hidden together when the PC cannot run Forge
        categories = [
            (tr("settings.cat_appearance"), [look_box]),
            (tr("settings.cat_hotkeys"), [hotkeys_box]),
            (tr("settings.cat_library"), [storage_box, folders_box, lib_box, tag_box]),
            (tr("age.title"), [age_box]),
            (tr("settings.cat_network"), [network_box, creds_box]),
            (tr("nav.manga"), [manga_box]),
            (tr("settings.cat_generation"), gen_boxes),
            (tr("settings.cat_system"), [self.backup, discord_box, self.about]),
        ]
        self.tabs = QTabWidget()
        for title, boxes in categories:
            self.tabs.addTab(self._tab_page(boxes), title)

        footer = QHBoxLayout()
        footer.addWidget(self.note, 1)
        footer.addWidget(self.save_btn)
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.addWidget(style.role(QLabel(tr("nav.settings")), "title"))
        layout.addWidget(self.tabs, 1)
        layout.addLayout(footer)

    def _tab_page(self, boxes: list[QGroupBox]) -> QScrollArea:
        """One category tab: its boxes stacked in a scrollable column, same look every tab had before categorising."""
        content = QWidget()
        content.setMaximumWidth(940)
        cl = QVBoxLayout(content)
        cl.setContentsMargins(0, 8, 8, 12)
        cl.setSpacing(6)
        for box in boxes:
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
        return scroll

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
        self._tag_paused = False
        self.tag_download.setEnabled(False)
        self.tag_pause_btn.setText(tr("settings.autotag_pause"))
        self.tag_pause_btn.show()
        self.tag_bar.show()
        self.tag_bar.setRange(0, 0)
        ctx = self.ctx

        def work() -> None:
            download_model(ctx.http, ctx.autotagger.model_dir,
                           progress=lambda name, done, total: self._tag_progress.emit(name, done, total),
                           paused=lambda: self._tag_paused)

        def done(_) -> None:
            self.tag_pause_btn.hide()
            if ctx.autotagger.available:
                self.tag_bar.hide()
                ctx.refresh_tagger()
            else:                                                   # stopped mid-way: a later click resumes it
                self.tag_download.setText(tr("settings.autotag_resume"))
                self.tag_download.setEnabled(True)
            self._refresh_tag_status()

        def failed(exc: Exception) -> None:
            self.tag_bar.hide()
            self.tag_pause_btn.hide()
            self.tag_download.setEnabled(True)
            self.tag_status.setText(tr("status.error", msg=str(exc)))

        run_async(work, on_done=done, on_error=failed)

    def _toggle_tag_pause(self) -> None:
        self._tag_paused = not self._tag_paused
        self.tag_pause_btn.setText(tr("settings.autotag_resume") if self._tag_paused else tr("settings.autotag_pause"))

    def _on_tag_progress(self, name: str, done: int, total: int) -> None:
        self.tag_bar.setRange(0, max(total, 1))
        self.tag_bar.setValue(done)

    def _custom_values(self) -> dict:
        return {key: button.color for key, button in self.custom_buttons.items()}

    def _theme_changed(self) -> None:
        """Picking a theme shows it at once; it stays only if the settings are saved (see hideEvent)."""
        self.custom_row.setVisible(self.theme.currentData() == "custom")
        theme_module.set_custom_colors(self._custom_values())
        apply_theme(QApplication.instance(), self.theme.currentData())

    def revert_preview(self) -> None:
        """Back to the saved theme: the pick was not saved. The controls follow, so they always show what is really applied."""
        cfg = self.ctx.cfg
        saved = cfg.get("theme")
        colors = {**theme_module.DEFAULT_CUSTOM, **(cfg.get("theme_custom") or {})}
        pending = (self.theme.currentData() != saved) or self._custom_values() != {
            k: theme_module._norm_hex(colors.get(k), v) for k, v in theme_module.DEFAULT_CUSTOM.items()}
        if not pending:
            return
        self.theme.blockSignals(True)
        self.theme.setCurrentIndex(max(self.theme.findData(saved), 0))
        self.theme.blockSignals(False)
        theme_module.set_custom_colors(colors)
        for key, button in self.custom_buttons.items():
            button.set_color(theme_module.custom_colors()[key])
        self.custom_row.setVisible(saved == "custom")
        apply_theme(QApplication.instance(), saved)

    def hideEvent(self, event) -> None:  # noqa: N802 - leaving the page (another section, minimised window) drops an unsaved pick
        super().hideEvent(event)
        self.revert_preview()

    def _custom_changed(self, _color: str = "") -> None:
        """A colour was picked: show the result at once when the custom theme is the chosen one."""
        theme_module.set_custom_colors(self._custom_values())
        if self.theme.currentData() == "custom":
            apply_theme(QApplication.instance(), "custom")

    def _custom_reset(self) -> None:
        for key, value in theme_module.DEFAULT_CUSTOM.items():
            self.custom_buttons[key].set_color(value)
        self._custom_changed()

    def _pick_folder(self, edit: QLineEdit) -> None:
        start = edit.text().strip() or str(self.ctx.paths.root)
        path = QFileDialog.getExistingDirectory(self, tr("settings.browse"), start)
        if path:
            edit.setText(path)

    def _show_locked(self) -> None:
        tags = agemode.locked_tags(self.age_mode.currentData())
        self.locked_tags.setPlainText(", ".join(tags) if tags else tr("age.locked.none"))

    def _confirm_adult(self) -> bool:
        return QMessageBox.question(self, "AniHUB", tr("age.confirm18")) == QMessageBox.StandardButton.Yes

    # --- Stable Diffusion availability ---------------------------------------------------------------------

    def _build_sd_box(self) -> QGroupBox:
        self.sd_status = style.role(QLabel(), "dim")
        self.sd_status.setWordWrap(True)
        self.sd_check_btn = style.secondary(QPushButton(tr("sd.check.button")), "refresh")
        self.sd_download_btn = style.secondary(QPushButton(tr("sd.download.button")), "download")
        self.sd_check_btn.clicked.connect(self._recheck_pc)
        self.sd_download_btn.clicked.connect(self._download_forge)
        self._show_sd_state()
        row = QHBoxLayout()
        row.addWidget(self.sd_check_btn)
        row.addWidget(self.sd_download_btn)
        row.addStretch(1)
        layout = QVBoxLayout()
        layout.addWidget(self.sd_status)
        layout.addLayout(row)
        box = QGroupBox(tr("sd.check.title"))
        box.setLayout(layout)
        return box

    def _show_sd_state(self, detail: str = "") -> None:
        base = tr("sd.check.enabled") if self.ctx.cfg.get("sd.enabled", True) is not False else tr("sd.check.disabled")
        self.sd_status.setText(base + ("\n" + detail if detail else ""))

    def _recheck_pc(self) -> None:
        """Measure the computer again (a new graphics card, more memory): switches the generation section on or off."""
        from anihub.services import sysreq

        self.sd_check_btn.setEnabled(False)
        self.sd_status.setText(tr("status.loading"))

        def done(a) -> None:
            self.sd_check_btn.setEnabled(True)
            was = self.ctx.cfg.get("sd.enabled", True) is not False
            self.ctx.cfg.set("sd.enabled", a.suitable)
            report = tr("sys.forge.gpu", d=a.gpu, gb=f"{a.vram_gb:.0f}") if a.gpu else tr("sys.forge.no_gpu")
            report += f" · {tr('sys.forge.ram', gb=f'{a.ram_gb:.0f}')} · {tr('sys.forge.disk', gb=f'{a.disk_gb:.0f}')}"
            if a.problems:
                report += "\n" + "\n".join("• " + tr(p) for p in a.problems)
            if was != a.suitable:
                report += "\n" + tr("sd.check.restart")
            self._show_sd_state(report)

        run_async(sysreq.assess_forge, on_done=done,
                  on_error=lambda exc: (self.sd_check_btn.setEnabled(True), self.sd_status.setText(tr("status.error", msg=str(exc)))))

    def _download_forge(self) -> None:
        from pathlib import Path

        from anihub.ui.forge_install_dialog import ForgeInstallDialog

        folder = QFileDialog.getExistingDirectory(self, tr("sd.download.button"), str(self.ctx.paths.apps))
        if not folder:
            return
        dlg = ForgeInstallDialog(self.ctx, Path(folder) / "Forge", self)
        dlg.exec()
        if dlg.installed is not None:
            self.forge_path.setText(str(dlg.installed))

    def _pick_forge(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, tr("settings.forge_path"), self.forge_path.text())
        if folder:
            self.forge_path.setText(os.path.normpath(folder))

    def _pick_comfyui(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, tr("settings.comfyui_path"), self.comfyui_path.text())
        if folder:
            self.comfyui_path.setText(os.path.normpath(folder))

    def _download_comfyui(self) -> None:
        from anihub.ui.comfyui_install_dialog import ComfyuiInstallDialog

        folder = QFileDialog.getExistingDirectory(self, tr("comfyui.download.button"), str(self.ctx.paths.apps))
        if not folder:
            return
        dlg = ComfyuiInstallDialog(self.ctx, Path(folder) / "ComfyUI", self)
        dlg.exec()
        if dlg.installed is not None:
            self.comfyui_path.setText(str(dlg.installed))

    def _pick_train_path(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, tr("train.path"), self.train_path.text())
        if folder:
            self.train_path.setText(os.path.normpath(folder))

    def _on_train_toggled(self, checked: bool) -> None:
        """The first time the box is ticked in this settings session, show the minimum requirements and the
        suitability verdict right away, same as the wizard already does for Forge -- instead of leaving the user to
        find the separate "Проверить" button before deciding whether to bother downloading sd-scripts at all."""
        if checked and not self.train_status.text():
            self._recheck_train()

    def _recheck_train(self) -> None:
        from anihub.services import lora_train, sysreq

        path = self.train_path.text().strip()
        problem = lora_train.check_install(Path(path)) if path else "err.train.no_folder"
        self.train_check_btn.setEnabled(False)
        self.train_status.setText(tr("status.loading"))

        def done(a) -> None:
            self.train_check_btn.setEnabled(True)
            report = tr("sys.forge.gpu", d=a.gpu, gb=f"{a.vram_gb:.0f}") if a.gpu else tr("sys.forge.no_gpu")
            report += f" · {tr('sys.forge.ram', gb=f'{a.ram_gb:.0f}')} · {tr('sys.forge.disk', gb=f'{a.disk_gb:.0f}')}"
            if problem:
                report += "\n• " + tr(problem)
            for p in a.problems:
                report += "\n• " + tr(p)
            self.train_status.setText(report)

        run_async(sysreq.assess_training, path, on_done=done,
                  on_error=lambda exc: (self.train_check_btn.setEnabled(True), self.train_status.setText(tr("status.error", msg=str(exc)))))

    def _download_train_scripts(self) -> None:
        from anihub.ui.lora_train_install_dialog import LoraTrainInstallDialog

        folder = QFileDialog.getExistingDirectory(self, tr("train.install"), str(self.ctx.paths.apps))
        if not folder:
            return
        dlg = LoraTrainInstallDialog(self.ctx, Path(folder) / "sd-scripts", self)
        dlg.exec()
        if dlg.installed is not None:
            self.train_path.setText(str(dlg.installed))

    def _save(self) -> None:
        cfg = self.ctx.cfg
        cfg.set("language", self.lang.currentData(), save=False)
        cfg.set("theme", self.theme.currentData(), save=False)
        cfg.set("ui.glass", self.glass.isChecked(), save=False)
        cfg.set("ui.smooth_scroll", self.smooth.isChecked(), save=False)
        cfg.set("theme_custom", self._custom_values(), save=False)
        theme_module.set_custom_colors(self._custom_values())
        cfg.set("ui.close_action", self.close_action.currentData(), save=False)
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
        if self.ctx.sd_enabled:
            # forge_box / gen_box / self.train_box are only ever parented into a layout when sd_enabled is True (see
            # __init__); with no parent, Qt is free to garbage-collect their C++ side, so reading these fields when
            # sd_enabled is False would hit an already-deleted QLineEdit instead of just being pointless.
            cfg.set("forge.path", self.forge_path.text().strip(), save=False)
            cfg.set("forge.port", self.forge_port.value(), save=False)
            cfg.set("forge.nowebui", self.forge_nowebui.isChecked(), save=False)
            cfg.set("forge.extra_args", self.forge_args.text().strip(), save=False)
            cfg.set("forge.idle_minutes", self.forge_idle.value(), save=False)
            cfg.set("forge.backends", self._backend_entries(), save=False)
            cfg.set("civitai.token", self.civitai_token.text().strip(), save=False)
            cfg.set("lora_train.enabled", self.train_enabled.isChecked(), save=False)
            cfg.set("lora_train.sd_scripts_path", self.train_path.text().strip(), save=False)
            cfg.set("comfyui.path", self.comfyui_path.text().strip(), save=False)
            cfg.set("comfyui.port", self.comfyui_port.value(), save=False)
            cfg.set("comfyui.idle_minutes", self.comfyui_idle.value(), save=False)
        cfg.set("library.near_dedup", self.near_mode.currentData(), save=False)
        cfg.set("library.trash_days", self.trash_days.value(), save=False)
        cfg.set("ui.confirm_trash", self.confirm_trash.isChecked(), save=False)
        cfg.set("autotag.enabled", self.tag_enabled.isChecked(), save=False)
        cfg.set("autotag.general_threshold", self.tag_general.value(), save=False)
        cfg.set("autotag.character_threshold", self.tag_char.value(), save=False)
        cfg.set("manga.port", self.manga_port.value(), save=False)
        cfg.set("manga.poll_minutes", self.manga_poll.value(), save=False)
        for action_id, edit in self.hotkey_edits.items():
            text = edit.keySequence().toString()
            cfg.set(f"hotkeys.{action_id}", "" if text == keymap.BY_ID[action_id].default else text, save=False)
        cfg.set("discord.enabled", self.discord_enabled.isChecked(), save=False)
        cfg.set("discord.client_id", self.discord_client_id.text().strip(), save=False)
        for key, edit in self.folder_fields.items():
            cfg.set(f"paths.{key}", edit.text().strip(), save=False)
        cfg.save()
        self.ctx.http.reconfigure()
        self.ctx.refresh_tagger()
        self.ctx.refresh_filter()
        self._refresh_tag_status()
        apply_theme(QApplication.instance(), cfg.get("theme"), glass=self.glass.isChecked())
        self.note.setText(tr("settings.saved"))
        self.saved.emit()
