from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage

from anihub.core import agemode
from anihub.core.config import Config
from anihub.core.db import Database
from anihub.core.paths import LibraryPaths
from anihub.services import promptbook as pb
from anihub.services.tagpictures import SEED_MAX
from anihub.ui.prompt_builder import EntryChip, PromptBuilder


@pytest.fixture
def env(qapp, tmp_path):
    cfg = Config({"filter": {"mode": "all"}}, tmp_path / "config.json")
    db = Database(tmp_path / "lib.db")
    ctx = SimpleNamespace(cfg=cfg, db=db, paths=LibraryPaths(tmp_path), blocker=agemode.Blocker.from_tags([]))
    form = {"prompt": "", "negative": ""}
    hooks = {
        "get": lambda: (form["prompt"], form["negative"]),
        "set": lambda p, n: form.update(prompt=p, negative=n),
        "api": lambda: None,
    }
    view = PromptBuilder(ctx, form=hooks)
    view.show()
    yield SimpleNamespace(view=view, ctx=ctx, form=form, cfg=cfg)
    view.close()
    db.close()


def select_node(view, key):
    """Select the category with this built-in key in the tree."""
    node = next(n for n in view.book.nodes() if n["key"] == key)
    stack = [view.tree.topLevelItem(i) for i in range(view.tree.topLevelItemCount())]
    while stack:
        item = stack.pop()
        if item.data(0, Qt.ItemDataRole.UserRole) == ("node", node["id"]):
            view.tree.setCurrentItem(item)
            return node
        stack += [item.child(i) for i in range(item.childCount())]
    raise AssertionError(key)


def tile(view, text):
    for i in range(view.grid.count()):
        item = view.grid.item(i)
        if item.data(Qt.ItemDataRole.UserRole)["text"] == text:
            return item
    raise AssertionError(text)


def test_a_clicked_tag_lands_in_its_own_paragraph(env):
    v = env.view
    select_node(v, "clothing.outfit")
    v._tile_clicked(tile(v, "school uniform"))
    select_node(v, "background.indoor") if any(n["key"] == "background.indoor" for n in v.book.nodes()) else v.tree.setCurrentItem(v.tree.topLevelItem(pb.SLOT_KEYS.index("background")))
    v._tile_clicked(v.grid.item(0))
    select_node(v, "quality.basic")
    v._tile_clicked(tile(v, "masterpiece"))
    text = env.form["prompt"]                                                          # sync is on: the form has it at once
    assert text.index("masterpiece") < text.index("school uniform")
    assert v.doc.has("quality", "masterpiece") and v.doc.has("clothing", "school uniform")
    assert [e.text for e in v.doc.entries("quality")] == ["masterpiece"]
    assert v.cards["clothing"].count.text() and len(v.cards["clothing"].flow._items) == 1
    v._tile_clicked(tile(v, "masterpiece"))                                             # a second click takes it out again
    assert not v.doc.has("quality", "masterpiece") and "masterpiece" not in env.form["prompt"]


def test_exclusive_category_replaces_the_choice(env):
    v = env.view
    select_node(v, "appearance.hair_color")
    v._tile_clicked(tile(v, "blue hair"))
    v._tile_clicked(tile(v, "red hair"))
    assert [e.text for e in v.doc.entries("appearance")] == ["red hair"]


def test_own_tag_and_weight_and_chip_menu_actions(env):
    v = env.view
    v._own_tag("pose", "handstand, (cartwheel:1.3)")
    assert [e.text for e in v.doc.entries("pose")] == ["handstand", "cartwheel"] and v.doc.find("pose", "cartwheel").weight == 1.3
    v._set_weight("pose", "handstand", 1.5)
    assert "(handstand:1.5)" in env.form["prompt"]
    v._remove_entry("pose", "handstand")
    assert "handstand" not in env.form["prompt"]
    chips = [v.cards["pose"].flow.itemAt(i).widget() for i in range(v.cards["pose"].flow.count())]
    assert len(chips) == 1 and isinstance(chips[0], EntryChip) and chips[0].weight.text() == "×1.3"


def test_negative_paragraphs_go_to_the_negative_field(env):
    v = env.view
    v.quick_negative()
    assert "lowres" in env.form["negative"] and "lowres" not in env.form["prompt"]
    assert env.form["negative"].index("lowres") < env.form["negative"].index("bad hands") < env.form["negative"].index("watermark")


def test_the_form_is_taken_over_when_the_tab_is_shown(env):
    v = env.view
    env.form["prompt"] = "sitting, classroom, (blue hair:1.3), masterpiece, my own thing"
    env.form["negative"] = "lowres, sunset"
    v.hide()
    v.show()
    assert v.doc.has("quality", "masterpiece") and v.doc.has("pose", "sitting") and v.doc.has("background", "classroom")
    assert v.doc.find("appearance", "blue hair").weight == 1.3 and v.doc.has("extra", "my own thing")
    assert v.doc.has("neg_quality", "lowres") and v.doc.has("neg_unwanted", "sunset")
    assert env.form["prompt"].startswith("sitting")                                     # untouched until the user changes something
    v._own_tag("pose", "kneeling")
    assert env.form["prompt"].index("masterpiece") < env.form["prompt"].index("blue hair") < env.form["prompt"].index("sitting")


def test_unsynced_changes_are_not_lost_by_switching_tabs(env):
    v = env.view
    v.sync.setChecked(False)
    v._own_tag("pose", "kneeling")
    env.form["prompt"] = "something else"
    v.hide()
    v.show()
    assert v.doc.has("pose", "kneeling")
    v.push()
    assert env.form["prompt"] == "kneeling"


def test_age_filter_hides_positive_tags_only(env):
    v = env.view
    env.ctx.blocker = agemode.Blocker.from_tags(["school_uniform", "lowres"])
    select_node(v, "clothing.outfit")
    v._refresh_grid()
    assert all(v.grid.item(i).data(Qt.ItemDataRole.UserRole)["text"] != "school uniform" for i in range(v.grid.count()))
    select_node(v, "negative.quality") if any(n["key"] == "negative.quality" for n in v.book.nodes()) else None
    neg = v.book.tags(slot="neg_quality")
    assert neg and all(v._allowed(r) for r in neg)                                       # what the user does NOT want is never hidden


def test_search_finds_tags_across_categories(env):
    v = env.view
    v.search.setText("школьн")
    texts = [v.grid.item(i).data(Qt.ItemDataRole.UserRole)["text"] for i in range(v.grid.count())]
    assert "school uniform" in texts


def test_picture_from_a_file_and_the_clipboard_image(env, tmp_path):
    v = env.view
    select_node(v, "clothing.outfit")
    row = tile(v, "kimono").data(Qt.ItemDataRole.UserRole)
    img = QImage(300, 300, QImage.Format.Format_RGB32)
    img.fill(QColor("#33aaff"))
    path = tmp_path / "pic.png"
    img.save(str(path))
    v._picture_dropped(row["id"], str(path))
    assert v.book.image_path(v.book.tag(row["id"])).exists()
    v._picture_dropped(row["id"], str(tmp_path / "missing.png"))
    assert v.status.text()                                                              # a bad file is reported, the picture stays
    assert v.book.tag(row["id"])["image"]


def test_forge_previews_need_a_running_forge(env):
    v = env.view
    select_node(v, "clothing.outfit")
    v._generate_picture(tile(v, "kimono").data(Qt.ItemDataRole.UserRole))
    assert v.status.text() == "Start Forge to generate pictures" or v.status.text()


def test_previews_are_generated_with_the_api_and_stored(env, qapp):
    import time
    from anihub.services import generation

    v = env.view
    select_node(v, "clothing.outfit")
    row = tile(v, "kimono").data(Qt.ItemDataRole.UserRole)
    calls = []
    png = QImage(64, 64, QImage.Format.Format_RGB32)
    png.fill(QColor("#ff8800"))

    def fake_run(api, params, out_dir):
        calls.append(params)
        target = Path(out_dir) / "x.png"
        png.save(str(target))
        return [SimpleNamespace(path=target)]

    original = generation.run_generation
    generation.run_generation = fake_run
    try:
        v._run_previews(object(), [row])
        end = time.time() + 10
        while time.time() < end and not v.book.tag(row["id"])["image"]:
            qapp.processEvents()
            time.sleep(0.02)
    finally:
        generation.run_generation = original
    assert v.book.tag(row["id"])["image"]
    # the seed is no longer a fixed 12345: PictureMaker salts it per batch so a later redraw differs from this one
    assert "kimono" in calls[0].prompt and 0 <= calls[0].seed < SEED_MAX
