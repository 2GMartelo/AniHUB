"""services/seethrough.py: the ComfyUI-See-through workflow builder and the output-folder parser that stands in for
its browser-only "Download PSD" button -- all pure data transformation, testable without a real ComfyUI or any of
See-through's model weights (see the module docstring for why)."""
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from PySide6.QtGui import QColor, QImage

from anihub.services import seethrough as st
from anihub.services.comfyui import ComfyError


def make_png(path: Path, color: str, size=(6, 4), alpha: int = 255) -> None:
    w, h = size
    img = QImage(w, h, QImage.Format.Format_RGBA8888)
    c = QColor(color)
    c.setAlpha(alpha)
    img.fill(c)
    path.parent.mkdir(parents=True, exist_ok=True)
    assert img.save(str(path), "PNG")


def write_layers_json(output_dir: Path, prefix: str, entries: list[dict], width=100, height=80, ts="20260101_000000",
                      uid="abc12345") -> Path:
    path = output_dir / f"{prefix}_{ts}_{uid}_layers.json"
    path.write_text(json.dumps({"prefix": prefix, "timestamp": f"{ts}_{uid}", "layers": entries,
                                "width": width, "height": height}), encoding="utf-8")
    return path


# --- build_workflow ---------------------------------------------------------------------------------------------

def test_build_workflow_wires_the_real_node_chain():
    wf = st.build_workflow("art.png", "anihub_test")
    assert wf["1"]["class_type"] == "LoadImage" and wf["1"]["inputs"]["image"] == "art.png"
    assert wf["2"]["class_type"] == st.LOAD_LAYERDIFF and wf["3"]["class_type"] == st.LOAD_DEPTH
    assert wf["4"]["class_type"] == st.GENERATE_LAYERS
    assert wf["4"]["inputs"]["image"] == ["1", 0] and wf["4"]["inputs"]["layerdiff_model"] == ["2", 0]
    assert wf["5"]["class_type"] == st.GENERATE_DEPTH
    assert wf["5"]["inputs"]["layers"] == ["4", 0] and wf["5"]["inputs"]["depth_model"] == ["3", 0]
    assert wf["6"]["class_type"] == st.POST_PROCESS and wf["6"]["inputs"]["layers_depth"] == ["5", 0]
    assert wf["7"]["class_type"] == st.SAVE_PSD
    assert wf["7"]["inputs"]["parts"] == ["6", 0] and wf["7"]["inputs"]["filename_prefix"] == "anihub_test"


def test_build_workflow_applies_settings():
    settings = st.SeeThroughSettings(resolution=1024, steps=15, tblr_split=False, use_lama=False,
                                     group_offload=True, seed=7, resolution_depth=720,
                                     layerdiff_model="local/model", depth_model="local/depth")
    wf = st.build_workflow("x.png", "p", settings)
    assert wf["4"]["inputs"] == {"image": ["1", 0], "layerdiff_model": ["2", 0], "seed": 7,
                                 "resolution": 1024, "num_inference_steps": 15}
    assert wf["5"]["inputs"]["resolution_depth"] == 720
    assert wf["6"]["inputs"] == {"layers_depth": ["5", 0], "tblr_split": False, "use_lama": False}
    assert wf["2"]["inputs"]["model"] == "local/model" and wf["2"]["inputs"]["group_offload"] is True
    assert wf["3"]["inputs"]["model"] == "local/depth"


def test_build_workflow_defaults_match_the_plugins_own_recommended_workflow():
    wf = st.build_workflow("x.png", "p")
    assert wf["4"]["inputs"]["resolution"] == 1280 and wf["4"]["inputs"]["num_inference_steps"] == 30
    assert wf["6"]["inputs"]["tblr_split"] is True


# --- is_installed ------------------------------------------------------------------------------------------------

def test_is_installed_true_only_when_every_node_is_present():
    have_all = SimpleNamespace(object_info=lambda: {n: {} for n in st.REQUIRED_NODES})
    assert st.is_installed(have_all) is True

    missing_one = SimpleNamespace(object_info=lambda: {n: {} for n in st.REQUIRED_NODES[:-1]})
    assert st.is_installed(missing_one) is False

    unreachable = SimpleNamespace(object_info=lambda: (_ for _ in ()).throw(ComfyError("down")))
    assert st.is_installed(unreachable) is False


# --- collect_output ---------------------------------------------------------------------------------------------

def test_collect_output_reverses_back_to_front_into_top_to_bottom(tmp_path):
    """The JSON lists layers farthest-first (SeeThrough_SavePSD sorts by depth_median descending); a PSD wants
    topmost/frontmost first -- see psd_writer.PsdLayer."""
    make_png(tmp_path / "p_ts_uid_back.png", "blue")
    make_png(tmp_path / "p_ts_uid_face.png", "red")
    entries = [
        {"name": "back", "filename": "p_ts_uid_back.png", "left": 0, "top": 0, "right": 6, "bottom": 4,
         "depth_median": 0.9},
        {"name": "face", "filename": "p_ts_uid_face.png", "left": 1, "top": 2, "right": 7, "bottom": 6,
         "depth_median": 0.1},
    ]
    write_layers_json(tmp_path, "p", entries)

    result = st.collect_output(tmp_path, "p")

    assert result.tags == ["face", "back"]                          # smaller depth_median (closer) comes first
    assert [l.name for l in result.layers] == ["face", "back"]
    assert (result.width, result.height) == (100, 80)
    face = result.layers[0]
    assert (face.x, face.y) == (1, 2) and face.image.shape == (4, 6, 4)
    assert tuple(int(v) for v in face.image[0, 0]) == (255, 0, 0, 255)


def test_collect_output_picks_the_latest_matching_file(tmp_path):
    make_png(tmp_path / "p_a_x_only.png", "green")
    write_layers_json(tmp_path, "p", [{"name": "old", "filename": "p_a_x_only.png", "left": 0, "top": 0,
                                       "right": 1, "bottom": 1, "depth_median": 1}], ts="20260101_000000", uid="0001")
    make_png(tmp_path / "p_b_x_only.png", "green")
    write_layers_json(tmp_path, "p", [{"name": "new", "filename": "p_b_x_only.png", "left": 0, "top": 0,
                                       "right": 1, "bottom": 1, "depth_median": 1}], ts="20260101_000001", uid="0002")

    result = st.collect_output(tmp_path, "p")
    assert result.tags == ["new"]


def test_collect_output_raises_when_nothing_matches(tmp_path):
    with pytest.raises(st.SeeThroughError, match="no See-through output"):
        st.collect_output(tmp_path, "anihub_missing")


def test_collect_output_raises_when_the_layer_list_is_empty(tmp_path):
    write_layers_json(tmp_path, "p", [])
    with pytest.raises(st.SeeThroughError, match="no layers"):
        st.collect_output(tmp_path, "p")


def test_collect_output_raises_a_clear_error_for_an_unreadable_layer_png(tmp_path):
    write_layers_json(tmp_path, "p", [{"name": "broken", "filename": "p_ts_uid_broken.png", "left": 0, "top": 0,
                                       "right": 1, "bottom": 1, "depth_median": 1}])
    (tmp_path / "p_ts_uid_broken.png").write_bytes(b"not a png")
    with pytest.raises(st.SeeThroughError, match="broken"):
        st.collect_output(tmp_path, "p")


# --- run(): the whole pipeline, with a fake ComfyApi / fake run_workflow -----------------------------------------

class FakeApi:
    def __init__(self, installed=True):
        self.installed = installed
        self.uploaded = []

    def object_info(self):
        return {n: {} for n in st.REQUIRED_NODES} if self.installed else {}

    def upload_image(self, path):
        self.uploaded.append(path)
        return path.name


def test_run_end_to_end_writes_a_psd(tmp_path, monkeypatch, qapp):
    out_dir = tmp_path / "comfy_output"
    src = tmp_path / "art.png"
    make_png(src, "yellow", size=(10, 8))
    api = FakeApi()
    submitted = {}

    def fake_run_workflow(api_, workflow, on_progress=None, should_stop=None, poll_interval=0.7):
        submitted["workflow"] = workflow
        prefix = workflow["7"]["inputs"]["filename_prefix"]
        make_png(out_dir / f"{prefix}_ts_uid_body.png", "yellow", size=(10, 8))
        write_layers_json(out_dir, prefix, [{"name": "body", "filename": f"{prefix}_ts_uid_body.png",
                                             "left": 0, "top": 0, "right": 10, "bottom": 8, "depth_median": 0.5}],
                          width=10, height=8)
        return {}

    monkeypatch.setattr(st, "run_workflow", fake_run_workflow)
    psd_path = tmp_path / "out.psd"

    result = st.run(api, out_dir, src, psd_path)

    assert psd_path.exists() and result.tags == ["body"]
    assert api.uploaded == [src]
    assert submitted["workflow"]["1"]["inputs"]["image"] == "art.png"


def test_run_refuses_when_the_plugin_is_not_installed(tmp_path):
    api = FakeApi(installed=False)
    with pytest.raises(st.SeeThroughError, match="not installed"):
        st.run(api, tmp_path, tmp_path / "art.png", tmp_path / "out.psd")
    assert api.uploaded == []                                       # never even tries to upload
