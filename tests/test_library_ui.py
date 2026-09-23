import base64
import json

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage

from anihub.core.db import Database
from anihub.services.generation import GenParams, fit_size, run_generation
from anihub.ui.grid import image_to_thumb
from anihub.ui.tag_widgets import TagCompleter, split_last_token
from anihub.ui.library_dialogs import TagEditDialog, normalize_tag

PNG = base64.b64encode(b"\x89PNG fake").decode()


def test_split_last_token_keeps_minus_and_head():
    assert split_last_token("cat -bl") == ("cat ", "-", "bl")
    assert split_last_token("bl") == ("", "", "bl")
    assert split_last_token("cat ") == ("cat ", "", "")
    assert split_last_token("a b @sm") == ("a b ", "", "@sm")


def test_normalize_tag():
    assert normalize_tag("  Blue  Hair ") == "blue_hair"


@pytest.fixture
def db(tmp_path):
    return Database(tmp_path / "t.db")


def add(db, name, tags):
    return db.add_item(kind="art", path=f"{name}.png", tags=[(t, "general") for t in tags])


def test_completer_suggests_for_last_word_and_rebuilds_the_line(qapp, db):
    from PySide6.QtWidgets import QLineEdit
    add(db, "a", ["blue_hair", "blue_eyes"])
    add(db, "b", ["blue_hair"])
    edit = QLineEdit()
    comp = TagCompleter(db, edit)
    edit.setText("cat -blue_h")
    comp._refresh("cat -blue_h")
    assert [comp._model.item(i).text() for i in range(comp._model.rowCount())] == ["blue_hair  (2)"]
    assert comp.splitPath("cat -blue_h") == ["blue_h"]
    assert comp.pathFromIndex(comp._model.index(0, 0)) == "cat -blue_hair "   # '-' and earlier words are kept


def test_completer_selection_does_not_duplicate_when_qt_previews_it_first(qapp, db):
    """Qt calls pathFromIndex() twice for one pick: once to preview the highlighted item (applied to the widget
    right away, e.g. on hover or arrow-key navigation), and again on the actual activation. Regression: the second
    call used to re-read the widget's own (already-previewed) text, appending the same tag a second time."""
    from PySide6.QtWidgets import QLineEdit
    add(db, "a", ["blue_hair"])
    edit = QLineEdit()
    comp = TagCompleter(db, edit)
    edit.setText("1girl blue_h")
    comp._refresh("1girl blue_h")
    idx = comp._model.index(0, 0)
    preview = comp.pathFromIndex(idx)
    assert preview == "1girl blue_hair "
    edit.setText(preview)                                    # what Qt's own hover-preview does before activating
    assert comp.pathFromIndex(idx) == preview                # the final activation must reproduce it, not extend it


def test_single_tag_completer_replaces_the_whole_text(qapp, db):
    from PySide6.QtWidgets import QLineEdit
    add(db, "a", ["blue_hair"])
    edit = QLineEdit()
    comp = TagCompleter(db, edit, multi=False)
    edit.setText("blue")
    comp._refresh("blue")
    assert comp.pathFromIndex(comp._model.index(0, 0)) == "blue_hair"


class Ctx:
    def __init__(self, db):
        self.db = db


def test_tag_edit_dialog_tristate_add_remove(qapp, db):
    a, b = add(db, "a", ["x", "y"]), add(db, "b", ["y"])
    d = TagEditDialog(Ctx(db), [a, b])
    states = {d.list.item(i).data(Qt.ItemDataRole.UserRole): d.list.item(i).checkState() for i in range(d.list.count())}
    assert states == {"y": Qt.CheckState.Checked, "x": Qt.CheckState.PartiallyChecked}
    d.edit.setText("New Tag")
    d._add_from_edit()
    for i in range(d.list.count()):                      # untick y (on both), tick the partial x for all
        item = d.list.item(i)
        name = item.data(Qt.ItemDataRole.UserRole)
        if name == "y":
            item.setCheckState(Qt.CheckState.Unchecked)
        elif name == "x":
            item.setCheckState(Qt.CheckState.Checked)
    add_, remove = d.changes()
    assert sorted(t[0] for t in add_) == ["new_tag", "x"] and remove == ["y"]
    d.accept()
    assert db.item_tags(a) == ["new_tag", "x"] and db.item_tags(b) == ["new_tag", "x"]


def test_tag_edit_dialog_untouched_partial_tags_stay_as_they_are(qapp, db):
    a, b = add(db, "a", ["x"]), add(db, "b", [])
    d = TagEditDialog(Ctx(db), [a, b])
    assert d.changes() == ([], [])
    d.accept()
    assert db.item_tags(a) == ["x"] and db.item_tags(b) == []


def test_tag_edit_dialog_typing_an_existing_tag_reuses_its_category(qapp, db):
    db.add_item(kind="art", path="c.png", tags=[("hatsune_miku", "character")])
    a = add(db, "a", [])
    d = TagEditDialog(Ctx(db), [a])
    d.edit.setText("hatsune miku")
    d._add_from_edit()
    assert d.changes()[0] == [("hatsune_miku", "character")]


def test_thumb_marks_change_the_image_only_when_given():
    from PySide6.QtCore import QBuffer, QIODevice
    img = QImage(400, 600, QImage.Format.Format_RGB32)
    img.fill(QColor("#336699"))
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    data = bytes(buf.data())
    plain = image_to_thumb(data, 180)                       # 120 x 180
    marked = image_to_thumb(data, 180, badge="GIF", mark="♥ ★3")
    assert plain.size() == marked.size()
    assert plain.pixelColor(60, 90) == marked.pixelColor(60, 90)                 # centre untouched
    assert plain.pixelColor(10, 10) != marked.pixelColor(10, 10)                 # badge pill, top-left
    assert plain.pixelColor(10, 170) != marked.pixelColor(10, 170)               # mark pill, bottom-left
    assert plain.pixelColor(110, 10) == marked.pixelColor(110, 10)               # top-right stays clean
    assert image_to_thumb(b"junk", 180) is None


def test_fit_size_keeps_aspect_and_snaps_to_64():
    w, h = fit_size(1000, 1500)
    assert w % 64 == 0 and h % 64 == 0 and abs(w / h - 1000 / 1500) < 0.08
    assert fit_size(0, 100) == (832, 1216)
    assert fit_size(100, 100) == (1024, 1024)
    assert max(fit_size(4000, 100)) <= 2048                                    # never absurdly large


def test_img2img_payload_and_dispatch(tmp_path):
    src = tmp_path / "in.png"
    src.write_bytes(b"\x89PNG source")
    params = GenParams(prompt="p", init_image=str(src), denoising_strength=0.4, model="m [h]")
    payload = params.to_payload()
    assert payload["denoising_strength"] == 0.4 and payload["resize_mode"] == 0
    assert base64.b64decode(payload["init_images"][0]) == b"\x89PNG source"
    assert "init_images" not in GenParams(prompt="p").to_payload()             # txt2img has no source

    calls = []

    class Api:
        def txt2img(self, payload):
            calls.append("txt2img")
            return {"images": [PNG], "info": json.dumps({"all_seeds": [1]})}

        def img2img(self, payload):
            calls.append("img2img")
            return {"images": [PNG], "info": json.dumps({"all_seeds": [2]})}

    run_generation(Api(), GenParams(prompt="p"), tmp_path / "o")
    res = run_generation(Api(), params, tmp_path / "o")
    assert calls == ["txt2img", "img2img"]
    assert res[0].meta["init_image"] == str(src) and res[0].seed == 2         # source kept in the saved parameters


class BatchApi:
    """Every txt2img call is its own `all_seeds`/`n_iter`-in-payload record, so a test can see exactly how the
    batch was actually split into calls."""

    def __init__(self):
        self.payloads: list[dict] = []

    def txt2img(self, payload):
        self.payloads.append(dict(payload))
        seed = payload["seed"] if payload["seed"] != -1 else 1000 + len(self.payloads)
        return {"images": [PNG], "info": json.dumps({"all_seeds": [seed]})}


def test_run_generation_splits_a_batch_count_into_one_call_each(tmp_path):
    api = BatchApi()
    delivered = []
    params = GenParams(prompt="p", seed=100, n_iter=3, batch_size=1)
    res = run_generation(api, params, tmp_path, on_batch=delivered.append)
    assert [p["n_iter"] for p in api.payloads] == [1, 1, 1]                    # never one call for the whole batch
    assert [p["seed"] for p in api.payloads] == [100, 101, 102]                # A1111-style: seed increments per image
    assert [r.seed for r in res] == [100, 101, 102]
    assert [d[0].seed for d in delivered] == [100, 101, 102]                   # on_batch fired once per call, in order


def test_run_generation_keeps_a_random_seed_random_across_the_batch(tmp_path):
    api = BatchApi()
    params = GenParams(prompt="p", seed=-1, n_iter=3, batch_size=2)
    res = run_generation(api, params, tmp_path, on_batch=lambda _r: None)
    assert [p["seed"] for p in api.payloads] == [-1, -1, -1]                   # -1 stays -1: Forge itself randomises
    assert len(res) == 3                                                        # one image per call (BatchApi returns one)


def test_run_generation_stops_early_when_should_stop_says_so(tmp_path):
    api = BatchApi()
    params = GenParams(prompt="p", seed=5, n_iter=5, batch_size=1)
    res = run_generation(api, params, tmp_path, should_stop=lambda: len(api.payloads) >= 2)
    assert len(api.payloads) == 2 and len(res) == 2                             # cancelled after the 2nd call finished


def test_run_generation_resolves_wildcards_into_the_sent_prompt(tmp_path):
    api = BatchApi()
    params = GenParams(prompt="1girl, __outfit__", negative_prompt="__bad__", seed=1)
    res = run_generation(api, params, tmp_path, wildcards={"outfit": ["kimono"], "bad": ["blurry"]})
    assert api.payloads[0]["prompt"] == "1girl, kimono" and api.payloads[0]["negative_prompt"] == "blurry"
    assert res[0].meta["prompt"] == "1girl, kimono"                             # the resolved text, not the template


def test_run_generation_resolves_wildcards_fresh_for_every_call_in_the_batch(tmp_path, monkeypatch):
    import anihub.services.generation as gen

    calls = []
    monkeypatch.setattr(gen, "resolve_wildcards", lambda text, lists: calls.append(text) or text)
    api = BatchApi()
    params = GenParams(prompt="1girl, __outfit__", negative_prompt="neg", seed=1, n_iter=3, batch_size=1)
    gen.run_generation(api, params, tmp_path, wildcards={"outfit": ["kimono"]})
    assert len(calls) == 6                       # prompt + negative_prompt resolved once per call, not once for the whole batch
