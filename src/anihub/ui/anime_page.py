"""Anime section (ТЗ 10): season calendar, the watch list with AniList sync, account dialog."""
from __future__ import annotations

import html
import time

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QGuiApplication, QPixmap
from PySide6.QtWidgets import (
    QComboBox, QDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QMenu, QMessageBox, QPushButton,
    QSpinBox, QTabWidget, QTextBrowser, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from anihub.context import AppContext
from anihub.core.i18n import tr
from anihub.services.anilist import (
    DEVELOPER_URL, PIN_REDIRECT, STATUSES, current_season, format_airing, shift_season,
)
from anihub.ui import style
from anihub.ui.anime_watch import WatchTab
from anihub.ui.music_tab import MusicTab
from anihub.ui.grid import ThumbGrid, image_to_thumb
from anihub.ui.workers import run_async


def status_name(status: str) -> str:
    return tr(f"anime.st.{status}")


def airing_text(next_episode: int | None, airing_at: float | None, now: float | None = None) -> str:
    left = format_airing(next_episode, airing_at, now)
    if left is None:
        return ""
    episode, seconds = left
    if seconds <= 0:
        return tr("anime.airing_now", ep=episode)
    days, rest = divmod(int(seconds), 86400)
    hours = rest // 3600
    minutes = (rest % 3600) // 60
    span = f"{days} {tr('anime.d')} {hours} {tr('anime.h')}" if days else (f"{hours} {tr('anime.h')} {minutes} {tr('anime.m')}" if hours else f"{minutes} {tr('anime.m')}")
    return tr("anime.airing_in", ep=episode, span=span)


def score_label(score: int) -> str:
    return f"{score / 10:.1f}".rstrip("0").rstrip(".") if score else "—"


class AnimeDetail(QDialog):
    """One show: description, next episode, and the list controls (status / progress / score)."""

    changed = Signal()

    def __init__(self, ctx: AppContext, media: dict, parent=None):
        super().__init__(parent)
        self.ctx, self.media = ctx, media
        self.tracker = ctx.anilist
        self.setWindowTitle(media["title"])
        self.resize(760, 520)
        self.cover = QLabel(alignment=Qt.AlignmentFlag.AlignTop)
        self.cover.setFixedSize(220, 320)
        self.cover.setObjectName("thumbHolder")
        title = QLabel(f"<h2>{html.escape(media['title'])}</h2>")
        title.setWordWrap(True)
        title.setTextFormat(Qt.TextFormat.RichText)
        native = QLabel(media.get("native") or "")
        style.role(native, "dim")
        season = f"{tr('anime.season.' + media['season'])} {media['year']}" if media.get("season") and media.get("year") else ""
        facts = [tr("anime.format." + media["format"]) if media.get("format") else "",
                 tr("anime.episodes_n", n=media["episodes"]) if media.get("episodes") else "",
                 tr("anime.airing." + media["status"]) if media.get("status") else "", media.get("studio", ""), season,
                 f"★ {media['score'] / 10:.1f}" if media.get("score") else ""]
        self.facts = QLabel("  ·  ".join(f for f in facts if f))
        self.facts.setWordWrap(True)
        style.role(self.facts, "dim")
        self.genres = QLabel(", ".join(media.get("genres", [])))
        self.genres.setWordWrap(True)
        self.next = QLabel(airing_text(media.get("next_episode"), media.get("next_airing")))
        self.next.setStyleSheet("font-weight: 600;")
        self.text = QTextBrowser()
        self.text.setPlainText(media.get("description") or tr("anime.no_description"))

        entry = ctx.db.anime_get(media["id"])
        self.status = QComboBox()
        for st in STATUSES:
            self.status.addItem(status_name(st), st)
        self.status.setCurrentIndex(self.status.findData(entry["status"]) if entry else self.status.findData("PLANNING"))
        self.progress = QSpinBox(minimum=0, maximum=media.get("episodes") or 9999, value=entry["progress"] if entry else 0)
        self.score = QComboBox()
        self.score.addItem("—", 0)
        for n in range(1, 11):
            self.score.addItem(str(n), n * 10)
        self.score.setCurrentIndex(max(self.score.findData((entry["score"] // 10) * 10 if entry else 0), 0))
        self.save_btn = style.primary(QPushButton(tr("anime.save") if entry else tr("anime.add")), "check")
        self.remove_btn = style.danger(QPushButton(tr("anime.remove")), "trash")
        self.remove_btn.setVisible(entry is not None)
        self.site_btn = style.secondary(QPushButton("AniList"), "external")
        self.site_btn.setVisible(bool(media.get("url")))
        self.message = QLabel()
        style.role(self.message, "dim")

        form = QFormLayout()
        form.addRow(tr("anime.status"), self.status)
        form.addRow(tr("anime.progress"), self.progress)
        form.addRow(tr("anime.score"), self.score)
        buttons = QHBoxLayout()
        for w in (self.save_btn, self.remove_btn, self.site_btn):
            buttons.addWidget(w)
        buttons.addStretch(1)
        right = QVBoxLayout()
        for w in (title, native, self.facts, self.genres, self.next):
            right.addWidget(w)
        right.addWidget(self.text, 1)
        right.addLayout(form)
        right.addLayout(buttons)
        right.addWidget(self.message)
        root = QHBoxLayout(self)
        root.addWidget(self.cover, 0, Qt.AlignmentFlag.AlignTop)
        root.addLayout(right, 1)
        self.save_btn.clicked.connect(self._save)
        self.remove_btn.clicked.connect(self._remove)
        self.site_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(media["url"])))
        self._load_cover()

    def _load_cover(self) -> None:
        url = self.media.get("cover")
        if not url:
            return

        def fetch() -> bytes:
            return self.ctx.media.get(url).read_bytes()

        def done(data: bytes) -> None:
            pm = QPixmap()
            if pm.loadFromData(data):
                self.cover.setPixmap(pm.scaled(220, 320, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))

        run_async(fetch, on_done=done, on_error=lambda exc: None)

    def _save(self) -> None:
        self.tracker.track(self.media, self.status.currentData(), self.progress.value(), self.score.currentData())
        self.message.setText(tr("anime.saved"))
        self.save_btn.setText(tr("anime.save"))
        self.remove_btn.show()
        self.changed.emit()

    def _remove(self) -> None:
        self.tracker.remove(self.media["id"])
        self.remove_btn.hide()
        self.save_btn.setText(tr("anime.add"))
        self.message.setText(tr("anime.removed"))
        self.changed.emit()


class AccountDialog(QDialog):
    """AniList sign-in: the user's own API client, authorize in the browser, paste the token shown there."""

    changed = Signal()

    def __init__(self, ctx: AppContext, parent=None):
        super().__init__(parent)
        self.ctx, self.tracker = ctx, ctx.anilist
        self.setWindowTitle(tr("anime.account"))
        self.resize(640, 470)
        steps = QLabel(tr("anime.account_steps", redirect=PIN_REDIRECT))
        steps.setWordWrap(True)
        steps.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.dev_btn = style.secondary(QPushButton(tr("anime.open_developer")), "external")
        self.copy_btn = style.secondary(QPushButton(tr("anime.copy_redirect")), "copy")
        self.client = QLineEdit(str(ctx.cfg.get("tracker.anilist.client_id", "") or ""), placeholderText=tr("anime.client_id"))
        self.auth_btn = style.secondary(QPushButton(tr("anime.open_auth")), "external")
        self.token = QLineEdit(placeholderText=tr("anime.token_ph"))
        self.token.setEchoMode(QLineEdit.EchoMode.Password)
        self.login_btn = style.primary(QPushButton(tr("anime.sign_in")), "check")
        self.logout_btn = style.danger(QPushButton(tr("anime.sign_out")), "x")
        self.status = QLabel()
        self.status.setWordWrap(True)
        top = QHBoxLayout()
        top.addWidget(self.dev_btn)
        top.addWidget(self.copy_btn)
        top.addStretch(1)
        form = QFormLayout()
        form.addRow("Client ID", self.client)
        form.addRow("", self.auth_btn)
        form.addRow(tr("anime.token"), self.token)
        row = QHBoxLayout()
        row.addWidget(self.login_btn)
        row.addWidget(self.logout_btn)
        row.addStretch(1)
        layout = QVBoxLayout(self)
        layout.addWidget(steps)
        layout.addLayout(top)
        layout.addLayout(form)
        layout.addLayout(row)
        layout.addWidget(self.status)
        layout.addStretch(1)
        self.dev_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(DEVELOPER_URL)))
        self.copy_btn.clicked.connect(lambda: QGuiApplication.clipboard().setText(PIN_REDIRECT))
        self.auth_btn.clicked.connect(self._open_auth)
        self.login_btn.clicked.connect(self._sign_in)
        self.logout_btn.clicked.connect(self._sign_out)
        self._refresh()

    def _refresh(self) -> None:
        user = self.ctx.cfg.get("tracker.anilist.user", "")
        signed = self.tracker.logged_in
        self.status.setText(tr("anime.signed_as", name=user) if signed else tr("anime.not_signed"))
        self.logout_btn.setEnabled(signed)

    def _open_auth(self) -> None:
        client = self.client.text().strip()
        if not client.isdigit():
            self.status.setText(tr("anime.client_bad"))
            return
        self.ctx.cfg.set("tracker.anilist.client_id", client)
        QDesktopServices.openUrl(QUrl(self.tracker.authorize_url(client)))

    def _sign_in(self) -> None:
        token = self.token.text().strip()
        if not token:
            return
        self.login_btn.setEnabled(False)
        self.status.setText(tr("status.loading"))

        def done(viewer: dict) -> None:
            self.login_btn.setEnabled(True)
            self.token.clear()
            self._refresh()
            self.changed.emit()

        def failed(exc: Exception) -> None:
            self.login_btn.setEnabled(True)
            self.status.setText(tr("status.error", msg=str(exc)))

        run_async(self.tracker.sign_in, token, on_done=done, on_error=failed)

    def _sign_out(self) -> None:
        self.tracker.sign_out()
        self._refresh()
        self.changed.emit()


class SeasonTab(QWidget):
    open_media = Signal(dict)
    list_changed = Signal()

    def __init__(self, ctx: AppContext, parent=None):
        super().__init__(parent)
        self.ctx, self.tracker = ctx, ctx.anilist
        self.season, self.year = current_season()
        self._gen, self._page, self._loading, self._exhausted = 0, 1, False, True
        self.prev_btn = style.secondary(QPushButton(), "chevron-left")
        self.next_btn = style.secondary(QPushButton(), "chevron-right")
        for b in (self.prev_btn, self.next_btn):
            b.setFixedWidth(38)
        self.season_label = QLabel()
        self.season_label.setStyleSheet("font-size: 16px; font-weight: 600;")
        self.season_label.setMinimumWidth(170)
        self.season_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.today_btn = style.secondary(QPushButton(tr("anime.this_season")), "clock")
        self.query = QLineEdit(placeholderText=tr("anime.search"))
        self.query.setClearButtonEnabled(True)
        self.go = style.primary(QPushButton(tr("search.button")), "search")
        self.grid = ThumbGrid(ctx.cfg.get("ui.thumb_size", 180) + 20)
        self.status = QLabel()
        top = QHBoxLayout()
        for w, s in ((self.prev_btn, 0), (self.season_label, 0), (self.next_btn, 0), (self.today_btn, 0), (self.query, 1), (self.go, 0)):
            top.addWidget(w, s)
        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(self.grid, 1)
        layout.addWidget(self.status)
        self.prev_btn.clicked.connect(lambda: self._move(-1))
        self.next_btn.clicked.connect(lambda: self._move(1))
        self.today_btn.clicked.connect(self._today)
        self.go.clicked.connect(self.reload)
        self.query.returnPressed.connect(self.reload)
        self.grid.need_more.connect(self._load_page)
        self.grid.itemDoubleClicked.connect(lambda it: self.open_media.emit(it.data(Qt.ItemDataRole.UserRole)))
        self.grid.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.grid.customContextMenuRequested.connect(self._menu)
        self._loaded_once = False
        self._update_label()

    def _update_label(self) -> None:
        searching = bool(self.query.text().strip())
        self.season_label.setText(f"{tr(f'anime.season.{self.season}')} {self.year}" if not searching else tr("anime.search_results"))
        self.prev_btn.setEnabled(not searching)
        self.next_btn.setEnabled(not searching)

    def _move(self, delta: int) -> None:
        self.season, self.year = shift_season(self.season, self.year, delta)
        self.query.clear()
        self.reload()

    def _today(self) -> None:
        self.season, self.year = current_season()
        self.query.clear()
        self.reload()

    def ensure_loaded(self) -> None:
        if not self._loaded_once:
            self.reload()

    def reload(self) -> None:
        self._loaded_once = True
        self._gen += 1
        self.grid.clear_items()
        self._page, self._loading, self._exhausted = 1, False, False
        self._update_label()
        self._load_page()

    def _allow_adult(self) -> bool:
        return "explicit" in self.ctx.allowed_ratings()

    def _load_page(self) -> None:
        if self._loading or self._exhausted:
            return
        self._loading = True
        self.status.setText(tr("status.loading"))
        gen, page, text = self._gen, self._page, self.query.text().strip()
        adult = self._allow_adult()

        def work():
            if text:
                return self.tracker.search(text, page, adult)
            return self.tracker.season(self.season, self.year, page, adult)

        def done(result) -> None:
            if gen != self._gen:
                return
            shows, more = result
            self._loading, self._exhausted = False, not more
            self._page += 1
            for media in shows:
                self._add(media)
            self.status.setText(tr("status.count", n=self.grid.count()) + ("" if more else "  ·  " + tr("status.end")))
            if more and shows:
                self.grid.request_fill()

        def failed(exc: Exception) -> None:
            if gen == self._gen:
                self._loading, self._exhausted = False, True
                self.status.setText(tr("status.error", msg=str(exc)))

        run_async(work, on_done=done, on_error=failed)

    def _mark(self, media: dict) -> str:
        entry = self.ctx.db.anime_get(media["id"])
        return f"✓ {status_name(entry['status'])}" if entry else ""

    def _add(self, media: dict) -> None:
        tip = media["title"] + (f"\n{airing_text(media.get('next_episode'), media.get('next_airing'))}" if media.get("next_episode") else "")
        badge = f"E{media['next_episode']}" if media.get("next_episode") else ""
        url, size, mark = media.get("cover"), self.grid.thumb_size, self._mark(media)

        def load():
            return image_to_thumb(self.ctx.media.get(url).read_bytes(), size, badge, mark) if url else None

        self.grid.add_entry(media, tip, load)

    def _menu(self, pos) -> None:
        item = self.grid.itemAt(pos)
        if item is None:
            return
        media = item.data(Qt.ItemDataRole.UserRole)
        menu = QMenu(self)
        menu.addAction(tr("anime.open"), lambda: self.open_media.emit(media))
        add = menu.addMenu(tr("anime.add_to"))
        for st in STATUSES:
            add.addAction(status_name(st), lambda st=st: self._quick_add(media, st))
        menu.exec(self.grid.viewport().mapToGlobal(pos))

    def _quick_add(self, media: dict, status: str) -> None:
        self.tracker.track(media, status)
        self.list_changed.emit()
        self.status.setText(tr("anime.added", title=media["title"], status=status_name(status)))


class MyListTab(QWidget):
    open_media = Signal(dict)
    list_changed = Signal()

    def __init__(self, ctx: AppContext, parent=None):
        super().__init__(parent)
        self.ctx, self.tracker = ctx, ctx.anilist
        self.filter = QComboBox()
        self.sync_btn = style.secondary(QPushButton(tr("anime.sync")), "refresh")
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels([tr("anime.col.title"), tr("anime.col.progress"), tr("anime.col.score"),
                                   tr("anime.col.status"), tr("anime.col.next")])
        self.tree.setRootIsDecorated(False)
        self.tree.setColumnWidth(0, 420)
        self.tree.setColumnWidth(3, 150)
        self.tree.setSelectionMode(QTreeWidget.SelectionMode.ExtendedSelection)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.plus_btn = style.primary(QPushButton("+1"), "plus")
        self.plus_btn.setToolTip(tr("anime.plus_tip"))
        self.minus_btn = style.secondary(QPushButton("−1"))
        self.status_btn = style.secondary(QPushButton(tr("anime.set_status") + "  ▾"), "list")
        self.status_menu = QMenu(self)
        self.status_btn.setMenu(self.status_menu)
        self.score_btn = style.secondary(QPushButton(tr("anime.score") + "  ▾"), "star")
        self.score_menu = QMenu(self)
        self.score_btn.setMenu(self.score_menu)
        self.remove_btn = style.danger(QPushButton(tr("anime.remove")), "trash")
        self.message = QLabel()
        style.role(self.message, "dim")
        for st in STATUSES:
            self.status_menu.addAction(status_name(st), lambda st=st: self._set_status(st))
        self.score_menu.addAction(tr("anime.no_score"), lambda: self._set_score(0))
        for n in range(1, 11):
            self.score_menu.addAction(str(n), lambda n=n: self._set_score(n * 10))
        top = QHBoxLayout()
        top.addWidget(self.filter)
        top.addStretch(1)
        top.addWidget(self.sync_btn)
        buttons = QHBoxLayout()
        for w in (self.plus_btn, self.minus_btn, self.status_btn, self.score_btn, self.remove_btn):
            buttons.addWidget(w)
        buttons.addStretch(1)
        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(self.tree, 1)
        layout.addLayout(buttons)
        layout.addWidget(self.message)
        self.filter.activated.connect(self.reload)
        self.sync_btn.clicked.connect(self.sync)
        self.plus_btn.clicked.connect(lambda: self._bump(1))
        self.minus_btn.clicked.connect(lambda: self._bump(-1))
        self.remove_btn.clicked.connect(self._remove)
        self.tree.itemDoubleClicked.connect(self._open)
        self.tree.customContextMenuRequested.connect(self._menu)
        self.tree.itemSelectionChanged.connect(self._buttons)
        self.reload()

    # --- list ----------------------------------------------------------------------------------

    def _fill_filter(self) -> None:
        current = self.filter.currentData()
        counts = self.ctx.db.anime_counts()
        self.filter.blockSignals(True)
        self.filter.clear()
        self.filter.addItem(f"{tr('anime.all')} ({sum(counts.values())})", None)
        for st in STATUSES:
            if counts.get(st):
                self.filter.addItem(f"{status_name(st)} ({counts[st]})", st)
        self.filter.setCurrentIndex(max(self.filter.findData(current), 0))
        self.filter.blockSignals(False)

    def reload(self) -> None:
        self._fill_filter()
        selected = {it.data(0, Qt.ItemDataRole.UserRole) for it in self.tree.selectedItems()}
        self.tree.clear()
        for row in self.ctx.db.anime_entries(self.filter.currentData()):
            total = row["episodes"] or "?"
            nxt = airing_text(row["next_episode"], row["next_airing"]) if row["airing_status"] == "RELEASING" else ""
            item = QTreeWidgetItem([row["title"], f"{row['progress']} / {total}", score_label(row["score"]),
                                    status_name(row["status"]) + ("" if row["synced"] or not self.tracker.logged_in else " ⟳"), nxt])
            item.setData(0, Qt.ItemDataRole.UserRole, row["media_id"])
            self.tree.addTopLevelItem(item)
            item.setSelected(row["media_id"] in selected)
        self.message.setText(tr("anime.list_count", n=self.tree.topLevelItemCount()))
        self._buttons()

    def _ids(self) -> list[int]:
        return [it.data(0, Qt.ItemDataRole.UserRole) for it in self.tree.selectedItems()]

    def _buttons(self) -> None:
        has = bool(self.tree.selectedItems())
        for b in (self.plus_btn, self.minus_btn, self.status_btn, self.score_btn, self.remove_btn):
            b.setEnabled(has)

    def _changed(self) -> None:
        self.reload()
        self.list_changed.emit()

    def _bump(self, delta: int) -> None:
        for mid in self._ids():
            row = self.ctx.db.anime_get(mid)
            if row:
                self.tracker.set_progress(mid, row["progress"] + delta)
        self._changed()

    def _set_status(self, status: str) -> None:
        for mid in self._ids():
            row = self.ctx.db.anime_get(mid)
            if row:
                progress = row["episodes"] if status == "COMPLETED" and row["episodes"] else row["progress"]
                self.ctx.db.anime_upsert(media_id=mid, status=status, progress=progress, synced=0, updated_at=time.time())
        self._changed()

    def _set_score(self, score: int) -> None:
        for mid in self._ids():
            self.tracker.set_score(mid, score)
        self._changed()

    def _remove(self) -> None:
        ids = self._ids()
        if ids and QMessageBox.question(self, tr("anime.remove"), tr("anime.remove_confirm", n=len(ids))) == QMessageBox.StandardButton.Yes:
            for mid in ids:
                self.tracker.remove(mid)
            self._changed()

    def _open(self, item: QTreeWidgetItem) -> None:
        row = self.ctx.db.anime_get(item.data(0, Qt.ItemDataRole.UserRole))
        if row is None:
            return
        from anihub.ui.palette_providers import media_from_row

        self.open_media.emit(media_from_row(row))

    def _menu(self, pos) -> None:
        if not self.tree.selectedItems():
            return
        menu = QMenu(self)
        menu.addAction("+1", lambda: self._bump(1))
        menu.addAction("−1", lambda: self._bump(-1))
        sm = menu.addMenu(tr("anime.set_status"))
        for st in STATUSES:
            sm.addAction(status_name(st), lambda st=st: self._set_status(st))
        menu.addAction(tr("anime.remove"), self._remove)
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    # --- sync ----------------------------------------------------------------------------------

    def sync(self) -> None:
        if not self.tracker.logged_in:
            self.message.setText(tr("anime.sign_in_first"))
            return
        self.sync_btn.setEnabled(False)
        self.message.setText(tr("anime.syncing"))

        def done(result: tuple[int, int]) -> None:
            self.sync_btn.setEnabled(True)
            self.reload()
            self.message.setText(tr("anime.synced", sent=result[0], got=result[1]))
            self.list_changed.emit()

        def failed(exc: Exception) -> None:
            self.sync_btn.setEnabled(True)
            self.message.setText(tr("status.error", msg=str(exc)))

        run_async(self.tracker.sync, on_done=done, on_error=failed)


class AnimePage(QWidget):
    def __init__(self, ctx: AppContext, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.season = SeasonTab(ctx)
        self.mylist = MyListTab(ctx)
        self.watch = WatchTab(ctx)
        self.music = MusicTab(ctx)
        self.tabs = QTabWidget()
        self.tabs.addTab(self.season, tr("anime.tab.season"))
        self.tabs.addTab(self.mylist, tr("anime.tab.list"))
        self.tabs.addTab(self.watch, tr("anime.tab.watch"))
        self.tabs.addTab(self.music, tr("anime.tab.music"))
        self.account_btn = style.secondary(QPushButton(), "user")
        self.account_label = QLabel()
        style.role(self.account_label, "dim")
        head = QHBoxLayout()
        head.addStretch(1)
        head.addWidget(self.account_label)
        head.addWidget(self.account_btn)
        layout = QVBoxLayout(self)
        layout.addLayout(head)
        layout.addWidget(self.tabs, 1)
        self.season.open_media.connect(self.show_media)
        self.mylist.open_media.connect(self.show_media)
        self.season.list_changed.connect(self._list_changed)
        self.watch.list_changed.connect(self._list_changed)
        self.mylist.list_changed.connect(self._push_in_background)
        self.account_btn.clicked.connect(self.open_account)
        self.tabs.currentChanged.connect(self._tab_changed)
        self._refresh_account()

    def _tab_changed(self, index: int) -> None:
        widget = self.tabs.widget(index)
        if widget is self.season and not self.ctx.cfg.get("network.offline", False):
            self.season.ensure_loaded()
        elif widget is self.watch:
            self.watch.ensure_loaded()
        elif widget is self.mylist:
            self.mylist.reload()

    def showEvent(self, e) -> None:  # noqa: N802
        super().showEvent(e)
        self._tab_changed(self.tabs.currentIndex())

    def _refresh_account(self) -> None:
        tracker = self.ctx.anilist
        user = self.ctx.cfg.get("tracker.anilist.user", "")
        self.account_label.setText(f"AniList: {user}" if tracker.logged_in else tr("anime.not_signed"))
        self.account_btn.setText(tr("anime.account"))

    def open_account(self) -> None:
        dlg = AccountDialog(self.ctx, self)
        dlg.changed.connect(self._account_changed)
        dlg.exec()

    def _account_changed(self) -> None:
        self._refresh_account()
        if self.ctx.anilist.logged_in:
            self.mylist.sync()

    def show_media(self, media: dict) -> None:
        dlg = AnimeDetail(self.ctx, media, self)
        dlg.changed.connect(self._list_changed)
        dlg.exec()

    def _list_changed(self) -> None:
        self.mylist.reload()
        self._push_in_background()

    def _push_in_background(self) -> None:
        """Changes go to AniList right away when signed in and online; otherwise they wait (the ⟳ mark) for the next sync."""
        tracker = self.ctx.anilist
        if tracker.logged_in and not self.ctx.cfg.get("network.offline", False):
            run_async(tracker.push, on_done=lambda _n: self.mylist.reload(), on_error=lambda exc: None)

    def set_offline(self, offline: bool) -> None:
        index = self.tabs.indexOf(self.season)
        self.tabs.setTabEnabled(index, not offline)
        self.mylist.sync_btn.setEnabled(not offline)
        if offline and self.tabs.currentWidget() is self.season:
            self.tabs.setCurrentWidget(self.mylist)
