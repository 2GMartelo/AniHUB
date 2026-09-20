"""Title window: cover, description, chapter list, library / category / offline-download actions."""
from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QHBoxLayout, QLabel, QMenu, QPushButton, QTextBrowser, QTreeWidget,
    QTreeWidgetItem, QVBoxLayout, QWidget,
)

from anihub.context import AppContext
from anihub.core.i18n import tr
from anihub.ui.manga_controller import MangaController
from anihub.ui.manga_reader import Reader
from anihub.ui.workers import run_async

ID_ROLE = Qt.ItemDataRole.UserRole


def fmt_date(ms) -> str:
    try:
        value = int(ms)
    except (TypeError, ValueError):
        return ""
    return datetime.fromtimestamp(value / 1000).strftime("%Y-%m-%d") if value > 0 else ""


class MangaDetail(QWidget):
    changed = Signal()  # library membership, categories or read state changed

    def __init__(self, ctx: AppContext, ctrl: MangaController, manga_id: int, start_chapter: int | None = None, parent=None):
        super().__init__(parent, Qt.WindowType.Window)
        self._start_chapter = start_chapter  # open the reader here as soon as the chapters are loaded
        self.ctx, self.ctrl, self.api = ctx, ctrl, ctx.suwayomi.api
        self.manga_id = manga_id
        self.manga: dict = {}
        self.chapters: list[dict] = []  # newest first, as the source lists them
        self.categories: list[dict] = []
        self._readers: list[Reader] = []
        self._loading_cats = False
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.resize(1000, 720)
        self.setWindowTitle(tr("status.loading"))

        self.cover = QLabel(alignment=Qt.AlignmentFlag.AlignCenter)
        self.cover.setFixedSize(220, 320)
        self.cover.setObjectName("thumbHolder")
        self.library_btn = QPushButton()
        self.library_btn.setCheckable(True)
        self.category = QComboBox()
        self.refresh_btn = QPushButton(tr("manga.refresh"))
        self.read_btn = QPushButton(tr("manga.read"))
        self.read_btn.setStyleSheet("font-weight: bold; padding: 8px;")
        left = QVBoxLayout()
        for w in (self.cover, self.library_btn, self.category, self.refresh_btn, self.read_btn):
            left.addWidget(w)
        left.addStretch(1)

        self.title = QLabel(wordWrap=True)
        self.title.setStyleSheet("font-size: 18px; font-weight: bold;")
        self.meta = QLabel(wordWrap=True)
        self.description = QTextBrowser()
        self.description.setMaximumHeight(130)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["", tr("manga.chapter"), tr("manga.scanlator"), tr("manga.date")])
        self.tree.setRootIsDecorated(False)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.setColumnWidth(0, 60)
        self.tree.setColumnWidth(1, 430)
        self.tree.setColumnWidth(2, 150)
        self.status = QLabel()

        self.btn_read = QPushButton(tr("manga.mark_read"))
        self.btn_unread = QPushButton(tr("manga.mark_unread"))
        self.btn_dl = QPushButton(tr("manga.download"))
        self.btn_del = QPushButton(tr("manga.delete_download"))
        actions = QHBoxLayout()
        for b in (self.btn_read, self.btn_unread, self.btn_dl, self.btn_del):
            actions.addWidget(b)
        actions.addStretch(1)

        right = QVBoxLayout()
        for w in (self.title, self.meta, self.description):
            right.addWidget(w)
        right.addWidget(self.tree, 1)
        right.addLayout(actions)
        right.addWidget(self.status)
        root = QHBoxLayout(self)
        root.addLayout(left)
        root.addLayout(right, 1)

        self.library_btn.clicked.connect(self._toggle_library)
        self.category.activated.connect(self._category_chosen)
        self.refresh_btn.clicked.connect(lambda: self.load(refresh=True))
        self.read_btn.clicked.connect(self._continue)
        self.tree.itemDoubleClicked.connect(lambda item: self._open_reader(item.data(1, ID_ROLE)))
        self.tree.customContextMenuRequested.connect(self._menu)
        self.btn_read.clicked.connect(lambda: self._mark(True))
        self.btn_unread.clicked.connect(lambda: self._mark(False))
        self.btn_dl.clicked.connect(self._download)
        self.btn_del.clicked.connect(self._delete_downloads)
        self.dl_timer = QTimer(self)
        self.dl_timer.timeout.connect(self._poll_downloads)
        self.load()

    # --- loading -----------------------------------------------------------------------------------------

    def load(self, refresh: bool = False) -> None:
        self.status.setText(tr("status.loading"))
        mid = self.manga_id

        def work():
            manga = self.api.manga(mid)
            chapters = self.api.chapters(mid)
            if refresh or not manga["initialized"] or not chapters:
                manga, chapters = self.api.refresh_manga(mid)
                chapters = self.api.chapters(mid)
                manga = self.api.manga(mid)
            return manga, chapters, self.api.categories()

        def done(result) -> None:
            self.manga, self.chapters, self.categories = result
            self._show()
            self.status.clear()
            if self._start_chapter is not None:
                chapter, self._start_chapter = self._start_chapter, None
                self._open_reader(chapter)

        run_async(work, on_done=done, on_error=lambda exc: self.status.setText(tr("status.error", msg=str(exc))))

    def _show(self) -> None:
        m = self.manga
        self.setWindowTitle(m["title"])
        self.title.setText(m["title"])
        parts = [p for p in (m.get("author"), m.get("artist") if m.get("artist") != m.get("author") else None,
                             (m.get("status") or "").capitalize()) if p]
        self.meta.setText(" · ".join(parts) + ("\n" + ", ".join(m.get("genre") or []) if m.get("genre") else ""))
        self.description.setPlainText(m.get("description") or "")
        self._update_library_ui()
        self._fill_chapters()
        if self.cover.pixmap().isNull() and m.get("thumbnailUrl"):
            run_async(lambda: self.api.fetch_bytes(m["thumbnailUrl"]), on_done=self._set_cover)

    def _set_cover(self, data: bytes) -> None:
        pm = QPixmap()
        if pm.loadFromData(data):
            self.cover.setPixmap(pm.scaled(self.cover.size(), Qt.AspectRatioMode.KeepAspectRatio,
                                           Qt.TransformationMode.SmoothTransformation))

    def _update_library_ui(self) -> None:
        in_lib = self.manga.get("inLibrary", False)
        self.library_btn.setChecked(in_lib)
        self.library_btn.setText(tr("manga.in_library") if in_lib else tr("manga.add_library"))
        self._loading_cats = True
        self.category.clear()
        self.category.addItem(tr("manga.no_category"), None)
        current = {c["id"] for c in self.manga.get("categories", {}).get("nodes", [])}
        for c in self.categories:
            if not c["default"]:
                self.category.addItem(c["name"], c["id"])
                if c["id"] in current:
                    self.category.setCurrentIndex(self.category.count() - 1)
        self.category.setEnabled(in_lib)
        self._loading_cats = False

    def _fill_chapters(self) -> None:
        self.tree.clear()
        for c in self.chapters:
            marks = ("✔" if c["isRead"] else "") + ("⬇" if c["isDownloaded"] else "") + ("🔖" if c["isBookmarked"] else "")
            name = c["name"] + (f"  (p.{c['lastPageRead'] + 1})" if not c["isRead"] and c["lastPageRead"] > 0 else "")
            item = QTreeWidgetItem([marks, name, c.get("scanlator") or "", fmt_date(c.get("uploadDate"))])
            item.setData(1, ID_ROLE, c["id"])
            if c["isRead"]:
                for col in range(4):
                    item.setForeground(col, self.palette().placeholderText())
            self.tree.addTopLevelItem(item)
        unread = sum(1 for c in self.chapters if not c["isRead"])
        self.status.setText(tr("manga.chapters_count", n=len(self.chapters), unread=unread))
        self.read_btn.setText(tr("manga.continue") if any(c["lastPageRead"] > 0 or c["isRead"] for c in self.chapters) else tr("manga.read"))
        self.read_btn.setEnabled(bool(self.chapters))

    # --- library / categories ----------------------------------------------------------------------------

    def _toggle_library(self) -> None:
        value = self.library_btn.isChecked()
        mid = self.manga_id

        def work():
            self.api.set_in_library(mid, value)
            return self.api.manga(mid)

        def done(manga: dict) -> None:
            self.manga = manga
            if value:
                self.ctrl.mark_known(mid)
            self._update_library_ui()
            self.changed.emit()

        run_async(work, on_done=done, on_error=lambda exc: self.status.setText(tr("status.error", msg=str(exc))))

    def _category_chosen(self) -> None:
        if self._loading_cats:
            return
        chosen = self.category.currentData()
        mid = self.manga_id
        others = [c["id"] for c in self.categories if not c["default"] and c["id"] != chosen]

        def work():
            self.api.set_manga_categories(mid, [chosen] if chosen is not None else [], others)
            return self.api.manga(mid)

        def done(manga: dict) -> None:
            self.manga = manga
            self.changed.emit()

        run_async(work, on_done=done, on_error=lambda exc: self.status.setText(tr("status.error", msg=str(exc))))

    # --- reading -----------------------------------------------------------------------------------------

    def _reading_order(self) -> list[dict]:
        return list(reversed(self.chapters))

    def _continue(self) -> None:
        order = self._reading_order()
        target = next((c for c in order if not c["isRead"]), order[0] if order else None)
        if target:
            self._open_reader(target["id"])

    def _open_reader(self, chapter_id: int) -> None:
        order = self._reading_order()
        index = next((i for i, c in enumerate(order) if c["id"] == chapter_id), 0)
        reader = Reader(self.ctx, self.manga, order, index, on_progress=self._progress_written)
        reader.destroyed.connect(lambda: (self._readers.remove(reader) if reader in self._readers else None, self.load_quiet()))
        self._readers.append(reader)
        reader.show()

    def _progress_written(self) -> None:
        self.changed.emit()

    def load_quiet(self) -> None:
        """Refresh chapter states after reading, without touching the source."""
        mid = self.manga_id
        run_async(lambda: (self.api.manga(mid), self.api.chapters(mid), self.api.categories()),
                  on_done=lambda r: (setattr(self, "manga", r[0]), setattr(self, "chapters", r[1]),
                                     setattr(self, "categories", r[2]), self._show()))

    # --- chapter actions ---------------------------------------------------------------------------------

    def _selected_ids(self) -> list[int]:
        return [it.data(1, ID_ROLE) for it in self.tree.selectedItems()]

    def _mark(self, read: bool) -> None:
        ids = self._selected_ids()
        if not ids:
            return
        run_async(lambda: self.api.update_chapters(ids, is_read=read, last_page_read=0 if not read else None),
                  on_done=lambda _: (self.load_quiet(), self.changed.emit()),
                  on_error=lambda exc: self.status.setText(tr("status.error", msg=str(exc))))

    def _download(self) -> None:
        ids = self._selected_ids()
        if not ids:
            return
        self.status.setText(tr("manga.downloading"))
        run_async(lambda: self.api.enqueue_downloads(ids), on_done=lambda _: self.dl_timer.start(2000),
                  on_error=lambda exc: self.status.setText(tr("status.error", msg=str(exc))))

    def _poll_downloads(self) -> None:
        def done(status: dict) -> None:
            if status["queue"]:
                self.status.setText(tr("manga.downloading_left", n=len(status["queue"]),
                                       p=int(status["queue"][0]["progress"] * 100)))
            else:
                self.dl_timer.stop()
                self.load_quiet()

        run_async(self.api.download_status, on_done=done, on_error=lambda exc: self.dl_timer.stop())

    def _delete_downloads(self) -> None:
        ids = self._selected_ids()
        if ids:
            run_async(lambda: self.api.delete_downloads(ids), on_done=lambda _: self.load_quiet())

    def _menu(self, pos) -> None:
        if not self.tree.selectedItems():
            return
        menu = QMenu(self)
        for label, fn in ((tr("manga.mark_read"), lambda: self._mark(True)), (tr("manga.mark_unread"), lambda: self._mark(False)),
                          (tr("manga.download"), self._download), (tr("manga.delete_download"), self._delete_downloads)):
            menu.addAction(label, fn)
        menu.exec(self.tree.mapToGlobal(pos))

    def closeEvent(self, event) -> None:
        self.dl_timer.stop()
        super().closeEvent(event)
