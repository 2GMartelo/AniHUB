"""Anime music search (AnimeThemes): find openings and endings by title, listen, download into the music library."""
from __future__ import annotations

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QLineEdit, QPushButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from anihub.context import AppContext
from anihub.core.i18n import tr
from anihub.services.animethemes import AnimeThemes, ThemeTrack
from anihub.ui import style
from anihub.ui.workers import run_async


class ThemesTab(QWidget):
    downloaded = Signal()                                # files were added to the music library

    def __init__(self, ctx: AppContext, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.api = AnimeThemes(ctx.http)
        self._gen, self._page, self._more, self._loading = 0, 1, False, False
        self.player = QMediaPlayer(self)
        self.audio = QAudioOutput(self)
        self.audio.setVolume(float(ctx.cfg.get("music.volume", 0.7)))
        self.player.setAudioOutput(self.audio)

        self.query = QLineEdit(placeholderText=tr("themes.search"))
        self.query.setClearButtonEnabled(True)
        self.go = style.primary(QPushButton(tr("search.button")), "search")
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels([tr("themes.col.anime"), tr("themes.col.theme"), tr("themes.col.artist")])
        self.tree.setRootIsDecorated(False)
        self.tree.setSelectionMode(QTreeWidget.SelectionMode.ExtendedSelection)
        self.tree.setColumnWidth(0, 340)
        self.tree.setColumnWidth(1, 300)
        self.play_btn = style.secondary(QPushButton(tr("themes.play")), "play")
        self.stop_btn = style.ghost(QPushButton(tr("themes.stop")), "stop")
        self.download_btn = style.primary(QPushButton(tr("themes.download")), "download")
        self.more_btn = style.ghost(QPushButton(tr("themes.more")), "chevron-down")
        self.status = style.role(QLabel(), "dim")
        self.status.setWordWrap(True)
        top = QHBoxLayout()
        top.addWidget(self.query, 1)
        top.addWidget(self.go)
        buttons = QHBoxLayout()
        for w in (self.play_btn, self.stop_btn, self.download_btn):
            buttons.addWidget(w)
        buttons.addStretch(1)
        buttons.addWidget(self.more_btn)
        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(self.tree, 1)
        layout.addLayout(buttons)
        layout.addWidget(self.status)
        self.go.clicked.connect(self.search)
        self.query.returnPressed.connect(self.search)
        self.more_btn.clicked.connect(self._load_page)
        self.play_btn.clicked.connect(self.play_selected)
        self.stop_btn.clicked.connect(self.player.stop)
        self.download_btn.clicked.connect(self.download_selected)
        self.tree.itemDoubleClicked.connect(lambda _i: self.play_selected())
        self.tree.itemSelectionChanged.connect(self._selection)
        self.player.errorOccurred.connect(lambda _e, msg: self.status.setText(tr("watch.play_error", msg=msg)))
        self.more_btn.setEnabled(False)
        self._selection()

    # --- search --------------------------------------------------------------------------------------------------

    def ensure_loaded(self) -> None:
        if self.tree.topLevelItemCount() == 0 and not self._loading and self._gen == 0:
            self.search()

    def search(self) -> None:
        self._gen += 1
        self._page, self._more = 1, False
        self.tree.clear()
        self._load_page()

    def _load_page(self) -> None:
        if self._loading:
            return
        self._loading = True
        self.more_btn.setEnabled(False)
        self.status.setText(tr("status.loading"))
        gen, page, text = self._gen, self._page, self.query.text().strip()

        def done(result) -> None:
            if gen != self._gen:
                return
            tracks, more = result
            self._loading, self._more = False, more
            self._page += 1
            adult = "explicit" in self.ctx.allowed_ratings()
            shown = [t for t in tracks if adult or not t.nsfw]
            for t in shown:
                item = QTreeWidgetItem([f"{t.anime} ({t.year})" if t.year else t.anime, t.label.split(" — ")[0], t.artists])
                item.setData(0, Qt.ItemDataRole.UserRole, t)
                self.tree.addTopLevelItem(item)
            self.more_btn.setEnabled(more)
            hidden = len(tracks) - len(shown)
            self.status.setText(tr("themes.count", n=self.tree.topLevelItemCount()) + (f" · {tr('novels.online.hidden', n=hidden)}" if hidden else ""))

        def failed(exc: Exception) -> None:
            if gen == self._gen:
                self._loading = False
                self.status.setText(tr("status.error", msg=str(exc)))

        run_async(lambda: self.api.search(text, page), on_done=done, on_error=failed)

    # --- actions -------------------------------------------------------------------------------------------------

    def selected_tracks(self) -> list[ThemeTrack]:
        return [i.data(0, Qt.ItemDataRole.UserRole) for i in self.tree.selectedItems()]

    def _selection(self) -> None:
        has = bool(self.tree.selectedItems())
        self.play_btn.setEnabled(has)
        self.download_btn.setEnabled(has)

    def play_selected(self) -> None:
        tracks = self.selected_tracks()
        if tracks:
            self.player.setSource(QUrl(tracks[0].audio_url))
            self.player.play()
            self.status.setText(tr("themes.playing", title=tracks[0].label))

    def download_selected(self) -> None:
        tracks = self.selected_tracks()
        if not tracks:
            return
        self.download_btn.setEnabled(False)
        root = self.ctx.paths.root / "music"

        def work() -> tuple[int, list[str]]:
            done, errors = 0, []
            for t in tracks:
                try:
                    self.api.download(t, root)
                    done += 1
                except Exception as exc:  # noqa: BLE001 - report and continue with the rest
                    errors.append(str(exc))
            return done, errors

        def finished(result) -> None:
            self.download_btn.setEnabled(True)
            done, errors = result
            self.status.setText(tr("themes.downloaded", n=done) + (f"  ·  {errors[0]}" if errors else ""))
            if done:
                self.downloaded.emit()

        self.status.setText(tr("themes.downloading", n=len(tracks)))
        run_async(work, on_done=finished,
                  on_error=lambda exc: (self.download_btn.setEnabled(True), self.status.setText(tr("status.error", msg=str(exc)))))

    def stop(self) -> None:
        self.player.stop()
