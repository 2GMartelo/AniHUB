"""User-created prompt-builder sections (services/promptbook.py's set_custom_slots family) and their UI in
ui/prompt_builder.py: adding, renaming, deleting and drag-reordering a section, on top of the fixed built-ins."""
from types import SimpleNamespace

import pytest
from PySide6.QtCore import Qt

from anihub.core import agemode
from anihub.core.config import Config
from anihub.core.db import Database
from anihub.core.paths import LibraryPaths
from anihub.services import promptbook as pb
from anihub.services.promptbook_data import SLOTS
from anihub.ui.prompt_builder import PromptBuilder


@pytest.fixture(autouse=True)
def reset_custom_slots():
    """pb.SLOT_KEYS/POSITIVE/NEGATIVE/SLOT_NAMES are process-global (like ui/theme.py's custom colours) -- leave
    them exactly as this test found them so a later, unrelated test never sees a section this file created."""
    yield
    pb.set_custom_slots([], [])


# --- services/promptbook.py: the merge/order logic, no UI ------------------------------------------------------

def test_custom_slot_key_slugifies_and_dedupes():
    assert pb.custom_slot_key(set(), "Wings & Halo") == "custom_wings_halo"
    assert pb.custom_slot_key({"custom_wings_halo"}, "Wings & Halo") == "custom_wings_halo_2"
    assert pb.custom_slot_key(set(), "!!!") == "custom_section"


def test_set_custom_slots_appends_after_the_built_ins_by_default():
    pb.set_custom_slots([{"key": "custom_wings", "label": "Wings", "negative": False}], [])
    assert pb.SLOT_KEYS[-1] == "custom_wings"
    assert pb.POSITIVE[-1] == "custom_wings"
    assert pb.slot_name("custom_wings", "en") == "Wings"
    assert pb.slot_name("custom_wings", "ru") == "Wings"          # one label, shown in either language


def test_set_custom_slots_honours_the_stored_order():
    pb.set_custom_slots([{"key": "custom_wings", "label": "Wings", "negative": False}],
                        ["custom_wings", "quality"])
    assert pb.SLOT_KEYS[:2] == ["custom_wings", "quality"]


def test_a_negative_custom_slot_lands_in_negative_not_positive():
    pb.set_custom_slots([{"key": "custom_bad", "label": "My bad stuff", "negative": True}], [])
    assert "custom_bad" in pb.NEGATIVE and "custom_bad" not in pb.POSITIVE


def test_is_custom_slot():
    pb.set_custom_slots([{"key": "custom_wings", "label": "Wings", "negative": False}], [])
    assert pb.is_custom_slot("custom_wings")
    assert not pb.is_custom_slot("clothing")


def test_add_rename_delete_round_trip_through_config(tmp_path):
    cfg = Config.load(tmp_path / "c.json")
    key = pb.add_custom_slot(cfg, "Wings", False)
    assert key == "custom_wings"
    assert key in pb.SLOT_KEYS
    assert cfg.get("promptbuilder.custom_slots") == [{"key": key, "label": "Wings", "negative": False}]
    assert cfg.get("promptbuilder.slot_order")[-1] == key

    pb.rename_custom_slot(cfg, key, "Feathered Wings")
    assert pb.slot_name(key, "en") == "Feathered Wings"

    doc = pb.PromptDoc()
    doc.add(key, "big wings")
    pb.delete_custom_slot(cfg, key, doc)
    assert key not in pb.SLOT_KEYS
    assert all(c["key"] != key for c in cfg.get("promptbuilder.custom_slots"))
    assert doc.has("extra", "big wings")                          # its tag moved to the positive fallback


def test_deleting_a_negative_custom_slot_moves_its_tags_to_neg_unwanted(tmp_path):
    cfg = Config.load(tmp_path / "c.json")
    key = pb.add_custom_slot(cfg, "Junk", True)
    doc = pb.PromptDoc()
    doc.add(key, "bad thing")
    pb.delete_custom_slot(cfg, key, doc)
    assert doc.has("neg_unwanted", "bad thing")


def test_reorder_slot_moves_a_key_right_before_the_target(tmp_path):
    cfg = Config.load(tmp_path / "c.json")
    pb.apply_custom_slots(cfg)
    pb.reorder_slot(cfg, "clothing", "quality")
    assert pb.SLOT_KEYS.index("clothing") == 0
    assert pb.SLOT_KEYS.index("quality") == 1


def test_reorder_slot_with_no_target_moves_to_the_end(tmp_path):
    cfg = Config.load(tmp_path / "c.json")
    pb.apply_custom_slots(cfg)
    pb.reorder_slot(cfg, "quality", None)
    assert pb.SLOT_KEYS[-1] == "quality"


def test_apply_custom_slots_is_idempotent_and_resets_cleanly(tmp_path):
    cfg = Config.load(tmp_path / "c.json")
    pb.add_custom_slot(cfg, "Temp", False)
    assert any(pb.is_custom_slot(k) for k in pb.SLOT_KEYS)
    pb.set_custom_slots([], [])
    assert [s[0] for s in SLOTS] == pb.SLOT_KEYS                  # back to exactly the built-ins


# --- "belongs to a character" (multi-character prompts) ----------------------------------------------------------

def test_the_built_in_character_slots_are_flagged_by_default():
    pb.set_custom_slots([], [])  # a clean baseline: no overrides, no custom slots
    assert pb.is_character_slot("clothing") and pb.is_character_slot("appearance")
    assert pb.is_character_slot("character") and pb.is_character_slot("expression") and pb.is_character_slot("pose")
    assert not pb.is_character_slot("quality") and not pb.is_character_slot("background")


def test_set_character_flag_overrides_a_built_in_slot(tmp_path):
    cfg = Config.load(tmp_path / "c.json")
    pb.apply_custom_slots(cfg)
    assert pb.is_character_slot("clothing")
    pb.set_character_flag(cfg, "clothing", False)
    assert not pb.is_character_slot("clothing")
    pb.set_character_flag(cfg, "background", True)
    assert pb.is_character_slot("background")


def test_a_new_custom_slot_can_be_marked_as_character_from_the_start(tmp_path):
    cfg = Config.load(tmp_path / "c.json")
    key = pb.add_custom_slot(cfg, "Wings", False, character=True)
    assert pb.is_character_slot(key)


def test_deleting_a_custom_character_slot_clears_its_override_and_moves_every_characters_tags(tmp_path):
    cfg = Config.load(tmp_path / "c.json")
    key = pb.add_custom_slot(cfg, "Wings", False, character=True)
    doc = pb.PromptDoc()
    doc.add(key, "small wings")
    doc.add(pb.character_key(key, 2), "big wings")
    pb.delete_custom_slot(cfg, key, doc)
    assert key not in pb.CHARACTER_SLOTS
    assert key not in (cfg.get("promptbuilder.character_overrides", {}) or {})
    assert doc.has("extra", "small wings") and doc.has("extra", "big wings")


def test_character_key_keeps_character_1_on_the_plain_slot_name():
    assert pb.character_key("clothing", 1) == "clothing"
    assert pb.character_key("clothing", 2) == "clothing::2"
    assert pb.character_key("clothing", 4) == "clothing::4"


# --- ui/prompt_builder.py wiring ---------------------------------------------------------------------------------

@pytest.fixture
def env(qapp, tmp_path):
    cfg = Config({"filter": {"mode": "all"}, "promptbuilder": {"default_character_seeded": True}}, tmp_path / "config.json")
    db = Database(tmp_path / "lib.db")
    ctx = SimpleNamespace(cfg=cfg, db=db, paths=LibraryPaths(tmp_path), blocker=agemode.Blocker.from_tags([]))
    form = {"prompt": "", "negative": ""}
    hooks = {"get": lambda: (form["prompt"], form["negative"]), "set": lambda p, n: form.update(prompt=p, negative=n),
            "api": lambda: None}
    view = PromptBuilder(ctx, form=hooks)
    view.show()
    yield SimpleNamespace(view=view, ctx=ctx, form=form, cfg=cfg)
    view.close()
    db.close()


def slot_item(view, key):
    for i in range(view.tree.topLevelItemCount()):
        item = view.tree.topLevelItem(i)
        if item.data(0, Qt.ItemDataRole.UserRole) == ("slot", key):
            return item
    raise AssertionError(key)


def test_new_slot_adds_a_tree_item_and_a_card(env, monkeypatch):
    from PySide6.QtWidgets import QInputDialog

    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("Wings", True)))
    view = env.view
    view.tree.setCurrentItem(slot_item(view, "clothing"))          # a positive slot: the new section should land in POSITIVE
    view._new_slot()
    key = "custom_wings"
    assert key in pb.POSITIVE
    assert slot_item(view, key) is not None
    assert key in view.cards


def test_new_slot_under_a_negative_selection_is_negative(env, monkeypatch):
    from PySide6.QtWidgets import QInputDialog

    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("Junk", True)))
    view = env.view
    view.tree.setCurrentItem(slot_item(view, "neg_quality"))
    view._new_slot()
    assert "custom_junk" in pb.NEGATIVE


def test_rename_and_delete_a_custom_section(env, monkeypatch):
    from PySide6.QtWidgets import QInputDialog, QMessageBox

    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("Wings", True)))
    view = env.view
    view._new_slot()
    key = "custom_wings"
    view.doc.add(key, "big wings")
    view._refresh_doc()

    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("Feathers", True)))
    view._rename_slot(key)
    assert view.cards[key].title.text() == "Feathers"

    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes))
    view._delete_slot(key)
    assert key not in pb.SLOT_KEYS
    assert key not in view.cards
    assert view.doc.has("extra", "big wings")                     # the tag survived the section's deletion


def test_built_in_slots_offer_no_rename_or_delete(env):
    view = env.view
    view.tree.setCurrentItem(slot_item(view, "clothing"))
    sel = view._selection()
    assert sel == ("slot", "clothing")
    assert not pb.is_custom_slot(sel[1])


def test_dragging_a_section_reorders_both_the_tree_and_the_cards(env, monkeypatch):
    from PySide6.QtWidgets import QInputDialog

    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("Wings", True)))
    view = env.view
    view.tree.setCurrentItem(slot_item(view, "clothing"))
    view._new_slot()
    key = "custom_wings"
    assert pb.POSITIVE[-1] == key                                  # freshly appended: last among the positive slots

    view._slot_dropped(key, ("slot", "quality"))                   # drag it to sit right before "quality"
    assert pb.SLOT_KEYS.index(key) == pb.SLOT_KEYS.index("quality") - 1
    assert list(view.cards).index(key) == list(view.cards).index("quality") - 1
    assert slot_item(view, key) is not None                        # the tree was rebuilt too, not just pb.SLOT_KEYS
