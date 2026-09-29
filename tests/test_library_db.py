import sqlite3

import pytest

from anihub.core.db import SCHEMA_VERSION, Database


@pytest.fixture
def db(tmp_path):
    return Database(tmp_path / "t.db")


def add(db, name, tags=(), **kw):
    kw.setdefault("path", f"arts/{name}.png")
    return db.add_item(tags=[(t, "general") for t in tags], kind=kw.pop("kind", "art"), **kw)


def test_migration_2_to_3_keeps_data_and_adds_tables(tmp_path):
    path = tmp_path / "v2.db"
    conn = sqlite3.connect(path)
    conn.executescript("""CREATE TABLE items (id INTEGER PRIMARY KEY, kind TEXT NOT NULL DEFAULT 'art', path TEXT NOT NULL,
        rating TEXT NOT NULL DEFAULT 'general', added_at REAL NOT NULL, favorite INTEGER NOT NULL DEFAULT 0,
        trashed_at REAL, meta TEXT, ext TEXT, size INTEGER);
        INSERT INTO items(path, added_at) VALUES ('a.png', 1);""")
    conn.execute("PRAGMA user_version=2")
    conn.commit()
    conn.close()
    db = Database(path)
    assert db.conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    assert db.count_items() == 1
    row = db.get_item(1)
    assert row["stars"] == 0 and row["phash"] is None
    db.create_category("A")  # new tables exist
    assert [c["name"] for c in db.categories()] == ["A"]


def test_tag_hierarchy_search_includes_descendants(db):
    a = add(db, "a", ["hatsune_miku"])
    b = add(db, "b", ["kagamine_rin"])
    c = add(db, "c", ["cat"])
    db.set_tag_parent("hatsune_miku", "vocaloid")
    db.set_tag_parent("kagamine_rin", "vocaloid")
    db.set_tag_parent("vocaloid", "music")
    ids = {r["id"] for r in db.search_items(["vocaloid"])}
    assert ids == {a, b}
    assert {r["id"] for r in db.search_items(["music"])} == {a, b}          # grandchildren too
    assert {r["id"] for r in db.search_items(["hatsune_miku"])} == {a}      # a child does not match its siblings
    assert {r["id"] for r in db.search_items([], ["vocaloid"])} >= {c}      # exclusion expands the same way
    assert a not in {r["id"] for r in db.search_items([], ["vocaloid"])}


def test_tag_parent_cycle_is_rejected(db):
    db.set_tag_parent("child", "parent")
    with pytest.raises(ValueError):
        db.set_tag_parent("parent", "child")
    with pytest.raises(ValueError):
        db.set_tag_parent("parent", "parent")


def test_smart_tag_is_an_any_of_group_and_expands_hierarchy(db):
    a = add(db, "a", ["hatsune_miku"])
    b = add(db, "b", ["megurine_luka"])
    add(db, "c", ["cat"])
    db.set_tag_parent("megurine_luka", "luka_group")
    sid = db.save_smart_tag("vocaloids", ["hatsune_miku", "luka_group"])
    assert {r["id"] for r in db.search_items(["@vocaloids"])} == {a, b}
    assert db.smart_tags() == [(sid, "vocaloids", ["hatsune_miku", "luka_group"])]
    assert db.search_items(["@missing"]) == []
    db.delete_smart_tag(sid)
    assert db.search_items(["@vocaloids"]) == []


def test_unknown_tag_matches_nothing_and_ratings_filter(db):
    add(db, "a", ["cat"], rating="explicit")
    add(db, "b", ["cat"], rating="general")
    assert db.search_items(["nope"]) == []
    assert len(db.search_items(["cat"], ratings=["general"])) == 1
    assert db.search_items(["cat"], ratings=[]) == []


def test_sorting(db):
    add(db, "b", added_at=2, size=5, stars=1, rating="explicit")
    add(db, "a", added_at=3, size=50, stars=5, rating="general")
    add(db, "c", added_at=1, size=500, stars=3, rating="questionable")
    names = lambda **kw: [r["path"][5:6] for r in db.search_items(**kw)]
    assert names(sort="added") == ["a", "b", "c"]
    assert names(sort="added", desc=False) == ["c", "b", "a"]
    assert names(sort="size") == ["c", "a", "b"]
    assert names(sort="name", desc=False) == ["a", "b", "c"]
    assert names(sort="stars") == ["a", "c", "b"]
    assert names(sort="rating") == ["b", "c", "a"]
    assert names(sort="bogus") == ["a", "b", "c"]           # unknown sort falls back to date, never reaches SQL


def test_stars_favorites_and_bulk_fields(db):
    ids = [add(db, n) for n in "abc"]
    db.set_field(ids[:2], "stars", 4)
    db.set_field(ids[1:], "favorite", 1)
    assert {r["id"] for r in db.search_items(min_stars=4)} == set(ids[:2])
    assert {r["id"] for r in db.search_items(favorites=True)} == set(ids[1:])
    with pytest.raises(ValueError):
        db.set_field(ids, "path", "x")                       # only whitelisted columns


def test_categories_default_and_membership(db):
    a, b = add(db, "a"), add(db, "b")
    c1, c2 = db.create_category("Best"), db.create_category("Later")
    db.set_default_category(c2)
    assert db.default_category() == c2
    db.set_default_category(c1)
    assert db.default_category() == c1 and [c["is_default"] for c in db.categories()] == [1, 0]
    db.set_item_categories([a, b], add=[c1])
    db.set_item_categories([b], add=[c2], remove=[c1])
    assert {r["id"] for r in db.search_items(category_id=c1)} == {a}
    assert {r["id"] for r in db.search_items(category_id=c2)} == {b}
    db.reorder_categories([c2, c1])
    assert [c["name"] for c in db.categories()] == ["Later", "Best"]
    assert db.category_counts() == {c1: 1, c2: 1}
    db.rename_category(c1, "Top")
    db.delete_category(c2)
    assert [c["name"] for c in db.categories()] == ["Top"] and db.item_category_ids(b) == set()


def test_categories_are_scoped_by_kind(db):
    db.create_category("X", kind="art")
    db.create_category("X", kind="manga")   # same name in another section is fine
    assert len(db.categories("art")) == 1 and len(db.categories("manga")) == 1
    with pytest.raises(sqlite3.IntegrityError):
        db.create_category("X", kind="art")


def test_collections(db):
    a, b = add(db, "a"), add(db, "b")
    col = db.create_collection("Wallpapers")
    db.add_to_collection([a, b], col)
    db.add_to_collection([a], col)                            # idempotent
    assert db.collection_counts() == {col: 2}
    db.remove_from_collection([a], col)
    assert {r["id"] for r in db.search_items(collection_id=col)} == {b}
    db.delete_collection(col)
    assert db.collections() == [] and db.count_items() == 2   # items survive


def test_bulk_tag_edit_and_common_tags(db):
    a, b = add(db, "a", ["x", "y"]), add(db, "b", ["y"])
    db.add_tags([a, b], [("z", "meta")])
    common = {t[0]: t[2] for t in db.tags_of_items([a, b])}
    assert common == {"y": 2, "z": 2, "x": 1}
    db.remove_tags([a, b], ["y", "unknown"])
    assert db.item_tags(a) == ["x", "z"] and db.item_tags(b) == ["z"]


def test_suggest_tags_prefix_first_then_substring_sorted_by_use(db):
    add(db, "1", ["blue_hair", "blue_eyes"])
    add(db, "2", ["blue_hair", "light_blue_hair"])
    add(db, "3", ["blue_hair"])
    names = [s[0] for s in db.suggest_tags("blue")]
    assert names[:2] == ["blue_hair", "blue_eyes"] and "light_blue_hair" in names   # prefix hits first, then substring
    assert db.suggest_tags("blue_h")[0] == ("blue_hair", "general", 3)
    assert db.suggest_tags("100%_") == []                                            # LIKE wildcards are escaped
    db.save_smart_tag("vocal", ["a"])
    assert db.suggest_tags("@vo") == [("@vocal", "smart", 0)]


def test_rename_and_merge_tags(db):
    a, b = add(db, "a", ["colour"]), add(db, "b", ["color"])
    db.set_tag_parent("colour", "art_terms")
    db.rename_tag("colour", "color")                          # merge into the existing tag
    assert db.item_tags(a) == ["color"] and db.tag_id("colour") is None
    db.rename_tag("color", "colours")
    assert db.item_tags(b) == ["colours"]


def test_delete_tag_reparents_children(db):
    db.set_tag_parent("child", "mid")
    db.set_tag_parent("mid", "top")
    db.delete_tag("mid")
    assert db.conn.execute("SELECT t.name FROM tags t WHERE parent_id=(SELECT id FROM tags WHERE name='top')").fetchall()[0][0] == "child"


def test_tag_tree_lists_only_structured_tags(db):
    add(db, "a", ["lonely", "kid"])
    db.set_tag_parent("kid", "parent")
    assert [r["name"] for r in db.tag_tree()] == ["kid", "parent"]
    assert [r["name"] for r in db.tag_tree("par")] == ["parent"]


def test_trash_listing_and_count(db):
    a, b = add(db, "a"), add(db, "b")
    db.update_fields(a, trashed_at=100.0, trash_path="trash/1.png")
    assert db.count_items() == 1 and db.count_search(trashed=True) == 1
    assert [r["id"] for r in db.search_items(trashed=True)] == [a]
    assert [r["id"] for r in db.trashed_before(200)] == [a] and db.trashed_before(50) == []
    with pytest.raises(ValueError):
        db.update_fields(a, sha256="x")


def test_source_lookup_includes_trashed(db):
    a = add(db, "a", source_site="danbooru", source_post_id="7")
    db.update_fields(a, trashed_at=1.0)
    assert not db.has_source_post("danbooru", "7") and db.find_by_source("danbooru", "7")["id"] == a


# --- Stable Diffusion tables (schema v4) ----------------------------------------------------------

def test_migration_3_to_4_adds_sd_tables(tmp_path):
    path = tmp_path / "v3.db"
    fresh = Database(path)
    for table in ("subscriptions", "anime_links", "anime_positions", "novels", "anime_list", "auto_rules", "sd_presets", "sd_history", "sd_queue", "pb_tags", "pb_nodes", "anime_saved"):
        fresh.conn.execute(f"DROP TABLE {table}")
    fresh.conn.execute("PRAGMA user_version=3")
    fresh.conn.commit()
    fresh.close()
    db = Database(path)
    assert db.conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    db.save_preset("preset", "p", {"steps": 5})
    assert db.presets("preset")[0][1:] == ("p", {"steps": 5})


def test_presets_upsert_kinds_and_delete(db):
    a = db.save_preset("preset", "Portrait", {"steps": 20})
    assert db.save_preset("preset", "Portrait", {"steps": 30}) == a          # same name -> replaced, same id
    db.save_preset("style", "Portrait", {"prompt": "x"})                      # other kind: separate namespace
    assert [p[2] for p in db.presets("preset")] == [{"steps": 30}] and len(db.presets("style")) == 1
    db.delete_preset(a)
    assert db.presets("preset") == []


def test_history_search_and_paging(db):
    db.add_history([{"path": f"sd/{i}.png", "seed": 100 + i, "model": "m", "prompt": f"red hair {i}", "negative": "lowres",
                     "params": {"steps": i}, "backend": "main"} for i in range(5)])
    db.add_history([{"path": "sd/x.png", "seed": 7, "prompt": "blue eyes", "params": {}}])
    assert db.history_count() == 6 and db.history_count("red") == 5
    assert [r["seed"] for r in db.history("blue")] == [7]
    assert [r["path"] for r in db.history("103")] == ["sd/3.png"]              # exact seed match
    assert len(db.history(limit=2, offset=1)) == 2
    assert db.history("100%") == []                                            # LIKE wildcards are escaped
    db.delete_history([r["id"] for r in db.history("red")[:2]])
    assert db.history_count() == 4
    db.clear_history()
    assert db.history_count() == 0


def test_queue_order_claim_and_states(db):
    a, b, c = (db.queue_add({"prompt": p}, p) for p in "abc")
    assert [r["label"] for r in db.queue_list()] == ["a", "b", "c"]
    db.queue_move(c, -1)
    assert [r["label"] for r in db.queue_list()] == ["a", "c", "b"]
    db.queue_move(a, -1)                                                       # already first: no-op
    assert db.queue_list()[0]["label"] == "a"
    first = db.queue_claim("main")
    second = db.queue_claim("gpu1")
    assert (first["label"], first["status"], first["backend"]) == ("a", "running", "main")
    assert second["label"] == "c" and second["id"] != first["id"]             # never the same job twice
    db.queue_remove([first["id"], b])                                          # a running job cannot be removed
    assert [r["label"] for r in db.queue_list()] == ["a", "c"]
    db.queue_update(first["id"], status="done", result_count=2, finished_at=1.0)
    assert db.queue_get(first["id"])["result_count"] == 2
    assert db.queue_recover() == 1 and db.queue_get(second["id"])["status"] == "pending"   # crash recovery
    db.queue_clear_finished()
    assert [r["label"] for r in db.queue_list()] == ["c"]
    with pytest.raises(ValueError):
        db.queue_update(first["id"], position=5)
    assert db.queue_claim("x")["label"] == "c" and db.queue_claim("x") is None


# --- browsing the library's own on-disk folders (ui/library_view.py's "Folders" sidebar section) --------------

def test_folder_tree_mirrors_the_real_paths_of_indexed_items(db):
    add(db, "a", path="arts/danbooru/a.png")
    add(db, "b", path="arts/danbooru/b.png")
    add(db, "c", path="arts/local/2026-09/c.png")
    add(db, "d", path="arts/local/2026-08/d.png")
    add(db, "e", path="arts/e.png")                                # directly under arts/: no folder node
    assert db.folder_tree() == {"danbooru": {}, "local": {"2026-09": {}, "2026-08": {}}}


def test_folder_tree_is_scoped_by_kind(db):
    add(db, "a", path="arts/danbooru/a.png", kind="art")
    add(db, "b", path="sd/generated/b.png", kind="sd")
    assert db.folder_tree("art") == {"danbooru": {}}
    assert db.folder_tree("sd") == {"generated": {}}


def test_folder_tree_ignores_trashed_items(db):
    a = add(db, "a", path="arts/danbooru/a.png")
    db.update_fields(a, trashed_at=1.0)
    assert db.folder_tree() == {}


def test_folder_tree_skips_items_stored_with_an_absolute_path(db):
    """core/paths.py's `generations` override: an item saved outside the library root has no on-disk folder node
    inside it (library/service.py's save_generation stores an absolute path in that case)."""
    add(db, "a", path="C:/outside/the/library/a.png", kind="sd")
    assert db.folder_tree("sd") == {}


def test_search_items_by_folder_matches_the_prefix_and_its_subfolders(db):
    a = add(db, "a", path="arts/danbooru/a.png")
    b = add(db, "b", path="arts/local/2026-09/b.png")
    c = add(db, "c", path="arts/local/2026-08/c.png")
    add(db, "d", path="arts/rule34/d.png")
    assert {r["id"] for r in db.search_items(folder="arts/danbooru")} == {a}
    assert {r["id"] for r in db.search_items(folder="arts/local")} == {b, c}   # recursive: both months
    assert db.count_search(folder="arts/local") == 2


def test_search_items_by_folder_does_not_match_a_same_prefixed_sibling(db):
    """"arts/local" must not also match "arts/local2/...": the LIKE pattern needs the trailing slash."""
    a = add(db, "a", path="arts/local/x.png")
    add(db, "b", path="arts/local2/y.png")
    assert {r["id"] for r in db.search_items(folder="arts/local")} == {a}
