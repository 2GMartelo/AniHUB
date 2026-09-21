"""Full viewer: still images, animated GIF/WebP, video (QtMultimedia), tag panel, slideshow, fullscreen."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QBrush, QColor, QGuiApplication, QImageReader, QKeyEvent, QMovie, QPixmap, QResizeEvent
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMenu, QSizePolicy, QSlider, QStackedWidget, QToolButton,
    QVBoxLayout, QWidget,
)

from anihub.core.i18n import tr
from anihub.ui import style
from anihub.ui.zoomview import ZoomLabel
from anihub.ui.workers import run_async

VIDEO_SUFFIXES = {".mp4", ".webm", ".mkv", ".mov"}
CATEGORY_ORDER = ["artist", "copyright", "character", "general", "meta"]
CATEGORY_COLORS = {"artist": "#e0575a", "copyright": "#d070d6", "character": "#3fb95a", "meta": "#f0a030"}


@dataclass
class ViewItem:
    title: str
    info: str
    fetch: Callable[[], Path]  # blocking, runs in a worker thread; returns a local file
    page_url: str = ""
    tags: list[tuple[str, str]] = field(default_factory=list)  # (name, category)
    payload: Any = None  # original object (e.g. Post) for the save callback
    favorite: bool = False  # library items only; kept in sync by the viewer
    stars: int = 0


class TagRow(QWidget):
    """A tag with its own buttons: the name searches for it alone, + adds it to the current search, − excludes it."""

    def __init__(self, name: str, color: str | None, on_action: Callable[[str], None], parent=None):
        super().__init__(parent)
        self.name = name
        self.label = QLabel(name)
        self.label.setCursor(Qt.CursorShape.PointingHandCursor)
        self.label.setToolTip(tr("tag.search"))
        if color:
            self.label.setStyleSheet(f"color: {color};")
        self.plus = QToolButton(text="+")
        self.minus = QToolButton(text="−")
        for button, key in ((self.plus, "tag.add"), (self.minus, "tag.exclude")):
            button.setProperty("tagbtn", True)
            button.setToolTip(tr(key))
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setFixedSize(22, 22)
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        row = QHBoxLayout(self)
        row.setContentsMargins(4, 0, 2, 0)
        row.setSpacing(4)
        row.addWidget(self.label, 1)
        row.addWidget(self.plus)
        row.addWidget(self.minus)
        self.plus.clicked.connect(lambda: on_action("add"))
        self.minus.clicked.connect(lambda: on_action("exclude"))
        self.label.mousePressEvent = lambda e: on_action("search")          # type: ignore[method-assign]


def fmt_time(ms: int) -> str:
    s = max(ms, 0) // 1000
    return f"{s // 60}:{s % 60:02d}"


class Viewer(QWidget):
    SLIDESHOW_MS = 4000
    tag_action = Signal(str, str)  # (tag, 'search' | 'add' | 'exclude')

    def __init__(self, items: list[ViewItem], index: int, on_save: Callable[[ViewItem], None] | None = None,
                 parent=None, on_favorite: Callable[[ViewItem, bool], None] | None = None,
                 on_stars: Callable[[ViewItem, int], None] | None = None):
        super().__init__(parent, Qt.WindowType.Window)
        self.items, self.index, self.on_save = items, index, on_save
        self.on_favorite, self.on_stars = on_favorite, on_stars
        self._pixmap: QPixmap | None = None
        self._movie: QMovie | None = None
        self._movie_size = QSize()
        self._request = 0
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.resize(1300, 850)

        # media area
        self.image = ZoomLabel(alignment=Qt.AlignmentFlag.AlignCenter)      # Ctrl + wheel zooms, drag pans, double click resets
        self.image.setMinimumSize(200, 200)
        self.image.setWordWrap(True)
        self.video = QVideoWidget()
        self.stack = QStackedWidget()
        self.stack.addWidget(self.image)
        self.stack.addWidget(self.video)
        self.player = QMediaPlayer(self)
        self.audio = QAudioOutput(self)
        self.audio.setMuted(True)  # clips autoplay: start silent, M toggles sound
        self.player.setAudioOutput(self.audio)
        self.player.setVideoOutput(self.video)
        self.player.setLoops(QMediaPlayer.Loops.Infinite)
        self.player.errorOccurred.connect(self._player_error)

        # video controls
        self.play_btn = self._tool("pause", "viewer.playpause", size=18, side=34)
        self.seek = QSlider(Qt.Orientation.Horizontal)
        self.time_label = QLabel("0:00 / 0:00")
        self.mute_btn = self._tool("volume-x", "viewer.mute", size=18, side=34)
        self.controls = QWidget()
        row = QHBoxLayout(self.controls)
        row.setContentsMargins(0, 0, 0, 0)
        for w in (self.play_btn, self.seek, self.time_label, self.mute_btn):
            row.addWidget(w, 1 if w is self.seek else 0)
        self.play_btn.clicked.connect(self.toggle_play)
        self.mute_btn.clicked.connect(self.toggle_mute)
        self.seek.sliderMoved.connect(self.player.setPosition)
        self.player.durationChanged.connect(lambda d: self.seek.setRange(0, d))
        self.player.positionChanged.connect(self._on_position)

        # tag panel
        self.tags = QListWidget()
        self.tags.setObjectName("tagList")
        self.tags.setFixedWidth(310)
        self.tags.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tags.customContextMenuRequested.connect(self._tag_menu)
        self.tags.itemDoubleClicked.connect(lambda it: self._emit_tag(it, "search"))

        # Keys (arrows, space...) must reach the viewer, not the child widgets.
        for w in (self.tags, self.play_btn, self.mute_btn, self.seek):
            w.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        self.info = QLabel(wordWrap=True)
        self.info.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.help = QLabel(tr("viewer.help"))
        self.help.setProperty("role", "muted")

        # one-hand mouse controls: big arrows at both sides + an action bar under the picture
        self.prev_btn = self._tool("chevron-left", "viewer.prev", size=28, side=52, tall=True)
        self.next_btn = self._tool("chevron-right", "viewer.next", size=28, side=52, tall=True)
        self.prev_btn.clicked.connect(lambda: self.step(-1))
        self.next_btn.clicked.connect(lambda: self.step(1))
        self.counter = QLabel()
        self.counter.setProperty("role", "dim")
        self.slide_btn = self._tool("play", "viewer.slideshow", checkable=True)
        self.slide_btn.clicked.connect(self.toggle_slideshow)
        self.fav_btn = self._tool("heart", "viewer.favorite")
        self.fav_btn.clicked.connect(self.toggle_favorite)
        self.stars_btn = self._tool("star", "viewer.stars")
        self.stars_btn.clicked.connect(self._stars_menu)
        self.save_btn = self._tool("download", "viewer.save")
        self.save_btn.clicked.connect(self._save)
        self.tags_btn = self._tool("tag", "viewer.tags", checkable=True)
        self.tags_btn.setChecked(True)
        self.tags_btn.clicked.connect(self.toggle_tags)
        self.full_btn = self._tool("maximize", "viewer.fullscreen")
        self.full_btn.clicked.connect(self.toggle_fullscreen)
        self.close_btn = self._tool("x", "viewer.close")
        self.close_btn.clicked.connect(self.close)
        self.fav_btn.setVisible(on_favorite is not None)
        self.stars_btn.setVisible(on_stars is not None)
        self.save_btn.setVisible(on_save is not None)
        self.bar = QWidget()
        bar = QHBoxLayout(self.bar)
        bar.setContentsMargins(0, 0, 0, 0)
        bar.setSpacing(8)
        bar.addWidget(self.counter)
        bar.addStretch(1)
        for w in (self.slide_btn, self.fav_btn, self.stars_btn, self.save_btn, self.tags_btn, self.full_btn, self.close_btn):
            bar.addWidget(w)
        bar.addStretch(1)
        bar.addSpacing(self.counter.sizeHint().width())

        media_col = QVBoxLayout()
        media_col.addWidget(self.stack, 1)
        media_col.addWidget(self.controls)
        top = QHBoxLayout()
        top.addWidget(self.prev_btn)
        top.addLayout(media_col, 1)
        top.addWidget(self.next_btn)
        top.addWidget(self.tags)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 10)
        layout.setSpacing(8)
        layout.addLayout(top, 1)
        layout.addWidget(self.bar)
        layout.addWidget(self.info)
        layout.addWidget(self.help)

        for w in (self.prev_btn, self.next_btn, self.slide_btn, self.fav_btn, self.stars_btn, self.save_btn,
                  self.tags_btn, self.full_btn, self.close_btn):
            w.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.timer = QTimer(self)
        self.timer.timeout.connect(lambda: self.step(1))
        self.show_current()

    def _tool(self, icon: str, tip_key: str, size: int = 20, side: int = 40, checkable: bool = False,
              tall: bool = False) -> QToolButton:
        button = QToolButton()
        button.setProperty("viewer", True)
        button.setToolTip(tr(tip_key))
        button.setCheckable(checkable)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setFixedWidth(side)
        if tall:
            button.setSizePolicy(button.sizePolicy().horizontalPolicy(), QSizePolicy.Policy.Expanding)
        else:
            button.setFixedHeight(side)
        style.bind_icon(button, icon, "normal", size)
        return button

    def _sync_actions(self) -> None:
        item = self.items[self.index]
        fav = item.favorite
        style.bind_icon(self.fav_btn, "heart-filled" if fav else "heart", "danger" if fav else "normal", 20)
        stars = item.stars
        style.bind_icon(self.stars_btn, "star-filled" if stars else "star", "accent" if stars else "normal", 20)
        self.stars_btn.setToolTip(tr("viewer.stars") + (f" · {stars}★" if stars else ""))
        self.counter.setText(f"{self.index + 1} / {len(self.items)}")
        many = len(self.items) > 1
        self.prev_btn.setEnabled(many)
        self.next_btn.setEnabled(many)

    def toggle_favorite(self) -> None:
        if self.on_favorite is None:
            return
        item = self.items[self.index]
        item.favorite = not item.favorite
        self.on_favorite(item, item.favorite)
        self._sync_actions()

    def _stars_menu(self) -> None:
        if self.on_stars is None:
            return
        menu = QMenu(self)
        for n in range(6):
            action = QAction("★" * n if n else tr("viewer.no_stars"), menu)
            action.triggered.connect(lambda _=False, v=n: self._set_stars(v))
            menu.addAction(action)
        menu.exec(self.stars_btn.mapToGlobal(self.stars_btn.rect().bottomLeft()))

    def _set_stars(self, value: int) -> None:
        item = self.items[self.index]
        item.stars = value
        if self.on_stars:
            self.on_stars(item, value)
        self._sync_actions()

    def _save(self) -> None:
        if self.on_save:
            self.on_save(self.items[self.index])

    def toggle_tags(self) -> None:
        show = self.tags.isHidden()
        self.tags.setVisible(show)
        self.tags_btn.setChecked(show)

    # --- navigation --------------------------------------------------------------

    def show_current(self) -> None:
        item = self.items[self.index]
        self.setWindowTitle(f"{item.title}  ({self.index + 1}/{len(self.items)})")
        self.info.setText(item.info)
        self._sync_actions()
        self._fill_tags(item.tags)
        self._stop_media()
        self.stack.setCurrentWidget(self.image)
        self.controls.hide()
        self.image.setText(tr("status.loading"))
        self._request += 1
        request = self._request

        def done(path: Path) -> None:
            if request == self._request:
                self._show_path(path)

        def failed(exc: Exception) -> None:
            if request == self._request:
                self.image.setText(tr("status.error", msg=str(exc)))

        run_async(item.fetch, on_done=done, on_error=failed)

    def step(self, delta: int) -> None:
        self.index = (self.index + delta) % len(self.items)
        self.show_current()

    # --- media -------------------------------------------------------------------

    def _stop_media(self) -> None:
        self.player.stop()
        self.player.setSource(QUrl())
        if self._movie is not None:
            self._movie.stop()
            self._movie = None
        self._pixmap = None
        self.image.set_source(None)
        self.image.clear()

    def _show_path(self, path: Path) -> None:
        if path.suffix.lower() in VIDEO_SUFFIXES:
            self.stack.setCurrentWidget(self.video)
            self.controls.show()
            self.player.setSource(QUrl.fromLocalFile(str(path)))
            self.player.play()
            style.bind_icon(self.play_btn, "pause", "normal", 18)
            return
        reader = QImageReader(str(path))
        if reader.supportsAnimation() and reader.imageCount() != 1:
            self._movie = QMovie(str(path))
            self._movie_size = reader.size()
            self.image.setMovie(self._movie)
            self._rescale()
            self._movie.start()
            return
        pm = QPixmap(str(path))
        if pm.isNull():
            self.image.setText(tr("viewer.unsupported", name=path.name, url=self.items[self.index].page_url))
            return
        self._pixmap = pm
        self.image.set_source(pm)                       # painted (fit to the window) by the label itself; zoom starts at "fit"

    def _rescale(self) -> None:
        if self._pixmap is None and self._movie is not None and self._movie_size.isValid():
            self._movie.setScaledSize(self._movie_size.scaled(self.image.size(), Qt.AspectRatioMode.KeepAspectRatio))

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._rescale()

    def _player_error(self, _error, message: str) -> None:
        self.stack.setCurrentWidget(self.image)
        self.controls.hide()
        self.image.setText(tr("status.error", msg=message))

    def _on_position(self, pos: int) -> None:
        if not self.seek.isSliderDown():
            self.seek.setValue(pos)
        self.time_label.setText(f"{fmt_time(pos)} / {fmt_time(self.player.duration())}")

    def _is_video(self) -> bool:
        return self.stack.currentWidget() is self.video

    def toggle_play(self) -> None:
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
            style.bind_icon(self.play_btn, "play", "normal", 18)
        else:
            self.player.play()
            style.bind_icon(self.play_btn, "pause", "normal", 18)

    def toggle_mute(self) -> None:
        self.audio.setMuted(not self.audio.isMuted())
        style.bind_icon(self.mute_btn, "volume-x" if self.audio.isMuted() else "volume", "normal", 18)

    def toggle_slideshow(self) -> None:
        self.timer.stop() if self.timer.isActive() else self.timer.start(self.SLIDESHOW_MS)
        running = self.timer.isActive()
        style.bind_icon(self.slide_btn, "pause" if running else "play", "normal", 20)
        self.slide_btn.setChecked(running)

    def toggle_fullscreen(self) -> None:
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()
        style.bind_icon(self.full_btn, "minimize" if self.isFullScreen() else "maximize", "normal", 20)

    # --- tags --------------------------------------------------------------------

    def _fill_tags(self, tags: list[tuple[str, str]]) -> None:
        self.tags.clear()
        groups: dict[str, list[str]] = {}
        for name, category in tags:
            groups.setdefault(category if category in CATEGORY_ORDER else "general", []).append(name)
        for category in CATEGORY_ORDER:
            names = groups.get(category)
            if not names:
                continue
            header = QListWidgetItem(tr(f"tagcat.{category}"))
            font = header.font()
            font.setBold(True)
            header.setFont(font)
            header.setFlags(Qt.ItemFlag.NoItemFlags)
            self.tags.addItem(header)
            for name in names:
                item = QListWidgetItem()
                item.setData(Qt.ItemDataRole.UserRole, name)
                item.setSizeHint(QSize(0, 30))
                self.tags.addItem(item)
                self.tags.setItemWidget(item, TagRow(name, CATEGORY_COLORS.get(category),
                                                     lambda mode, n=name: self.tag_action.emit(n, mode)))

    def _emit_tag(self, item: QListWidgetItem, mode: str) -> None:
        tag = item.data(Qt.ItemDataRole.UserRole)
        if tag:
            self.tag_action.emit(tag, mode)

    def _tag_menu(self, pos) -> None:
        item = self.tags.itemAt(pos)
        if item is None or not item.data(Qt.ItemDataRole.UserRole):
            return
        menu = QMenu(self)
        for mode, key in (("search", "tag.search"), ("add", "tag.add"), ("exclude", "tag.exclude")):
            action = QAction(tr(key), menu)
            action.triggered.connect(lambda _=False, m=mode: self._emit_tag(item, m))
            menu.addAction(action)
        copy = QAction(tr("tag.copy"), menu)
        copy.triggered.connect(lambda: QGuiApplication.clipboard().setText(item.data(Qt.ItemDataRole.UserRole)))
        menu.addAction(copy)
        menu.exec(self.tags.mapToGlobal(pos))

    # --- events ------------------------------------------------------------------

    def keyPressEvent(self, event: QKeyEvent) -> None:
        key = event.key()
        if key in (Qt.Key.Key_Right, Qt.Key.Key_D):
            self.step(1)
        elif key in (Qt.Key.Key_Left, Qt.Key.Key_A):
            self.step(-1)
        elif key == Qt.Key.Key_Space:
            self.toggle_play() if self._is_video() else self.toggle_slideshow()
        elif key == Qt.Key.Key_P:
            self.toggle_slideshow()
        elif key in (Qt.Key.Key_F, Qt.Key.Key_F11):
            self.toggle_fullscreen()
        elif key == Qt.Key.Key_T:
            self.toggle_tags()
        elif key == Qt.Key.Key_L and self.on_favorite:
            self.toggle_favorite()
        elif key == Qt.Key.Key_M:
            self.toggle_mute()
        elif key == Qt.Key.Key_S and self.on_save:
            self._save()
        elif key == Qt.Key.Key_Escape:
            self.showNormal() if self.isFullScreen() else self.close()
        else:
            super().keyPressEvent(event)

    def wheelEvent(self, event) -> None:  # noqa: N802 - wheel over the picture flips through items
        delta = event.angleDelta().y()
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            event.ignore()                              # Ctrl + wheel is the picture's zoom (ZoomLabel), never a page flip
        elif delta and len(self.items) > 1:
            self.step(-1 if delta > 0 else 1)
            event.accept()
        else:
            super().wheelEvent(event)

    def closeEvent(self, event) -> None:
        self.timer.stop()
        self._stop_media()
        super().closeEvent(event)
