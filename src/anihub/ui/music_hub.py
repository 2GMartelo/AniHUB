"""The Music section: your library, internet radio and the anime-music search, with one sound at a time."""
from __future__ import annotations

from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtWidgets import QTabWidget

from anihub.context import AppContext
from anihub.core.i18n import tr
from anihub.ui.music_radio import RadioTab
from anihub.ui.music_search import ThemesTab
from anihub.ui.music_tab import MusicTab


class MusicHub(QTabWidget):
    def __init__(self, ctx: AppContext, parent=None):
        super().__init__(parent)
        self.library = MusicTab(ctx)
        self.radio = RadioTab(ctx)
        self.themes = ThemesTab(ctx)
        self.addTab(self.library, tr("music.tab.library"))
        self.addTab(self.radio, tr("music.tab.radio"))
        self.addTab(self.themes, tr("music.tab.search"))
        self.themes.downloaded.connect(self.library.rescan)
        players = {"library": self.library.player, "radio": self.radio.player, "themes": self.themes.player}
        for name, player in players.items():
            player.playbackStateChanged.connect(lambda state, n=name: self._one_at_a_time(n, state, players))
        self.currentChanged.connect(lambda i: self.themes.ensure_loaded() if i == 2 else None)

    @staticmethod
    def _one_at_a_time(name: str, state, players: dict) -> None:
        """A player that starts silences the others (a radio on top of an opening is never wanted)."""
        if state == QMediaPlayer.PlaybackState.PlayingState:
            for other, player in players.items():
                if other != name and player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
                    player.stop() if other == "radio" else player.pause()
