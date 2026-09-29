"""The Watch tab (ТЗ 10.1/10.2): pick a source, find a title, choose an episode, play it."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QComboBox, QDialog, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMenu, QPushButton, QSplitter,
    QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from anihub.context import AppContext
from anihub.core.i18n import tr
from anihub.sources.anime.base import AnimeEntry, AnimeSource, Episode
from anihub.ui import style
from anihub.ui.anime_player import AnimePlayer, fmt
from anihub.ui.extensions_dialog import ExtensionsDialog
from anihub.ui.grid import ThumbGrid, image_to_thumb
from anihub.ui.lang_filter import LangFilter, lang_name
from anihub.ui.novels_page import placeholder_cover
from anihub.ui.workers import run_async, run_status


def source_title(source: AnimeSource) -> str:
    if source.name == "local":
        return tr("watch.local")
    return source.title if source.lang == "multi" else f"{source.title} · {lang_name(source.lang)}"


class LinkDialog(QDialog):
    """Choose which AniList show a title is, so watched episodes update your list."""

    def __init__(self, ctx: AppContext, title: str, parent=None):
        super().__init__(parent)
        self.ctx, self.chosen = ctx, None
        self.setWindowTitle(tr("watch.link_title"))
        self.resize(560, 460)
        self.query = QLineEdit(title)
        self.go = style.primary(QPushButton(tr("search.button")), "search")
        self.list = QListWidget()
        self.ok = style.primary(QPushButton(tr("watch.link_ok")), "check")
        self.ok.setEnabled(False)
        self.message = QLabel()
        style.role(self.message, "dim")
        row = QHBoxLayout()
        row.addWidget(self.query, 1)
        row.addWidget(self.go)
        layout = QVBoxLayout(self)
        layout.addLayout(row)
        layout.addWidget(self.list, 1)
        layout.addWidget(self.message)
        layout.addWidget(self.ok, 0, Qt.AlignmentFlag.AlignLeft)
        self.go.clicked.connect(self._search)
        self.query.returnPressed.connect(self._search)
        self.list.itemSelectionChanged.connect(lambda: self.ok.setEnabled(bool(self.list.selectedItems())))
        self.list.itemDoubleClicked.connect(lambda _i: self._accept())
        self.ok.clicked.connect(self._accept)
        self._search()

    def _search(self) -> None:
        text = self.query.text().strip()
        if not text:
            return
        self.message.setText(tr("status.loading"))
        adult = "explicit" in self.ctx.allowed_ratings()

        def done(result) -> None:
            self.list.clear()
            for media in result[0]:
                extra = " · ".join(x for x in (media["format"], str(media["year"] or ""),
                                               tr("anime.episodes_n", n=media["episodes"]) if media["episodes"] else "") if x)
                item = QListWidgetItem(f"{media['title']}   ({extra})" if extra else media["title"])
                item.setData(Qt.ItemDataRole.UserRole, media)
                self.list.addItem(item)
            self.message.setText(tr("track.found", n=self.list.count()))

        run_status(lambda: self.ctx.anilist.search(text, 1, adult), on_done=done, status=self.message)

    def _accept(self) -> None:
        item = self.list.currentItem()
        if item is not None:
            self.chosen = item.data(Qt.ItemDataRole.UserRole)
            self.accept()


SAVED = "__saved__"            # the pseudo-source of the source box that shows the user's shelf (later / watching / done)
SHELF = (("later", "watch.shelf.later"), ("watching", "watch.shelf.watching"), ("done", "watch.shelf.done"))


class WatchTab(QWidget):
    list_changed = Signal()

    def __init__(self, ctx: AppContext, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.entry: AnimeEntry | None = None
        self.episodes: list[Episode] = []
        self._gen, self._page, self._loading, self._exhausted = 0, 1, False, True
        self._players: list[AnimePlayer] = []
        self._src: AnimeSource | None = None            # the source of the title on the right (in the shelf it differs from the source box)

        self.source_box = QComboBox()
        self.shelf_filter = QComboBox()
        self.shelf_filter.hide()
        self.query = QLineEdit(placeholderText=tr("watch.search"))
        self.query.setClearButtonEnabled(True)
        self.go = style.primary(QPushButton(tr("search.button")), "search")
        self.folder_btn = style.secondary(QPushButton(tr("watch.open_folder")), "folder")
        self.lang_filter = LangFilter(ctx.cfg, "anime.langs")
        self.ext_btn = style.secondary(QPushButton(tr("ext.button")), "layers")
        self.grid = ThumbGrid(ctx.cfg.get("ui.thumb_size", 180) + 20)
        self.status = QLabel()
        style.role(self.status, "dim")
        top = QHBoxLayout()
        for w, s in ((self.source_box, 0), (self.shelf_filter, 0), (self.lang_filter, 0), (self.query, 1), (self.go, 0), (self.ext_btn, 0),
                     (self.folder_btn, 0)):
            top.addWidget(w, s)
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.addLayout(top)
        ll.addWidget(self.grid, 1)
        ll.addWidget(self.status)

        self.title = QLabel()
        self.title.setStyleSheet("font-size: 17px; font-weight: 600;")
        self.title.setWordWrap(True)
        self.link_label = QLabel()
        style.role(self.link_label, "dim")
        self.link_label.setWordWrap(True)
        self.link_btn = style.secondary(QPushButton(tr("watch.link")), "external")
        self.unlink_btn = style.ghost(QPushButton(tr("watch.unlink")), "x")
        self.site_btn = style.ghost(QPushButton(tr("watch.site")), "external")
        self.shelf_btn = style.secondary(QPushButton(tr("watch.shelf.add") + "  ▾"), "heart")
        self.shelf_menu = QMenu(self)
        self.shelf_btn.setMenu(self.shelf_menu)
        self.shelf_menu.aboutToShow.connect(self._build_shelf_menu)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels([tr("watch.col.no"), tr("watch.col.title"), tr("watch.col.state")])
        self.tree.setRootIsDecorated(False)
        self.tree.setColumnWidth(0, 60)
        self.tree.setColumnWidth(1, 260)
        self.tree.setSelectionMode(QTreeWidget.SelectionMode.ExtendedSelection)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.play_btn = style.primary(QPushButton(tr("watch.play")), "play")
        self.seen_btn = style.secondary(QPushButton(tr("watch.mark_seen")), "check")
        self.unseen_btn = style.secondary(QPushButton(tr("watch.mark_unseen")), "x")
        self.message = QLabel()
        self.message.setWordWrap(True)
        style.role(self.message, "dim")
        self.hint = style.EmptyState("tv", tr("watch.pick_title"), tr("watch.pick_text"))
        link_row = QHBoxLayout()
        for w in (self.shelf_btn, self.link_btn, self.unlink_btn, self.site_btn):
            link_row.addWidget(w)
        link_row.addStretch(1)
        buttons = QHBoxLayout()
        for w in (self.play_btn, self.seen_btn, self.unseen_btn):
            buttons.addWidget(w)
        buttons.addStretch(1)
        self.details = QWidget()
        dl = QVBoxLayout(self.details)
        for item in (self.title, self.link_label):
            dl.addWidget(item)
        dl.addLayout(link_row)
        dl.addWidget(self.tree, 1)
        dl.addLayout(buttons)
        dl.addWidget(self.message)
        self.details.hide()
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.addWidget(self.hint, 1)
        rl.addWidget(self.details, 1)
        split = QSplitter()
        split.addWidget(left)
        split.addWidget(right)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(split)

        self.reload_sources()
        self.source_box.activated.connect(lambda _i: (self.ctx.cfg.set("anime.last_source", self.source_box.currentData()), self.search()))
        self.lang_filter.changed.connect(lambda: (self.reload_sources(), self.search()))
        self.ext_btn.clicked.connect(self._extensions)
        self.go.clicked.connect(self.search)
        self.query.returnPressed.connect(self.search)
        self.folder_btn.clicked.connect(self._open_folder)
        self.grid.need_more.connect(self._load_page)
        self.grid.itemDoubleClicked.connect(self._open_item)
        self.shelf_filter.activated.connect(lambda _i: self.search())
        self.link_btn.clicked.connect(self._link)
        self.unlink_btn.clicked.connect(self._unlink)
        self.site_btn.clicked.connect(lambda: self.entry and self.entry.url.startswith("http") and QDesktopServices.openUrl(QUrl(self.entry.url)))
        self.play_btn.clicked.connect(self.play)
        self.seen_btn.clicked.connect(lambda: self._mark(True))
        self.unseen_btn.clicked.connect(lambda: self._mark(False))
        self.tree.itemDoubleClicked.connect(lambda item: self.play(self.tree.indexOfTopLevelItem(item)))
        self.tree.customContextMenuRequested.connect(self._menu)
        self._loaded_once = False

    # --- sources / search --------------------------------------------------------------------------------

    def reload_sources(self) -> None:
        """The source list: adult sources only in the 18+ mode, online ones filtered by the chosen languages."""
        adult = "explicit" in self.ctx.allowed_ratings()
        sources = {n: s for n, s in self.ctx.anime_sources.items() if adult or not s.nsfw}
        self.lang_filter.set_languages({s.lang for n, s in sources.items() if n != "local"})
        current = self.source_box.currentData() or self.ctx.cfg.get("anime.last_source")
        self.source_box.clear()
        self.source_box.addItem(tr("watch.shelf"), SAVED)
        for name, source in sources.items():
            if name == "local" or self.lang_filter.accepts(source.lang):
                self.source_box.addItem(source_title(source), name)
        index = self.source_box.findData(current) if current is not None else -1
        self.source_box.setCurrentIndex(index if index >= 0 else min(1, self.source_box.count() - 1))       # the shelf is never the default

    def _extensions(self) -> None:
        dlg = ExtensionsDialog(self.ctx, self.ctx.extensions, ("anime",), lambda: self.ctx.anime_sources, self)
        dlg.exec()
        if dlg.changed:
            self.reload_sources()

    def source(self) -> AnimeSource | None:
        return self.ctx.anime_sources.get(self.source_box.currentData())

    def _in_shelf(self) -> bool:
        return self.source_box.currentData() == SAVED

    def ensure_loaded(self) -> None:
        if not self._loaded_once:
            self.search()

    def _open_folder(self) -> None:
        import os

        folder = self.ctx.paths.anime
        folder.mkdir(parents=True, exist_ok=True)
        os.startfile(folder)

    def search(self) -> None:
        shelf = self._in_shelf()
        self.shelf_filter.setVisible(shelf)
        self.lang_filter.setVisible(not shelf)
        self.query.setVisible(not shelf)
        self.go.setVisible(not shelf)
        if shelf:
            self._loaded_once = True
            self._gen += 1
            self.folder_btn.hide()
            self._show_shelf()
            return
        if self.source() is None:
            return
        self._loaded_once = True
        self._gen += 1
        self.grid.clear_items()
        self._page, self._loading, self._exhausted = 1, False, False
        self.folder_btn.setVisible(self.source().name == "local")
        self._load_page()

    def _fill_shelf_filter(self) -> None:
        counts = self.ctx.db.saved_counts()
        current = self.shelf_filter.currentData()
        self.shelf_filter.blockSignals(True)
        self.shelf_filter.clear()
        self.shelf_filter.addItem(f"{tr('watch.shelf.all')} ({sum(counts.values())})", "")
        for status, key in SHELF:
            self.shelf_filter.addItem(f"{tr(key)} ({counts.get(status, 0)})", status)
        self.shelf_filter.setCurrentIndex(max(self.shelf_filter.findData(current), 0))
        self.shelf_filter.blockSignals(False)

    def _show_shelf(self) -> None:
        """The user's shelf: every saved title with its state (later / watching / done); a double click opens it where it was left."""
        self._fill_shelf_filter()
        self.grid.clear_items()
        self._loading, self._exhausted = False, True
        rows = self.ctx.db.saved_list(self.shelf_filter.currentData() or None)
        for row in rows:
            entry = AnimeEntry(id=row["entry_id"], title=row["title"], cover=row["cover"], url=row["url"])
            self._add_entry((row["source"], entry), entry, f"{entry.title}\n{tr(dict(SHELF)[row['status']])}")
        self.status.setText(tr("watch.shelf_n", n=len(rows)) if rows else tr("watch.shelf_empty"))

    def _open_item(self, item) -> None:
        data = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(data, tuple):                                   # a shelf tile: (source name, entry)
            source = self.ctx.anime_sources.get(data[0])
            if source is None:
                self.status.setText(tr("watch.shelf_no_source", name=data[0]))
                return
            self.select_entry(data[1], source)
        else:
            self.select_entry(data)

    def _load_page(self) -> None:
        source = self.source()
        if self._loading or self._exhausted or source is None:
            return
        self._loading = True
        self.status.setText(tr("status.loading"))
        gen, page, text = self._gen, self._page, self.query.text().strip()

        def done(result) -> None:
            if gen != self._gen:
                return
            entries, more = result
            self._loading, self._exhausted = False, not more
            self._page += 1
            for entry in entries:
                self._add(source, entry)
            empty = self.grid.count() == 0
            self.status.setText(tr("watch.local_empty") if empty and source.name == "local" else
                                tr("status.count", n=self.grid.count()) + ("" if more else "  ·  " + tr("status.end")))
            if more and entries:
                self.grid.request_fill()

        def failed(exc: Exception) -> None:
            if gen == self._gen:
                self._loading, self._exhausted = False, True
                self.status.setText(tr("status.error", msg=str(exc)))

        run_async(lambda: source.search(text, page), on_done=done, on_error=failed)

    def _add(self, source: AnimeSource, entry: AnimeEntry) -> None:
        self._add_entry(entry, entry, entry.title)

    def _add_entry(self, payload, entry: AnimeEntry, tooltip: str) -> None:
        size = self.grid.thumb_size

        def load():
            cover = entry.cover
            try:
                if cover.startswith("http"):
                    return image_to_thumb(self.ctx.media.get(cover).read_bytes(), size)
                if cover and Path(cover).is_file():
                    return image_to_thumb(Path(cover).read_bytes(), size)
            except Exception:  # noqa: BLE001 - a missing cover is not an error
                pass
            return placeholder_cover(entry.title, size)

        self.grid.add_entry(payload, tooltip, load)

    # --- one title ------------------------------------------------------------------------------------------

    def select_entry(self, entry: AnimeEntry, source: AnimeSource | None = None) -> None:
        source = source or self.source()
        if source is None:
            return
        self._src = source
        self.entry = entry
        self.hint.hide()
        self.details.show()
        self.title.setText(entry.title)
        self.tree.clear()
        self.episodes = []
        self.message.setText(tr("status.loading"))
        self._show_link()
        self._show_shelf_state()
        self.site_btn.setVisible(entry.url.startswith("http"))

        def done(episodes: list[Episode]) -> None:
            if self.entry is not entry:
                return
            self.episodes = episodes
            self.message.setText(tr("watch.episodes_n", n=len(episodes)) if episodes else tr("watch.no_episodes"))
            self._fill_tree()

        run_status(lambda: source.episodes(entry), on_done=done, status=self.message)

    def _show_link(self) -> None:
        media = self.ctx.watch.linked_media(self._src.name, self.entry.id) if self.entry and self._src else None
        self.link_label.setText(tr("watch.linked_to", title=media["title"]) if media else tr("watch.not_linked"))
        self.unlink_btn.setVisible(media is not None)
        self.link_btn.setText(tr("watch.relink") if media else tr("watch.link"))

    def _fill_tree(self) -> None:
        source, entry = self._src, self.entry
        if source is None or entry is None:
            return
        positions = self.ctx.watch.positions(source.name, entry.id)
        selected = {self.tree.indexOfTopLevelItem(i) for i in self.tree.selectedItems()}
        self.tree.clear()
        for i, ep in enumerate(self.episodes):
            pos = positions.get(ep.id)
            if pos and pos["watched"]:
                state = "✓ " + tr("watch.watched")
            elif pos and pos["position_ms"] > 15_000:
                state = tr("watch.resume_at", t=fmt(pos["position_ms"]))
            else:
                state = ""
            item = QTreeWidgetItem([f"{ep.number:g}", ep.title if ep.title and ep.title != f"{ep.number:g}" else "", state])
            self.tree.addTopLevelItem(item)
            item.setSelected(i in selected)

    def _link(self) -> None:
        if self.entry is None:
            return
        dlg = LinkDialog(self.ctx, self.entry.title, self)
        if dlg.exec() and dlg.chosen:
            self.ctx.watch.link(self._src.name, self.entry.id, dlg.chosen)
            self._show_link()
            self.message.setText(tr("watch.link_saved"))

    def _unlink(self) -> None:
        if self.entry is not None:
            self.ctx.watch.link(self._src.name, self.entry.id, None)
            self._show_link()

    # --- playing --------------------------------------------------------------------------------------------

    def play(self, index: int | None = None) -> None:
        source, entry = self._src, self.entry
        if source is None or entry is None or not self.episodes:
            return
        saved = self.ctx.db.saved_get(source.name, entry.id)
        if saved is not None and saved["status"] == "later":           # started: it is no longer "for later"
            self._set_shelf("watching")
        if not isinstance(index, int) or index < 0:
            selected = self.tree.selectedItems()
            if selected:
                index = self.tree.indexOfTopLevelItem(selected[0])
            else:
                nxt = self.ctx.watch.next_episode(source.name, entry.id, self.episodes)
                index = self.episodes.index(nxt) if nxt else 0
        player = AnimePlayer(self.ctx, source, entry, self.episodes, index, self)
        player.progress_changed.connect(self._fill_tree)
        player.progress_changed.connect(self.list_changed)
        player.destroyed.connect(lambda: self._players.remove(player) if player in self._players else None)
        self._players.append(player)
        player.show()

    def _selected_episodes(self) -> list[Episode]:
        return [self.episodes[self.tree.indexOfTopLevelItem(i)] for i in self.tree.selectedItems()]

    def _mark(self, watched: bool) -> None:
        source, entry = self._src, self.entry
        if source is None or entry is None:
            return
        for ep in self._selected_episodes():
            self.ctx.watch.mark(source.name, entry.id, ep, watched)
        self._fill_tree()
        self.list_changed.emit()

    # --- the shelf: later / watching / done ---------------------------------------------------------------------------------

    def _shelf_status(self) -> str | None:
        if self._src is None or self.entry is None:
            return None
        row = self.ctx.db.saved_get(self._src.name, self.entry.id)
        return row["status"] if row else None

    def _show_shelf_state(self) -> None:
        status = self._shelf_status()
        self.shelf_btn.setText((tr(dict(SHELF)[status]) if status else tr("watch.shelf.add")) + "  ▾")

    def _build_shelf_menu(self) -> None:
        self.shelf_menu.clear()
        current = self._shelf_status()
        for status, key in SHELF:
            action = self.shelf_menu.addAction(tr(key), lambda st=status: self._set_shelf(st))
            action.setCheckable(True)
            action.setChecked(status == current)
        if current:
            self.shelf_menu.addSeparator()
            self.shelf_menu.addAction(tr("watch.shelf.remove"), lambda: self._set_shelf(None))

    def _set_shelf(self, status: str | None) -> None:
        """Puts the open title on the shelf (or takes it off). "Done" also marks every episode as watched."""
        source, entry = self._src, self.entry
        if source is None or entry is None:
            return
        if status is None:
            self.ctx.db.saved_remove(source.name, entry.id)
        else:
            self.ctx.db.saved_set(source.name, entry.id, entry.title, entry.cover, entry.url, status)
            if status == "done":
                for ep in self.episodes:
                    self.ctx.watch.mark(source.name, entry.id, ep, True)
                self._fill_tree()
        self._show_shelf_state()
        self.message.setText(tr("watch.shelf_saved", state=tr(dict(SHELF)[status])) if status else tr("watch.shelf_removed"))
        self.list_changed.emit()
        if self._in_shelf():
            self._show_shelf()

    def _menu(self, pos) -> None:
        if not self.tree.selectedItems():
            return
        menu = QMenu(self)
        menu.addAction(tr("watch.play"), self.play)
        menu.addAction(tr("watch.mark_seen"), lambda: self._mark(True))
        menu.addAction(tr("watch.mark_unseen"), lambda: self._mark(False))
        menu.exec(self.tree.viewport().mapToGlobal(pos))
