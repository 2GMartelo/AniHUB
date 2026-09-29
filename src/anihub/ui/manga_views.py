"""Manga tabs: library, browse sources, extensions, updates."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QTreeWidget,
    QTreeWidgetItem, QVBoxLayout, QWidget,
)

from anihub.context import AppContext
from anihub.core.i18n import get_language, tr
from anihub.ui import style
from anihub.services.suwayomi import SuwayomiError, filter_changes
from anihub.ui.manga_filters import FilterPanel, SourceSettingsDialog, is_account_pref
from anihub.ui.grid import ThumbGrid, image_to_thumb
from anihub.ui.manga_controller import MangaController
from anihub.ui.manga_detail import fmt_date
from anihub.ui.workers import run_async, run_status

LANG_NAMES = {"en": "English", "ru": "Русский", "ja": "日本語", "zh": "中文", "ko": "한국어", "es": "Español",
              "fr": "Français", "de": "Deutsch", "pt": "Português", "it": "Italiano", "id": "Indonesia",
              "tr": "Türkçe", "vi": "Tiếng Việt", "th": "ไทย", "ar": "العربية", "pl": "Polski", "uk": "Українська",
              "all": "Multi", "other": "Other", "localsourcelang": "Local"}


def lang_label(code: str) -> str:
    return f"{LANG_NAMES.get(code, code)} ({code})"


def nsfw_hidden(ctx: AppContext, warning: str) -> bool:
    """NSFW extensions/sources stay hidden until the 'explicit' rating is enabled in settings."""
    return warning == "NSFW" and "explicit" not in ctx.allowed_ratings()


def cover_entry(grid: ThumbGrid, api, manga: dict, badge: str = "") -> None:
    url = manga.get("thumbnailUrl")
    tip = manga["title"] + (f"\n{manga['author']}" if manga.get("author") else "")
    grid.add_entry(manga, tip, (lambda: image_to_thumb(api.fetch_bytes(url), grid.thumb_size, badge)) if url else (lambda: None))


def default_lang_index(combo: QComboBox) -> int:
    for wanted in (get_language(), "en"):
        i = combo.findData(wanted)
        if i >= 0:
            return i
    return 0


def library_match(manga: dict, text: str = "", genre: str | None = None, status: str | None = None,
                  unread_only: bool = False) -> bool:
    """Local filtering of the manga library: title substring, genre, publication status, unread chapters."""
    if genre and genre not in (manga.get("genre") or []):
        return False
    if status and manga.get("status") != status:
        return False
    if unread_only and not manga.get("unreadCount"):
        return False
    return text.lower().strip() in manga["title"].lower()


class MangaLibraryTab(QWidget):
    open_manga = Signal(int)

    def __init__(self, ctx: AppContext, ctrl: MangaController, parent=None):
        super().__init__(parent)
        self.ctx, self.ctrl, self.api = ctx, ctrl, ctx.suwayomi.api
        self._gen = 0
        self._loading_cats = False
        self.category = QComboBox()
        self.filter = QLineEdit(placeholderText=tr("manga.filter"))
        self.genre = QComboBox()
        self.status_box = QComboBox()
        self.unread_only = QCheckBox(tr("manga.unread_only"))
        self.check_btn = QPushButton(tr("manga.check_updates"))
        self.reload_btn = style.ghost(QPushButton(), "refresh")
        self.reload_btn.setFixedWidth(34)
        self.grid = ThumbGrid(ctx.cfg.get("ui.thumb_size", 180) + 20)
        self.status = QLabel()
        top = QHBoxLayout()
        for w, s in ((self.category, 0), (self.filter, 1), (self.genre, 0), (self.status_box, 0), (self.unread_only, 0),
                     (self.check_btn, 0), (self.reload_btn, 0)):
            top.addWidget(w, s)
        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(self.grid, 1)
        layout.addWidget(self.status)
        self.category.activated.connect(self.reload)
        self.filter.textChanged.connect(self._apply_filter)
        self.genre.activated.connect(self._apply_filter)
        self.status_box.activated.connect(self._apply_filter)
        self.unread_only.toggled.connect(self._apply_filter)
        self.reload_btn.clicked.connect(self.reload)
        self.check_btn.clicked.connect(self._check)
        self.grid.itemDoubleClicked.connect(lambda it: self.open_manga.emit(it.data(Qt.ItemDataRole.UserRole)["id"]))
        self._mangas: list[dict] = []

    def _check(self) -> None:
        self.status.setText(tr("manga.checking"))
        self.ctrl.check_updates(force_refresh=True)
        from PySide6.QtCore import QTimer
        QTimer.singleShot(45_000, lambda: (self.ctrl.check_updates(), self.reload()))  # sources need time to answer

    def reload(self) -> None:
        if not self.ctrl.state.ready:
            return
        self._gen += 1
        gen = self._gen
        selected = self.category.currentData()

        def work():
            return self.api.categories(), self.api.library(selected)

        def done(result) -> None:
            if gen != self._gen:
                return
            cats, mangas = result
            self._loading_cats = True
            self.category.clear()
            self.category.addItem(tr("manga.all"), None)
            for c in cats:
                if not c["default"]:
                    self.category.addItem(c["name"], c["id"])
            self.category.setCurrentIndex(max(self.category.findData(selected), 0))
            self._loading_cats = False
            self._mangas = mangas
            self._fill_facets()
            self._apply_filter()

        run_status(work, on_done=done, status=self.status)

    def _fill_facets(self) -> None:
        """Genres and publication statuses that actually occur in the library become filter choices."""
        genre, status = self.genre.currentData(), self.status_box.currentData()
        self.genre.clear()
        self.genre.addItem(tr("manga.any_genre"), None)
        for g in sorted({g for m in self._mangas for g in (m.get("genre") or [])}, key=str.lower):
            self.genre.addItem(g, g)
        self.genre.setCurrentIndex(max(self.genre.findData(genre), 0))
        self.status_box.clear()
        self.status_box.addItem(tr("manga.any_status"), None)
        for st in sorted({m.get("status") for m in self._mangas if m.get("status")}):
            self.status_box.addItem(tr(f"manga.status.{st}"), st)
        self.status_box.setCurrentIndex(max(self.status_box.findData(status), 0))

    def matches(self, manga: dict) -> bool:
        return library_match(manga, self.filter.text(), self.genre.currentData(), self.status_box.currentData(),
                             self.unread_only.isChecked())

    def _apply_filter(self) -> None:
        self.grid.clear_items()
        shown = [m for m in self._mangas if self.matches(m)]
        for m in shown:
            cover_entry(self.grid, self.api, m, str(m["unreadCount"]) if m["unreadCount"] else "")
        self.status.setText(tr("manga.library_count", n=len(shown)))


class MangaBrowseTab(QWidget):
    open_manga = Signal(int)

    def __init__(self, ctx: AppContext, ctrl: MangaController, parent=None):
        super().__init__(parent)
        self.ctx, self.ctrl, self.api = ctx, ctrl, ctx.suwayomi.api
        self._sources: list[dict] = []
        self._gen, self._page, self._loading, self._exhausted = 0, 1, False, True
        self.lang = QComboBox()
        self.source = QComboBox()
        self.source.setMinimumWidth(220)
        self.mode = QComboBox()
        self.mode.addItem(tr("manga.popular"), "POPULAR")
        self.mode.addItem(tr("manga.latest"), "LATEST")
        self.query = QLineEdit(placeholderText=tr("manga.search"))
        self.go = style.primary(QPushButton(tr("search.button")), "search")
        self.filters_btn = style.secondary(QPushButton(tr("manga.filters")), "filter")
        self.filters_btn.setCheckable(True)
        self.filters_btn.setToolTip(tr("manga.filters_tip"))
        self.settings_btn = style.secondary(QPushButton(tr("manga.source_settings")), "user")
        self.settings_btn.setToolTip(tr("manga.source_settings_tip"))
        self.settings_btn.hide()
        self.panel = FilterPanel()
        self.panel.hide()
        self._filters_for = ""
        self.grid = ThumbGrid(ctx.cfg.get("ui.thumb_size", 180) + 20)
        self.status = QLabel()
        top = QHBoxLayout()
        for w, s in ((self.lang, 0), (self.source, 0), (self.mode, 0), (self.query, 1), (self.go, 0),
                     (self.filters_btn, 0), (self.settings_btn, 0)):
            top.addWidget(w, s)
        body = QHBoxLayout()
        body.addWidget(self.grid, 1)
        body.addWidget(self.panel)
        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addLayout(body, 1)
        layout.addWidget(self.status)
        self.lang.activated.connect(self._fill_sources)
        self.source.currentIndexChanged.connect(self._source_changed)
        self.filters_btn.toggled.connect(self.panel.setVisible)
        self.panel.changed.connect(self._update_filter_badge)
        self.panel.apply_requested.connect(self.search)
        self.settings_btn.clicked.connect(self._open_source_settings)
        self.go.clicked.connect(self.search)
        self.query.returnPressed.connect(self.search)
        self.mode.activated.connect(self.search)
        self.grid.need_more.connect(self._load_page)
        self.grid.itemDoubleClicked.connect(lambda it: self.open_manga.emit(it.data(Qt.ItemDataRole.UserRole)["id"]))

    def reload_sources(self) -> None:
        if not self.ctrl.state.ready:
            return
        run_status(self.api.sources, on_done=self._sources_loaded, status=self.status)

    def _sources_loaded(self, sources: list[dict]) -> None:
        self._sources = [s for s in sources if not nsfw_hidden(self.ctx, s["extension"]["contentWarning"])]
        self.lang.blockSignals(True)
        self.lang.clear()
        for code in sorted({s["lang"] for s in self._sources}, key=lambda c: (c != get_language(), c != "en", c)):
            self.lang.addItem(lang_label(code), code)
        self.lang.setCurrentIndex(default_lang_index(self.lang))
        self.lang.blockSignals(False)
        self._fill_sources()
        if not self._sources:
            self.status.setText(tr("manga.no_sources"))

    def _fill_sources(self) -> None:
        code = self.lang.currentData()
        self.source.clear()
        for s in self._sources:
            if s["lang"] == code:
                self.source.addItem(s["displayName"], s)

    def _source_changed(self) -> None:
        """A new source: fetch its filters (genres, tags...) and show the login/settings button if it has any."""
        source = self.source.currentData()
        self.settings_btn.setVisible(bool(source and source.get("isConfigurable")))
        self.settings_btn.setText(tr("manga.source_settings"))
        self._filters_for = source["id"] if source else ""
        if source and source.get("isConfigurable"):
            wanted_id = source["id"]

            def account_check(prefs: list[dict]) -> None:              # a source with a login field says so on its button: "Sign in"
                current = self.source.currentData()
                if current and current["id"] == wanted_id and any(is_account_pref(p) for p in prefs):
                    self.settings_btn.setText(tr("manga.source_login"))

            run_async(self.api.source_preferences, wanted_id, on_done=account_check, on_error=lambda _e: None)
        self.panel.set_filters([])
        self.filters_btn.setEnabled(False)
        if source is None:
            return
        wanted = source["id"]

        def done(nodes: list[dict]) -> None:
            if wanted != self._filters_for:
                return
            self.panel.set_filters(nodes)
            self.filters_btn.setEnabled(bool(nodes))

        run_async(self.api.source_filters, wanted, on_done=done, on_error=lambda exc: None)

    def _update_filter_badge(self) -> None:
        n = self.panel.active_count()
        self.filters_btn.setText(tr("manga.filters") + (f" · {n}" if n else ""))

    def _open_source_settings(self) -> None:
        source = self.source.currentData()
        if source is None:
            return
        dialog = SourceSettingsDialog(self.api, source, self)
        dialog.exec()
        if dialog.changed:
            self.search()  # settings such as login or mirrors change what the source returns

    def search(self) -> None:
        if self.source.currentData() is None:
            return
        self._gen += 1
        self.grid.clear_items()
        self._page, self._loading, self._exhausted = 1, False, False
        self._load_page()

    def _load_page(self) -> None:
        source = self.source.currentData()
        if self._loading or self._exhausted or source is None:
            return
        self._loading = True
        self.status.setText(tr("status.loading"))
        gen, page, query = self._gen, self._page, self.query.text().strip()
        changes = filter_changes(self.panel.nodes, self.panel.state())
        kind = "SEARCH" if (query or changes) else self.mode.currentData()
        if kind == "LATEST" and not source["supportsLatest"]:
            kind = "POPULAR"

        def done(result) -> None:
            if gen != self._gen:
                return
            mangas, has_next = result
            self._loading, self._exhausted = False, not has_next
            self._page += 1
            for m in mangas:
                cover_entry(self.grid, self.api, m)
            self.status.setText(tr("status.count", n=self.grid.count()) + ("" if has_next else "  ·  " + tr("status.end")))
            if has_next and mangas:
                self.grid.request_fill()

        def failed(exc: Exception) -> None:
            if gen == self._gen:
                self._loading, self._exhausted = False, True
                self.status.setText(tr("status.error", msg=str(exc)))

        run_async(self.api.browse, source["id"], kind, page, query, changes, on_done=done, on_error=failed)


class MangaExtensionsTab(QWidget):
    catalogue_changed = Signal()

    def __init__(self, ctx: AppContext, ctrl: MangaController, parent=None):
        super().__init__(parent)
        self.ctx, self.ctrl, self.api = ctx, ctrl, ctx.suwayomi.api
        self._all: list[dict] = []
        self.search = QLineEdit(placeholderText=tr("ext.search"))
        self.lang = QComboBox()
        self.installed_only = QCheckBox(tr("ext.installed_only"))
        self.refresh_btn = QPushButton(tr("ext.refresh"))
        self.file_btn = QPushButton(tr("ext.from_file"))
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels([tr("ext.name"), tr("ext.lang"), tr("ext.version"), tr("ext.status")])
        self.tree.setRootIsDecorated(False)
        self.tree.setColumnWidth(0, 340)
        self.tree.setSortingEnabled(True)
        self.install_btn = QPushButton(tr("ext.install"))
        self.remove_btn = QPushButton(tr("ext.uninstall"))
        self.store_edit = QLineEdit(placeholderText=tr("ext.store_placeholder"))
        self.store_add = QPushButton(tr("ext.store_add"))
        self.stores = QComboBox()
        self.store_remove = QPushButton(tr("ext.store_remove"))
        self.status = QLabel()
        self.status.setWordWrap(True)

        top = QHBoxLayout()
        for w, s in ((self.search, 1), (self.lang, 0), (self.installed_only, 0), (self.refresh_btn, 0), (self.file_btn, 0)):
            top.addWidget(w, s)
        act = QHBoxLayout()
        act.addWidget(self.install_btn)
        act.addWidget(self.remove_btn)
        act.addStretch(1)
        stores = QHBoxLayout()
        for w, s in ((QLabel(tr("ext.stores")), 0), (self.stores, 1), (self.store_remove, 0), (self.store_edit, 2), (self.store_add, 0)):
            stores.addWidget(w, s)
        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(self.tree, 1)
        layout.addLayout(act)
        layout.addLayout(stores)
        layout.addWidget(self.status)

        self.search.textChanged.connect(self._fill)
        self.lang.activated.connect(self._fill)
        self.installed_only.toggled.connect(self._fill)
        self.refresh_btn.clicked.connect(self.refresh_catalogue)
        self.file_btn.clicked.connect(self._from_file)
        self.install_btn.clicked.connect(self._install)
        self.remove_btn.clicked.connect(self._uninstall)
        self.store_add.clicked.connect(self._add_store)
        self.store_remove.clicked.connect(self._remove_store)
        self.tree.itemSelectionChanged.connect(self._update_buttons)

    def _busy(self, text: str = "") -> None:
        for w in (self.install_btn, self.remove_btn, self.refresh_btn, self.file_btn, self.store_add, self.store_remove):
            w.setEnabled(not text)
        self.status.setText(text)
        if not text:
            self._update_buttons()

    def _error(self, exc: Exception) -> None:
        msg = str(exc)
        if "занят другим процессом" in msg or "being used by another process" in msg:
            msg = tr("ext.locked")  # Windows keeps the loaded jar locked until the service restarts
        self._busy()
        self.status.setText(tr("status.error", msg=msg))

    def load(self) -> None:
        if not self.ctrl.state.ready:
            return
        self._busy(tr("status.loading"))

        def work():
            return self.api.extensions(), self.api.stores()

        def done(result) -> None:
            self._all, stores = result
            self.stores.clear()
            for s in stores:
                self.stores.addItem(s["name"] or s["indexUrl"], s["indexUrl"])
            langs = sorted({e["lang"] for e in self._all}, key=lambda c: (c != get_language(), c != "en", c))
            wanted = self.lang.currentData()
            self.lang.clear()
            self.lang.addItem(tr("ext.all_langs"), None)
            for code in langs:
                self.lang.addItem(lang_label(code), code)
            self.lang.setCurrentIndex(max(self.lang.findData(wanted), 0) if wanted else max(self.lang.findData(get_language()), 0))
            self._fill()
            self._busy()

        run_async(work, on_done=done, on_error=self._error)

    def refresh_catalogue(self) -> None:
        self._busy(tr("ext.refreshing"))
        run_async(self.api.refresh_extensions, on_done=lambda _: self.load(), on_error=self._error)

    def _fill(self) -> None:
        text, code, only = self.search.text().lower().strip(), self.lang.currentData(), self.installed_only.isChecked()
        self.tree.setSortingEnabled(False)
        self.tree.clear()
        n = 0
        for e in self._all:
            if code and e["lang"] != code:
                continue
            if only and not e["isInstalled"]:
                continue
            if text and text not in e["name"].lower():
                continue
            if nsfw_hidden(self.ctx, e["contentWarning"]) and not e["isInstalled"]:
                continue
            state = (tr("ext.state.update") if e["hasUpdate"] else tr("ext.state.installed")) if e["isInstalled"] else ""
            if e["isObsolete"]:
                state += " " + tr("ext.state.obsolete")
            name = e["name"].removeprefix("Tachiyomi: ") + ("  [18+]" if e["contentWarning"] == "NSFW" else "")
            item = QTreeWidgetItem([name, e["lang"], e["versionName"], state.strip()])
            item.setData(0, Qt.ItemDataRole.UserRole, e)
            self.tree.addTopLevelItem(item)
            n += 1
        self.tree.setSortingEnabled(True)
        self.status.setText(tr("ext.count", n=n, total=len(self._all)))
        self._update_buttons()

    def _selected(self) -> dict | None:
        items = self.tree.selectedItems()
        return items[0].data(0, Qt.ItemDataRole.UserRole) if items else None

    def _update_buttons(self) -> None:
        e = self._selected()
        self.install_btn.setEnabled(bool(e) and (not e["isInstalled"] or e["hasUpdate"]))
        self.install_btn.setText(tr("ext.update") if e and e["isInstalled"] and e["hasUpdate"] else tr("ext.install"))
        self.remove_btn.setEnabled(bool(e) and e["isInstalled"])

    def _act(self, action: str) -> None:
        e = self._selected()
        if not e:
            return
        self._busy(tr("ext.working", name=e["name"]))
        run_async(self.api.set_extension, e["pkgName"], action, on_done=lambda _: (self.catalogue_changed.emit(), self.load()),
                  on_error=self._error)

    def _install(self) -> None:
        e = self._selected()
        self._act("update" if e and e["isInstalled"] else "install")

    def _uninstall(self) -> None:
        self._act("uninstall")

    def _from_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, tr("ext.from_file"), "", "Extensions (*.jar *.apk)")
        if not path:
            return
        from pathlib import Path
        self._busy(tr("ext.working", name=Path(path).name))

        def done(_) -> None:
            self.catalogue_changed.emit()
            self.load()

        def failed(exc: Exception) -> None:
            self._error(exc)
            self.status.setText(self.status.text() + "\n" + tr("ext.file_hint"))

        run_async(self.api.install_external, Path(path), on_done=done, on_error=failed)

    def _add_store(self) -> None:
        url = self.store_edit.text().strip()
        if not url:
            return
        self._busy(tr("ext.refreshing"))

        def work():
            self.api.add_store(url)
            return self.api.refresh_extensions()

        run_async(work, on_done=lambda _: (self.store_edit.clear(), self.load()), on_error=self._error)

    def _remove_store(self) -> None:
        url = self.stores.currentData()
        if url and QMessageBox.question(self, tr("ext.store_remove"), url) == QMessageBox.StandardButton.Yes:
            self._busy(tr("ext.refreshing"))
            run_async(self.api.remove_store, url, on_done=lambda _: self.load(), on_error=self._error)


class MangaUpdatesTab(QWidget):
    open_chapter = Signal(int, int)  # manga id, chapter id

    def __init__(self, ctx: AppContext, ctrl: MangaController, parent=None):
        super().__init__(parent)
        self.ctx, self.ctrl, self.api = ctx, ctrl, ctx.suwayomi.api
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels([tr("manga.title"), tr("manga.chapter"), tr("manga.date")])
        self.tree.setRootIsDecorated(False)
        self.tree.setColumnWidth(0, 360)
        self.tree.setColumnWidth(1, 300)
        self.unread_only = QCheckBox(tr("manga.unread_only"), checked=True)
        self.reload_btn = style.ghost(QPushButton(), "refresh")
        self.reload_btn.setFixedWidth(34)
        self.status = QLabel()
        top = QHBoxLayout()
        top.addWidget(self.unread_only)
        top.addStretch(1)
        top.addWidget(self.reload_btn)
        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(self.tree, 1)
        layout.addWidget(self.status)
        self.reload_btn.clicked.connect(self.reload)
        self.unread_only.toggled.connect(self.reload)
        self.tree.itemDoubleClicked.connect(lambda it: self.open_chapter.emit(*it.data(0, Qt.ItemDataRole.UserRole)))

    def reload(self) -> None:
        if not self.ctrl.state.ready:
            return
        only = self.unread_only.isChecked()

        def work():
            flt = {"inLibrary": {"equalTo": True}}
            if only:
                flt["isRead"] = {"equalTo": False}
            return self.api.gql(
                "query($f:ChapterFilterInput){ chapters(filter:$f, order:[{by:UPLOAD_DATE, byType:DESC}], first:150)"
                "{ nodes { id name uploadDate isRead manga { id title } } } }", {"f": flt})["chapters"]["nodes"]

        def done(nodes: list[dict]) -> None:
            self.tree.clear()
            for c in nodes:
                item = QTreeWidgetItem([c["manga"]["title"], c["name"], fmt_date(c["uploadDate"])])
                item.setData(0, Qt.ItemDataRole.UserRole, (c["manga"]["id"], c["id"]))
                self.tree.addTopLevelItem(item)
            self.status.setText(tr("manga.updates_count", n=len(nodes)))

        run_status(work, on_done=done, status=self.status)
