"""Manga tracking (ТЗ 4.9): tracker accounts (MyAnimeList, AniList, Kitsu...) and per-title binding. Suwayomi keeps the accounts
and pushes reading progress; this is the UI for it."""
from __future__ import annotations

import html

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDoubleSpinBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMessageBox, QPushButton, QStackedWidget, QVBoxLayout, QWidget,
)

from anihub.core.i18n import tr
from anihub.services.suwayomi import oauth_callback
from anihub.ui import style
from anihub.ui.workers import run_async, run_status


class TrackerAccountsDialog(QDialog):
    """Sign in / out of the trackers Suwayomi supports."""

    changed = Signal()

    def __init__(self, api, parent=None):
        super().__init__(parent)
        self.api = api
        self.trackers: list[dict] = []
        self.setWindowTitle(tr("track.accounts"))
        self.resize(640, 460)
        hint = QLabel(tr("track.accounts_hint"))
        hint.setWordWrap(True)
        style.role(hint, "dim")
        self.list = QListWidget()
        self.list.setMaximumWidth(200)
        self.state = QLabel()
        self.state.setWordWrap(True)
        # OAuth page: open the site, approve, paste the address the browser ends up on
        self.open_btn = style.secondary(QPushButton(tr("track.open_login")), "external")
        self.paste = QLineEdit(placeholderText=tr("track.paste_ph"))
        self.paste_btn = style.primary(QPushButton(tr("track.sign_in")), "check")
        oauth = QWidget()
        ol = QVBoxLayout(oauth)
        ol.setContentsMargins(0, 0, 0, 0)
        steps = QLabel(tr("track.oauth_steps"))
        steps.setWordWrap(True)
        for w in (steps, self.open_btn, self.paste, self.paste_btn):
            ol.addWidget(w)
        ol.addStretch(1)
        # credentials page (Kitsu)
        self.user = QLineEdit(placeholderText=tr("track.username"))
        self.password = QLineEdit(placeholderText=tr("track.password"))
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.cred_btn = style.primary(QPushButton(tr("track.sign_in")), "check")
        cred = QWidget()
        cl = QVBoxLayout(cred)
        cl.setContentsMargins(0, 0, 0, 0)
        for w in (self.user, self.password, self.cred_btn):
            cl.addWidget(w)
        cl.addStretch(1)
        self.pages = QStackedWidget()
        self.pages.addWidget(oauth)
        self.pages.addWidget(cred)
        self.logout_btn = style.danger(QPushButton(tr("track.sign_out")), "x")
        self.message = QLabel()
        self.message.setWordWrap(True)
        right = QVBoxLayout()
        right.addWidget(self.state)
        right.addWidget(self.pages)
        right.addWidget(self.logout_btn, 0, Qt.AlignmentFlag.AlignLeft)
        right.addWidget(self.message)
        right.addStretch(1)
        body = QHBoxLayout()
        body.addWidget(self.list)
        body.addLayout(right, 1)
        layout = QVBoxLayout(self)
        layout.addWidget(hint)
        layout.addLayout(body, 1)

        self.list.currentRowChanged.connect(self._select)
        self.open_btn.clicked.connect(self._open_login)
        self.paste_btn.clicked.connect(self._login_oauth)
        self.paste.returnPressed.connect(self._login_oauth)
        self.cred_btn.clicked.connect(self._login_credentials)
        self.logout_btn.clicked.connect(self._logout)
        self.reload()

    def reload(self) -> None:
        current = self.list.currentRow()
        run_async(self.api.trackers, on_done=lambda t: self._loaded(t, current), on_error=self._failed)

    def _loaded(self, trackers: list[dict], row: int) -> None:
        self.trackers = trackers
        self.list.blockSignals(True)
        self.list.clear()
        for t in trackers:
            item = QListWidgetItem(("● " if t["isLoggedIn"] else "○ ") + t["name"])
            self.list.addItem(item)
        self.list.blockSignals(False)
        self.list.setCurrentRow(max(row, 0) if trackers else -1)
        self._select(self.list.currentRow())

    def _current(self) -> dict | None:
        row = self.list.currentRow()
        return self.trackers[row] if 0 <= row < len(self.trackers) else None

    def _select(self, _row: int) -> None:
        t = self._current()
        if t is None:
            return
        if t["isLoggedIn"]:
            text = tr("track.signed_in", name=t["name"]) + (" " + tr("track.expired") if t.get("isTokenExpired") else "")
        else:
            text = tr("track.not_signed", name=t["name"])
        self.state.setText(text)
        self.logout_btn.setVisible(t["isLoggedIn"])
        self.pages.setVisible(not t["isLoggedIn"] or bool(t.get("isTokenExpired")))
        self.pages.setCurrentIndex(0 if t.get("authUrl") else 1)

    def _failed(self, exc: Exception) -> None:
        self.message.setText(tr("status.error", msg=str(exc)))

    def _open_login(self) -> None:
        t = self._current()
        if t and t.get("authUrl"):
            QDesktopServices.openUrl(QUrl(t["authUrl"]))

    def _after_login(self, ok: bool) -> None:
        self.message.setText(tr("track.login_ok") if ok else tr("track.login_failed"))
        self.paste.clear()
        self.password.clear()
        self.changed.emit()
        self.reload()

    def _login_oauth(self) -> None:
        t = self._current()
        text = self.paste.text().strip()
        if t is None or not text:
            return
        callback = oauth_callback(t["name"], text)
        run_async(self.api.tracker_login_oauth, t["id"], callback, on_done=self._after_login, on_error=self._failed)

    def _login_credentials(self) -> None:
        t = self._current()
        if t is None or not self.user.text().strip() or not self.password.text():
            return
        run_async(self.api.tracker_login_credentials, t["id"], self.user.text().strip(), self.password.text(),
                  on_done=self._after_login, on_error=self._failed)

    def _logout(self) -> None:
        t = self._current()
        if t is None:
            return

        def done(_r) -> None:
            self.message.setText(tr("track.logged_out"))
            self.changed.emit()
            self.reload()

        run_async(self.api.tracker_logout, t["id"], on_done=done, on_error=self._failed)


class TrackCard(QGroupBox):
    """One tracker for one title: the bound record (status / chapters / score) or a search to bind it."""

    changed = Signal()

    def __init__(self, api, manga: dict, tracker: dict, record: dict | None, parent=None):
        super().__init__(tracker["name"], parent)
        self.api, self.manga, self.tracker, self.record = api, manga, tracker, record
        self.layout_ = QVBoxLayout(self)
        self.message = QLabel()
        style.role(self.message, "dim")
        if record:
            self._build_record()
        else:
            self._build_search()
        self.layout_.addWidget(self.message)

    # --- bound ----------------------------------------------------------------------------------

    def _build_record(self) -> None:
        r = self.record
        title = QLabel(f'<a href="{html.escape(r["remoteUrl"])}">{html.escape(r["title"])}</a>')
        title.setOpenExternalLinks(True)
        self.status = QComboBox()
        for s in self.tracker["statuses"]:
            self.status.addItem(s["name"], s["value"])
        self.status.setCurrentIndex(max(self.status.findData(r["status"]), 0))
        self.chapters = QDoubleSpinBox(minimum=0, maximum=r["totalChapters"] or 99999, decimals=1, singleStep=1,
                                       value=float(r["lastChapterRead"]))
        self.score = QComboBox()
        for sc in self.tracker["scores"]:
            self.score.addItem(sc, sc)
        self.score.setCurrentIndex(max(self.score.findData(r["displayScore"]), 0))
        form = QFormLayout()
        form.addRow(tr("track.status"), self.status)
        form.addRow(tr("track.chapters") + (f" / {r['totalChapters']}" if r["totalChapters"] else ""), self.chapters)
        form.addRow(tr("track.score"), self.score)
        self.save_btn = style.primary(QPushButton(tr("anime.save")), "check")
        self.unbind_btn = style.danger(QPushButton(tr("track.unbind")), "trash")
        row = QHBoxLayout()
        row.addWidget(self.save_btn)
        row.addWidget(self.unbind_btn)
        row.addStretch(1)
        for w in (title,):
            self.layout_.addWidget(w)
        self.layout_.addLayout(form)
        self.layout_.addLayout(row)
        self.save_btn.clicked.connect(self._save)
        self.unbind_btn.clicked.connect(self._unbind)

    def _save(self) -> None:
        rid, status, chapters, score = self.record["id"], self.status.currentData(), self.chapters.value(), self.score.currentData()
        run_async(lambda: self.api.track_update(rid, status=status, last_chapter_read=chapters, score=score),
                  on_done=lambda _r: self.message.setText(tr("anime.saved")), on_error=self._failed)

    def _unbind(self) -> None:
        delete = False
        if self.tracker.get("supportsTrackDeletion"):
            answer = QMessageBox.question(self, tr("track.unbind"), tr("track.unbind_confirm", name=self.tracker["name"]),
                                          QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                                          | QMessageBox.StandardButton.Cancel)
            if answer == QMessageBox.StandardButton.Cancel:
                return
            delete = answer == QMessageBox.StandardButton.Yes
        run_async(self.api.track_unbind, self.record["id"], delete, on_done=lambda _r: self.changed.emit(), on_error=self._failed)

    # --- not bound ------------------------------------------------------------------------------

    def _build_search(self) -> None:
        self.query = QLineEdit(self.manga["title"])
        self.go = style.primary(QPushButton(tr("search.button")), "search")
        self.results = QListWidget()
        self.results.setMaximumHeight(150)
        self.bind_btn = style.secondary(QPushButton(tr("track.bind")), "plus")
        self.bind_btn.setEnabled(False)
        row = QHBoxLayout()
        row.addWidget(self.query, 1)
        row.addWidget(self.go)
        self.layout_.addLayout(row)
        self.layout_.addWidget(self.results)
        self.layout_.addWidget(self.bind_btn, 0, Qt.AlignmentFlag.AlignLeft)
        self.go.clicked.connect(self._search)
        self.query.returnPressed.connect(self._search)
        self.bind_btn.clicked.connect(self._bind)
        self.results.itemSelectionChanged.connect(lambda: self.bind_btn.setEnabled(bool(self.results.selectedItems())))
        self.results.itemDoubleClicked.connect(lambda _i: self._bind())

    def _search(self) -> None:
        text = self.query.text().strip()
        if not text:
            return
        self.message.setText(tr("status.loading"))

        def done(found: list[dict]) -> None:
            self.results.clear()
            for r in found:
                extra = " · ".join(x for x in (r["publishingType"], r["publishingStatus"],
                                               tr("track.n_chapters", n=r["totalChapters"]) if r["totalChapters"] else "") if x)
                item = QListWidgetItem(f"{r['title']}   ({extra})" if extra else r["title"])
                item.setData(Qt.ItemDataRole.UserRole, r["remoteId"])
                item.setToolTip(r.get("summary", "")[:400])
                self.results.addItem(item)
            self.message.setText(tr("track.found", n=len(found)))

        run_async(self.api.track_search, self.tracker["id"], text, on_done=done, on_error=self._failed)

    def _bind(self) -> None:
        item = self.results.currentItem()
        if item is None:
            return
        self.bind_btn.setEnabled(False)
        run_async(self.api.track_bind, self.manga["id"], self.tracker["id"], item.data(Qt.ItemDataRole.UserRole),
                  on_done=lambda _r: self.changed.emit(), on_error=self._failed)

    def _failed(self, exc: Exception) -> None:
        self.message.setText(tr("status.error", msg=str(exc)))


class TrackDialog(QDialog):
    """Bind one manga to its entry on each tracker you are signed in to."""

    def __init__(self, api, manga: dict, parent=None):
        super().__init__(parent)
        self.api, self.manga = api, manga
        self.setWindowTitle(tr("track.title", title=manga["title"]))
        self.resize(560, 620)
        self.body = QVBoxLayout()
        self.accounts_btn = style.secondary(QPushButton(tr("track.accounts")), "user")
        self.message = QLabel()
        style.role(self.message, "dim")
        self.message.setWordWrap(True)
        layout = QVBoxLayout(self)
        layout.addLayout(self.body, 1)
        layout.addWidget(self.message)
        layout.addWidget(self.accounts_btn, 0, Qt.AlignmentFlag.AlignLeft)
        self.accounts_btn.clicked.connect(self._accounts)
        self.reload()

    def _accounts(self) -> None:
        dlg = TrackerAccountsDialog(self.api, self)
        dlg.changed.connect(self.reload)
        dlg.exec()
        self.reload()

    def reload(self) -> None:
        self.message.setText(tr("status.loading"))

        def work():
            return self.api.trackers(), self.api.track_records(self.manga["id"])

        run_status(work, on_done=self._loaded, status=self.message)

    def _loaded(self, result) -> None:
        trackers, records = result
        while self.body.count():
            item = self.body.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()
        by_tracker = {r["trackerId"]: r for r in records}
        signed = [t for t in trackers if t["isLoggedIn"]]
        for t in signed:
            card = TrackCard(self.api, self.manga, t, by_tracker.get(t["id"]))
            card.changed.connect(self.reload)
            self.body.addWidget(card)
        self.body.addStretch(1)
        self.message.setText("" if signed else tr("track.none_signed"))
