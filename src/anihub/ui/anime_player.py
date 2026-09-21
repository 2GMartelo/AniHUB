"""Episode player (ТЗ 10.1): QtMultimedia with resume, speed, quality, auto-next and progress tracking."""
from __future__ import annotations

import subprocess
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QKeyEvent
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QComboBox, QHBoxLayout, QLabel, QSlider, QToolButton, QVBoxLayout, QWidget,
)

from anihub.context import AppContext
from anihub.core.i18n import tr
from anihub.sources.anime.base import AnimeEntry, AnimeSource, Episode, Stream
from anihub.ui import style
from anihub.ui.workers import run_async

SPEEDS = (0.5, 0.75, 1.0, 1.25, 1.5, 2.0)
SAVE_EVERY_MS = 5000
SEEK_MS = 10_000


def fmt(ms: int) -> str:
    s = max(int(ms), 0) // 1000
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60}:{s % 60:02d}"


def stream_url(stream: Stream, http=None) -> QUrl:
    """Local paths become file URLs; streams that need headers go through the local proxy (the player cannot send headers)."""
    if "://" not in stream.url:
        return QUrl.fromLocalFile(str(Path(stream.url)))
    if stream.headers and http is not None:
        from anihub.net.streamproxy import proxy_for

        return QUrl(proxy_for(http).url_for(stream.url, stream.headers))
    return QUrl(stream.url)


def external_command(player: str, stream: Stream) -> list[str]:
    """Command line for an external player (mpv-style header option when the stream needs headers)."""
    cmd = [player]
    if stream.headers and "mpv" in Path(player).name.lower():
        cmd.append("--http-header-fields=" + ",".join(f"{k}: {v}" for k, v in stream.headers.items()))
    if stream.headers and "vlc" in Path(player).name.lower() and "Referer" in stream.headers:
        cmd.append(f"--http-referrer={stream.headers['Referer']}")
    cmd.append(stream.url)
    return cmd


class AnimePlayer(QWidget):
    progress_changed = Signal()          # something was saved: the watch tab refreshes its marks

    def __init__(self, ctx: AppContext, source: AnimeSource, entry: AnimeEntry, episodes: list[Episode], index: int, parent=None):
        super().__init__(parent, Qt.WindowType.Window)
        self.ctx, self.source, self.entry, self.episodes, self.index = ctx, source, entry, episodes, index
        self.watch = ctx.watch
        self.streams: list[Stream] = []
        self._request = 0
        self._seek_to = 0
        self._ended = False
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.resize(1180, 720)

        self.video = QVideoWidget()
        self.player = QMediaPlayer(self)
        self.audio = QAudioOutput(self)
        self.player.setAudioOutput(self.audio)
        self.player.setVideoOutput(self.video)
        self.audio.setVolume(float(ctx.cfg.get("anime.volume", 0.8)))

        self.title = QLabel()
        style.role(self.title, "dim")
        self.message = QLabel()
        self.message.setWordWrap(True)
        self.prev_btn = self._tool("skip-back", "reader.prev_chapter")
        self.play_btn = self._tool("pause", "viewer.playpause", size=22)
        self.next_btn = self._tool("skip-forward", "reader.next_chapter")
        self.back_btn = self._tool("chevrons-left", "watch.back10")
        self.fwd_btn = self._tool("chevrons-right", "watch.fwd10")
        self.mute_btn = self._tool("volume", "viewer.mute")
        self.full_btn = self._tool("maximize", "reader.fullscreen")
        self.ext_btn = self._tool("external", "watch.external")
        self.seek = QSlider(Qt.Orientation.Horizontal)
        self.time_label = QLabel("0:00 / 0:00")
        self.time_label.setMinimumWidth(110)
        self.volume = QSlider(Qt.Orientation.Horizontal)
        self.volume.setRange(0, 100)
        self.volume.setValue(int(self.audio.volume() * 100))
        self.volume.setFixedWidth(90)
        self.speed = QComboBox()
        for s in SPEEDS:
            self.speed.addItem(f"{s:g}×", s)
        self.speed.setCurrentIndex(SPEEDS.index(1.0))
        self.quality = QComboBox()
        self.quality.setMinimumWidth(90)

        bar = QHBoxLayout()
        bar.setContentsMargins(10, 4, 10, 8)
        bar.setSpacing(8)
        for w in (self.prev_btn, self.back_btn, self.play_btn, self.fwd_btn, self.next_btn):
            bar.addWidget(w)
        bar.addWidget(self.time_label)
        bar.addWidget(self.seek, 1)
        for w in (self.quality, self.speed, self.mute_btn, self.volume, self.ext_btn, self.full_btn):
            bar.addWidget(w)
        self.bar = QWidget()
        self.bar.setLayout(bar)
        head = QHBoxLayout()
        head.setContentsMargins(12, 6, 12, 0)
        head.addWidget(self.title, 1)
        head.addWidget(self.message, 2)
        self.head = QWidget()
        self.head.setLayout(head)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.head)
        layout.addWidget(self.video, 1)
        layout.addWidget(self.bar)
        for w in (self.prev_btn, self.play_btn, self.next_btn, self.back_btn, self.fwd_btn, self.mute_btn, self.full_btn,
                  self.ext_btn, self.seek, self.volume, self.speed, self.quality):
            w.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        self.save_timer = QTimer(self)
        self.save_timer.timeout.connect(self.save)
        self.save_timer.start(SAVE_EVERY_MS)
        self.prev_btn.clicked.connect(lambda: self.open_episode(self.index - 1))
        self.next_btn.clicked.connect(lambda: self.open_episode(self.index + 1))
        self.play_btn.clicked.connect(self.toggle_play)
        self.back_btn.clicked.connect(lambda: self.skip(-SEEK_MS))
        self.fwd_btn.clicked.connect(lambda: self.skip(SEEK_MS))
        self.mute_btn.clicked.connect(self.toggle_mute)
        self.full_btn.clicked.connect(self.toggle_fullscreen)
        self.ext_btn.clicked.connect(self.open_external)
        self.seek.sliderMoved.connect(self.player.setPosition)
        self.volume.valueChanged.connect(self._volume)
        self.speed.activated.connect(lambda _i: self.player.setPlaybackRate(self.speed.currentData()))
        self.quality.activated.connect(self._quality)
        self.player.durationChanged.connect(lambda d: self.seek.setRange(0, d))
        self.player.positionChanged.connect(self._position)
        self.player.mediaStatusChanged.connect(self._status)
        self.player.playbackStateChanged.connect(self._state)
        self.player.errorOccurred.connect(lambda _e, msg: self._error(msg))
        self.open_episode(index)

    def _tool(self, icon: str, tip_key: str, size: int = 20) -> QToolButton:
        b = QToolButton()
        b.setProperty("viewer", True)
        b.setToolTip(tr(tip_key))
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.setFixedSize(38, 38)
        style.bind_icon(b, icon, "normal", size)
        return b

    # --- episodes ----------------------------------------------------------------------------------

    @property
    def episode(self) -> Episode:
        return self.episodes[self.index]

    def open_episode(self, index: int) -> None:
        if not 0 <= index < len(self.episodes):
            return
        self.save()
        self.index = index
        self._ended = False
        self._request += 1
        request = self._request
        self.player.stop()
        self.title.setText(f"{self.entry.title} · {self._label(self.episode)}")
        self.setWindowTitle(self.title.text())
        self.prev_btn.setEnabled(index > 0)
        self.next_btn.setEnabled(index < len(self.episodes) - 1)
        self.message.setText(tr("status.loading"))
        self.quality.clear()
        episode = self.episode

        def done(streams: list[Stream]) -> None:
            if request != self._request:
                return
            self.streams = streams
            if not streams:
                self.message.setText(tr("watch.no_streams"))
                return
            for s in streams:
                self.quality.addItem(s.label or tr("watch.stream"), s)
            self.play_stream(streams[0])

        run_async(lambda: self.source.streams(self.entry, episode), on_done=done,
                  on_error=lambda exc: request == self._request and self.message.setText(tr("status.error", msg=str(exc))))

    @staticmethod
    def _label(episode: Episode) -> str:
        number = f"{episode.number:g}"
        return tr("watch.episode_n", n=number) + (f" — {episode.title}" if episode.title and episode.title != number else "")

    def play_stream(self, stream: Stream) -> None:
        self.message.clear()
        self._seek_to = self.watch.resume_ms(self.source.name, self.entry.id, self.episode)
        self.player.setSource(stream_url(stream, self.ctx.http))
        self.player.setPlaybackRate(self.speed.currentData())
        self.player.play()

    def _quality(self, _i: int) -> None:
        stream = self.quality.currentData()
        if stream is not None:
            self._seek_to = self.player.position()
            self.player.setSource(stream_url(stream, self.ctx.http))
            self.player.play()

    def open_external(self) -> None:
        stream = self.quality.currentData() or (self.streams[0] if self.streams else None)
        if stream is None:
            return
        player = str(self.ctx.cfg.get("anime.external_player", "") or "")
        try:
            if player:
                subprocess.Popen(external_command(player, stream), creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))          # noqa: S603 - the user's own configured player
            else:
                import os

                os.startfile(stream.url)
            self.player.pause()
        except OSError as exc:
            self.message.setText(tr("status.error", msg=str(exc)))

    # --- playback ----------------------------------------------------------------------------------

    def _status(self, status) -> None:
        M = QMediaPlayer.MediaStatus
        if status in (M.LoadedMedia, M.BufferedMedia) and self._seek_to:
            self.player.setPosition(self._seek_to)
            self._seek_to = 0
        elif status == M.EndOfMedia:
            self._ended = True
            self.save(force_end=True)
            if self.ctx.cfg.get("anime.autoplay_next", True) and self.index < len(self.episodes) - 1:
                self.open_episode(self.index + 1)

    def _state(self, state) -> None:
        playing = state == QMediaPlayer.PlaybackState.PlayingState
        style.bind_icon(self.play_btn, "pause" if playing else "play", "normal", 22)

    def _position(self, pos: int) -> None:
        if not self.seek.isSliderDown():
            self.seek.setValue(pos)
        self.time_label.setText(f"{fmt(pos)} / {fmt(self.player.duration())}")

    def _error(self, message: str) -> None:
        self.message.setText(tr("watch.play_error", msg=message))

    def toggle_play(self) -> None:
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def skip(self, delta: int) -> None:
        self.player.setPosition(max(0, min(self.player.position() + delta, self.player.duration() or 10**9)))

    def toggle_mute(self) -> None:
        self.audio.setMuted(not self.audio.isMuted())
        style.bind_icon(self.mute_btn, "volume-x" if self.audio.isMuted() else "volume", "normal", 20)

    def _volume(self, value: int) -> None:
        self.audio.setVolume(value / 100)
        self.ctx.cfg.set("anime.volume", value / 100)

    def toggle_fullscreen(self) -> None:
        full = not self.isFullScreen()
        self.showFullScreen() if full else self.showNormal()
        self.head.setVisible(not full)
        style.bind_icon(self.full_btn, "minimize" if full else "maximize", "normal", 20)

    # --- progress ----------------------------------------------------------------------------------

    def save(self, force_end: bool = False) -> None:
        if not self.streams:
            return
        duration = int(self.player.duration())
        position = duration if force_end else int(self.player.position())
        if duration <= 0 or (position <= 0 and not force_end):
            return
        self._record(position, duration)

    def _record(self, position: int, duration: int) -> None:
        self.watch.record(self.source.name, self.entry.id, self.episode, position, duration)
        self.progress_changed.emit()

    def keyPressEvent(self, e: QKeyEvent) -> None:  # noqa: N802
        k, shift = e.key(), bool(e.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        if k == Qt.Key.Key_Space:
            self.toggle_play()
        elif k == Qt.Key.Key_Right:
            self.skip(6 * SEEK_MS if shift else SEEK_MS)
        elif k == Qt.Key.Key_Left:
            self.skip(-6 * SEEK_MS if shift else -SEEK_MS)
        elif k == Qt.Key.Key_Up:
            self.volume.setValue(min(100, self.volume.value() + 5))
        elif k == Qt.Key.Key_Down:
            self.volume.setValue(max(0, self.volume.value() - 5))
        elif k == Qt.Key.Key_N:
            self.open_episode(self.index + 1)
        elif k == Qt.Key.Key_P:
            self.open_episode(self.index - 1)
        elif k == Qt.Key.Key_M:
            self.toggle_mute()
        elif k in (Qt.Key.Key_F, Qt.Key.Key_F11):
            self.toggle_fullscreen()
        elif k == Qt.Key.Key_Escape:
            self.toggle_fullscreen() if self.isFullScreen() else self.close()
        else:
            super().keyPressEvent(e)

    def closeEvent(self, event) -> None:  # noqa: N802
        self.save_timer.stop()
        self.save()
        self.player.stop()
        self.player.setSource(QUrl())
        super().closeEvent(event)
