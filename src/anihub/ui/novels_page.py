"""Light novels section (ТЗ 11): the shelf and the text reader."""
from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QPoint, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QFont, QImage, QKeyEvent, QLinearGradient, QPainter
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QListWidget, QMenu, QMessageBox, QPushButton, QSlider,
    QSplitter, QTextBrowser, QToolButton, QVBoxLayout, QWidget,
)

from anihub.context import AppContext
from anihub.core import agemode
from anihub.core.i18n import tr
from anihub.library.novel_store import collect_books
from anihub.library.novels import BOOK_EXTS, Book, BookError, open_book
from anihub.library.online_novels import download_epub, open_online
from anihub.ui import style, theme
from anihub.ui.grid import ThumbGrid, image_to_thumb
from anihub.ui.workers import run_async

THEMES = {  # reading themes: (background, text, link)
    "dark": ("#15181e", "#d8dce4", "#a996ff"),
    "light": ("#fbfbf9", "#1e2230", "#a8285f"),
    "sepia": ("#f4ecd8", "#3b2f22", "#8a4b12"),
}
COLUMN = 780                              # widest text column, px


def placeholder_cover(title: str, size: int) -> QImage:
    """A cover for books that have none: a gradient picked from the title, with the title on it."""
    h = sum(ord(c) for c in title) % 360
    img = QImage(int(size * 0.72), size, QImage.Format.Format_RGB32)
    p = QPainter(img)
    g = QLinearGradient(0, 0, img.width(), img.height())
    g.setColorAt(0, QColor.fromHsv(h, 110, 150))
    g.setColorAt(1, QColor.fromHsv((h + 40) % 360, 140, 70))
    p.fillRect(img.rect(), g)
    font = QFont()
    font.setPixelSize(max(12, size // 12))
    font.setWeight(QFont.Weight.DemiBold)
    p.setFont(font)
    p.setPen(QColor("white"))
    p.drawText(img.rect().adjusted(10, 10, -10, -10), Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, title[:90])
    p.end()
    return img


def progress_text(row) -> str:
    if row["finished"]:
        return "✓"
    if not row["last_read_at"]:
        return ""
    total = max(row["chapters"], 1)
    return f"{min(100, int(((row['chapter_index'] + row['scroll']) / total) * 100))}%"


class BookBrowser(QTextBrowser):
    """QTextBrowser that serves the pictures of the open book (`book:` URLs)."""
    zoom_wheel = Signal(int)

    def __init__(self):
        super().__init__()
        self.book: Book | None = None
        self.setOpenLinks(False)
        self.setFrameShape(QTextBrowser.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._cache: dict[str, QImage] = {}

    def loadResource(self, kind, url: QUrl):  # noqa: N802
        if url.scheme() == "book" and self.book is not None:
            name = url.toString()[5:] if url.path() == "" else url.path()
            if name not in self._cache:
                data = self.book.resource(name)
                image = QImage.fromData(data) if data else QImage()
                limit = max(self.viewport().width() - 8, 100)
                if not image.isNull() and image.width() > limit:
                    image = image.scaledToWidth(limit, Qt.TransformationMode.SmoothTransformation)
                self._cache[name] = image
            return self._cache[name]
        return super().loadResource(kind, url)

    def reset_cache(self) -> None:
        self._cache.clear()

    def wheelEvent(self, e) -> None:  # noqa: N802
        if e.modifiers() & Qt.KeyboardModifier.ControlModifier:          # Ctrl + wheel = the reader's font size (remembered)
            if e.angleDelta().y():
                self.zoom_wheel.emit(1 if e.angleDelta().y() > 0 else -1)
            e.accept()
        else:
            super().wheelEvent(e)


class NovelReader(QWidget):
    closed = Signal()

    def __init__(self, ctx: AppContext, row, parent=None):
        super().__init__(parent, Qt.WindowType.Window)
        self.ctx, self.novel_id = ctx, row["id"]
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.resize(1000, 820)
        self._loading = False                  # an online chapter is on its way: nothing to save yet
        self.book = open_online(ctx.novel_sources, ctx.http, row) if ctx.novels.is_online(row) else open_book(ctx.novels.file_of(row))
        self.chapters = len(self.book)
        self.index = min(int(row["chapter_index"]), self.chapters - 1)
        self._pending_scroll = float(row["scroll"])
        cfg = ctx.cfg
        self.font_size = int(cfg.get("novels.font_size", 19))
        self.theme_name = cfg.get("novels.theme", "app")
        self.setWindowTitle(row["title"])

        self.browser = BookBrowser()
        self.browser.book = self.book
        self.toc = QListWidget()
        self.toc.setMinimumWidth(220)
        for i, t in enumerate(self.book.titles):
            self.toc.addItem(f"{i + 1}. {t}" if t != str(i + 1) else t)
        self.toc.setVisible(False)
        self.title = QLabel(row["title"])
        style.role(self.title, "dim")
        self.toc_btn = self._tool("list", "novels.toc")
        self.smaller = self._tool("minus", "novels.smaller")
        self.bigger = self._tool("plus", "novels.bigger")
        self.theme_box = QComboBox()
        for key in ("app", "dark", "light", "sepia"):
            self.theme_box.addItem(tr(f"novels.theme.{key}"), key)
        self.theme_box.setCurrentIndex(max(self.theme_box.findData(self.theme_name), 0))
        self.full_btn = self._tool("maximize", "reader.fullscreen")
        self.close_btn = self._tool("x", "reader.close")
        self.prev_btn = self._tool("chevron-left", "reader.prev_chapter", size=24)
        self.next_btn = self._tool("chevron-right", "reader.next_chapter", size=24)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, max(self.chapters - 1, 0))
        self.status = QLabel()
        self.status.setMinimumWidth(150)
        self.status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        top = QHBoxLayout()
        top.setContentsMargins(10, 6, 10, 6)
        for w in (self.toc_btn, self.title):
            top.addWidget(w, 1 if w is self.title else 0)
        for w in (self.smaller, self.bigger, self.theme_box, self.full_btn, self.close_btn):
            top.addWidget(w)
        self.top = QWidget()
        self.top.setLayout(top)
        bottom = QHBoxLayout()
        bottom.setContentsMargins(10, 6, 10, 8)
        for w, s in ((self.prev_btn, 0), (self.slider, 1), (self.status, 0), (self.next_btn, 0)):
            bottom.addWidget(w, s)
        self.bottom = QWidget()
        self.bottom.setLayout(bottom)
        split = QSplitter()
        split.addWidget(self.toc)
        split.addWidget(self.browser)
        split.setStretchFactor(1, 1)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.top)
        layout.addWidget(split, 1)
        layout.addWidget(self.bottom)
        for w in (self.toc_btn, self.smaller, self.bigger, self.theme_box, self.full_btn, self.close_btn, self.prev_btn,
                  self.next_btn, self.slider, self.toc, self.browser):
            w.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        self.save_timer = QTimer(self)
        self.save_timer.setSingleShot(True)
        self.save_timer.timeout.connect(self.save)
        self.browser.zoom_wheel.connect(lambda d: self.set_font(self.font_size + d))
        self.toc_btn.clicked.connect(lambda: self.toc.setVisible(not self.toc.isVisible()))
        self.toc.itemClicked.connect(lambda _i: self.goto(self.toc.currentRow()))
        self.smaller.clicked.connect(lambda: self.set_font(self.font_size - 1))
        self.bigger.clicked.connect(lambda: self.set_font(self.font_size + 1))
        self.theme_box.activated.connect(lambda _i: self.set_theme(self.theme_box.currentData()))
        self.full_btn.clicked.connect(self.toggle_fullscreen)
        self.close_btn.clicked.connect(self.close)
        self.prev_btn.clicked.connect(lambda: self.goto(self.index - 1))
        self.next_btn.clicked.connect(lambda: self.goto(self.index + 1))
        self.slider.valueChanged.connect(self._slider)
        self.browser.verticalScrollBar().valueChanged.connect(lambda _v: (self._update_status(), self.save_timer.start(1500)))
        self._apply_theme()
        self.show_chapter(self.index, self._pending_scroll)

    def _tool(self, icon: str, tip_key: str, size: int = 20) -> QToolButton:
        b = QToolButton()
        b.setProperty("viewer", True)
        b.setToolTip(tr(tip_key))
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.setFixedSize(38, 38)
        style.bind_icon(b, icon, "normal", size)
        return b

    # --- look --------------------------------------------------------------------------------------

    def _colors(self) -> tuple[str, str, str]:
        if self.theme_name in THEMES:
            return THEMES[self.theme_name]
        t = theme.current()
        return t.bg, t.text, t.accent_text

    def _apply_theme(self) -> None:
        bg, fg, link = self._colors()
        self.browser.setStyleSheet(f"QTextBrowser {{ background: {bg}; color: {fg}; selection-background-color: {link}; }}")
        css = (f"body {{ color: {fg}; }} a {{ color: {link}; }} p {{ margin-top: 0px; margin-bottom: {self.font_size * 0.7:.0f}px; "
               f"line-height: 150%; text-indent: 0px; }} h2 {{ margin-top: 24px; margin-bottom: 14px; }} "
               f"h3 {{ margin-top: 16px; }} blockquote {{ margin-left: 26px; color: {fg}; }}")
        self.browser.document().setDefaultStyleSheet(css)
        font = QFont(self.browser.font())
        font.setPointSizeF(self.font_size * 0.75)
        self.browser.document().setDefaultFont(font)

    def set_font(self, size: int) -> None:
        self.font_size = max(10, min(size, 44))
        self.ctx.cfg.set("novels.font_size", self.font_size)
        self._reload_keeping_place()

    def set_theme(self, name: str) -> None:
        self.theme_name = name
        self.ctx.cfg.set("novels.theme", name)
        self._reload_keeping_place()

    def _reload_keeping_place(self) -> None:
        ratio = self._ratio()
        self._apply_theme()
        self.show_chapter(self.index, ratio)

    def resizeEvent(self, e) -> None:  # noqa: N802
        super().resizeEvent(e)
        side = max(24, (self.browser.width() - COLUMN) // 2)
        self.browser.setViewportMargins(side, 12, side, 12)

    # --- chapters / progress ---------------------------------------------------------------------------

    def _ratio(self) -> float:
        bar = self.browser.verticalScrollBar()
        return bar.value() / bar.maximum() if bar.maximum() else 0.0

    def show_chapter(self, index: int, scroll: float = 0.0) -> None:
        index = max(0, min(index, self.chapters - 1))
        self.index = index
        self.browser.reset_cache()
        if getattr(self.book, "remote", False) and not self.book.cached(index):
            self._loading = True
            self.browser.setHtml(f"<html><body><p>{tr('status.loading')}</p></body></html>")
            self._fetch(index, scroll)
        else:
            try:
                body = self.book.chapter_html(index)
            except (KeyError, BookError, OSError) as exc:
                body = f"<p>{exc}</p>"
            self.browser.setHtml(f"<html><body>{body}</body></html>")
            self._prefetch(index + 1)
        self.slider.blockSignals(True)
        self.slider.setValue(index)
        self.slider.blockSignals(False)
        self.toc.setCurrentRow(index)
        self.prev_btn.setEnabled(index > 0)
        self.next_btn.setEnabled(index < self.chapters - 1)
        QTimer.singleShot(0, lambda: self._scroll_to(scroll))
        self._update_status()
        self.save_timer.start(1500)

    def _fetch(self, index: int, scroll: float) -> None:
        """Online books: the chapter is downloaded in a worker, then shown (if the reader is still on it)."""
        def done(_result) -> None:
            if index != self.index:
                return
            self._loading = False
            self.browser.reset_cache()
            self.browser.setHtml(f"<html><body>{self.book.chapter_html(index)}</body></html>")
            QTimer.singleShot(0, lambda: self._scroll_to(scroll))
            self._prefetch(index + 1)

        def failed(exc: Exception) -> None:
            if index == self.index:
                self._loading = False
                self.browser.setHtml(f"<html><body><p>{tr('status.error', msg=str(exc))}</p></body></html>")

        run_async(lambda: self.book.fetch(index), on_done=done, on_error=failed)

    def _prefetch(self, index: int) -> None:
        if getattr(self.book, "remote", False) and 0 <= index < self.chapters and not self.book.cached(index):
            run_async(lambda: self.book.fetch(index), on_done=lambda _r: None, on_error=lambda _e: None)

    def _scroll_to(self, ratio: float) -> None:
        bar = self.browser.verticalScrollBar()
        bar.setValue(int(bar.maximum() * max(0.0, min(ratio, 1.0))))
        self._update_status()

    def goto(self, index: int) -> None:
        if 0 <= index < self.chapters and index != self.index:
            self.save()
            self.show_chapter(index, 0.0)

    def _slider(self, value: int) -> None:
        self.goto(value)

    def _update_status(self) -> None:
        self.status.setText(tr("novels.status", n=self.index + 1, total=self.chapters, pct=int(self._ratio() * 100)))

    def save(self) -> None:
        if self._loading:
            return
        self.ctx.novels.save_progress(self.novel_id, self.index, self._ratio(), self.chapters)

    # --- input ---------------------------------------------------------------------------------------

    def toggle_fullscreen(self) -> None:
        full = not self.isFullScreen()
        self.showFullScreen() if full else self.showNormal()
        self.top.setVisible(not full)
        style.bind_icon(self.full_btn, "minimize" if full else "maximize", "normal", 20)

    def _page(self, direction: int) -> None:
        bar = self.browser.verticalScrollBar()
        step = int(self.browser.viewport().height() * 0.9)
        if direction > 0 and bar.value() >= bar.maximum():
            self.goto(self.index + 1)
        elif direction < 0 and bar.value() <= 0:
            if self.index > 0:
                self.goto(self.index - 1)
                QTimer.singleShot(0, lambda: self._scroll_to(1.0))
        else:
            bar.setValue(bar.value() + direction * step)

    def keyPressEvent(self, e: QKeyEvent) -> None:  # noqa: N802
        k = e.key()
        if k in (Qt.Key.Key_Space, Qt.Key.Key_PageDown):
            self._page(1)
        elif k in (Qt.Key.Key_Backspace, Qt.Key.Key_PageUp):
            self._page(-1)
        elif k in (Qt.Key.Key_Right, Qt.Key.Key_BracketRight):
            self.goto(self.index + 1)
        elif k in (Qt.Key.Key_Left, Qt.Key.Key_BracketLeft):
            self.goto(self.index - 1)
        elif k == Qt.Key.Key_Down:
            self.browser.verticalScrollBar().setValue(self.browser.verticalScrollBar().value() + 60)
        elif k == Qt.Key.Key_Up:
            self.browser.verticalScrollBar().setValue(self.browser.verticalScrollBar().value() - 60)
        elif k in (Qt.Key.Key_Plus, Qt.Key.Key_Equal):
            self.set_font(self.font_size + 1)
        elif k == Qt.Key.Key_Minus:
            self.set_font(self.font_size - 1)
        elif k == Qt.Key.Key_T:
            self.toc.setVisible(not self.toc.isVisible())
        elif k in (Qt.Key.Key_F, Qt.Key.Key_F11):
            self.toggle_fullscreen()
        elif k == Qt.Key.Key_Escape:
            self.toggle_fullscreen() if self.isFullScreen() else self.close()
        else:
            super().keyPressEvent(e)

    def closeEvent(self, event) -> None:  # noqa: N802
        self.save_timer.stop()
        self.save()
        self.book.close()
        self.closed.emit()
        super().closeEvent(event)


class NovelsPage(QWidget):
    _download_progress = Signal(int, int)             # from the download worker thread

    def __init__(self, ctx: AppContext, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self._readers: list[NovelReader] = []
        self._download_progress.connect(lambda done, total: self.status.setText(tr("novels.downloading", done=done, total=total)))
        self.import_btn = style.primary(QPushButton(tr("novels.import")), "plus")
        self.folder_btn = style.secondary(QPushButton(tr("novels.import_folder")), "folder")
        self.filter = QLineEdit(placeholderText=tr("novels.filter"))
        self.filter.setClearButtonEnabled(True)
        self.unfinished = QCheckBox(tr("novels.unfinished"))
        self.grid = ThumbGrid(ctx.cfg.get("ui.thumb_size", 180) + 20)
        self.empty = style.EmptyState("book", tr("novels.empty_title"), tr("novels.empty_text"))
        self.status = QLabel()
        style.role(self.status, "dim")
        top = QHBoxLayout()
        for w, s in ((self.import_btn, 0), (self.folder_btn, 0), (self.filter, 1), (self.unfinished, 0)):
            top.addWidget(w, s)
        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(self.grid, 1)
        layout.addWidget(self.empty, 1)
        layout.addWidget(self.status)
        self.import_btn.clicked.connect(self._import_files)
        self.folder_btn.clicked.connect(self._import_folder)
        self.filter.textChanged.connect(self.reload)
        self.unfinished.toggled.connect(self.reload)
        self.grid.itemDoubleClicked.connect(lambda it: self.open_book(it.data(Qt.ItemDataRole.UserRole)))
        self.grid.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.grid.customContextMenuRequested.connect(self._menu)
        self.reload()

    # --- shelf -----------------------------------------------------------------------------------------

    def reload(self) -> None:
        rows = [r for r in self.ctx.db.novels(self.filter.text().strip(), self.unfinished.isChecked()) if self._visible(r)]
        total = len([r for r in self.ctx.db.novels() if self._visible(r)])
        self.grid.clear_items()
        size = self.grid.thumb_size
        for row in rows:
            cover = self.ctx.novels.cover_of(row)
            tip = row["title"] + (f"\n{row['author']}" if row["author"] else "") + f"\n{tr('novels.chapters_n', n=row['chapters'])}"

            def load(row=row, cover=cover):
                if cover and cover.exists():
                    return image_to_thumb(cover.read_bytes(), size, progress_text(row))
                img = placeholder_cover(row["title"], size)
                return img

            self.grid.add_entry(dict(row), tip, load)
        self.grid.setVisible(total > 0)
        self.empty.setVisible(total == 0)
        self.status.setText(tr("novels.count", n=len(rows)) if total else "")

    def _visible(self, row) -> bool:
        """Online titles follow the age mode and the tag filter of the moment (the mode may have been lowered since)."""
        if not self.ctx.novels.is_online(row):
            return True
        try:
            from anihub.library.online_novels import parse_remote

            entry, _ = parse_remote(row["remote"])
        except (ValueError, KeyError, TypeError):
            return True
        return agemode.age_ok(self.ctx.cfg, entry.age) and not self.ctx.blocker.blocked_in(entry.tags)

    def _import_files(self) -> None:
        exts = " ".join(f"*.{e}" for e in sorted(BOOK_EXTS))
        files, _ = QFileDialog.getOpenFileNames(self, tr("novels.import"), "", f"{tr('novels.books')} ({exts})")
        if files:
            self._run_import(collect_books([Path(f) for f in files]))

    def _import_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, tr("novels.import_folder"))
        if folder:
            self._run_import(collect_books([Path(folder)]))

    def _run_import(self, files: list[Path]) -> None:
        if not files:
            self.status.setText(tr("novels.none_found"))
            return
        self.status.setText(tr("status.loading"))
        self.import_btn.setEnabled(False)

        def done(counts: dict) -> None:
            self.import_btn.setEnabled(True)
            self.reload()
            self.status.setText(tr("novels.imported", **counts))

        run_async(self.ctx.novels.import_books, files, on_done=done,
                  on_error=lambda exc: (self.import_btn.setEnabled(True), self.status.setText(tr("status.error", msg=str(exc)))))

    # --- reading -----------------------------------------------------------------------------------------

    def open_book(self, payload: dict) -> None:
        row = self.ctx.db.novel_get(payload["id"])
        if row is None:
            return
        try:
            reader = NovelReader(self.ctx, row, self)
        except (BookError, OSError) as exc:
            QMessageBox.warning(self, tr("novels.title"), str(exc))
            return
        reader.closed.connect(self.reload)
        reader.destroyed.connect(lambda: self._readers.remove(reader) if reader in self._readers else None)
        self._readers.append(reader)
        reader.show()

    def _menu(self, pos: QPoint) -> None:
        item = self.grid.itemAt(pos)
        if item is None:
            return
        payload = item.data(Qt.ItemDataRole.UserRole)
        row = self.ctx.db.novel_get(payload["id"])
        menu = QMenu(self)
        menu.addAction(tr("anime.open"), lambda: self.open_book(payload))
        menu.addAction(tr("novels.mark_unfinished") if row["finished"] else tr("novels.mark_finished"),
                       lambda: self._set_finished(row["id"], not row["finished"]))
        if self.ctx.novels.is_online(row):
            menu.addAction(tr("novels.download"), lambda: self._download(row))
        else:
            menu.addAction(tr("lib.show_folder"), lambda: os.startfile(self.ctx.novels.file_of(row).parent))
        menu.addSeparator()
        menu.addAction(tr("lib.delete"), lambda: self._delete(row))
        menu.exec(self.grid.viewport().mapToGlobal(pos))

    def _download(self, row) -> None:
        """An online title -> an EPUB on the shelf (read offline from now on; the reading place is kept)."""
        import tempfile

        book = open_online(self.ctx.novel_sources, self.ctx.http, row)
        self.status.setText(tr("status.loading"))

        def work():
            with tempfile.TemporaryDirectory() as tmp:
                epub = download_epub(book, Path(tmp) / f"{row['id']}.epub", lambda d, t: self._download_progress.emit(d, t))
                return self.ctx.novels.replace_with_file(row, epub)

        def done(new_id) -> None:
            book.close()
            self.reload()
            self.status.setText(tr("novels.downloaded") if new_id else tr("status.error", msg="?"))

        def failed(exc: Exception) -> None:
            book.close()
            self.status.setText(tr("status.error", msg=str(exc)))

        run_async(work, on_done=done, on_error=failed)

    def _set_finished(self, novel_id: int, finished: bool) -> None:
        self.ctx.db.novel_update(novel_id, finished=int(finished))
        self.reload()

    def _delete(self, row) -> None:
        if QMessageBox.question(self, tr("lib.delete"), tr("novels.delete_confirm", title=row["title"])) == QMessageBox.StandardButton.Yes:
            self.ctx.novels.delete(row["id"])
            self.reload()
