from pathlib import Path

import pytest
from PySide6.QtCore import Qt

from anihub.core.config import Config
from anihub.core.db import Database
from anihub.core.paths import LibraryPaths
from anihub.library.rules import RuleEngine, has_actions, has_conditions, parse_list
from anihub.library.service import LibraryService
from tests.test_library_service import FileHttp, make_image, save_png


@pytest.fixture
def db(tmp_path):
    return Database(tmp_path / "t.db")


def add(db, name, tags=(), **kw):
    kw.setdefault("path", f"arts/{name}.png")
    return db.add_item(tags=[(t, "general") for t in tags], kind=kw.pop("kind", "art"), **kw)


def test_parse_list_and_validators():
    assert parse_list("a b,  c\nd") == ["a", "b", "c", "d"] and parse_list("") == []
    assert not has_conditions({}) and has_conditions({"authors": ["x"]})
    assert not has_actions({}) and has_actions({"stars": 0}) and has_actions({"add_tags": ["t"]})


def test_rule_puts_matching_items_into_a_collection(db):
    col = db.create_collection("Cats")
    a, b, c = add(db, "a", ["cat"]), add(db, "b", ["cat", "dog"]), add(db, "c", ["dog"])
    db.save_rule("cats not dogs", {"tags_all": ["cat"], "tags_none": ["dog"]}, {"collection_id": col})
    result = RuleEngine(db).apply([a, b, c])
    assert list(result.values()) == [1]
    assert [r["id"] for r in db.search_items(collection_id=col)] == [a]


def test_rule_without_conditions_never_matches(db):
    a = add(db, "a", ["cat"])
    db.save_rule("bad", {}, {"favorite": True})
    assert RuleEngine(db).apply([a]) == {}
    assert db.get_item(a)["favorite"] == 0


def test_author_site_rating_conditions_and_actions(db):
    a = add(db, "a", author="Alice Bob", source_site="danbooru", rating="general")
    b = add(db, "b", author="carol", source_site="danbooru", rating="general")
    c = add(db, "c", author="alice", source_site="local", rating="general")
    db.save_rule("alice on danbooru", {"authors": ["alice"], "sites": ["danbooru"]},
                 {"favorite": True, "stars": 5, "add_tags": ["fav_artist"], "rating": "sensitive"})
    RuleEngine(db).apply([a, b, c])
    row = db.get_item(a)
    assert (row["favorite"], row["stars"], row["rating"]) == (1, 5, "sensitive")
    assert "fav_artist" in db.item_tags(a)
    assert db.get_item(b)["favorite"] == 0 and db.get_item(c)["favorite"] == 0


def test_parent_tag_condition_matches_children(db):
    a = add(db, "a", ["hatsune_miku"])
    db.set_tag_parent("hatsune_miku", "vocaloid")
    db.save_rule("vocaloid", {"tags_any": ["vocaloid"]}, {"add_tags": ["music"]})
    RuleEngine(db).apply([a])
    assert "music" in db.item_tags(a)


def test_rules_run_in_order_and_can_chain(db):
    a = add(db, "a", ["cat"])
    db.save_rule("first", {"tags_all": ["cat"]}, {"add_tags": ["pet"]})
    db.save_rule("second", {"tags_all": ["pet"]}, {"favorite": True})
    RuleEngine(db).apply([a])
    assert db.get_item(a)["favorite"] == 1


def test_disabled_rules_and_trashed_items_are_skipped(db):
    a, b = add(db, "a", ["cat"]), add(db, "b", ["cat"])
    rid = db.save_rule("r", {"tags_all": ["cat"]}, {"favorite": True}, enabled=False)
    assert RuleEngine(db).apply([a]) == {}
    db.set_rule_enabled(rid, True)
    db.update_fields(b, trashed_at=1.0)
    RuleEngine(db).apply([a, b])
    assert db.get_item(a)["favorite"] == 1 and db.get_item(b)["favorite"] == 0


def test_deleted_collection_does_not_break_the_rule(db):
    col = db.create_collection("Gone")
    a = add(db, "a", ["cat"])
    db.save_rule("r", {"tags_all": ["cat"]}, {"collection_id": col, "favorite": True})
    db.delete_collection(col)
    RuleEngine(db).apply([a])                                   # must not raise
    assert db.get_item(a)["favorite"] == 1


def test_rule_crud_and_reorder(db):
    r1 = db.save_rule("one", {"tags_all": ["a"]}, {"favorite": True})
    r2 = db.save_rule("two", {"tags_all": ["b"]}, {"favorite": True})
    db.move_rule(r2, -1)
    assert [r["name"] for r in db.rules()] == ["two", "one"]
    db.save_rule("uno", {"tags_all": ["a"]}, {"stars": 3}, rule_id=r1)
    assert db.rules()[1]["name"] == "uno" and db.rules()[1]["actions"] == {"stars": 3}
    db.delete_rule(r2)
    assert len(db.rules()) == 1


def test_apply_all_covers_existing_library(db):
    ids = [add(db, f"i{n}", ["cat"] if n % 2 else ["dog"]) for n in range(1200)]
    rid = db.save_rule("cats", {"tags_all": ["cat"]}, {"favorite": True})
    total = RuleEngine(db).apply_all()
    assert total == {rid: 600}
    assert db.conn.execute("SELECT COUNT(*) FROM items WHERE favorite=1").fetchone()[0] == 600


def test_new_items_from_import_get_the_rules_applied(tmp_path):
    paths = LibraryPaths(tmp_path / "lib")
    paths.ensure()
    cfg = Config.load(tmp_path / "c.json")
    svc = LibraryService(Database(paths.db_file), paths, FileHttp({}), cfg)
    col = svc.db.create_collection("Local")
    svc.db.save_rule("local", {"sites": ["local"]}, {"collection_id": col, "stars": 2})
    src = save_png(tmp_path / "src" / "a.png", make_image(3))
    assert svc.import_files([src], use_tagger=False)["saved"] == 1
    item = svc.db.search_items(collection_id=col)[0]
    assert item["stars"] == 2
    cfg.set("library.auto_rules", False, save=False)
    src2 = save_png(tmp_path / "src" / "b.png", make_image(4))
    svc.import_files([src2], use_tagger=False)
    assert len(svc.db.search_items(collection_id=col)) == 1     # the switch turns automation off


def test_rules_dialog_creates_saves_and_applies(qapp, tmp_path):
    from types import SimpleNamespace

    from anihub.ui.rules_dialog import RulesDialog

    db = Database(tmp_path / "d.db")
    col = db.create_collection("Cats")
    item = add(db, "a", ["cat"])
    cfg = Config.load(tmp_path / "c.json")
    ctx = SimpleNamespace(db=db, cfg=cfg, library=SimpleNamespace(rules=RuleEngine(db)))
    dlg = RulesDialog(ctx)
    assert not dlg.editor.isEnabled()
    dlg._new()
    dlg.name.setText("cats")
    dlg._save()                                                   # nothing filled in: refused
    assert db.rules()[0]["conditions"] == {} and dlg.status.text() == "Добавьте хотя бы одно условие и одно действие."
    dlg.tags_all.setText("cat")
    dlg.collection.setCurrentIndex(dlg.collection.findData(col))
    dlg.favorite.setChecked(True)
    dlg._save()
    rule = db.rules()[0]
    assert rule["name"] == "cats" and rule["conditions"] == {"tags_all": ["cat"]}
    assert rule["actions"] == {"collection_id": col, "favorite": True}
    dlg.list.item(0).setCheckState(Qt.CheckState.Unchecked)
    assert not db.rules()[0]["enabled"]
    dlg.close()
