"""Manga reader: paged (single / double-page spreads), right-to-left, and webtoon (endless vertical scroll).

Pages are fetched lazily from Suwayomi. Reading progress (last page / read flag) is written back to it.
"""
from __future__ import annotations

from PySide6.QtCore import (
    QEasingCurve, QPoint, QPointF, QPropertyAnimation, QRectF, QSizeF, Qt, QTimer, QVariantAnimation, Signal,
)
from PySide6.QtGui import QColor, QImage, QKeyEvent, QMouseEvent, QPainter, QPixmap, QResizeEvent
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QHBoxLayout, QLabel, QScrollArea, QSlider, QStackedWidget, QToolButton, QVBoxLayout, QWidget,
)

from anihub.context import AppContext
from anihub.core.i18n import tr
from anihub.ui import style
from anihub.ui.image_context_menu import show_image_menu
from anihub.ui.zoomview import STEP, clamp_pan, clamp_zoom, zoom_pan
from anihub.ui.workers import run_async

MODES = ("paged", "double", "webtoon")
PRELOAD_AHEAD = 4
MAX_CACHED = 60


def is_wide(img: QImage | None) -> bool:
    return img is not None and img.width() > img.height()


def spread_at(images: dict[int, QImage], count: int, i: int, double: bool) -> list[int]:
    """Page indexes shown together starting at page i. Cover (page 0) and wide pages stand alone."""
    if not double or i <= 0 or i >= count - 1:
        return [i]
    if i not in images or (i + 1) not in images:
        return [i]  # sizes unknown yet: show single until both pages are loaded
    if is_wide(images[i]) or is_wide(images[i + 1]):
        return [i]
    return [i, i + 1]


def step_back(images: dict[int, QImage], count: int, i: int, double: bool) -> int:
    """First page of the spread that precedes page i."""
    if i <= 1 or not double:
        return max(i - 1, 0)
    j = i - 2
    if j >= 1 and j in images and (j + 1) in images and not is_wide(images[j]) and not is_wide(images[j + 1]):
        return j
    return i - 1


class PagedCanvas(QWidget):
    """One page or a spread. Ctrl + wheel zooms (the level is kept between pages), a drag pans a zoomed page, a click on a
    half flips; flipping slides the old page out to one side while the next one comes in from the other."""
    clicked_side = Signal(str)  # "left" | "right"
    zoom_changed = Signal(float)
    menu_requested = Signal(QPoint)  # local position; a right click never flips the page
    SLIDE_MS = 300

    def __init__(self):
        super().__init__()
        self.images: list[QImage | None] = []
        self.rtl = True
        self.message = ""
        self.zoom = 1.0
        self._pan = QPointF()
        self._press: QPointF | None = None
        self._moved = False
        self._old: tuple[list[QImage | None], float, QPointF] | None = None      # what is sliding out
        self._dir = 0                                                              # +1: the new page enters from the right
        self._t = 1.0
        self._anim = QVariantAnimation(self, duration=self.SLIDE_MS)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.valueChanged.connect(self._on_slide)
        self._anim.finished.connect(self._end_slide)
        self.setMinimumSize(300, 300)

    # --- content -------------------------------------------------------------------------------------------------

    def show_images(self, images: list[QImage | None], message: str = "") -> None:
        self.images, self.message = images, message
        self.update()

    def reset_pan(self) -> None:
        self._pan = QPointF()

    def start_slide(self, direction: int) -> None:
        """The page on screen leaves (to the left when direction is +1, to the right when -1). Call before show_images()."""
        if not any(im is not None for im in self.images) or not self.isVisible() or not direction:
            self._old = None
            return
        self._old = (list(self.images), self.zoom, QPointF(self._pan))
        self._dir, self._t = direction, 0.0
        self._pan = QPointF()
        self._anim.stop()
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.start()

    def _on_slide(self, value) -> None:
        self._t = float(value)
        self.update()

    def _end_slide(self) -> None:
        self._old, self._t = None, 1.0
        self.update()

    # --- geometry --------------------------------------------------------------------------------------------------

    def _ordered(self, images) -> list[QImage]:
        shown = list(reversed(images)) if (self.rtl and len(images) == 2) else list(images)
        return [im for im in shown if im is not None]

    def _fitted(self, images) -> QSizeF:
        """Size of the page (or spread) at zoom 1: as large as fits, equal heights side by side."""
        ready = self._ordered(images)
        if not ready:
            return QSizeF(0, 0)
        h0 = ready[0].height()
        total_w = sum(im.width() * (h0 / im.height()) for im in ready)
        scale = min(self.width() / total_w, self.height() / h0)
        return QSizeF(total_w * scale, h0 * scale)

    def _rects(self, images, zoom: float, pan: QPointF) -> list[tuple[QImage, QRectF]]:
        ready = self._ordered(images)
        if not ready:
            return []
        fitted = self._fitted(images)
        h0 = ready[0].height()
        total_w = sum(im.width() * (h0 / im.height()) for im in ready)
        k = fitted.width() * zoom / total_w                                          # px per (height-normalised) image px
        h = h0 * (fitted.height() / h0) * zoom
        x = (self.width() - fitted.width() * zoom) / 2 + pan.x()
        y = (self.height() - h) / 2 + pan.y()
        out = []
        for im in ready:
            w = im.width() * (h0 / im.height()) * k
            out.append((im, QRectF(x, y, w, h)))
            x += w
        return out

    def _draw(self, p: QPainter, images, zoom: float, pan: QPointF, message: str) -> None:
        rects = self._rects(images, zoom, pan)
        if not rects:
            p.setPen(QColor("#9aa0a6"))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, message or tr("status.loading"))
            return
        for im, rect in rects:
            p.drawImage(rect, im)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.fillRect(self.rect(), QColor("#101214"))
        width = self.width()
        if self._old is not None and self._t < 1.0:
            old_images, old_zoom, old_pan = self._old
            p.save()
            p.translate(-self._dir * self._t * width, 0)
            self._draw(p, old_images, old_zoom, old_pan, "")
            p.restore()
            p.translate(self._dir * (1.0 - self._t) * width, 0)
        self._draw(p, self.images, self.zoom, self._pan, self.message)

    # --- zoom / pan / click ----------------------------------------------------------------------------------------

    def set_zoom(self, zoom: float, anchor: QPointF | None = None) -> None:
        zoom = clamp_zoom(zoom)
        fitted = self._fitted(self.images)
        if zoom == self.zoom or fitted.isEmpty():
            self.zoom = zoom if fitted.isEmpty() else self.zoom
            return
        area = QSizeF(self.width(), self.height())
        anchor = anchor if anchor is not None else QPointF(area.width() / 2, area.height() / 2)
        self._pan = zoom_pan(self.zoom, zoom, self._pan, anchor, area, fitted)
        self.zoom = zoom
        self.update()
        self.zoom_changed.emit(zoom)

    def wheelEvent(self, e) -> None:
        if e.modifiers() & Qt.KeyboardModifier.ControlModifier:
            if e.angleDelta().y():
                self.set_zoom(self.zoom * STEP ** (e.angleDelta().y() / 120), e.position())
            e.accept()
        else:
            e.ignore()                                                                 # the reader flips the page

    def mousePressEvent(self, e: QMouseEvent) -> None:
        if e.button() != Qt.MouseButton.LeftButton:
            return
        self._press, self._moved = e.position(), False

    def mouseMoveEvent(self, e: QMouseEvent) -> None:
        if self._press is None:
            return
        delta = e.position() - self._press
        if not self._moved and delta.manhattanLength() < 6:
            return
        self._moved = True
        self._press = e.position()
        if self.zoom > 1.0:
            fitted = self._fitted(self.images)
            self._pan = clamp_pan(self._pan + delta, QSizeF(fitted.width() * self.zoom, fitted.height() * self.zoom),
                                  QSizeF(self.width(), self.height()))
            self.update()

    def mouseReleaseEvent(self, e: QMouseEvent) -> None:
        if self._press is not None and not self._moved:
            self.clicked_side.emit("left" if e.position().x() < self.width() / 2 else "right")
        self._press = None

    def mouseDoubleClickEvent(self, e: QMouseEvent) -> None:
        if self.zoom != 1.0:
            self._pan = QPointF()
            self.zoom = 1.0
            self.update()
            self.zoom_changed.emit(1.0)

    def contextMenuEvent(self, e) -> None:  # noqa: N802
        self.menu_requested.emit(e.pos())


class WebtoonView(QScrollArea):
    """Endless vertical strip. The strip has a readable width of its own (a manhwa page is not stretched over the whole
    window): Ctrl + wheel changes it and the reader remembers it. The plain wheel, keys and buttons scroll smoothly."""
    page_changed = Signal(int)
    need_page = Signal(int)
    width_changed = Signal(int)
    page_menu_requested = Signal(int, QPoint)  # (page index, already-global position)
    DEFAULT_COLUMN = 800
    MIN_COLUMN = 240
    SCROLL_MS = 260

    def __init__(self):
        super().__init__()
        self.setWidgetResizable(True)
        self.setFrameShape(QScrollArea.Shape.NoFrame)
        self.setStyleSheet("background: #101214;")
        self.container = QWidget()
        self.lay = QVBoxLayout(self.container)
        self.lay.setContentsMargins(0, 0, 0, 0)
        self.lay.setSpacing(0)
        self.setWidget(self.container)
        self.column = self.DEFAULT_COLUMN                       # the strip's width in px (never wider than the window)
        self.labels: list[QLabel] = []
        self.images: dict[int, QImage] = {}
        self._target = 0
        self._anim = QPropertyAnimation(self.verticalScrollBar(), b"value", self)
        self._anim.setDuration(self.SCROLL_MS)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.verticalScrollBar().valueChanged.connect(self._on_scroll)

    def set_pages(self, count: int) -> None:
        for lab in self.labels:
            lab.deleteLater()
        self.labels, self.images = [], {}
        for i in range(count):
            lab = QLabel(alignment=Qt.AlignmentFlag.AlignCenter)
            lab.setFixedHeight(int(self._width() * 1.4))
            lab.setStyleSheet("color: #9aa0a6;")
            lab.setText("…")
            lab.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            lab.customContextMenuRequested.connect(lambda pos, i=i, lab=lab: self.page_menu_requested.emit(i, lab.mapToGlobal(pos)))
            self.lay.addWidget(lab)
            self.labels.append(lab)

    def _width(self) -> int:
        return max(min(self.column, self.viewport().width()), 200)

    def set_image(self, i: int, img: QImage) -> None:
        self.images[i] = img
        self._fit(i)

    def _fit(self, i: int) -> None:
        img = self.images.get(i)
        if img is None or i >= len(self.labels):
            return
        pm = QPixmap.fromImage(img.scaledToWidth(self._width(), Qt.TransformationMode.SmoothTransformation))
        self.labels[i].setPixmap(pm)
        self.labels[i].setFixedHeight(pm.height())

    def _refit_all(self) -> None:
        for i in self.images:
            self._fit(i)
        for i, lab in enumerate(self.labels):
            if i not in self.images:
                lab.setFixedHeight(int(self._width() * 1.4))

    def resizeEvent(self, e: QResizeEvent) -> None:
        super().resizeEvent(e)
        self._refit_all()

    # --- width (Ctrl + wheel) --------------------------------------------------------------------------------------

    def set_column(self, width: int, notify: bool = True) -> None:
        """Change the strip's width and keep the place: the same spot of the same page stays in view."""
        width = max(self.MIN_COLUMN, min(int(width), max(self.viewport().width(), self.MIN_COLUMN)))
        if width == self.column:
            return
        page = self.current_page()
        lab = self.labels[page] if self.labels else None
        frac = (self.verticalScrollBar().value() - lab.y()) / max(lab.height(), 1) if lab is not None else 0.0
        self.column = width
        self._refit_all()

        def restore() -> None:
            if lab is not None and page < len(self.labels):
                target = self.labels[page]
                self.verticalScrollBar().setValue(int(target.y() + frac * target.height()))

        QTimer.singleShot(0, restore)
        if notify:
            self.width_changed.emit(width)

    def zoom_steps(self, steps: float) -> None:
        self.set_column(round(self.column * STEP ** steps))

    # --- scrolling -------------------------------------------------------------------------------------------------

    def scroll_by(self, delta: int, animated: bool = True) -> None:
        bar = self.verticalScrollBar()
        base = self._target if self._anim.state() == QPropertyAnimation.State.Running else bar.value()
        self._target = max(0, min(base + int(delta), bar.maximum()))
        self._anim.stop()
        if not animated:
            bar.setValue(self._target)
            return
        self._anim.setStartValue(bar.value())
        self._anim.setEndValue(self._target)
        self._anim.start()

    def wheelEvent(self, e) -> None:
        if e.modifiers() & Qt.KeyboardModifier.ControlModifier:
            if e.angleDelta().y():
                self.zoom_steps(e.angleDelta().y() / 120)
            e.accept()
            return
        pixels = e.pixelDelta().y()
        if pixels:                                                                    # a touchpad already scrolls smoothly
            self._anim.stop()
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - pixels)
        else:
            self.scroll_by(-int(e.angleDelta().y() * 1.1))
        e.accept()

    def current_page(self) -> int:
        mid = self.verticalScrollBar().value() + self.viewport().height() // 2
        for i, lab in enumerate(self.labels):
            if lab.y() + lab.height() >= mid:
                return i
        return max(len(self.labels) - 1, 0)

    def scroll_to_page(self, i: int) -> None:
        if 0 <= i < len(self.labels):
            self._anim.stop()
            self.verticalScrollBar().setValue(self.labels[i].y())

    def _on_scroll(self) -> None:
        cur = self.current_page()
        for i in range(cur, min(cur + PRELOAD_AHEAD + 1, len(self.labels))):
            self.need_page.emit(i)
        self.page_changed.emit(cur)


class Reader(QWidget):
    """chapters: the title's chapters in reading order (oldest first)."""

    def __init__(self, ctx: AppContext, manga: dict, chapters: list[dict], index: int, on_progress=None, parent=None):
        super().__init__(parent, Qt.WindowType.Window)
        self.ctx, self.api = ctx, ctx.suwayomi.api
        self.manga, self.chapters, self.index = manga, chapters, index
        self.on_progress = on_progress  # called after progress was written (e.g. to refresh the detail window)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.resize(1000, 900)
        cfg = ctx.cfg
        self.mode = cfg.get("manga.reader.mode", "paged")
        if self.mode not in MODES:
            self.mode = "paged"
        self.rtl = bool(cfg.get("manga.reader.rtl", True))
        self.pages: list[str] = []
        self.images: dict[int, QImage] = {}
        self.loading: set[int] = set()
        self.page = 0
        self._token = 0
        self._marked_read = False

        self.title = QLabel()
        self.mode_box = QComboBox()
        for m in MODES:
            self.mode_box.addItem(tr(f"reader.mode.{m}"), m)
        self.mode_box.setCurrentIndex(MODES.index(self.mode))
        self.rtl_box = QCheckBox(tr("reader.rtl"), checked=self.rtl)
        # on-screen controls, so the whole reader can be driven with a mouse only
        self.prev_btn = self._tool("skip-back", "reader.prev_chapter")
        self.next_btn = self._tool("skip-forward", "reader.next_chapter")
        self.left_btn = self._tool("chevron-left", "reader.go_left", size=24, side=46)
        self.right_btn = self._tool("chevron-right", "reader.go_right", size=24, side=46)
        self.full_btn = self._tool("maximize", "reader.fullscreen")
        self.close_btn = self._tool("x", "reader.close")
        self.page_slider = QSlider(Qt.Orientation.Horizontal)
        self.page_label = QLabel("0 / 0")
        self.page_label.setMinimumWidth(64)
        self.page_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.bar = QWidget()
        row = QHBoxLayout(self.bar)
        row.setContentsMargins(10, 6, 10, 6)
        row.setSpacing(10)
        row.addWidget(self.title, 1)
        row.addWidget(self.mode_box)
        row.addWidget(self.rtl_box)
        row.addWidget(self.full_btn)
        row.addWidget(self.close_btn)
        self.bottom = QWidget()
        bottom = QHBoxLayout(self.bottom)
        bottom.setContentsMargins(10, 6, 10, 8)
        bottom.setSpacing(8)
        for w in (self.prev_btn, self.left_btn):
            bottom.addWidget(w)
        bottom.addWidget(self.page_slider, 1)
        bottom.addWidget(self.page_label)
        for w in (self.right_btn, self.next_btn):
            bottom.addWidget(w)

        self.canvas = PagedCanvas()
        self.canvas.rtl = self.rtl
        self.canvas.zoom = clamp_zoom(float(cfg.get("manga.reader.zoom", 1.0) or 1.0))         # remembered for manga
        self.web = WebtoonView()
        self.web.column = int(cfg.get("manga.reader.webtoon_width", WebtoonView.DEFAULT_COLUMN) or WebtoonView.DEFAULT_COLUMN)
        self._cfg_timer = QTimer(self)                                                          # the wheel fires often: save once
        self._cfg_timer.setSingleShot(True)
        self._cfg_timer.timeout.connect(cfg.save)
        self.stack = QStackedWidget()
        self.stack.addWidget(self.canvas)
        self.stack.addWidget(self.web)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.bar)
        layout.addWidget(self.stack, 1)
        layout.addWidget(self.bottom)
        for w in (self.mode_box, self.rtl_box, self.prev_btn, self.next_btn, self.web, self.canvas, self.left_btn,
                  self.right_btn, self.full_btn, self.close_btn, self.page_slider):
            w.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._syncing = False
        self._apply_direction()

        self.mode_box.currentIndexChanged.connect(lambda: self.set_mode(self.mode_box.currentData()))
        self.rtl_box.toggled.connect(self.set_rtl)
        self.prev_btn.clicked.connect(lambda: self.open_chapter(self.index - 1))
        self.next_btn.clicked.connect(lambda: self.open_chapter(self.index + 1))
        self.left_btn.clicked.connect(lambda: self._press_arrow("left"))
        self.right_btn.clicked.connect(lambda: self._press_arrow("right"))
        self.full_btn.clicked.connect(self.toggle_fullscreen)
        self.close_btn.clicked.connect(self.close)
        self.page_slider.valueChanged.connect(self._slider_moved)
        self.canvas.clicked_side.connect(self._on_click_side)
        self.canvas.zoom_changed.connect(lambda z: self._remember("manga.reader.zoom", round(z, 3)))
        self.canvas.menu_requested.connect(self._show_page_menu)
        self.web.width_changed.connect(lambda w: self._remember("manga.reader.webtoon_width", int(w)))
        self.web.need_page.connect(self._ensure)
        self.web.page_changed.connect(self._on_web_page)
        self.web.page_menu_requested.connect(self._show_web_page_menu)
        self.save_timer = QTimer(self)
        self.save_timer.setSingleShot(True)
        self.save_timer.timeout.connect(self._save_progress)
        self.setFocus()
        self.open_chapter(index)

    def _remember(self, key: str, value) -> None:
        self.ctx.cfg.set(key, value, save=False)
        self._cfg_timer.start(600)

    def _zoom_step(self, steps: float) -> None:
        if self.mode == "webtoon":
            self.web.zoom_steps(steps)
        else:
            self.canvas.set_zoom(self.canvas.zoom * STEP ** steps)

    def _zoom_reset(self) -> None:
        if self.mode == "webtoon":
            self.web.set_column(WebtoonView.DEFAULT_COLUMN)
        else:
            self.canvas.set_zoom(1.0)
            self.canvas.reset_pan()

    def _slide_direction(self, forward: bool) -> int:
        """Which way the page on screen leaves: to the left for a forward flip, except in right-to-left reading."""
        return (1 if forward else -1) * (-1 if self.rtl else 1)

    def _tool(self, icon: str, tip_key: str, size: int = 20, side: int = 38) -> QToolButton:
        button = QToolButton()
        button.setProperty("viewer", True)
        button.setToolTip(tr(tip_key))
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setFixedSize(side, 38)
        style.bind_icon(button, icon, "normal", size)
        return button

    def _press_arrow(self, side: str) -> None:
        """The on-screen arrows point where the picture moves: in right-to-left mode the left arrow goes forward."""
        self._on_click_side(side)

    def _apply_direction(self) -> None:
        rtl = self.rtl and self.mode != "webtoon"
        self.page_slider.setInvertedAppearance(rtl)
        self.left_btn.setToolTip(tr("reader.next_page" if rtl else "reader.prev_page"))
        self.right_btn.setToolTip(tr("reader.prev_page" if rtl else "reader.next_page"))

    def _slider_moved(self, value: int) -> None:
        if not self._syncing and self.pages and value != self.page:
            self._goto(value, initial=self.mode == "webtoon")

    # --- chapters / pages --------------------------------------------------------------------------------

    @property
    def chapter(self) -> dict:
        return self.chapters[self.index]

    def open_chapter(self, index: int, last_page: bool = False) -> None:
        if not 0 <= index < len(self.chapters):
            return
        self._flush_progress()
        if self.mode != "webtoon":
            self.canvas.start_slide(self._slide_direction(index > self.index))
        self.index = index
        self._token += 1
        token = self._token
        self.pages, self.images, self.loading, self._marked_read = [], {}, set(), False
        self.canvas.show_images([], tr("status.loading"))
        self.web.set_pages(0)
        self._update_title()
        chapter = self.chapter

        def done(pages: list[str]) -> None:
            if token != self._token:
                return
            self.pages = pages
            if not pages:
                self.canvas.show_images([], tr("reader.no_pages"))
                return
            start = len(pages) - 1 if last_page else (0 if chapter["isRead"] else min(chapter["lastPageRead"], len(pages) - 1))
            self.web.set_pages(len(pages))
            self.page = max(start, 0)
            self._show_mode_widget()
            self._goto(self.page, initial=True)

        run_async(self.api.chapter_pages, chapter["id"], on_done=done,
                  on_error=lambda exc: token == self._token and self.canvas.show_images([], tr("status.error", msg=str(exc))))

    def _ensure(self, i: int) -> None:
        if not 0 <= i < len(self.pages) or i in self.images or i in self.loading:
            return
        self.loading.add(i)
        token, url = self._token, self.pages[i]

        def fetch() -> QImage:
            img = QImage.fromData(self.api.fetch_bytes(url))
            if img.isNull():
                raise ValueError("bad image")
            return img

        def done(img: QImage) -> None:
            self.loading.discard(i)
            if token != self._token:
                return
            self.images[i] = img
            self._trim_cache()
            self.web.set_image(i, img)
            if self.mode != "webtoon":
                self._refresh_canvas()

        run_async(fetch, on_done=done, on_error=lambda exc: self.loading.discard(i))

    def _trim_cache(self) -> None:
        if len(self.images) > MAX_CACHED:
            for k in sorted(self.images, key=lambda k: abs(k - self.page))[MAX_CACHED:]:
                if self.mode != "webtoon":
                    del self.images[k]

    # --- navigation --------------------------------------------------------------------------------------

    def _shown(self) -> list[int]:
        return spread_at(self.images, len(self.pages), self.page, self.mode == "double")

    def _goto(self, i: int, initial: bool = False) -> None:
        if not self.pages:
            return
        previous = self.page
        self.page = min(max(i, 0), len(self.pages) - 1)
        if self.mode != "webtoon" and not initial and self.page != previous:
            self.canvas.start_slide(self._slide_direction(self.page > previous))
        if self.mode == "webtoon":
            for k in range(self.page, self.page + PRELOAD_AHEAD + 1):
                self._ensure(k)
            if initial:
                QTimer.singleShot(0, lambda: self.web.scroll_to_page(self.page))
        else:
            for k in range(self.page - 1, self.page + PRELOAD_AHEAD + 1):
                self._ensure(k)
            if self.page != previous:
                self.canvas.reset_pan()
            self._refresh_canvas()
        self._page_changed()

    def _refresh_canvas(self) -> None:
        shown = self._shown()
        self.canvas.show_images([self.images.get(k) for k in shown])
        if shown != [self.page]:
            self._page_changed()

    def _page_changed(self) -> None:
        self._update_title()
        self.save_timer.start(1200)

    def next_page(self) -> None:
        if self.mode == "webtoon":
            bar = self.web.verticalScrollBar()
            if bar.value() >= bar.maximum():
                self.open_chapter(self.index + 1)
            else:
                self.web.scroll_by(int(self.web.viewport().height() * 0.9))
            return
        last = self._shown()[-1]
        if last >= len(self.pages) - 1:
            self._mark_read()
            self.open_chapter(self.index + 1)
        else:
            self._goto(last + 1)

    def prev_page(self) -> None:
        if self.mode == "webtoon":
            bar = self.web.verticalScrollBar()
            if bar.value() <= 0:
                self.open_chapter(self.index - 1, last_page=True)
            else:
                self.web.scroll_by(-int(self.web.viewport().height() * 0.9))
            return
        if self.page <= 0:
            self.open_chapter(self.index - 1, last_page=True)
        else:
            self._goto(step_back(self.images, len(self.pages), self.page, self.mode == "double"))

    def _on_click_side(self, side: str) -> None:
        forward = (side == "left") if (self.rtl and self.mode != "webtoon") else (side == "right")
        self.next_page() if forward else self.prev_page()

    def _page_filename(self, i: int) -> str:
        title = self.manga.get("title", "manga")
        name = self.chapter.get("name", "")
        return f"{title} - {name} - p{i + 1:03d}.png".replace("/", "-")

    def _show_page_menu(self, pos) -> None:
        """A right click on the paged canvas: whichever half of a double-page spread was clicked."""
        shown = self._shown()
        if not shown:
            return
        i = shown[0] if pos.x() < self.canvas.width() / 2 else shown[-1]
        img = self.images.get(i)
        if img is not None:
            show_image_menu(self.canvas, self.canvas.mapToGlobal(pos), image=img, suggested_name=self._page_filename(i))

    def _show_web_page_menu(self, i: int, global_pos) -> None:
        img = self.web.images.get(i)
        if img is not None:
            show_image_menu(self.web, global_pos, image=img, suggested_name=self._page_filename(i))

    def _on_web_page(self, i: int) -> None:
        if i != self.page:
            self.page = i
            self._page_changed()

    # --- settings ----------------------------------------------------------------------------------------

    def set_mode(self, mode: str) -> None:
        if mode == self.mode:
            return
        self.mode = mode
        self.ctx.cfg.set("manga.reader.mode", mode)
        self._apply_direction()
        self._show_mode_widget()
        self._goto(self.page, initial=True)
        if mode == "webtoon":
            for i, img in self.images.items():
                self.web.set_image(i, img)

    def set_rtl(self, value: bool) -> None:
        self.rtl = value
        self.canvas.rtl = value
        self._apply_direction()
        self.ctx.cfg.set("manga.reader.rtl", value)
        self.canvas.update()

    def _show_mode_widget(self) -> None:
        self.stack.setCurrentWidget(self.web if self.mode == "webtoon" else self.canvas)

    def cycle_mode(self) -> None:
        self.mode_box.setCurrentIndex((MODES.index(self.mode) + 1) % len(MODES))

    def toggle_fullscreen(self) -> None:
        if self.isFullScreen():
            self.showNormal()
            self.bar.show()
        else:
            self.bar.hide()  # the bottom bar stays: it has the fullscreen button to come back
            self.showFullScreen()
        style.bind_icon(self.full_btn, "minimize" if self.isFullScreen() else "maximize", "normal", 20)

    # --- progress ----------------------------------------------------------------------------------------

    def _update_title(self) -> None:
        n = len(self.pages)
        self.title.setText(f"{self.manga['title']} — {self.chapter['name']}")
        self.setWindowTitle(self.title.text())
        self.prev_btn.setEnabled(self.index > 0)
        self.next_btn.setEnabled(self.index < len(self.chapters) - 1)
        self._syncing = True
        self.page_slider.setRange(0, max(n - 1, 0))
        self.page_slider.setValue(self.page)
        self.page_slider.setEnabled(n > 1)
        self._syncing = False
        self.page_label.setText(f"{self.page + 1} / {n}" if n else "–")

    def _reached_end(self) -> bool:
        if not self.pages:
            return False
        if self.mode == "webtoon":
            bar = self.web.verticalScrollBar()
            return self.page >= len(self.pages) - 1 and bar.value() >= bar.maximum() - 5
        return self._shown()[-1] >= len(self.pages) - 1

    def _mark_read(self) -> None:
        if self._marked_read:
            return
        self._marked_read = True
        cid = self.chapter["id"]
        self.chapter["isRead"] = True
        manga_id = self.manga.get("id")

        def work() -> None:
            self.api.update_chapters([cid], is_read=True)
            if manga_id is not None:
                self.api.sync_tracking(manga_id)          # MyAnimeList / AniList / Kitsu, when the title is bound

        run_async(work, on_done=lambda _: self._notify())

    def _save_progress(self) -> None:
        if not self.pages:
            return
        cid, page = self.chapter["id"], self.page
        self.chapter["lastPageRead"] = page
        if self._reached_end():
            self._mark_read()
        run_async(lambda: self.api.update_chapters([cid], last_page_read=page), on_done=lambda _: self._notify())

    def _flush_progress(self) -> None:
        if self.save_timer.isActive():
            self.save_timer.stop()
            self._save_progress()

    def _notify(self) -> None:
        if self.on_progress:
            self.on_progress()

    # --- events ------------------------------------------------------------------------------------------

    def keyPressEvent(self, e: QKeyEvent) -> None:
        k = e.key()
        if k == Qt.Key.Key_Left:
            self.next_page() if (self.rtl and self.mode != "webtoon") else self.prev_page()
        elif k == Qt.Key.Key_Right:
            self.prev_page() if (self.rtl and self.mode != "webtoon") else self.next_page()
        elif k in (Qt.Key.Key_Space, Qt.Key.Key_PageDown):
            self.next_page()
        elif k in (Qt.Key.Key_Backspace, Qt.Key.Key_PageUp):
            self.prev_page()
        elif k == Qt.Key.Key_Down and self.mode == "webtoon":
            self.web.scroll_by(120)
        elif k == Qt.Key.Key_Up and self.mode == "webtoon":
            self.web.scroll_by(-120)
        elif k == Qt.Key.Key_BracketRight:
            self.open_chapter(self.index + 1)
        elif k == Qt.Key.Key_BracketLeft:
            self.open_chapter(self.index - 1)
        elif k == Qt.Key.Key_Home:
            self._goto(0, initial=True)
        elif k == Qt.Key.Key_End:
            self._goto(len(self.pages) - 1, initial=True)
        elif k in (Qt.Key.Key_Plus, Qt.Key.Key_Equal):
            self._zoom_step(1)
        elif k == Qt.Key.Key_Minus:
            self._zoom_step(-1)
        elif k == Qt.Key.Key_0:
            self._zoom_reset()
        elif k == Qt.Key.Key_M:
            self.cycle_mode()
        elif k == Qt.Key.Key_R:
            self.rtl_box.toggle()
        elif k in (Qt.Key.Key_F, Qt.Key.Key_F11):
            self.toggle_fullscreen()
        elif k == Qt.Key.Key_Escape:
            self.toggle_fullscreen() if self.isFullScreen() else self.close()
        else:
            super().keyPressEvent(e)

    def wheelEvent(self, e) -> None:
        if e.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self._zoom_step(e.angleDelta().y() / 120)                 # Ctrl + wheel anywhere in the window
        elif self.mode != "webtoon":
            (self.prev_page if e.angleDelta().y() > 0 else self.next_page)()

    def closeEvent(self, event) -> None:
        self._token += 1
        self._flush_progress()
        super().closeEvent(event)
