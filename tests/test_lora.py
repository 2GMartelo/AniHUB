import json
import struct
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage

from anihub.core.config import Config
from anihub.core.i18n import tr
from anihub.services import lora as lo
from anihub.services.lora import Lora, LoraError


def make_model(folder: Path, name="miku.safetensors", header: dict | None = None) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    body = json.dumps({"__metadata__": header or {}}).encode()
    path.write_bytes(struct.pack("<Q", len(body)) + body + b"\0" * 16)
    return path


def picture(color="#ff0066", size=(300, 200)) -> QImage:
    img = QImage(*size, QImage.Format.Format_RGB32)
    img.fill(QColor(color))
    return img


# --- service -----------------------------------------------------------------------------------------------------------------

def test_scan_finds_models_in_subfolders_and_skips_other_files(tmp_path):
    make_model(tmp_path, "a.safetensors")
    make_model(tmp_path / "chars", "b.pt")
    (tmp_path / "a.json").write_text("{}")
    (tmp_path / "c.safetensors.download").write_bytes(b"x")
    assert [p.relative_to(tmp_path).as_posix() for p in lo.scan(tmp_path)] == ["a.safetensors", "chars/b.pt"]
    assert lo.scan(tmp_path / "missing") == []


def test_card_json_roundtrip_keeps_unknown_keys_and_uses_forge_names(tmp_path):
    model = make_model(tmp_path)
    json_file = lo.json_path(model)
    json_file.write_text(json.dumps({"description": "old", "notes": "keep me", "activation text": "hatsune miku"}), encoding="utf-8")
    lora = lo.load(model, tmp_path)
    assert lora.description == "old" and lora.keywords == "hatsune miku" and lora.weight == 0.8 and lora.extra == {"notes": "keep me"}
    lora.description, lora.weight, lora.base, lora.negative = "Vocaloid", 0.65, "SDXL", "bad hands"
    lora.template = "<lora:{name}:{weight}> {keywords}"
    lo.save(lora)
    data = json.loads(json_file.read_text(encoding="utf-8"))
    assert data["description"] == "Vocaloid" and data["preferred weight"] == 0.65 and data["sd version"] == "SDXL"
    assert data["activation text"] == "hatsune miku" and data["negative text"] == "bad hands" and data["notes"] == "keep me"
    assert data[lo.TEMPLATE_KEY] == "<lora:{name}:{weight}> {keywords}"
    again = lo.load(model, tmp_path)
    assert again.template == lora.template and again.weight == 0.65
    again.template = lo.DEFAULT_TEMPLATE                                   # the default is not written at all
    lo.save(again)
    assert lo.TEMPLATE_KEY not in json.loads(json_file.read_text(encoding="utf-8"))
    json_file.write_text("not json", encoding="utf-8")                      # a broken card is not a crash
    assert lo.load(model, tmp_path).description == ""


def test_template_rendering_and_keyword_cleanup():
    assert lo.render_template(lo.DEFAULT_TEMPLATE, "miku", 0.8, "hatsune miku, teal hair") == "<lora:miku:0.8>, hatsune miku, teal hair"
    assert lo.render_template(lo.DEFAULT_TEMPLATE, "miku", 1.0, "") == "<lora:miku:1>"                       # no dangling comma
    assert lo.render_template("{keywords}, <lora:{name}:{weight}>", "m", 0.5, "kw,") == "kw, <lora:m:0.5>"
    assert lo.render_template("{keywords}, <lora:{name}:{weight}>", "m", 0.5, "") == "<lora:m:0.5>"
    assert lo.clean_keywords("a,  b ,, A\nc") == "a, b, c"
    lora = Lora(Path("x/miku.safetensors"), Path("x"), keywords="k1, k2", weight=0.7, template="{keywords}, <lora:{name}:{weight}>")
    assert lora.prompt_text() == "k1, k2, <lora:miku:0.7>" and lora.prompt_text(1.2) == "k1, k2, <lora:miku:1.2>"


def test_rename_moves_the_sidecar_files_with_the_model(tmp_path):
    model = make_model(tmp_path)
    lo.save(Lora(model, tmp_path, description="d"))
    lo.set_preview(model, picture())
    new = lo.rename(model, "miku_v2")
    assert new.name == "miku_v2.safetensors" and new.exists() and not model.exists()
    assert (tmp_path / "miku_v2.json").exists() and (tmp_path / "miku_v2.preview.png").exists()
    assert not (tmp_path / "miku.json").exists() and not (tmp_path / "miku.preview.png").exists()
    assert lo.load(new, tmp_path).description == "d"
    assert lo.rename(new, "miku_v2") == new                                                             # nothing to do


def test_rename_refuses_bad_or_taken_names_and_changes_nothing(tmp_path):
    model = make_model(tmp_path)
    make_model(tmp_path, "other.safetensors")
    lo.save(Lora(model, tmp_path))
    for bad, code in (("", "empty"), ("a:b", "chars"), ("a,b", "chars"), ("a/b", "chars"), ("x<y", "chars"), ("other", "exists")):
        with pytest.raises(LoraError, match=code):
            lo.rename(model, bad)
    assert model.exists() and lo.json_path(model).exists()
    (tmp_path / "other.json").write_text("{}")                                                          # a taken SIDECAR name blocks it too
    with pytest.raises(LoraError, match="exists"):
        lo.rename(model, "other")
    assert model.exists() and lo.json_path(model).exists()
    assert lo.rename(model, "Miku").name == "Miku.safetensors"                                          # a change of letter case is a rename


def test_preview_replaces_older_pictures_and_is_found_like_forge_does(tmp_path):
    model = make_model(tmp_path)
    picture().save(str(tmp_path / "miku.png"))                                                          # an old picture that would win
    picture("#00ff00").save(str(tmp_path / "miku.preview.jpg"))
    assert lo.find_preview(model) == tmp_path / "miku.png"
    big = picture("#3366ff", (2000, 1000))
    target = lo.set_preview(model, big)
    assert target == tmp_path / "miku.preview.png" and lo.find_preview(model) == target
    shot = QImage(str(target))
    assert (shot.width(), shot.height()) == (768, 384)                                                  # scaled down, aspect kept
    assert not (tmp_path / "miku.png").exists() and not (tmp_path / "miku.preview.jpg").exists()
    with pytest.raises(LoraError, match="picture"):
        lo.set_preview(model, b"nope")
    assert lo.find_preview(model) == target                                                              # the good one survived
    lo.clear_preview(model)
    assert lo.find_preview(model) is None


def test_header_metadata_keywords_and_civitai_words(tmp_path):
    freq = {"set1": {"hatsune miku": 40, "teal hair": 30, "1girl": 90}, "set2": {"1girl": 10, "twintails": 5}}
    model = make_model(tmp_path, header={"ss_tag_frequency": json.dumps(freq), "ss_base_model_version": "sdxl_base_v1-0"})
    assert lo.header_metadata(model)["ss_base_model_version"] == "sdxl_base_v1-0" and lo.base_from_header(model) == "sdxl_base_v1-0"
    assert lo.suggested_keywords(model) == ["1girl", "hatsune miku", "teal hair", "twintails"]
    assert lo.suggested_keywords(model, limit=2) == ["1girl", "hatsune miku"]
    model.with_name("miku.civitai.info").write_text(json.dumps({"trainedWords": ["miku style", " "]}), encoding="utf-8")
    assert lo.suggested_keywords(model) == ["miku style"]                                               # CivitAI's own words win
    bad = tmp_path / "bad.safetensors"
    bad.write_bytes(b"\xff" * 40)
    assert lo.header_metadata(bad) == {} and lo.suggested_keywords(bad) == []
    assert lo.header_metadata(tmp_path / "x.pt") == {}


# --- editor ------------------------------------------------------------------------------------------------------------------

@pytest.fixture
def editor(qapp, tmp_path):
    from anihub.ui.lora_editor import LoraEditor

    root = tmp_path / "forge" / "models" / "Lora"
    make_model(root, "miku.safetensors", header={"ss_tag_frequency": json.dumps({"s": {"hatsune miku": 5, "teal hair": 3}})})
    make_model(root / "styles", "watercolor.safetensors")
    cfg = Config({"forge": {"path": str(tmp_path / "forge")}}, tmp_path / "config.json")
    prompt = {"text": "", "neg": ""}

    def insert(text, negative, name):
        if f"<lora:{name}:" in prompt["text"]:
            return False
        prompt["text"] = (prompt["text"] + ", " + text).strip(", ")
        prompt["neg"] = (prompt["neg"] + ", " + negative).strip(", ") if negative else prompt["neg"]
        return True

    refreshed = []
    view = LoraEditor(SimpleNamespace(cfg=cfg), hooks={"insert": insert, "refresh": lambda: refreshed.append(1)})
    view.resize(1100, 700)
    view.show()
    yield SimpleNamespace(view=view, root=root, prompt=prompt, refreshed=refreshed)
    view._timer.stop()
    view.close()


def select(view, name):
    view.grid.setCurrentItem(next(i for p, i in view.items.items() if p.stem == name))


def test_editor_lists_cards_and_searches(editor):
    v = editor.view
    assert sorted(p.stem for p in v.items) == ["miku", "watercolor"]
    v.search.setText("water")
    assert v.items[editor.root / "miku.safetensors"].isHidden() and not v.items[editor.root / "styles" / "watercolor.safetensors"].isHidden()
    v.search.setText("styles")                                                                            # the folder name is searched too
    assert not v.items[editor.root / "styles" / "watercolor.safetensors"].isHidden()


def test_editor_saves_the_card_renames_and_writes_the_picture(editor, qapp):
    v = editor.view
    select(v, "miku")
    assert v.name.text() == "miku" and not v._dirty
    v.description.setPlainText("Hatsune Miku character")
    v.keywords.setPlainText("hatsune miku,  teal hair")
    v.weight.setValue(0.9)
    v.name.setText("miku_v2")
    v._set_picture(picture("#00ccff"))
    assert v._dirty and v.result.text() == "<lora:miku_v2:0.9>, hatsune miku, teal hair"
    assert v.save() is True
    new = editor.root / "miku_v2.safetensors"
    assert new.exists() and not (editor.root / "miku.safetensors").exists()
    data = json.loads((editor.root / "miku_v2.json").read_text(encoding="utf-8"))
    assert data["description"] == "Hatsune Miku character" and data["activation text"] == "hatsune miku, teal hair" and data["preferred weight"] == 0.9
    assert (editor.root / "miku_v2.preview.png").exists()
    assert v.current.path == new and not v._dirty and "miku_v2" in v.message.text()
    assert new in v.items and (editor.root / "miku.safetensors") not in v.items


def test_editor_reports_name_problems_and_keeps_the_file(editor):
    v = editor.view
    make_model(editor.root, "taken.safetensors")
    v.reload()
    select(v, "miku")
    v.name.setText("taken")
    v.description.setPlainText("x")
    assert v.save() is False and v.message.text() == tr("lora.err.exists")
    assert (editor.root / "miku.safetensors").exists()
    v.name.setText("a:b")
    assert v.save() is False and v.message.text() == tr("lora.err.chars") and (editor.root / "miku.safetensors").exists()
    v._revert()
    assert v.name.text() == "miku" and not v._dirty


def test_editor_inserts_the_lora_with_its_template_once(editor):
    v = editor.view
    select(v, "miku")
    v.keywords.setPlainText("hatsune miku")
    v.template.setText("{keywords}, <lora:{name}:{weight}>")
    v.negative.setText("bad hands")
    v.insert_current()                                                                                      # saves first, then inserts
    assert editor.prompt["text"] == "hatsune miku, <lora:miku:0.8>" and editor.prompt["neg"] == "bad hands"
    v.insert_current()
    assert editor.prompt["text"] == "hatsune miku, <lora:miku:0.8>"                                         # not twice
    assert lo.load(editor.root / "miku.safetensors", editor.root).template == "{keywords}, <lora:{name}:{weight}>"


def test_editor_suggests_keywords_from_the_file_and_clears_the_picture(editor):
    v = editor.view
    select(v, "miku")
    v._add_keywords(lo.suggested_keywords(v.current.path))
    assert v.keywords.toPlainText() == "hatsune miku, teal hair" and v._dirty
    v._set_picture(picture())
    v.save()
    assert lo.find_preview(editor.root / "miku.safetensors") is not None
    v._clear_picture()
    v.save()
    assert lo.find_preview(editor.root / "miku.safetensors") is None


def test_editor_without_a_forge_folder_says_so(qapp, tmp_path):
    from anihub.ui.lora_editor import LoraEditor

    view = LoraEditor(SimpleNamespace(cfg=Config({}, tmp_path / "c.json")))
    assert view.grid.count() == 0 and view.status.text()
    view._timer.stop()
