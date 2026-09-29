"""ui/koikatsucards_dialog.py: search results populate with covers, and "Download selected" saves into
<koikatsu folder>/UserData/chara/female (services/koikatsucards.py's own cards_dir())."""
import time
from types import SimpleNamespace

from PySide6.QtCore import Qt

from anihub.core.config import Config
from anihub.core.paths import LibraryPaths
from anihub.net.http import HttpClient
from anihub.services import koikatsucards as kkc
from anihub.ui.koikatsucards_dialog import KoikatsuCardsDialog, cards_dir


def wait(qapp, cond, limit=5):
    end = time.time() + limit
    while time.time() < end and not cond():
        qapp.processEvents()
        time.sleep(0.01)


def make_ctx(tmp_path, koikatsu_path: str = ""):
    cfg = Config.load(tmp_path / "c.json")
    cfg.set("library_path", str(tmp_path / "lib"), save=False)
    if koikatsu_path:
        cfg.set("koikatsu.path", koikatsu_path, save=False)
    http = HttpClient(cfg)
    return SimpleNamespace(cfg=cfg, http=http, paths=LibraryPaths(tmp_path / "lib"))


def test_cards_dir_is_the_games_own_female_character_folder(tmp_path):
    assert cards_dir(str(tmp_path / "Koikatsu")) == tmp_path / "Koikatsu" / "UserData" / "chara" / "female"


def test_dialog_searches_on_open_and_lists_results(qapp, tmp_path, monkeypatch):
    monkeypatch.setattr(kkc, "search", lambda http, q, page=1: [kkc.Card("slug-1", "Title 1", "Original", "Author", "")])
    ctx = make_ctx(tmp_path)
    dlg = KoikatsuCardsDialog(ctx)
    wait(qapp, lambda: dlg.results.count() == 1)
    assert dlg.results.item(0).data(Qt.ItemDataRole.UserRole) == "slug-1"
    dlg.close()


def test_download_selected_needs_a_koikatsu_folder_first(qapp, tmp_path, monkeypatch):
    monkeypatch.setattr(kkc, "search", lambda http, q, page=1: [kkc.Card("slug-1", "Title 1", "Original", "Author", "")])
    ctx = make_ctx(tmp_path)                                    # no koikatsu.path set
    dlg = KoikatsuCardsDialog(ctx)
    wait(qapp, lambda: dlg.results.count() == 1)
    dlg.results.setCurrentRow(0)
    monkeypatch.setattr("anihub.ui.koikatsucards_dialog.QMessageBox.information", lambda *a, **k: None)
    dlg._download_selected()
    assert not (tmp_path / "lib").exists() or not any((tmp_path / "lib").rglob("*.png"))
    dlg.close()


def test_download_selected_saves_the_card_and_reports_how_many(qapp, tmp_path, monkeypatch):
    koikatsu = tmp_path / "Koikatsu"
    monkeypatch.setattr(kkc, "search", lambda http, q, page=1: [kkc.Card("slug-1", "Title 1", "Original", "Author", "")])
    monkeypatch.setattr(kkc, "download_card", lambda http, slug, dest: (dest / f"{slug}.png").parent.mkdir(parents=True, exist_ok=True)
                        or (dest / f"{slug}.png").write_bytes(b"card") or (dest / f"{slug}.png"))
    ctx = make_ctx(tmp_path, koikatsu_path=str(koikatsu))
    dlg = KoikatsuCardsDialog(ctx)
    wait(qapp, lambda: dlg.results.count() == 1)
    dlg.results.setCurrentRow(0)
    received = []
    dlg.downloaded.connect(received.append)
    dlg._download_selected()
    wait(qapp, lambda: received)
    assert received == [1]
    assert (koikatsu / "UserData" / "chara" / "female" / "slug-1.png").read_bytes() == b"card"
    dlg.close()
