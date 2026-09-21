"""CivitAI browser: search, pick a version, download into the right Forge folder (ТЗ 5.2)."""
from __future__ import annotations

import webbrowser
from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QIcon, QImage, QPixmap
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QProgressBar, QPushButton,
    QSplitter, QTextBrowser, QVBoxLayout, QWidget,
)

from anihub.context import AppContext
from anihub.core import agemode
from anihub.core.i18n import tr
from anihub.services import civitai
from anihub.ui.workers import run_async

BASES = ["", "SDXL", "Illustrious", "Pony", "SD 1.5", "Flux"]


class CivitaiView(QWidget):
    installed = Signal(str)          # model type of a freshly installed file (Forge lists should refresh)
    _progress = Signal(int, int)     # emitted from the download worker thread

    def __init__(self, ctx: AppContext, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self._models: list[civitai.CivitModel] = []
        self._next_url: str | None = None
        self._cancel = False
        self._downloading = False
        self._gen = 0

        self.link = QLineEdit(placeholderText=tr("civ.link"))
        self.open_link = QPushButton(tr("civ.open_link"))
        self.query = QLineEdit(placeholderText=tr("civ.query"))
        self.type = QComboBox()
        for t in civitai.TYPES:
            self.type.addItem(tr(f"civ.type.{t}"), t)
        self.sort = QComboBox()
        for s in civitai.SORTS:
            self.sort.addItem(tr(f"civ.sort.{s}"), s)
        self.base = QComboBox()
        for b in BASES:
            self.base.addItem(b or tr("civ.any_base"), b)
        mode = agemode.mode_of(ctx.cfg)
        self.nsfw = QCheckBox(tr("civ.nsfw_mode", mode=mode) if mode != "12" else tr("civ.nsfw"))
        self.nsfw.setEnabled(mode != "12")  # the same rule as everywhere: 16+ / 18+ models only in the 16+ / 18+ age mode
        self.nsfw.setChecked(mode != "12")
        if mode == "12":
            self.nsfw.setToolTip(tr("civ.nsfw_off"))
        self.search_btn = QPushButton(tr("search.button"))
        self.more_btn = QPushButton(tr("civ.more"))
        self.more_btn.setEnabled(False)
        self.list = QListWidget()
        self.list.setIconSize(QSize(72, 72))
        self.list.setMinimumWidth(320)

        self.title = QLabel(wordWrap=True)
        self.title.setStyleSheet("font-size: 16px; font-weight: bold;")
        self.meta = QLabel(wordWrap=True)
        self.description = QTextBrowser()
        self.description.setOpenLinks(False)
        self.version = QComboBox()
        self.file = QComboBox()
        self.words = QLabel(wordWrap=True)
        self.words.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.download_btn = QPushButton(tr("civ.download"))
        self.download_btn.setStyleSheet("font-weight: bold; padding: 8px;")
        self.download_btn.setEnabled(False)
        self.cancel_btn = QPushButton(tr("import.cancel"))
        self.cancel_btn.hide()
        self.page_btn = QPushButton(tr("civ.page"))
        self.page_btn.setEnabled(False)
        self.bar = QProgressBar()
        self.bar.hide()
        self.status = QLabel()
        self.status.setWordWrap(True)

        link_row = QHBoxLayout()
        link_row.addWidget(self.link, 1)
        link_row.addWidget(self.open_link)
        top = QHBoxLayout()
        for w, s in ((self.query, 1), (self.type, 0), (self.sort, 0), (self.base, 0), (self.nsfw, 0), (self.search_btn, 0)):
            top.addWidget(w, s)
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.addWidget(self.list, 1)
        ll.addWidget(self.more_btn)
        act = QHBoxLayout()
        act.addWidget(self.download_btn, 1)
        act.addWidget(self.cancel_btn)
        act.addWidget(self.page_btn)
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        for w in (self.title, self.meta, self.description):
            rl.addWidget(w)
        rl.addWidget(QLabel(tr("civ.version")))
        rl.addWidget(self.version)
        rl.addWidget(QLabel(tr("civ.file")))
        rl.addWidget(self.file)
        rl.addWidget(self.words)
        rl.addLayout(act)
        rl.addWidget(self.bar)
        split = QSplitter()
        split.addWidget(left)
        split.addWidget(right)
        split.setStretchFactor(1, 1)
        layout = QVBoxLayout(self)
        layout.addLayout(link_row)
        layout.addLayout(top)
        layout.addWidget(split, 1)
        layout.addWidget(self.status)

        self.search_btn.clicked.connect(self.search)
        self.query.returnPressed.connect(self.search)
        self.more_btn.clicked.connect(lambda: self.search(more=True))
        self.open_link.clicked.connect(self._open_link)
        self.link.returnPressed.connect(self._open_link)
        self.list.currentRowChanged.connect(self._select)
        self.version.currentIndexChanged.connect(self._version_changed)
        self.download_btn.clicked.connect(self._download)
        self.cancel_btn.clicked.connect(lambda: setattr(self, "_cancel", True))
        self.page_btn.clicked.connect(lambda: webbrowser.open(self._current().page_url) if self._current() else None)
        self.base.activated.connect(self._fill_list)
        self._progress.connect(lambda d, t: (self.bar.setRange(0, max(t, 1)), self.bar.setValue(d)))

    def _token(self) -> str:
        return str(self.ctx.cfg.get("civitai.token") or "")

    # --- search --------------------------------------------------------------------------------------------

    def search(self, more: bool = False) -> None:
        self.status.setText(tr("status.loading"))
        self.search_btn.setEnabled(False)
        gen = self._gen = self._gen + (0 if more else 1)
        next_url = self._next_url if more else None
        args = (self.ctx.http, self.query.text(), self.type.currentData(), self.sort.currentData(),
                self.nsfw.isChecked() and self.nsfw.isEnabled(), self._token(), next_url, 20, agemode.mode_of(self.ctx.cfg))

        def done(result) -> None:
            self.search_btn.setEnabled(True)
            if gen != self._gen:
                return
            models, self._next_url = result
            self._models = (self._models + models) if more else models
            self.more_btn.setEnabled(bool(self._next_url))
            self._fill_list()
            self.status.setText(tr("civ.found", n=len(self._models)))

        def failed(exc: Exception) -> None:
            self.search_btn.setEnabled(True)
            self.status.setText(tr("status.error", msg=str(exc)))

        run_async(civitai.search, *args, on_done=done, on_error=failed)

    def _visible_models(self) -> list[civitai.CivitModel]:
        base = self.base.currentData()
        if not base:
            return self._models
        return [m for m in self._models if any(base.lower() in v.base_model.lower() for v in m.versions)]

    def _fill_list(self) -> None:
        self.list.blockSignals(True)
        self.list.clear()
        for m in self._visible_models():
            bases = ", ".join(dict.fromkeys(v.base_model for v in m.versions[:3] if v.base_model))
            item = QListWidgetItem(f"{m.name}\n{m.creator} · ↓{m.downloads} · {bases}")
            item.setData(Qt.ItemDataRole.UserRole, m)
            self.list.addItem(item)
            self._load_preview(item, m)
        self.list.blockSignals(False)
        if self.list.count():
            self.list.setCurrentRow(0)
            self._select(0)
        else:
            self._select(-1)

    def _load_preview(self, item: QListWidgetItem, model: civitai.CivitModel) -> None:
        """Only the pictures CivitAI rates as fitting the age mode are fetched as previews; the rest stay blank."""
        images = model.versions[0].images if model.versions else []
        limit = civitai.IMAGE_LEVEL_LIMIT.get(agemode.mode_of(self.ctx.cfg), 1)
        url = next((i["url"] for i in images if int(i.get("nsfwLevel") or 1) <= limit and i.get("url")), None)
        if not url:
            return

        def fetch():
            img = QImage.fromData(self.ctx.http.get_bytes(url))
            return None if img.isNull() else img.scaled(72, 72, Qt.AspectRatioMode.KeepAspectRatio,
                                                        Qt.TransformationMode.SmoothTransformation)

        run_async(fetch, on_done=lambda img: img is not None and item.setIcon(QIcon(QPixmap.fromImage(img))))

    def _open_link(self) -> None:
        parsed = civitai.parse_model_url(self.link.text())
        if not parsed:
            self.status.setText(tr("civ.bad_link"))
            return
        model_id, version_id = parsed
        self.status.setText(tr("status.loading"))

        def done(model: civitai.CivitModel) -> None:
            self._gen += 1
            self._models, self._next_url = [model], None
            self.more_btn.setEnabled(False)
            self._fill_list()
            if version_id is not None:
                idx = next((i for i, v in enumerate(model.versions) if v.id == version_id), 0)
                self.version.setCurrentIndex(idx)
            self.status.clear()

        run_async(civitai.get_model, self.ctx.http, model_id, self._token(), on_done=done,
                  on_error=lambda exc: self.status.setText(tr("status.error", msg=str(exc))))

    # --- details -------------------------------------------------------------------------------------------

    def _current(self) -> civitai.CivitModel | None:
        item = self.list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _select(self, _row: int) -> None:
        model = self._current()
        self.version.blockSignals(True)
        self.version.clear()
        self.download_btn.setEnabled(False)
        self.page_btn.setEnabled(model is not None)
        if model is None:
            self.title.clear()
            self.meta.clear()
            self.description.clear()
            self.file.clear()
            self.words.clear()
            self.version.blockSignals(False)
            return
        self.title.setText(model.name)
        self.meta.setText(f"{tr(f'civ.type.{model.type}') if model.type in civitai.TYPES else model.type} · {model.creator} · "
                          f"↓{model.downloads} · ★{model.rating:.1f}" + (" · 18+" if model.nsfw else ""))
        self.description.setPlainText(model.description)
        for v in model.versions:
            self.version.addItem(f"{v.name}  ({v.base_model})", v)
        self.version.blockSignals(False)
        self._version_changed()

    def _version_changed(self) -> None:
        version = self.version.currentData()
        self.file.clear()
        self.words.clear()
        if version is None:
            return
        for f in version.files:
            if f.kind == "Model":
                self.file.addItem(f"{f.name}  ({f.size_kb / 1024:.1f} MB)" + (" ★" if f.primary else ""), f)
        best = civitai.pick_file(version)
        if best is not None:
            for i in range(self.file.count()):
                if self.file.itemData(i) is best:
                    self.file.setCurrentIndex(i)
        if version.trained_words:
            self.words.setText(tr("civ.words", words=", ".join(version.trained_words)))
        self.download_btn.setEnabled(self.file.count() > 0 and not self._downloading)

    # --- download --------------------------------------------------------------------------------------------

    def _forge_dir(self) -> Path | None:
        raw = self.ctx.cfg.get("forge.path")
        return Path(raw) if raw else None

    def _download(self) -> None:
        model, file = self._current(), self.file.currentData()
        forge_dir = self._forge_dir()
        if model is None or file is None:
            return
        if forge_dir is None or not forge_dir.exists():
            self.status.setText(tr("civ.no_forge"))
            return
        try:
            dest = civitai.target_dir(forge_dir, model.type)
        except civitai.CivitaiError as exc:
            self.status.setText(str(exc))
            return
        self._downloading, self._cancel = True, False
        self.download_btn.setEnabled(False)
        self.cancel_btn.show()
        self.bar.show()
        self.bar.setRange(0, 0)
        self.status.setText(tr("civ.downloading", name=file.name, folder=str(dest)))
        token = self._token()

        def work() -> tuple[Path, str]:
            path = civitai.download(self.ctx.http, file, dest, token, progress=lambda d, t: self._progress.emit(d, t),
                                    cancelled=lambda: self._cancel)
            kind = civitai.REFRESH_KIND.get(model.type)
            if kind:  # tell every running backend to rescan, so the file shows up without a restart
                for backend in self.ctx.backends:
                    if backend.state.ready:
                        try:
                            backend.api.refresh(kind)
                        except Exception:  # noqa: BLE001 - a backend that cannot refresh just needs a restart
                            pass
            return path, model.type

        def finish() -> None:
            self._downloading = False
            self.cancel_btn.hide()
            self.bar.hide()
            self._version_changed()

        def done(result) -> None:
            finish()
            path, mtype = result
            self.status.setText(tr("civ.installed", path=str(path)))
            self.installed.emit(mtype)

        def failed(exc: Exception) -> None:
            finish()
            self.status.setText(tr("civ.cancelled") if self._cancel else tr("status.error", msg=str(exc)))

        run_async(work, on_done=done, on_error=failed)
