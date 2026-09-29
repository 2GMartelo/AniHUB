"""The Music tab (п. 12.1): OST albums per title with a small audio player."""
from __future__ import annotations

import os
import random

from PySide6.QtCore import Qt, QUrl
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QLineEdit, QPushButton, QSlider, QToolButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from anihub.context import AppContext
from anihub.core.i18n import tr
from anihub.services import music
from anihub.services.music import Album, Track
from anihub.ui import style
from anihub.ui.anime_player import fmt


class MusicTab(QWidget):
    def __init__(self, ctx: AppContext, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.albums: list[Album] = []
        self.queue: list[Track] = []               # what plays now (the current album, or the search results)
        self.index = -1
        self.shuffle = False
        self.repeat = False
        self.player = QMediaPlayer(self)
        self.audio = QAudioOutput(self)
        self.audio.setVolume(float(ctx.cfg.get("music.volume", 0.7)))
        self.player.setAudioOutput(self.audio)

        self.filter = QLineEdit(placeholderText=tr("music.filter"))
        self.filter.setClearButtonEnabled(True)
        self.folder_btn = style.secondary(QPushButton(tr("music.open_folder")), "folder")
        self.rescan_btn = style.ghost(QPushButton(tr("music.rescan")), "refresh")
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels([tr("music.col.track"), tr("music.col.title")])
        self.tree.setColumnWidth(0, 420)
        self.tree.setRootIsDecorated(True)
        self.empty = style.EmptyState("volume", tr("music.empty_title"), tr("music.empty_text"))
        self.now = QLabel(tr("music.nothing"))
        style.role(self.now, "dim")
        self.prev_btn = self._tool("skip-back", "reader.prev_chapter")
        self.play_btn = self._tool("play", "viewer.playpause", size=22)
        self.next_btn = self._tool("skip-forward", "reader.next_chapter")
        self.shuffle_btn = self._tool("refresh", "music.shuffle")
        self.shuffle_btn.setCheckable(True)
        self.repeat_btn = self._tool("rotate", "music.repeat")
        self.repeat_btn.setCheckable(True)
        self.seek = QSlider(Qt.Orientation.Horizontal)
        self.time = QLabel("0:00 / 0:00")
        self.time.setMinimumWidth(100)
        self.volume = QSlider(Qt.Orientation.Horizontal)
        self.volume.setRange(0, 100)
        self.volume.setValue(int(self.audio.volume() * 100))
        self.volume.setFixedWidth(100)

        top = QHBoxLayout()
        top.addWidget(self.filter, 1)
        top.addWidget(self.folder_btn)
        top.addWidget(self.rescan_btn)
        bar = QHBoxLayout()
        for w in (self.prev_btn, self.play_btn, self.next_btn, self.shuffle_btn, self.repeat_btn):
            bar.addWidget(w)
        bar.addWidget(self.time)
        bar.addWidget(self.seek, 1)
        bar.addWidget(self.volume)
        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(self.tree, 1)
        layout.addWidget(self.empty, 1)
        layout.addWidget(self.now)
        layout.addLayout(bar)
        for w in (self.prev_btn, self.play_btn, self.next_btn, self.shuffle_btn, self.repeat_btn, self.seek, self.volume):
            w.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        self.filter.textChanged.connect(self._fill)
        self.folder_btn.clicked.connect(self._open_folder)
        self.rescan_btn.clicked.connect(self.rescan)
        self.tree.itemDoubleClicked.connect(self._activated)
        self.play_btn.clicked.connect(self.toggle)
        self.prev_btn.clicked.connect(lambda: self.step(-1))
        self.next_btn.clicked.connect(lambda: self.step(1))
        self.shuffle_btn.toggled.connect(lambda v: setattr(self, "shuffle", v))
        self.repeat_btn.toggled.connect(lambda v: setattr(self, "repeat", v))
        self.seek.sliderMoved.connect(self.player.setPosition)
        self.volume.valueChanged.connect(self._volume)
        self.player.durationChanged.connect(lambda d: self.seek.setRange(0, d))
        self.player.positionChanged.connect(self._position)
        self.player.mediaStatusChanged.connect(self._status)
        self.player.playbackStateChanged.connect(self._state)
        self.player.errorOccurred.connect(lambda _e, msg: self.now.setText(tr("watch.play_error", msg=msg)))
        self.rescan()

    def _tool(self, icon: str, tip_key: str, size: int = 20) -> QToolButton:
        b = QToolButton()
        b.setProperty("viewer", True)
        b.setToolTip(tr(tip_key))
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.setFixedSize(38, 38)
        style.bind_icon(b, icon, "normal", size)
        return b

    # --- library -----------------------------------------------------------------------------------------

    def rescan(self) -> None:
        self.albums = music.scan(self.ctx.paths.music)
        self._fill()

    def _open_folder(self) -> None:
        folder = self.ctx.paths.music
        folder.mkdir(parents=True, exist_ok=True)
        os.startfile(folder)

    def _fill(self) -> None:
        needle = self.filter.text().strip().lower()
        titles = [r["title"] for r in self.ctx.db.anime_entries()]
        self.tree.clear()
        shown = 0
        for album in self.albums:
            tracks = [t for t in album.tracks if not needle or needle in t.title.lower() or needle in album.name.lower()]
            if not tracks:
                continue
            linked = music.match_title(album, titles)
            head = QTreeWidgetItem([(album.name or tr("music.loose")) + (f"   ·   {tr('music.in_list', title=linked)}" if linked else ""),
                                    tr("music.tracks_n", n=len(tracks))])
            head.setData(0, Qt.ItemDataRole.UserRole, ("album", album.name))
            self.tree.addTopLevelItem(head)
            for t in tracks:
                item = QTreeWidgetItem([str(t.number) if t.number is not None else "", t.title])
                item.setData(0, Qt.ItemDataRole.UserRole, ("track", t))
                head.addChild(item)
            head.setExpanded(bool(needle) or len(self.albums) == 1)
            shown += len(tracks)
        self.tree.setVisible(bool(self.albums))
        self.empty.setVisible(not self.albums)

    def _activated(self, item: QTreeWidgetItem) -> None:
        kind, payload = item.data(0, Qt.ItemDataRole.UserRole)
        if kind == "album":
            album = next((a for a in self.albums if a.name == payload), None)
            if album:
                self.play_list(list(album.tracks), 0)
            return
        parent = item.parent()
        siblings = [parent.child(i).data(0, Qt.ItemDataRole.UserRole)[1] for i in range(parent.childCount())]
        self.play_list(siblings, siblings.index(payload))

    # --- playback ------------------------------------------------------------------------------------------

    def play_list(self, tracks: list[Track], index: int) -> None:
        self.queue, self.index = tracks, index
        self._play_current()

    def _play_current(self) -> None:
        if not 0 <= self.index < len(self.queue):
            return
        track = self.queue[self.index]
        self.now.setText(f"{track.title}   ·   {track.path.parent.name}")
        self.player.setSource(QUrl.fromLocalFile(str(track.path)))
        self.player.play()

    def toggle(self) -> None:
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
        elif self.queue:
            self.player.play()

    def next_index(self, delta: int, ended: bool = False) -> int | None:
        """Where to go from here: shuffle picks another track, repeat wraps around (also when a track ends)."""
        n = len(self.queue)
        if not n:
            return None
        if self.shuffle and n > 1:
            return random.choice([i for i in range(n) if i != self.index])
        nxt = self.index + delta
        if 0 <= nxt < n:
            return nxt
        return nxt % n if (self.repeat or not ended) else None

    def step(self, delta: int, ended: bool = False) -> None:
        nxt = self.next_index(delta, ended)
        if nxt is not None:
            self.index = nxt
            self._play_current()

    def _status(self, status) -> None:
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            self.step(1, ended=True)

    def _state(self, state) -> None:
        style.bind_icon(self.play_btn, "pause" if state == QMediaPlayer.PlaybackState.PlayingState else "play", "normal", 22)

    def _position(self, pos: int) -> None:
        if not self.seek.isSliderDown():
            self.seek.setValue(pos)
        self.time.setText(f"{fmt(pos)} / {fmt(self.player.duration())}")

    def _volume(self, value: int) -> None:
        self.audio.setVolume(value / 100)
        self.ctx.cfg.set("music.volume", value / 100)

    def stop(self) -> None:
        self.player.stop()
