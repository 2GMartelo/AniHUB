"""Radio tab: Anison.FM and the user's own stations."""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtMultimedia import QAudioOutput, QMediaMetaData, QMediaPlayer
from PySide6.QtWidgets import (
    QDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton, QSlider, QToolButton,
    QVBoxLayout, QWidget,
)

from anihub.context import AppContext
from anihub.core.i18n import tr
from anihub.net.http import HttpError
from anihub.services import radio
from anihub.services.radio import Station
from anihub.ui import style
from anihub.ui.workers import run_async

STATUS_EVERY_MS = 15_000


class StationDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("radio.add"))
        self.resize(520, 150)
        self.name = QLineEdit(placeholderText=tr("radio.name"))
        self.url = QLineEdit(placeholderText="https://…/stream  ·  .pls  ·  .m3u")
        form = QFormLayout()
        form.addRow(tr("radio.name"), self.name)
        form.addRow(tr("radio.url"), self.url)
        ok = style.primary(QPushButton(tr("settings.save")), "check")
        ok.clicked.connect(self.accept)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(ok, 0, Qt.AlignmentFlag.AlignRight)


class RadioTab(QWidget):
    def __init__(self, ctx: AppContext, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.station: Station | None = None
        self._request = 0
        self.player = QMediaPlayer(self)
        self.audio = QAudioOutput(self)
        self.audio.setVolume(float(ctx.cfg.get("music.volume", 0.7)))
        self.player.setAudioOutput(self.audio)

        self.list = QListWidget()
        self.add_btn = style.secondary(QPushButton(tr("radio.add")), "plus")
        self.remove_btn = style.ghost(QPushButton(tr("radio.remove")), "x")
        self.play_btn = self._tool("play", "viewer.playpause", 22)
        self.now = QLabel(tr("radio.pick"))
        self.now.setStyleSheet("font-size: 15px; font-weight: 600;")
        self.now.setWordWrap(True)
        self.state = style.role(QLabel(), "dim")
        self.volume = QSlider(Qt.Orientation.Horizontal)
        self.volume.setRange(0, 100)
        self.volume.setValue(int(self.audio.volume() * 100))
        self.volume.setFixedWidth(120)
        hint = style.role(QLabel(tr("radio.hint")), "dim")
        hint.setWordWrap(True)
        top = QHBoxLayout()
        top.addWidget(self.add_btn)
        top.addWidget(self.remove_btn)
        top.addStretch(1)
        bar = QHBoxLayout()
        bar.addWidget(self.play_btn)
        info = QVBoxLayout()
        info.addWidget(self.now)
        info.addWidget(self.state)
        bar.addLayout(info, 1)
        bar.addWidget(self.volume)
        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(self.list, 1)
        layout.addWidget(hint)
        layout.addLayout(bar)
        for w in (self.play_btn, self.volume):
            w.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        self._poll = QTimer(self)
        self._poll.timeout.connect(self._poll_status)
        self.list.itemDoubleClicked.connect(lambda it: self.play(it.data(Qt.ItemDataRole.UserRole)))
        self.list.itemSelectionChanged.connect(self._selection)
        self.add_btn.clicked.connect(self._add)
        self.remove_btn.clicked.connect(self._remove)
        self.play_btn.clicked.connect(self.toggle)
        self.volume.valueChanged.connect(self._volume)
        self.player.playbackStateChanged.connect(self._state)
        self.player.metaDataChanged.connect(self._meta)
        self.player.mediaStatusChanged.connect(self._media_status)
        self.player.errorOccurred.connect(lambda _e, msg: self.state.setText(tr("radio.error", msg=msg)))
        self.reload()

    def _tool(self, icon: str, tip_key: str, size: int = 20) -> QToolButton:
        b = QToolButton()
        b.setProperty("viewer", True)
        b.setToolTip(tr(tip_key))
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.setFixedSize(44, 44)
        style.bind_icon(b, icon, "normal", size)
        return b

    # --- stations ------------------------------------------------------------------------------------------------

    def reload(self) -> None:
        self.list.clear()
        for st in radio.stations(self.ctx.cfg):
            item = QListWidgetItem(st.name + ("   ·   " + tr("radio.mine") if st.custom else ""))
            item.setData(Qt.ItemDataRole.UserRole, st)
            self.list.addItem(item)
        self._selection()

    def _selected(self) -> Station | None:
        item = self.list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _selection(self) -> None:
        st = self._selected()
        self.remove_btn.setEnabled(bool(st and st.custom))

    def _add(self) -> None:
        dlg = StationDialog(self)
        if dlg.exec() and radio.add_station(self.ctx.cfg, dlg.name.text(), dlg.url.text()):
            self.reload()

    def _remove(self) -> None:
        st = self._selected()
        if st and st.custom:
            radio.remove_station(self.ctx.cfg, st.url)
            self.reload()

    # --- playback ------------------------------------------------------------------------------------------------

    def play(self, station: Station) -> None:
        self.station = station
        self._request += 1
        request = self._request
        self.now.setText(station.name)
        self.state.setText(tr("status.loading"))
        if radio.is_playlist_url(station.url):
            def done(url: str | None) -> None:
                if request != self._request:
                    return
                if url:
                    self._start(url)
                else:
                    self.state.setText(tr("radio.error", msg=tr("radio.bad_playlist")))

            run_async(lambda: radio.first_stream(self.ctx.http.get_text(station.url)), on_done=done,
                      on_error=lambda exc: request == self._request and self.state.setText(tr("radio.error", msg=str(exc))))
        else:
            self._start(station.url)

    def _start(self, url: str) -> None:
        self.player.setSource(QUrl(url))
        self.player.play()
        if self.station and self.station.status_url:
            self._poll_status()
            self._poll.start(STATUS_EVERY_MS)
        else:
            self._poll.stop()

    def toggle(self) -> None:
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.stop()                                              # a live stream: stop, do not pause (no buffer to resume)
            self._poll.stop()
        else:
            st = self.station or self._selected()
            if st is not None:
                self.play(st)

    def stop(self) -> None:
        self.player.stop()
        self._poll.stop()

    def _poll_status(self) -> None:
        st = self.station
        if st is None or not st.status_url:
            return
        request = self._request

        def done(text: str) -> None:
            if request == self._request and text and self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
                self.state.setText(text)

        run_async(lambda: radio.now_playing(self.ctx.http.get_json(st.status_url)), on_done=done, on_error=lambda _e: None)

    def _meta(self) -> None:
        """Stations that put the title into the stream (ICY tags) show it here."""
        if self.station is not None and self.station.status_url:
            return
        title = self.player.metaData().value(QMediaMetaData.Key.Title)
        if title:
            self.state.setText(str(title))

    def _media_status(self, status) -> None:
        M = QMediaPlayer.MediaStatus
        if status == M.BufferingMedia or status == M.LoadingMedia:
            self.state.setText(tr("status.loading"))
        elif status == M.InvalidMedia:
            self.state.setText(tr("radio.error", msg=tr("radio.invalid")))

    def _state(self, state) -> None:
        playing = state == QMediaPlayer.PlaybackState.PlayingState
        style.bind_icon(self.play_btn, "stop" if playing else "play", "normal", 22)
        if not playing and self.station is not None and state == QMediaPlayer.PlaybackState.StoppedState:
            self.state.setText(tr("radio.stopped"))

    def _volume(self, value: int) -> None:
        self.audio.setVolume(value / 100)
        self.ctx.cfg.set("music.volume", value / 100)
