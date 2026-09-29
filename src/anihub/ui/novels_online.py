"""Light novels from websites: the "Online" tab (source, language filter, search, details) and the hub that puts it next to the shelf."""
from __future__ import annotations

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QComboBox, QDialog, QHBoxLayout, QLabel, QLineEdit, QPushButton, QTabWidget, QTextEdit, QVBoxLayout, QWidget,
)

from anihub.context import AppContext
from anihub.core import agemode
from anihub.core.i18n import tr
from anihub.sources.novels.base import NovelChapter, NovelEntry, NovelSource
from anihub.ui import style
from anihub.ui.extensions_dialog import ExtensionsDialog
from anihub.ui.grid import ThumbGrid, image_to_thumb
from anihub.ui.lang_filter import LangFilter, lang_name
from anihub.ui.novels_page import NovelsPage, placeholder_cover
from anihub.ui.workers import run_async, run_status


def blocked_by_filter(ctx: AppContext, entry: NovelEntry) -> bool:
    """The title's own genres/tags hit the age mode's or the user's hidden tags."""
    return ctx.blocker.blocked_in(entry.tags)


class NovelDialog(QDialog):
    """One online title: description, and the ways to read it."""

    def __init__(self, ctx: AppContext, source: NovelSource, entry: NovelEntry, parent=None):
        super().__init__(parent)
        self.ctx, self.source, self.entry = ctx, source, entry
        self.chapters: list[NovelChapter] = []
        self.novel_id: int | None = None                 # set when the user chooses to read: the shelf row to open
        self.setWindowTitle(entry.title)
        self.resize(640, 560)
        self.title = QLabel(entry.title)
        self.title.setStyleSheet("font-size: 18px; font-weight: 600;")
        self.title.setWordWrap(True)
        self.meta = style.role(QLabel(), "dim")
        self.meta.setWordWrap(True)
        self.text = QTextEdit(readOnly=True)
        self.message = style.role(QLabel(tr("status.loading")), "dim")
        self.message.setWordWrap(True)
        self.read_btn = style.primary(QPushButton(tr("novels.online.read")), "book")
        self.shelf_btn = style.secondary(QPushButton(tr("novels.online.to_shelf")), "plus")
        self.site_btn = style.ghost(QPushButton(tr("watch.site")), "external")
        for b in (self.read_btn, self.shelf_btn):
            b.setEnabled(False)
        row = QHBoxLayout()
        for w in (self.read_btn, self.shelf_btn, self.site_btn):
            row.addWidget(w)
        row.addStretch(1)
        layout = QVBoxLayout(self)
        layout.addWidget(self.title)
        layout.addWidget(self.meta)
        layout.addWidget(self.text, 1)
        layout.addWidget(self.message)
        layout.addLayout(row)
        self.read_btn.clicked.connect(lambda: self._to_shelf(read=True))
        self.shelf_btn.clicked.connect(lambda: self._to_shelf(read=False))
        self.site_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(entry.url)))
        self.site_btn.setVisible(entry.url.startswith("http"))
        self._show_meta()
        self._load()

    def _show_meta(self) -> None:
        e = self.entry
        parts = [e.author, f"{e.age}+" if e.age else "", ", ".join(e.tags[:8])]
        self.meta.setText(" · ".join(p for p in parts if p))
        self.text.setPlainText(e.description)

    def _load(self) -> None:
        def work():
            entry = self.source.details(self.entry)
            return entry, self.source.chapters(entry)

        def done(result) -> None:
            self.entry, self.chapters = result
            self._show_meta()
            if not agemode.age_ok(self.ctx.cfg, self.entry.age):
                self.message.setText(tr("novels.online.age"))
            elif blocked_by_filter(self.ctx, self.entry):
                self.message.setText(tr("novels.online.filtered"))
            elif not self.chapters:
                self.message.setText(tr("novels.online.no_chapters"))
            else:
                self.message.setText(tr("novels.chapters_n", n=len(self.chapters)))
                self.read_btn.setEnabled(True)
                self.shelf_btn.setEnabled(True)

        run_status(work, on_done=done, status=self.message)

    def _to_shelf(self, read: bool) -> None:
        self.read_btn.setEnabled(False)
        self.shelf_btn.setEnabled(False)
        self.message.setText(tr("status.loading"))
        entry, chapters = self.entry, self.chapters

        def work() -> int:
            cover = None
            if entry.cover:
                try:
                    cover = self.ctx.media.get(entry.cover).read_bytes()
                except Exception:  # noqa: BLE001 - a book without a cover is fine
                    cover = None
            return self.ctx.novels.add_online(self.source.name, entry, chapters, cover)

        def done(novel_id: int) -> None:
            self.novel_id = novel_id
            if read:
                self.accept()
            else:
                self.message.setText(tr("novels.online.added"))
                self.shelf_btn.setVisible(False)
                self.read_btn.setEnabled(True)
                self.changed = True

        run_status(work, on_done=done, status=self.message)


class OnlineNovelsTab(QWidget):
    shelf_changed = Signal()
    open_requested = Signal(int)                         # a shelf row to read

    def __init__(self, ctx: AppContext, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self._gen, self._page, self._loading, self._exhausted, self._loaded_once = 0, 1, False, True, False
        self.source_box = QComboBox()
        self.lang_filter = LangFilter(ctx.cfg, "novels.langs")
        self.query = QLineEdit(placeholderText=tr("novels.online.search"))
        self.query.setClearButtonEnabled(True)
        self.go = style.primary(QPushButton(tr("search.button")), "search")
        self.ext_btn = style.secondary(QPushButton(tr("ext.button")), "layers")
        self.grid = ThumbGrid(ctx.cfg.get("ui.thumb_size", 180) + 20)
        self.status = style.role(QLabel(), "dim")
        top = QHBoxLayout()
        for w, s in ((self.source_box, 0), (self.lang_filter, 0), (self.query, 1), (self.go, 0), (self.ext_btn, 0)):
            top.addWidget(w, s)
        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(self.grid, 1)
        layout.addWidget(self.status)
        self.reload_sources()
        self.source_box.activated.connect(lambda _i: (self.ctx.cfg.set("novels.last_source", self.source_box.currentData()), self.search()))
        self.lang_filter.changed.connect(lambda: (self.reload_sources(), self.search()))
        self.go.clicked.connect(self.search)
        self.query.returnPressed.connect(self.search)
        self.ext_btn.clicked.connect(self._extensions)
        self.grid.need_more.connect(self._load_page)
        self.grid.itemDoubleClicked.connect(lambda it: self.open_entry(it.data(Qt.ItemDataRole.UserRole)))

    # --- sources / search --------------------------------------------------------------------------------------

    def reload_sources(self) -> None:
        adult = "explicit" in self.ctx.allowed_ratings()
        sources = {n: s for n, s in self.ctx.novel_sources.items() if adult or not s.nsfw}
        self.lang_filter.set_languages({s.lang for s in sources.values()})
        current = self.source_box.currentData() or self.ctx.cfg.get("novels.last_source")
        self.source_box.clear()
        for name, source in sources.items():
            if self.lang_filter.accepts(source.lang):
                self.source_box.addItem(source.title if source.lang == "multi" else f"{source.title} · {lang_name(source.lang)}", name)
        if current is not None:
            self.source_box.setCurrentIndex(max(self.source_box.findData(current), 0))

    def source(self) -> NovelSource | None:
        return self.ctx.novel_sources.get(self.source_box.currentData())

    def ensure_loaded(self) -> None:
        if not self._loaded_once:
            self.search()

    def _extensions(self) -> None:
        dlg = ExtensionsDialog(self.ctx, self.ctx.extensions, ("novel",), lambda: self.ctx.novel_sources, self)
        dlg.exec()
        if dlg.changed:
            self.reload_sources()

    def search(self) -> None:
        if self.source() is None:
            self.status.setText(tr("novels.online.no_sources"))
            return
        self._loaded_once = True
        self._gen += 1
        self.grid.clear_items()
        self._page, self._loading, self._exhausted = 1, False, False
        self._load_page()

    def _load_page(self) -> None:
        source = self.source()
        if self._loading or self._exhausted or source is None:
            return
        self._loading = True
        self.status.setText(tr("status.loading"))
        gen, page, text = self._gen, self._page, self.query.text().strip()

        def done(result) -> None:
            if gen != self._gen:
                return
            entries, more = result
            self._loading, self._exhausted = False, not more
            self._page += 1
            shown = [e for e in entries if agemode.age_ok(self.ctx.cfg, e.age)]
            for entry in shown:
                self._add(entry)
            hidden = len(entries) - len(shown)
            self.status.setText(tr("status.count", n=self.grid.count()) + (f"  ·  {tr('novels.online.hidden', n=hidden)}" if hidden else "")
                                + ("" if more else "  ·  " + tr("status.end")))
            if more:
                self.grid.request_fill()

        def failed(exc: Exception) -> None:
            if gen == self._gen:
                self._loading, self._exhausted = False, True
                self.status.setText(tr("status.error", msg=str(exc)))

        run_async(lambda: source.search(text, page), on_done=done, on_error=failed)

    def _add(self, entry: NovelEntry) -> None:
        size = self.grid.thumb_size

        def load():
            try:
                if entry.cover.startswith("http"):
                    return image_to_thumb(self.ctx.media.get(entry.cover).read_bytes(), size, f"{entry.age}+" if entry.age else "")
            except Exception:  # noqa: BLE001 - a missing cover is not an error
                pass
            return placeholder_cover(entry.title, size)

        self.grid.add_entry(entry, entry.title, load)

    def open_entry(self, entry: NovelEntry) -> None:
        source = self.source()
        if source is None:
            return
        dlg = NovelDialog(self.ctx, source, entry, self)
        result = dlg.exec()
        if getattr(dlg, "changed", False) or dlg.novel_id is not None:
            self.shelf_changed.emit()
        if result and dlg.novel_id is not None:
            self.open_requested.emit(dlg.novel_id)


class NovelsHub(QTabWidget):
    """The Light novels section: the local shelf and the online sources side by side."""

    def __init__(self, ctx: AppContext, parent=None):
        super().__init__(parent)
        self.shelf = NovelsPage(ctx)
        self.online = OnlineNovelsTab(ctx)
        self.addTab(self.shelf, tr("novels.tab.shelf"))
        self.addTab(self.online, tr("novels.tab.online"))
        self.online.shelf_changed.connect(self.shelf.reload)
        self.online.open_requested.connect(lambda novel_id: (self.shelf.reload(), self.shelf.open_book({"id": novel_id})))
        self.currentChanged.connect(lambda i: self.online.ensure_loaded() if i == 1 else None)
