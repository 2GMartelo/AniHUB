import pytest
from PySide6.QtGui import QColor, QImage

from anihub.core.db import Database
from anihub.services import promptbook as pb
from anihub.services.promptbook import Entry, PromptBook, PromptDoc
from anihub.services.promptbook_data import RAW, SLOTS, parse_catalog


@pytest.fixture
def book(tmp_path):
    db = Database(tmp_path / "lib.db")
    b = PromptBook(db, tmp_path)
    b.seed()
    yield b
    db.close()


# --- the built-in catalogue -----------------------------------------------------------------------------------------------

def test_slots_follow_the_writing_order_of_a_good_prompt():
    keys = [s[0] for s in SLOTS if not s[3]]
    order = ["quality", "style", "subject", "character", "appearance", "expression", "clothing", "pose", "camera", "background", "lighting", "extra"]
    assert keys == order
    assert keys.index("quality") < keys.index("character") < keys.index("appearance") < keys.index("clothing") < keys.index("pose") < keys.index("background")
    assert [s[0] for s in SLOTS if s[3]] == ["neg_quality", "neg_anatomy", "neg_artifacts", "neg_unwanted"]


def test_catalogue_parses_into_categories_and_tags():
    cats = parse_catalog()
    assert len(cats) > 40 and sum(len(c["tags"]) for c in cats) > 600
    keys = [c["key"] for c in cats]
    assert len(set(keys)) == len(keys), "duplicate category key"
    slots = {s[0] for s in SLOTS}
    assert {c["slot"] for c in cats} <= slots and slots <= {c["slot"] for c in cats}                # every paragraph has content
    for c in cats:
        assert c["name"] and c["name_ru"] and c["tags"], c["key"]
        texts = [t for t, _l in c["tags"]]
        assert len(set(texts)) == len(texts), (c["key"], "tag twice in a category")
        assert all(t == t.strip() and "," not in t and "=" not in t for t in texts), c["key"]
    hair = next(c for c in cats if c["key"] == "appearance.hair_color")
    assert hair["exclusive"] and ("blue hair", "синие волосы") in hair["tags"]
    assert not next(c for c in cats if c["key"] == "appearance.hairstyle")["exclusive"]
    assert "masterpiece" in dict(next(c for c in cats if c["key"] == "quality.basic")["tags"])


def test_seed_is_idempotent_and_keeps_user_changes(book):
    n_tags = len(book.tags())
    assert n_tags > 600
    book.seed()
    assert len(book.tags()) == n_tags                                                              # nothing doubled
    blue = next(t for t in book.tags(query="blue hair"))
    book.delete_tag(blue["id"])                                                                    # a built-in tag is only hidden
    assert not book.tags(query="blue hair") or all(t["text"] != "blue hair" for t in book.tags(query="blue hair"))
    book.seed()
    assert all(t["text"] != "blue hair" for t in book.tags())                                      # not brought back by a re-seed
    book.restore_defaults()
    assert any(t["text"] == "blue hair" for t in book.tags())


def test_tags_by_category_slot_and_search(book):
    nodes = book.nodes("clothing")
    outfit = next(n for n in nodes if n["key"] == "clothing.outfit")
    rows = book.tags([outfit["id"]])
    assert any(r["text"] == "school uniform" and r["label"] == "школьная форма" for r in rows)
    assert all(r["slot"] == "clothing" for r in rows)
    assert {r["slot"] for r in book.tags(slot="background")} == {"background"}
    assert [r["text"] for r in book.tags(query="школьн")][:1] == ["school uniform"] or any("школьн" in r["label"] for r in book.tags(query="школьн"))
    assert book.tags(query="   ") == book.tags()
    hair = next(n for n in book.nodes("appearance") if n["key"] == "appearance.hair_color")
    assert book.tags([hair["id"]])[0]["exclusive"] == 1


def test_user_categories_tags_and_pictures(book, tmp_path):
    mine = book.add_node("clothing", "My outfits")
    sub = book.add_node("clothing", "Winter", parent_id=mine)
    assert set(book.subtree_ids(mine)) == {mine, sub}
    tid = book.add_tag(sub, " red scarf ,", "красный шарф")
    assert book.tag(tid)["text"] == "red scarf" and book.tag(tid)["slot"] == "clothing"
    assert book.add_tag(sub, "Red Scarf") == tid                                                   # the same tag: not doubled
    assert book.add_tag(sub, "  ") is None
    assert [t["text"] for t in book.tags(book.subtree_ids(mine))] == ["red scarf"]                 # a category shows its subcategories' tags
    img = QImage(400, 200, QImage.Format.Format_RGB32)
    img.fill(QColor("#ff0066"))
    path = book.set_image(tid, img)
    assert path.exists() and QImage(str(path)).width() == 256 and QImage(str(path)).height() == 256    # square crop
    assert book.image_path(book.tag(tid)) == path
    assert book.set_image(tid, b"not an image") is None
    book.clear_image(tid)
    assert not path.exists() and book.tag(tid)["image"] == ""
    book.set_image(tid, img)
    book.delete_node(mine)                                                                          # user rows really go, pictures too
    assert book.tag(tid) is None and not (book.image_dir / f"{tid}.jpg").exists() and book.node(sub) is None
    outfit = next(n for n in book.nodes("clothing") if n["key"] == "clothing.outfit")
    book.delete_node(outfit["id"])                                                                  # a built-in category is hidden
    assert all(n["key"] != "clothing.outfit" for n in book.nodes("clothing")) and any(n["key"] == "clothing.outfit" for n in book.nodes("clothing", include_hidden=True))


# --- the document ----------------------------------------------------------------------------------------------------------

def test_tags_land_in_their_own_paragraph_in_writing_order():
    doc = PromptDoc()
    doc.add("background", "classroom")
    doc.add("clothing", "school uniform")
    doc.add("quality", "masterpiece")
    doc.add("appearance", "blue hair")
    doc.add("character", "hatsune miku")
    doc.add("pose", "sitting")
    doc.add("quality", "best quality")
    assert doc.positive() == ("masterpiece, best quality,\nhatsune miku,\nblue hair,\nschool uniform,\nsitting,\nclassroom")
    doc.add("neg_quality", "lowres")
    doc.add("neg_anatomy", "bad hands")
    doc.add("neg_artifacts", "watermark")
    assert doc.negative() == "lowres,\nbad hands,\nwatermark"
    assert "lowres" not in doc.positive()


def test_add_remove_toggle_move_and_weights():
    doc = PromptDoc()
    assert doc.add("appearance", "blue hair") is not None and doc.add("appearance", "Blue  Hair") is None    # never twice
    assert doc.add("appearance", "  ") is None and doc.add("appearance", ",") is None
    assert doc.toggle("appearance", "long hair") is True and doc.toggle("appearance", "long hair") is False
    doc.add("appearance", "ponytail")
    doc.add("appearance", "bangs")
    doc.move("appearance", "bangs", -2)
    assert [e.text for e in doc.entries("appearance")] == ["bangs", "blue hair", "ponytail"]
    doc.move("appearance", "bangs", 99)
    assert [e.text for e in doc.entries("appearance")][-1] == "bangs"
    doc.set_weight("appearance", "blue hair", 1.25)
    assert doc.positive() == "(blue hair:1.25), ponytail, bangs"
    doc.set_weight("appearance", "blue hair", 1.3)
    doc.set_weight("appearance", "ponytail", 0.5)
    assert doc.positive() == "(blue hair:1.3), (ponytail:0.5), bangs"
    doc.set_weight("appearance", "ponytail", 99)
    assert doc.find("appearance", "ponytail").weight == 2.0
    doc.set_weight("appearance", "ponytail", 1.0)
    assert Entry("x", 1.0).render() == "x" and Entry("x", 2.0).render() == "(x:2)" and Entry("x", 0.1).render() == "(x:0.1)"
    doc.move_to_slot("appearance", "bangs", "extra")
    assert [e.text for e in doc.entries("extra")] == ["bangs"] and not doc.has("appearance", "bangs")
    assert doc.count(pb.POSITIVE) == 3 and not doc.is_empty()
    doc.clear(negative=False)
    assert doc.is_empty()


def test_an_exclusive_category_keeps_one_choice():
    doc = PromptDoc()
    doc.add("appearance", "blue hair", group="7", exclusive=True)
    doc.add("appearance", "long hair", group="8", exclusive=True)
    doc.add("appearance", "red hair", group="7", exclusive=True)                                    # replaces the colour, not the length
    assert [e.text for e in doc.entries("appearance")] == ["long hair", "red hair"]
    doc.add("appearance", "ponytail", group="9", exclusive=False)
    doc.add("appearance", "twintails", group="9", exclusive=False)
    assert len(doc.entries("appearance")) == 4                                                       # a normal category adds up


# --- parsing a written prompt ------------------------------------------------------------------------------------------------

def test_split_and_weights():
    assert pb.split_top_level("a, (b, c:1.2), d\ne, <lora:x:0.8>, [f g]") == ["a", "(b, c:1.2)", "d", "e", "<lora:x:0.8>", "[f g]"]
    assert pb.parse_piece("(blue hair:1.3)") == ("blue hair", 1.3) and pb.parse_piece("(x)") == ("x", 1.1)
    assert pb.parse_piece("[x]") == ("x", 0.9) and pb.parse_piece("plain tag") == ("plain tag", 1.0)
    assert pb.parse_piece("(x:9)") == ("x", 2.0)
    assert pb.estimate_tokens("masterpiece, 1girl") == 3


def test_parse_prompt_sorts_known_tags_into_slots_and_keeps_the_rest(book):
    lookup = book.lookup()
    text = "sitting, classroom, (blue hair:1.3), masterpiece, school uniform, <lora:miku:0.8>, my own tag, smile, BREAK"
    doc = pb.parse_prompt(text, lookup)
    assert doc.has("quality", "masterpiece") and doc.has("appearance", "blue hair") and doc.has("clothing", "school uniform")
    assert doc.has("pose", "sitting") and doc.has("background", "classroom") and doc.has("expression", "smile")
    assert doc.find("appearance", "blue hair").weight == 1.3
    assert [e.text for e in doc.entries("extra")] == ["<lora:miku:0.8>", "my own tag", "BREAK"] or doc.has("extra", "my own tag")
    assert doc.positive().startswith("masterpiece,\nblue hair") or doc.positive().startswith("masterpiece,")
    assert doc.positive().index("masterpiece") < doc.positive().index("blue hair") < doc.positive().index("school uniform") < doc.positive().index("sitting") < doc.positive().index("classroom")
    neg = pb.parse_prompt("lowres, bad hands, watermark, sunset, extra thing", lookup, negative=True)
    assert neg.has("neg_quality", "lowres") and neg.has("neg_anatomy", "bad hands") and neg.has("neg_artifacts", "watermark")
    assert neg.has("neg_unwanted", "sunset") and neg.has("neg_unwanted", "extra thing")                # positive/unknown tags stay somewhere in the negative
    assert not neg.positive()


def test_preview_prompts_show_the_tag_in_a_fitting_shot():
    assert "no humans" in pb.preview_prompt("background", "classroom")[0]
    assert "full body" in pb.preview_prompt("clothing", "kimono")[0] and "portrait" in pb.preview_prompt("appearance", "blue hair")[0]
    assert "kimono" in pb.preview_prompt("clothing", "kimono")[0] and "watermark" in pb.preview_prompt("clothing", "kimono")[1]


# --- the picture pack that ships with the app -------------------------------------------------------------------------------------

def _tag(book, text):
    return next(t for t in book.tags(query=text) if t["text"] == text)


def _picture(color):
    img = QImage(64, 64, QImage.Format.Format_RGB32)
    img.fill(QColor(color))
    return img


def test_pack_export_and_import_roundtrip(book, tmp_path):
    for text, color in (("blue hair", "#3366ff"), ("red hair", "#ff3333")):
        book.set_image(_tag(book, text)["id"], _picture(color))
    mine = book.add_node("clothing", "Mine")
    book.set_image(book.add_tag(mine, "custom hat"), _picture("#00ff00"))                                # a user's tag has no stable key: not exported
    pack = tmp_path / "out" / "pack.zip"
    assert book.export_pack(pack) == 2
    other_db = Database(tmp_path / "other.db")
    other = PromptBook(other_db, tmp_path / "other")
    other.seed()
    assert other.apply_pack(pack, overwrite=True) == 2
    assert other.image_path(_tag(other, "blue hair")).exists() and not _tag(other, "black hair")["image"]
    other_db.close()


def test_automatic_pack_respects_what_the_user_did(book, tmp_path):
    src = book.tags(query="blue hair")[0]
    book.set_image(src["id"], _picture("#3366ff"))
    book.set_image(_tag(book, "red hair")["id"], _picture("#ff3333"))
    book.set_image(_tag(book, "green hair")["id"], _picture("#33ff33"))
    pack = tmp_path / "pack.zip"
    book.export_pack(pack)
    for text in ("blue hair", "red hair", "green hair"):
        book.clear_image(_tag(book, text)["id"])
    book.wipe_images()
    db2 = Database(tmp_path / "fresh.db")
    fresh = PromptBook(db2, tmp_path / "fresh")
    fresh.seed()
    mine = _tag(fresh, "green hair")
    fresh.set_image(mine["id"], _picture("#111111"))                                                      # the user's own picture exists BEFORE the pack
    assert fresh.apply_pack(pack) == 2 and _tag(fresh, "blue hair")["image"] and _tag(fresh, "red hair")["image"]
    own = fresh.image_path(_tag(fresh, "green hair")).read_bytes()
    assert fresh.apply_pack(pack) == 0                                                                    # nothing twice
    fresh.clear_image(_tag(fresh, "red hair")["id"])                                                      # removed on purpose: stays removed
    assert fresh.apply_pack(pack) == 0 and not _tag(fresh, "red hair")["image"]
    assert fresh.image_path(_tag(fresh, "green hair")).read_bytes() == own                                 # own picture untouched
    # a newer pack replaces a picture that came from the old one and was not touched, but not the user's
    for text, color in (("blue hair", "#0000aa"), ("green hair", "#00aa00")):
        book.set_image(_tag(book, text)["id"], _picture(color))
    book.set_image(_tag(book, "red hair")["id"], _picture("#aa0000"))
    newer = tmp_path / "pack2.zip"
    book.export_pack(newer)
    assert fresh.apply_pack(newer) == 1                                                                   # only blue hair: the others are the user's
    assert QImage(str(fresh.image_path(_tag(fresh, "blue hair")))).pixelColor(5, 5).blue() > 150
    assert fresh.apply_pack(tmp_path / "missing.zip") == 0
    (tmp_path / "bad.zip").write_bytes(b"not a zip")
    assert fresh.apply_pack(tmp_path / "bad.zip") == 0
    db2.close()
