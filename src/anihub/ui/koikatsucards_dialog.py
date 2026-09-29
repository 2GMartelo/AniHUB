"""Search koikatsucards.com and download character cards straight into the configured Koikatsu install
(services/koikatsucards.py). Downloading needs the site's own login cookie -- imported the same way as any other
source's, via Settings' "Import logins from a file" (see the hint label below)."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPushButton, QVBoxLayout,
)

from anihub.context import AppContext
from anihub.core.i18n import tr
from anihub.services import koikatsucards as kkc
from anihub.ui import style
from anihub.ui.workers import run_async


def cards_dir(koikatsu_path: str) -> Path:
    """Where a downloaded character card goes: <Koikatsu install>\\UserData\\chara\\female, the game's own folder
    for character cards it will list in-game."""
    return Path(koikatsu_path) / "UserData" / "chara" / "female"


class KoikatsuCardsDialog(QDialog):
    downloaded = Signal(int)          # how many cards were saved, once the batch finishes

    def __init__(self, ctx: AppContext, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self._results: list[kkc.Card] = []
        self.setWindowTitle(tr("kkc.title"))
        self.resize(640, 560)
        hint = style.role(QLabel(tr("kkc.hint")), "dim")
        hint.setWordWrap(True)
        self.query = QLineEdit(placeholderText=tr("kkc.query_ph"))
        self.go = style.primary(QPushButton(tr("search.button")), "search")
        self.results = QListWidget()
        self.results.setIconSize(QSize(64, 88))
        self.results.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.status = style.role(QLabel(), "dim")
        self.status.setWordWrap(True)
        self.download_btn = style.primary(QPushButton(tr("kkc.download_selected")), "download")
        self.download_btn.setEnabled(False)
        row = QHBoxLayout()
        row.addWidget(self.query, 1)
        row.addWidget(self.go)
        layout = QVBoxLayout(self)
        layout.addWidget(hint)
        layout.addLayout(row)
        layout.addWidget(self.results, 1)
        layout.addWidget(self.status)
        layout.addWidget(self.download_btn, 0, Qt.AlignmentFlag.AlignLeft)
        self.go.clicked.connect(self._search)
        self.query.returnPressed.connect(self._search)
        self.results.itemSelectionChanged.connect(lambda: self.download_btn.setEnabled(bool(self.results.selectedItems())))
        self.download_btn.clicked.connect(self._download_selected)
        self._search()

    def _search(self) -> None:
        self.status.setText(tr("status.loading"))
        self.go.setEnabled(False)
        query = self.query.text().strip()

        def done(cards: list[kkc.Card]) -> None:
            self.go.setEnabled(True)
            self._results = cards
            self.results.clear()
            for card in cards:
                extra = f" · {card.work}" if card.work and card.work != "Original" else ""
                item = QListWidgetItem(f"{card.title}{extra}\n{card.author}")
                item.setData(Qt.ItemDataRole.UserRole, card.slug)
                self.results.addItem(item)
                if card.thumb:
                    run_async(self.ctx.http.get_bytes, card.thumb, on_done=lambda data, it=item: self._set_thumb(it, data),
                              on_error=lambda _exc: None)
            self.status.setText(tr("kkc.found", n=len(cards)))

        def failed(exc: Exception) -> None:
            self.go.setEnabled(True)
            self.status.setText(tr("status.error", msg=str(exc)))

        run_async(kkc.search, self.ctx.http, query, on_done=done, on_error=failed)

    def _set_thumb(self, item: QListWidgetItem, data: bytes) -> None:
        try:
            item.listWidget()
        except RuntimeError:
            return
        pix = QPixmap()
        if pix.loadFromData(data):
            item.setIcon(QIcon(pix.scaled(64, 88, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)))

    def _download_selected(self) -> None:
        koikatsu_path = str(self.ctx.cfg.get("koikatsu.path") or "").strip()
        if not koikatsu_path:
            QMessageBox.information(self, tr("kkc.title"), tr("kkc.need_folder"))
            return
        slugs = [item.data(Qt.ItemDataRole.UserRole) for item in self.results.selectedItems()]
        dest = cards_dir(koikatsu_path)
        self.download_btn.setEnabled(False)
        self.status.setText(tr("status.loading"))

        def work() -> tuple[int, str]:
            saved, error = 0, ""
            for slug in slugs:
                try:
                    kkc.download_card(self.ctx.http, slug, dest)
                    saved += 1
                except kkc.KoikatsuCardsError as exc:
                    error = str(exc)
                    break
            return saved, error

        def done(result: tuple[int, str]) -> None:
            saved, error = result
            self.download_btn.setEnabled(True)
            self.status.setText(tr("kkc.saved", n=saved, path=str(dest)) + (f"\n{error}" if error else ""))
            if saved:
                self.downloaded.emit(saved)

        run_async(work, on_done=done, on_error=lambda exc: (self.download_btn.setEnabled(True), self.status.setText(tr("status.error", msg=str(exc)))))
