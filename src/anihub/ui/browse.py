"""Site browser: tag search across sources, infinite-scroll thumbnail grid, viewer, save to library."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QImage
from PySide6.QtWidgets import (
    QComboBox, QHBoxLayout, QLabel, QLineEdit, QListWidgetItem, QPushButton, QVBoxLayout, QWidget,
)

from anihub.context import AppContext
from anihub.core.i18n import tr
from anihub.sources.base import Post, Source, SourceError
from anihub.ui import icons, style
from anihub.ui.grid import PAYLOAD, ThumbGrid, image_to_thumb
from anihub.ui.tagquery import apply_tag
from anihub.ui.viewer import ViewItem, Viewer
from anihub.ui.workers import run_async


class BrowseView(QWidget):
    library_changed = Signal()

    def __init__(self, ctx: AppContext, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self._gen = 0
        self._page = 1
        self._loading = False
        self._exhausted = True
        self._hidden = 0
        self._tags: list[str] = []
        self._viewers: list[Viewer] = []

        self.source = QComboBox()
        for src in ctx.sources.values():
            self.source.addItem(src.title, src.name)
        last = ctx.cfg.get("browse.last_source")
        idx = self.source.findData(last)
        self.source.setCurrentIndex(max(idx, 0))
        self.query = QLineEdit(placeholderText=tr("search.placeholder"))
        self.search_btn = QPushButton(tr("search.button"))
        self.save_btn = QPushButton(tr("action.save"))
        self.save_btn.setEnabled(False)
        self.grid = ThumbGrid(ctx.cfg.get("ui.thumb_size", 180))
        self.grid.hover_loader = self._hover_loader
        self.status = style.role(QLabel(), "dim")
        style.primary(self.search_btn, "search")
        style.secondary(self.save_btn, "save")
        self.query.addAction(icons.icon("search", size=16), QLineEdit.ActionPosition.LeadingPosition)
        self.grid.set_empty("search", tr("browse.empty_title"), tr("browse.empty_hint"))

        top = QHBoxLayout()
        top.setSpacing(8)
        top.addWidget(self.source)
        top.addWidget(self.query, 1)
        top.addWidget(self.search_btn)
        top.addWidget(self.save_btn)
        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(self.grid, 1)
        layout.addWidget(self.status)

        self.search_btn.clicked.connect(self.start_search)
        self.query.returnPressed.connect(self.start_search)
        self.save_btn.clicked.connect(self._save_selected)
        self.grid.need_more.connect(self._load_page)
        self.grid.itemDoubleClicked.connect(self._open_viewer)
        self.grid.itemSelectionChanged.connect(lambda: self.save_btn.setEnabled(bool(self.grid.selectedItems())))

    # --- searching ---------------------------------------------------------------

    def start_search(self) -> None:
        self._gen += 1
        self.grid.clear_items()
        self._page, self._exhausted, self._loading, self._hidden = 1, False, False, 0
        self._tags = self.query.text().split()
        self.ctx.cfg.set("browse.last_source", self.source.currentData())
        self._load_page()

    def _fetch(self, source: Source, tags: list[str], page: int, limit: int, allowed: set[str]):
        shown: list[Post] = []
        hidden = 0
        for _ in range(4):  # skip pages that are entirely hidden by the rating filter
            raw = source.search(tags, page, limit)
            page += 1
            if not raw:
                return shown, page, True, hidden
            shown = [p for p in raw if p.rating in allowed]
            hidden += len(raw) - len(shown)
            if shown:
                break
        return shown, page, False, hidden

    def _load_page(self) -> None:
        if self._loading or self._exhausted:
            return
        self._loading = True
        self.status.setText(tr("status.loading"))
        gen = self._gen
        source = self.ctx.sources[self.source.currentData()]
        limit = int(self.ctx.cfg.get("browse.page_size", 40))
        allowed = set(self.ctx.allowed_ratings())

        def done(result) -> None:
            if gen != self._gen:
                return
            posts, next_page, exhausted, hidden = result
            self._page, self._exhausted, self._loading = next_page, exhausted, False
            self._hidden += hidden
            for post in posts:
                self.grid.add_entry(post, self._tooltip(post), lambda p=post: image_to_thumb(
                    self.ctx.http.get_bytes(p.preview_url), self.grid.thumb_size, p.badge))
            self._update_status()
            if not exhausted and posts:
                self.grid.request_fill()

        def failed(exc: Exception) -> None:
            if gen != self._gen:
                return
            self._loading = False
            self._exhausted = True
            msg = str(exc) if isinstance(exc, SourceError) else f"{type(exc).__name__}: {exc}"
            self.status.setText(tr("status.error", msg=msg))

        run_async(self._fetch, source, self._tags, self._page, limit, allowed, on_done=done, on_error=failed)

    def _update_status(self) -> None:
        text = tr("status.count", n=self.grid.count())
        if self._hidden:
            text += f"  ·  hidden by rating filter: {self._hidden}"
        if self._exhausted:
            text += f"  ·  {tr('status.end')}"
        self.status.setText(text)

    def _hover_loader(self, post: Post):
        """Large preview when the mouse rests on a thumbnail (ТЗ 3.5): the sample for stills, the preview otherwise."""
        def load() -> QImage | None:
            if post.badge or (post.resolver and not post.file_url):  # video / gif / lazy file: the preview image will do
                image = QImage.fromData(self.ctx.http.get_bytes(post.preview_url))
            else:
                image = QImage(str(self.ctx.media.get(post.display_url())))
            return None if image.isNull() else image

        return load

    @staticmethod
    def _tooltip(post: Post) -> str:
        head = f"{post.title}\n" if post.title else ""
        return f"{head}#{post.id}  {post.rating}  {post.width}x{post.height}  ★{post.score}\n{post.author}"

    # --- viewer / saving ---------------------------------------------------------

    def _view_item(self, post: Post) -> ViewItem:
        info = ((f"{post.title} · " if post.title else "") + f"{post.site} #{post.id} · {post.rating} · {post.width}x{post.height}"
                + (f" · {post.author}" if post.author else "") + f" · ★{post.score}")
        # display_url() may hit the network (lazy sources), so it is resolved inside the worker.
        return ViewItem(f"{post.site} #{post.id}", info, lambda: self.ctx.media.get(post.display_url()),
                        post.page_url, post.tags, post)

    def _open_viewer(self, item: QListWidgetItem) -> None:
        posts = self.grid.payloads()
        viewer = Viewer([self._view_item(p) for p in posts], self.grid.row(item), self._save_from_viewer)
        viewer.tag_action.connect(lambda tag, mode: self._tag_from_viewer(viewer, tag, mode))
        viewer.destroyed.connect(lambda: self._viewers.remove(viewer) if viewer in self._viewers else None)
        self._viewers.append(viewer)
        viewer.show()

    def _tag_from_viewer(self, viewer: Viewer, tag: str, mode: str) -> None:
        self.query.setText(apply_tag(self.query.text(), tag, mode))
        viewer.close()
        self.window().activateWindow()
        self.start_search()

    def _save_from_viewer(self, item: ViewItem) -> None:
        self._save([item.payload])

    def _save_selected(self) -> None:
        self._save(self.grid.selected_payloads())

    def _save(self, posts: list[Post]) -> None:
        if not posts:
            return
        self.save_btn.setEnabled(False)
        self.status.setText(tr("status.loading"))

        def done(counts: dict) -> None:
            self.save_btn.setEnabled(bool(self.grid.selectedItems()))
            text = tr("status.saved", saved=counts["saved"], dup=counts["duplicate"], failed=counts["failed"])
            if counts.get("similar"):
                text += "  ·  " + tr("status.similar", n=counts["similar"])
            self.status.setText(text)
            self.library_changed.emit()

        def failed(exc: Exception) -> None:
            self.save_btn.setEnabled(True)
            self.status.setText(tr("status.error", msg=str(exc)))

        run_async(self.ctx.library.save_posts, posts, on_done=done, on_error=failed)
