import json
import struct
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QMimeData, Qt
from PySide6.QtGui import QColor, QImage

from anihub.core import agemode
from anihub.core.config import Config
from anihub.core.db import Database
from anihub.core.i18n import tr
from anihub.core.paths import LibraryPaths
from anihub.services import generation
from anihub.services import lora as lo
from anihub.services import promptbook as pb
from anihub.services.promptbook import PromptBook
from anihub.services.tagpictures import SEED_MAX, PictureMaker
from anihub.ui import builder_dnd as dnd
from anihub.ui.prompt_builder import PromptBuilder


def make_lora(folder: Path, name: str, **card) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{name}.safetensors"
    body = json.dumps({"__metadata__": {}}).encode()
    path.write_bytes(struct.pack("<Q", len(body)) + body)
    if card:
        lo.save(lo.Lora(path, folder, **card))
    return path


@pytest.fixture
def book(tmp_path):
    db = Database(tmp_path / "lib.db")
    b = PromptBook(db, tmp_path)
    b.seed()
    yield b
    db.close()


@pytest.fixture
def env(qapp, tmp_path):
    root = tmp_path / "forge" / "models" / "Lora"
    make_lora(root, "watercolor_style", category="style", keywords="watercolor", weight=0.7)
    make_lora(root, "miku_v2", category="character", keywords="hatsune miku", negative="bad hands")
    make_lora(root, "unsorted_one")
    cfg = Config({"forge": {"path": str(tmp_path / "forge")}, "promptbuilder": {"default_character_seeded": True}}, tmp_path / "config.json")
    db = Database(tmp_path / "lib.db")
    ctx = SimpleNamespace(cfg=cfg, db=db, paths=LibraryPaths(tmp_path), blocker=agemode.Blocker.from_tags([]))
    form = {"prompt": "", "negative": ""}
    hooks = {"get": lambda: (form["prompt"], form["negative"]), "set": lambda p, n: form.update(prompt=p, negative=n), "api": lambda: None}
    view = PromptBuilder(ctx, form=hooks)
    view.show()
    yield SimpleNamespace(view=view, root=root, form=form, ctx=ctx)
    view._lora_timer.stop()
    view.close()
    db.close()


def select(view, data):
    stack = [view.tree.topLevelItem(i) for i in range(view.tree.topLevelItemCount())]
    while stack:
        item = stack.pop()
        if item.data(0, dnd.ROLE) == data:
            view.tree.setCurrentItem(item)
            return item
        stack += [item.child(i) for i in range(item.childCount())]
    raise AssertionError(data)


def tiles(view):
    return {view.grid.item(i).data(Qt.ItemDataRole.UserRole)["text"]: view.grid.item(i) for i in range(view.grid.count())}


# --- moving tags and categories -------------------------------------------------------------------------------------------------

def test_a_tag_moves_to_another_category_and_its_slot_follows(book):
    school = next(t for t in book.tags(query="school uniform") if t["text"] == "school uniform")
    bottoms = next(n for n in book.nodes("clothing") if n["key"] == "clothing.bottoms")
    assert book.move_tag(school["id"], bottoms["id"]) is True
    assert book.tag(school["id"])["node_id"] == bottoms["id"] and book.tag(school["id"])["slot"] == "clothing"
    hair = next(n for n in book.nodes("appearance") if n["key"] == "appearance.hairstyle")
    assert book.move_tag(school["id"], hair["id"]) is True and book.tag(school["id"])["slot"] == "appearance"     # into another paragraph
    assert book.move_tag(school["id"], hair["id"]) is False                                                     # already there
    twin = next(t for t in book.tags([hair["id"]]) if t["text"] == "ponytail")
    outfit = next(n for n in book.nodes("clothing") if n["key"] == "clothing.outfit")
    book.add_tag(outfit["id"], "ponytail")                                                                     # the same name is already in the target
    assert book.move_tag(twin["id"], outfit["id"]) is False
    book.seed()                                                                                                # a re-seed neither doubles nor restores it
    assert len([t for t in book.tags() if t["text"] == "school uniform"]) == 1


def test_a_category_moves_under_another_and_between_slots(book):
    nodes = {n["key"]: n for n in book.nodes() if n["key"]}
    tops, bottoms = nodes["clothing.tops"], nodes["clothing.bottoms"]
    assert book.move_node(tops["id"], bottoms["id"]) is True
    assert book.node(tops["id"])["parent_id"] == bottoms["id"]
    assert book.move_node(bottoms["id"], tops["id"]) is False                                                   # not into its own child
    assert book.move_node(bottoms["id"], bottoms["id"]) is False
    mine = book.add_node("clothing", "Mine")
    sub = book.add_node("clothing", "Sub", parent_id=mine)
    assert book.move_node(mine, None, "pose") is True
    assert book.node(mine)["slot"] == "pose" and book.node(sub)["slot"] == "pose"                               # the whole subtree follows
    assert {t["slot"] for t in book.tags(book.subtree_ids(mine))} <= {"pose"}
    assert book.move_node(mine, None, "") is False


def test_drop_rules():
    assert dnd.drop_allowed(dnd.TAG_MIME, ("node", 3)) and not dnd.drop_allowed(dnd.TAG_MIME, ("slot", "pose"))
    assert dnd.drop_allowed(dnd.NODE_MIME, ("slot", "pose")) and dnd.drop_allowed(dnd.NODE_MIME, ("node", 1))
    assert dnd.drop_allowed(dnd.LORA_MIME, ("lora", "style")) and dnd.drop_allowed(dnd.LORA_MIME, ("lora", ""))
    assert not dnd.drop_allowed(dnd.LORA_MIME, ("lora", None)) and not dnd.drop_allowed(dnd.LORA_MIME, ("node", 1))
    mime = dnd.make_mime(dnd.TAG_MIME, [4, 5])
    assert dnd.read_mime(mime, dnd.TAG_MIME) == [4, 5] and dnd.read_mime(QMimeData(), dnd.TAG_MIME) is None


def test_dropping_on_the_tree_moves_things_in_the_builder(env):
    v = env.view
    select(v, ("slot", "clothing"))
    hat = next(t for t in v.book.tags(query="hat") if t["text"] == "hat")
    bottoms = next(n for n in v.book.nodes("clothing") if n["key"] == "clothing.bottoms")
    v.tree.tags_dropped.emit([hat["id"]], ("node", bottoms["id"]))
    assert v.book.tag(hat["id"])["node_id"] == bottoms["id"] and "1" in v.status.text()
    v.tree.node_dropped.emit(bottoms["id"], ("slot", "pose"))
    assert v.book.node(bottoms["id"])["slot"] == "pose"
    v.tree.tags_dropped.emit([hat["id"]], ("node", bottoms["id"]))                                             # already there
    assert v.status.text() == tr("pb.move_none")


# --- the LoRA tab ----------------------------------------------------------------------------------------------------------------

def test_the_lora_tab_is_first_and_has_five_fixed_groups(env):
    v = env.view
    top = v.tree.topLevelItem(0)
    assert top.data(0, dnd.ROLE) == ("lora", None) and top.text(0) == "LoRA"
    groups = [top.child(i).data(0, dnd.ROLE)[1] for i in range(top.childCount())]
    assert groups == ["", "style", "character", "pose", "clothing", "tool"]
    assert v._selection() == ("slot", "quality")                                                               # the builder still opens on a normal paragraph
    select(v, ("lora", None))
    assert sorted(tiles(v)) == ["miku_v2", "unsorted_one", "watercolor_style"]
    select(v, ("lora", "style"))
    assert list(tiles(v)) == ["watercolor_style"]
    select(v, ("lora", ""))
    assert list(tiles(v)) == ["unsorted_one"]


def test_the_lora_tab_cannot_be_edited(env):
    v = env.view
    select(v, ("lora", None))
    opened = []
    v._new_node = lambda *a: opened.append(a)
    v._tree_menu(v.tree.visualItemRect(v.tree.currentItem()).center())                                         # no menu is shown for the LoRA tab
    assert not opened
    assert v._current_slot() == "extra"


def test_a_lora_tile_writes_the_lora_and_its_negative_text_and_a_second_click_removes_them(env):
    v = env.view
    select(v, ("lora", "character"))
    v._tile_clicked(tiles(v)["miku_v2"])
    assert v.doc.has("extra", "<lora:miku_v2:0.8>, hatsune miku") and v.doc.has("neg_unwanted", "bad hands")
    assert "<lora:miku_v2:0.8>" in env.form["prompt"] and "bad hands" in env.form["negative"]
    v._refresh_grid()
    assert v._lora_active("miku_v2") and not v._lora_active("watercolor_style")
    v._tile_clicked(tiles(v)["miku_v2"])
    assert v.doc.is_empty() and env.form["prompt"] == "" and env.form["negative"] == ""


def test_a_lora_is_sorted_into_a_group_by_dropping_or_from_its_menu(env):
    v = env.view
    path = env.root / "unsorted_one.safetensors"
    v.tree.loras_dropped.emit([str(path)], ("lora", "pose"))
    assert lo.load(path, env.root).category == "pose"
    v._set_lora_group([str(path)], "tool")
    assert lo.load(path, env.root).category == "tool"
    v._set_lora_group([str(path)], "")
    assert lo.load(path, env.root).category == ""
    data = json.loads(lo.json_path(path).read_text(encoding="utf-8"))
    assert lo.CATEGORY_KEY not in data


def test_the_lora_editor_keeps_the_group_when_saving(qapp, tmp_path):
    root = tmp_path / "Lora"
    path = make_lora(root, "a", category="pose", description="d")
    from anihub.ui.lora_editor import LoraEditor

    view = LoraEditor(SimpleNamespace(cfg=Config({"lora": {"dir": str(root)}}, tmp_path / "c.json")))
    view.open_lora(path)
    assert view.category.currentData() == "pose"
    view.description.setPlainText("new")
    assert view.save() is True
    card = lo.load(path, root)
    assert card.category == "pose" and card.description == "new"
    view._timer.stop()


# --- the standard character ------------------------------------------------------------------------------------------------------

def test_the_standard_character_drives_the_picture_prompts():
    ch = pb.character_from({"hair": "long silver hair", "eyes": "red eyes", "top": "black hoodie", "extra": "glasses", "negative": "hat",
                            "seed": "77", "junk": 1})
    assert ch["seed"] == 77 and ch["hair"] == "long silver hair" and "junk" not in ch
    prompt, negative = pb.preview_prompt("expression", "smile", "expression.mood", ch)
    assert "long silver hair" in prompt and "red eyes" in prompt and "black hoodie" in prompt and prompt.rstrip().endswith("simple background")
    assert "glasses" in prompt and ", hat" in negative
    hair = pb.preview_prompt("appearance", "blue hair", "appearance.hair_color", ch)[0]
    assert "long silver hair" not in hair and "red eyes" in hair                                                # her hair gives way to the tag's
    shoes = pb.preview_prompt("clothing", "boots", "clothing.footwear", ch)[0]
    assert "black hoodie" in shoes and "pleated skirt" in shoes
    assert pb.character_from(None) == pb.DEFAULT_CHARACTER and pb.character_from({"cfg": "abc"}) == pb.DEFAULT_CHARACTER          # bad values fall back


def test_picture_maker_uses_the_character_settings(book, tmp_path):
    calls = []

    class FakeApi:
        def models(self):
            return [{"title": "waiIllustriousSDXL_v140.safetensors [abc]"}, {"title": "other.safetensors [x]"}]

    def fake_run(api, params, out_dir):
        calls.append(params)
        img = QImage(64, 64, QImage.Format.Format_RGB32)
        img.fill(QColor("#123456"))
        target = Path(out_dir) / "x.png"
        img.save(str(target))
        return [SimpleNamespace(path=target)]

    original = generation.run_generation
    generation.run_generation = fake_run
    try:
        maker = PictureMaker(FakeApi(), {"model": "wai", "seed": 100, "size": 640, "steps": 12, "cfg": 4.0, "sampler": "DPM++ 2M"})
        row = next(t for t in book.tags(query="smile") if t["text"] == "smile")
        data = maker.draw(row, "expression.mood")
        assert QImage.fromData(data).width() == 64
        p = calls[0]
        assert p.model.startswith("waiIllustrious") and p.width == p.height == 640 and p.steps == 12 and p.cfg_scale == 4.0
        assert p.sampler_name == "DPM++ 2M" and p.seed == (100 + maker._salt) % SEED_MAX and "smile" in p.prompt
        quality = next(t for t in book.tags(query="masterpiece") if t["text"] == "masterpiece")
        maker.draw(quality, "quality.basic")
        # words without a comparison get their own seed too (still offset by the same per-batch salt as the rest)
        assert calls[1].seed == (100 + maker._salt + quality["id"]) % SEED_MAX
        with pytest.raises(ValueError):
            PictureMaker(FakeApi(), {"model": "nothing like it"}).draw(row, "")
    finally:
        generation.run_generation = original


def test_progress_line_says_percent_step_and_time():
    frac, text = generation.progress_line({"progress": 0.375, "eta_relative": 12.4, "state": {"sampling_step": 9, "sampling_steps": 24, "job_no": 0, "job_count": 1}})
    assert frac == 0.375 and text.startswith("37%") and "9/24" in text and "12" in text
    assert generation.progress_line({"progress": 0.1, "state": {"sampling_steps": 0}}) == (0.0, "")
    assert "1/3" in generation.progress_line({"progress": 0.5, "state": {"sampling_step": 5, "sampling_steps": 10, "job_no": 0, "job_count": 3}})[1]


def test_character_tab_saves_its_settings(qapp, tmp_path):
    from anihub.ui.character_tab import CharacterTab

    cfg = Config({}, tmp_path / "c.json")
    tab = CharacterTab(SimpleNamespace(cfg=cfg))
    assert tab.hair.text() == "short brown hair"
    tab.hair.setText("long silver hair")
    tab.seed.setValue(99)
    assert "long silver hair" in tab.sample.toPlainText()
    tab.save()
    saved = pb.character_from(cfg.get("promptbook.character"))
    assert saved["hair"] == "long silver hair" and saved["seed"] == 99
    tab._reset()
    assert tab.hair.text() == "short brown hair"
    tab.test()                                                                          # no Forge: it says so instead of crashing
    assert tab.message.text() == tr("pb.need_forge")


# --- regression: a real QAction click in the shelf menu must reach _set_shelf with the real status --------------------------------
# (QMenu.addAction(text, slot)'s triggered(bool) does NOT land in a slot's own default argument the way a button's clicked(bool)
# does -- confirmed by hand -- but this exercises the real, un-mocked menu end to end anyway.)

def test_anime_shelf_menu_survives_a_real_trigger(qapp, tmp_path):
    from tests.test_anime_watch import wait, watch_ctx

    from anihub.ui.anime_watch import SHELF, WatchTab

    ctx = watch_ctx(tmp_path, ["Frieren/Frieren - 01.mkv"])
    tab = WatchTab(ctx)
    tab.ensure_loaded()
    wait(qapp, lambda: tab.grid.count() == 1)
    entry = tab.grid.item(0).data(Qt.ItemDataRole.UserRole)
    tab.select_entry(entry)
    tab._build_shelf_menu()
    action = next(a for a in tab.shelf_menu.actions() if a.text() == tr(dict(SHELF)["watching"]))
    action.trigger()
    assert ctx.db.saved_get("local", "Frieren")["status"] == "watching"
