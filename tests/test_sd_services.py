import base64
import hashlib
import json
import struct
import subprocess
import zlib
from datetime import datetime
from pathlib import Path

import pytest

from anihub.core.config import Config
from anihub.core.db import Database
from anihub.net.http import HttpError
from anihub.services import civitai
from anihub.services.backends import build_backends
from anihub.services.forge import ForgeManager
from anihub.services.generation import (
    GenParams, GenResult, model_hash_of, params_from_dict, parse_infotext, read_png_text, record_history, run_upscale)
from anihub.services.schedule import next_run, parse_time, schedule_due

PNG_B64 = base64.b64encode(b"\x89PNG upscaled").decode()


# --- parameters ------------------------------------------------------------------------------------

def test_payload_hires_vae_clip_skip_and_variations():
    p = GenParams(prompt="x", enable_hr=True, hr_scale=1.6, hr_upscaler="R-ESRGAN 4x+", hr_steps=12, hr_denoise=0.35,
                  vae="ae.safetensors", clip_skip=2, model="m [h]", subseed=5, subseed_strength=0.3).to_payload()
    assert (p["enable_hr"], p["hr_scale"], p["hr_upscaler"], p["hr_second_pass_steps"]) == (True, 1.6, "R-ESRGAN 4x+", 12)
    assert p["denoising_strength"] == 0.35                     # txt2img: the hires-pass denoise
    assert p["hr_additional_modules"] == ["Use same choices"]  # real Forge returns HTTP 500 without it
    assert p["override_settings"] == {"sd_model_checkpoint": "m [h]", "forge_additional_modules": ["ae.safetensors"],
                                      "CLIP_stop_at_last_layers": 2}
    assert p["override_settings_restore_afterwards"] is False
    assert (p["subseed"], p["subseed_strength"]) == (5, 0.3)


def test_payload_defaults_stay_minimal(tmp_path):
    p = GenParams(prompt="x").to_payload()
    for key in ("enable_hr", "override_settings", "subseed", "denoising_strength", "init_images"):
        assert key not in p
    src = tmp_path / "s.png"
    src.write_bytes(b"x")
    both = GenParams(prompt="x", init_image=str(src), enable_hr=True, denoising_strength=0.5, hr_denoise=0.9).to_payload()
    assert "enable_hr" not in both and both["denoising_strength"] == 0.5   # img2img wins: hires is txt2img only


def test_params_from_dict_ignores_unknown_and_old_keys():
    p = params_from_dict({"prompt": "a", "steps": 9, "future_option": True})
    assert (p.prompt, p.steps, p.cfg_scale) == ("a", 9, 6.0)
    assert GenParams(prompt="word " * 40).summary(20).endswith("…") and len(GenParams(prompt="word " * 40).summary(20)) == 21


# --- infotext / PNG info -----------------------------------------------------------------------------

INFO = """1girl, red hair, <lora:style:0.8>, simple background
Negative prompt: lowres, bad hands
Steps: 10, Sampler: Euler a, Schedule type: Automatic, CFG scale: 6.0, Seed: 7, Size: 896x1216, Model hash: bdb59bac77, Model: waiIllustriousSDXL_v140, Denoising strength: 0.55, Clip skip: 2, Lora hashes: "style: abc123, other: def456", Version: f2.0.1"""


def test_parse_infotext_full():
    r = parse_infotext(INFO)
    assert r["prompt"] == "1girl, red hair, <lora:style:0.8>, simple background"
    assert r["negative_prompt"] == "lowres, bad hands"
    assert (r["steps"], r["sampler_name"], r["scheduler"], r["cfg_scale"], r["seed"]) == (10, "Euler a", "Automatic", 6.0, 7)
    assert (r["width"], r["height"], r["model"], r["clip_skip"]) == (896, 1216, "waiIllustriousSDXL_v140", 2)
    assert r["denoising_strength"] == 0.55 and "enable_hr" not in r          # plain img2img strength
    assert r["model_hash"] == "bdb59bac77"


def test_parse_infotext_hires_and_missing_negative():
    text = "a cat\nSteps: 20, Sampler: DPM++ 2M, CFG scale: 5, Seed: 1, Size: 512x512, Denoising strength: 0.4, " \
           "Hires upscale: 2, Hires steps: 8, Hires upscaler: Latent"
    r = parse_infotext(text)
    assert r["prompt"] == "a cat" and "negative_prompt" not in r
    assert r["enable_hr"] and r["hr_scale"] == 2.0 and r["hr_steps"] == 8 and r["hr_upscaler"] == "Latent"
    assert r["hr_denoise"] == 0.4 and "denoising_strength" not in r          # with hires the strength belongs to the hires pass
    assert parse_infotext("Negative prompt: only negative\nSteps: 5")["negative_prompt"] == "only negative"


def chunk(kind: bytes, body: bytes) -> bytes:
    return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))


def make_png(extra_chunks: list[bytes]) -> bytes:
    ihdr = chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
    idat = chunk(b"IDAT", zlib.compress(b"\x00\xff\x00\x00"))
    return b"\x89PNG\r\n\x1a\n" + ihdr + b"".join(extra_chunks) + idat + chunk(b"IEND", b"")


def test_read_png_text_chunks(tmp_path):
    ztxt = b"comment\0\0" + zlib.compress("zipped ✓".encode())
    itxt = b"parameters\0\0\0\0\0" + "тест\nSteps: 3".encode()
    path = tmp_path / "a.png"
    path.write_bytes(make_png([chunk(b"tEXt", b"parameters\0" + "plain ✓".encode()), chunk(b"zTXt", ztxt),
                               chunk(b"iTXt", b"other\0\0\0\0\0" + "тест".encode())]))
    text = read_png_text(path)
    assert text["parameters"] == "plain ✓" and text["comment"] == "zipped ✓" and text["other"] == "тест"
    only_itxt = tmp_path / "b.png"
    only_itxt.write_bytes(make_png([chunk(b"iTXt", itxt)]))
    assert read_png_text(only_itxt)["parameters"] == "тест\nSteps: 3"
    bad = tmp_path / "c.png"
    bad.write_bytes(b"not a png")
    assert read_png_text(bad) == {}


def test_model_hash_of_reads_the_embedded_model_hash(tmp_path):
    path = tmp_path / "a.png"
    path.write_bytes(make_png([chunk(b"tEXt", b"parameters\0" + INFO.encode())]))
    assert model_hash_of(path) == "bdb59bac77"
    no_meta = tmp_path / "b.png"
    no_meta.write_bytes(make_png([]))
    assert model_hash_of(no_meta) == ""


# --- upscale / history ---------------------------------------------------------------------------------

def test_run_upscale_writes_next_to_generations_and_keeps_meta(tmp_path):
    src = tmp_path / "a.png"
    src.write_bytes(b"\x89PNG src")
    seen = {}

    class Api:
        def extra_single(self, payload):
            seen.update(payload)
            return {"image": PNG_B64}

    res = run_upscale(Api(), src, "R-ESRGAN 4x+", 2.0, tmp_path / "out", {"prompt": "p", "seed": 9})
    assert res.path.exists() and res.path.name.startswith("a_x2") and res.seed == 9
    assert seen["upscaler_1"] == "R-ESRGAN 4x+" and seen["upscaling_resize"] == 2.0
    assert res.meta["upscaled_from"] == "a.png" and res.meta["prompt"] == "p"


def test_record_history_uses_relative_paths(tmp_path):
    db = Database(tmp_path / "t.db")
    root = tmp_path / "lib"
    img = root / "sd" / "generated" / "x.png"
    img.parent.mkdir(parents=True)
    img.write_bytes(b"x")
    record_history(db, root, [GenResult(img, 5, {"prompt": "p", "negative_prompt": "n", "model": "m"})], "gpu1")
    row = db.history()[0]
    assert (row["path"], row["seed"], row["prompt"], row["backend"]) == ("sd/generated/x.png", 5, "p", "gpu1")
    assert json.loads(row["params"])["negative_prompt"] == "n"


# --- schedule ---------------------------------------------------------------------------------------------

def test_schedule_due_window_and_once_per_day():
    s = {"enabled": True, "time": "02:00", "window_hours": 6}
    at = lambda h, m=0: datetime(2026, 9, 20, h, m)
    assert not schedule_due(at(1, 59), s)                       # too early
    assert schedule_due(at(2, 0), s) and schedule_due(at(7, 59), s)
    assert not schedule_due(at(8, 1), s)                        # missed by more than the window: wait for tomorrow
    assert not schedule_due(at(3), {**s, "last_run": "2026-09-20"})   # already ran today
    assert not schedule_due(at(3), {**s, "enabled": False})
    assert schedule_due(at(3), {**s, "last_run": "2026-09-19"})


def test_next_run_and_time_parsing():
    s = {"enabled": True, "time": "23:30"}
    assert next_run(datetime(2026, 9, 20, 10), s) == datetime(2026, 9, 20, 23, 30)
    assert next_run(datetime(2026, 9, 21, 10), {**s, "last_run": "2026-09-21"}) == datetime(2026, 9, 22, 23, 30)
    assert next_run(datetime(2026, 9, 20, 10), {"enabled": False}) is None
    assert parse_time("7:05") == (7, 5) and parse_time("bogus") == (2, 0) and parse_time("25:00") == (2, 0)


# --- backends ---------------------------------------------------------------------------------------------

def test_build_backends_filters_bad_entries(tmp_path):
    cfg = Config.load(tmp_path / "c.json")
    cfg.set("forge.backends", [
        {"name": "gpu 1", "port": 7861, "gpu": 1},
        {"name": "dup-port", "port": 7861, "gpu": 0},          # same port as another backend
        {"name": "main", "port": 7999},                          # name clash with the primary
        {"name": "off", "port": 7862, "enabled": False},
        {"name": "low", "port": 80},                             # privileged port
        {"broken": True},
        {"name": "gpu2", "port": 7863, "gpu": None}], save=False)
    backends = build_backends(cfg, tmp_path)
    assert [(b.name, b.port, b.gpu) for b in backends] == [("main", 7860, None), ("gpu_1", 7861, 1), ("gpu2", 7863, None)]


def test_extra_backend_pins_gpu_and_uses_its_own_port_and_files(tmp_path, monkeypatch):
    forge = tmp_path / "webui"
    forge.mkdir()
    (forge / "webui.bat").write_text("@echo off\n")
    cfg = Config.load(tmp_path / "c.json")
    cfg.set("forge.path", str(forge), save=False)
    mgr = ForgeManager(cfg, tmp_path / "work", "gpu1", port=7861, gpu=1, nowebui=True)
    mgr.api.ping = lambda: False
    started = {}

    class P:
        pid = 1

        def poll(self):
            return None

    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: started.update(args=a, kwargs=k) or P())
    mgr.start()
    assert started["kwargs"]["env"]["CUDA_VISIBLE_DEVICES"] == "1"
    script = (tmp_path / "work" / "forge_launch_gpu1.bat").read_bytes().decode("cp866", "replace")
    assert "--api --port 7861 --nowebui" in script
    assert mgr.log_file.name == "forge-gpu1.log" and mgr.api.base_url.endswith(":7861")
    main = ForgeManager(cfg, tmp_path / "work")
    assert main.log_file.name == "forge.log" and main.port == 7860


# --- CivitAI ---------------------------------------------------------------------------------------------

RAW = {"id": 5, "name": "Detailer", "type": "LORA", "nsfw": False, "description": "<p>Adds <b>detail</b></p><br>Line2",
       "creator": {"username": "bob"}, "stats": {"downloadCount": 10, "rating": 4.5},
       "modelVersions": [{"id": 50, "name": "v1", "baseModel": "SDXL 1.0", "trainedWords": ["dtl"], "images": [{"url": "u", "nsfwLevel": 1}],
                          "downloadUrl": "https://civitai.com/api/download/models/50",
                          "files": [{"id": 1, "name": "pickle.ckpt", "sizeKB": 10, "type": "Model", "metadata": {"format": "PickleTensor"}},
                                    {"id": 2, "name": "d.safetensors", "sizeKB": 20, "type": "Model", "primary": True,
                                     "metadata": {"format": "SafeTensor"}, "hashes": {"SHA256": "ABC"}},
                                    {"id": 3, "name": "notes.txt", "sizeKB": 1, "type": "Training Data"}]}]}


def test_parse_model_and_pick_file():
    m = civitai.parse_model(RAW)
    assert (m.name, m.type, m.creator, m.downloads, m.rating) == ("Detailer", "LORA", "bob", 10, 4.5)
    assert m.description == "Adds detail\n\nLine2" and m.page_url == "https://civitai.red/models/5"
    v = m.versions[0]
    assert v.base_model == "SDXL 1.0" and v.trained_words == ["dtl"]
    best = civitai.pick_file(v)
    assert best.name == "d.safetensors" and best.sha256 == "abc" and best.url.endswith("/models/50")   # version url fallback
    assert civitai.pick_file(civitai.CivitVersion(1, "x", "")) is None


def test_parse_model_url():
    assert civitai.parse_model_url("https://civitai.com/models/123/some-name?modelVersionId=456") == (123, 456)
    assert civitai.parse_model_url("civitai.com/models/77") == (77, None)


# --- find_by_hash: "which model was this picture made with" -----------------------------------------------------

class HashHttp:
    def __init__(self, response=None, error=None):
        self.response, self.error, self.calls = response, error, []

    def get_json(self, url, params=None, headers=None, **kw):
        self.calls.append((url, headers))
        if self.error:
            raise self.error
        return self.response


def test_find_by_hash_resolves_a_real_hit():
    response = {"id": 128713, "modelId": 257749, "name": "v1.0", "model": {"name": "hassakuXLIllustrious"}}
    http = HashHttp(response)
    match = civitai.find_by_hash(http, "bdb59bac77", token="tok")
    assert match.model_id == 257749 and match.model_name == "hassakuXLIllustrious" and match.version_id == 128713
    assert match.page_url == "https://civitai.red/models/257749?modelVersionId=128713"
    assert http.calls[0][0].endswith("/model-versions/by-hash/bdb59bac77")
    assert http.calls[0][1]["Authorization"] == "Bearer tok"


def test_find_by_hash_returns_none_for_an_unknown_or_empty_hash():
    assert civitai.find_by_hash(HashHttp({}), "deadbeef00") is None                 # no modelId in the response
    http = HashHttp(response={"modelId": 1})
    assert civitai.find_by_hash(http, "") is None                                   # nothing to look up
    assert not http.calls                                                            # never mind, no call was made either


def test_find_by_hash_fails_quietly_on_a_network_or_404_error():
    assert civitai.find_by_hash(HashHttp(error=HttpError(404)), "bdb59bac77") is None
    assert civitai.parse_model_url(" 88 ") == (88, None)
    assert civitai.parse_model_url("https://example.com/models/1") is None


def test_safe_filename_and_target_dirs(tmp_path):
    assert civitai.safe_filename("<lora:leonard0:>.safetensors") == "_lora_leonard0__.safetensors"
    assert civitai.safe_filename("embedding:x.safetensors") == "embedding_x.safetensors"
    assert civitai.safe_filename("  ..  ") == "model.safetensors"
    assert civitai.target_dir(tmp_path, "LORA") == tmp_path / "models" / "Lora"
    assert civitai.target_dir(tmp_path, "TextualInversion") == tmp_path / "embeddings"
    with pytest.raises(civitai.CivitaiError):
        civitai.target_dir(tmp_path, "Workflow")


class FakeHttp:
    def __init__(self, content=b"model-bytes", error=None):
        self.content, self.error, self.calls = content, error, []

    def download(self, url, dest, progress=None, cancelled=None, paused=None, headers=None):
        self.calls.append((url, headers))
        if self.error:
            raise self.error
        dest.write_bytes(self.content)
        if progress:
            progress(len(self.content), len(self.content))

    def get_json(self, url, params=None, headers=None, **kw):
        self.calls.append((url, params, headers))
        return {"items": [RAW], "metadata": {"nextPage": "https://next"}}


def civ_file(content=b"model-bytes", sha=True):
    return civitai.CivitFile(1, "a<b>.safetensors", 1, hashlib.sha256(content).hexdigest() if sha else "", "https://x/dl")


def test_download_verifies_checksum_sends_token_and_cleans_up(tmp_path):
    http = FakeHttp()
    path = civitai.download(http, civ_file(), tmp_path / "Lora", token="secret")
    assert path.name == "a_b_.safetensors" and path.read_bytes() == b"model-bytes"
    assert http.calls[0][1]["Authorization"] == "Bearer secret"
    assert not list((tmp_path / "Lora").glob("*.download"))
    assert civitai.download(FakeHttp(), civ_file(), tmp_path / "Lora") == path             # already installed, same hash


def test_download_rejects_corrupt_files_and_never_overwrites(tmp_path):
    with pytest.raises(civitai.CivitaiError, match="Checksum"):
        civitai.download(FakeHttp(content=b"tampered"), civ_file(), tmp_path / "d")
    assert not list((tmp_path / "d").iterdir())                                             # nothing left behind
    (tmp_path / "d").mkdir(exist_ok=True)
    (tmp_path / "d" / "a_b_.safetensors").write_bytes(b"other")
    with pytest.raises(civitai.CivitaiError, match="already exists"):
        civitai.download(FakeHttp(), civ_file(), tmp_path / "d")
    with pytest.raises(civitai.CivitaiError, match="login"):
        civitai.download(FakeHttp(error=HttpError(401)), civ_file(), tmp_path / "e")


def test_download_returns_none_when_paused_and_keeps_the_partial_file(tmp_path):
    http = FakeHttp()
    result = civitai.download(http, civ_file(), tmp_path / "Lora", paused=lambda: True)
    assert result is None
    assert not (tmp_path / "Lora" / "a_b_.safetensors").exists()                          # never verified/renamed
    assert list((tmp_path / "Lora").glob("*.download"))                                   # kept for a later resume


def test_search_builds_query_and_returns_next_page():
    http = FakeHttp()
    models, nxt = civitai.search(http, "detail", "LORA", "Newest", nsfw=False, token="t")
    assert models[0].name == "Detailer" and nxt == "https://next"
    _url, params, headers = http.calls[0]
    assert params["query"] == "detail" and params["types"] == "LORA" and params["nsfw"] == "false"
    assert headers["Authorization"] == "Bearer t"
    civitai.search(http, "", nsfw=True)
    assert "query" not in http.calls[1][1] and http.calls[1][1]["nsfw"] == "true"


def test_civitai_red_is_the_site_and_age_modes_limit_what_is_shown():
    assert civitai.API == "https://civitai.red/api/v1"
    assert civitai.parse_model_url("https://civitai.red/models/9/x") == (9, None) and civitai.parse_model_url("civitai.com/models/9") == (9, None)
    assert civitai.level_ok(1, "12") and civitai.level_ok(3, "12") and not civitai.level_ok(4, "12")           # PG, PG-13 only
    assert civitai.level_ok(4 | 1, "16") and not civitai.level_ok(8, "16") and not civitai.level_ok(1 | 16, "16")  # R yes, X / XXX no
    assert civitai.level_ok(60, "18") and civitai.level_ok(0, "12") and not civitai.level_ok(60, "16")


def test_search_drops_models_the_age_mode_does_not_allow():
    class FakeHttp:
        def get_json(self, url, params=None, headers=None):
            return {"items": [{"id": 1, "name": "safe", "type": "LORA", "nsfwLevel": 1}, {"id": 2, "name": "r", "type": "LORA", "nsfwLevel": 5},
                              {"id": 3, "name": "x", "type": "LORA", "nsfwLevel": 60}], "metadata": {}}

    names = lambda mode: [m.name for m in civitai.search(FakeHttp(), nsfw=True, mode=mode)[0]]              # noqa: E731
    assert names("12") == ["safe"] and names("16") == ["safe", "r"] and names("18") == ["safe", "r", "x"]
