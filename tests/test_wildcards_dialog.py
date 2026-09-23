from anihub.context import AppContext
from anihub.core.config import Config
from anihub.ui.wildcards_dialog import WildcardsDialog


def make_ctx(tmp_path, **wildcards):
    cfg = Config.load(tmp_path / "c.json")
    cfg.set("library_path", str(tmp_path / "lib"), save=False)
    if wildcards:
        cfg.set("wildcards", wildcards, save=False)
    return AppContext.build(cfg)


def test_dialog_loads_existing_lists(qapp, tmp_path):
    dlg = WildcardsDialog(make_ctx(tmp_path, outfits=["kimono", "swimsuit"]))
    assert dlg.names.count() == 1 and dlg.names.item(0).text() == "outfits"
    dlg.names.setCurrentItem(dlg.names.item(0))
    assert dlg.entries.toPlainText() == "kimono\nswimsuit"


def test_adding_a_list_and_its_entries_persists_to_config(qapp, tmp_path, monkeypatch):
    from anihub.ui import wildcards_dialog as wd

    monkeypatch.setattr(wd.QInputDialog, "getText", staticmethod(lambda *a, **k: ("poses", True)))
    ctx = make_ctx(tmp_path)
    dlg = WildcardsDialog(ctx)
    dlg.add_btn.click()                                                       # goes through the real _add_list() path
    assert dlg.names.count() == 1 and dlg.names.currentItem().text() == "poses"
    dlg.entries.setPlainText("standing\nsitting")
    assert ctx.cfg.get("wildcards")["poses"] == ["standing", "sitting"]


def test_removing_a_list_drops_it_from_config(qapp, tmp_path):
    ctx = make_ctx(tmp_path, outfits=["kimono"])
    dlg = WildcardsDialog(ctx)
    dlg.names.setCurrentItem(dlg.names.item(0))
    dlg.remove_btn.click()
    assert dlg.names.count() == 0
    assert "outfits" not in ctx.cfg.get("wildcards")


def test_empty_lists_are_not_saved(qapp, tmp_path):
    ctx = make_ctx(tmp_path)
    dlg = WildcardsDialog(ctx)
    dlg.lists["empty"] = []
    from PySide6.QtWidgets import QListWidgetItem
    dlg.names.addItem(QListWidgetItem("empty"))
    dlg.names.setCurrentItem(dlg.names.item(0))
    dlg._persist()
    assert "empty" not in ctx.cfg.get("wildcards")
