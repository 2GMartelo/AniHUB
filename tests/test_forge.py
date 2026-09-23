import base64
import json
import sqlite3

from anihub.core.db import SCHEMA_VERSION, Database
from anihub.core.paths import LibraryPaths
from anihub.library.service import LibraryService
from anihub.services.forge import ForgeError, build_launcher_script
from anihub.services.generation import GenParams, progress_text, prompt_tags, run_txt2img

PNG = base64.b64encode(b"\x89PNG fake image bytes").decode()


def test_launcher_keeps_user_settings_and_adds_flags(tmp_path):
    (tmp_path / "webui-user.bat").write_text(
        "@echo off\nset PYTHON=\nset COMMANDLINE_ARGS=--cuda-malloc\n\ncall webui.bat\n", encoding="utf-8")
    script = build_launcher_script(tmp_path, 7861, True, "--xformers")
    lines = script.splitlines()
    assert "set COMMANDLINE_ARGS=--cuda-malloc" in lines          # the user's own args survive
    assert sum(1 for l in lines if l.lower().startswith("call ") and "webui.bat" in l) == 1  # theirs replaced by ours
    assert lines.index("set COMMANDLINE_ARGS=%COMMANDLINE_ARGS% --api --port 7861 --nowebui --xformers") \
        < lines.index(f'call "{tmp_path / "webui.bat"}"')
    assert f'cd /d "{tmp_path}"' in lines
    assert "\r\r" not in script and script.endswith("\r\n")  # CRLF only, never doubled


def test_launcher_file_bytes_roundtrip(tmp_path):
    """The launcher must reach disk with exactly one CR before each LF (regression: \\r\\r\\n on Windows)."""
    from anihub.core.config import Config
    from anihub.services.forge import ForgeManager
    (tmp_path / "webui.bat").write_text("@echo off\n")
    cfg = Config.load(tmp_path / "c.json")
    cfg.set("forge.path", str(tmp_path), save=False)
    mgr = ForgeManager(cfg, tmp_path / "work")
    mgr.api.ping = lambda: False
    import subprocess
    started = {}
    real_popen = subprocess.Popen
    subprocess.Popen = lambda *a, **k: started.update(args=a, kwargs=k) or type("P", (), {"pid": 1, "poll": lambda s: None})()
    try:
        mgr.start()
    finally:
        subprocess.Popen = real_popen
    raw = (tmp_path / "work" / "forge_launch.bat").read_bytes()
    assert b"\r\r" not in raw and raw.count(b"\r\n") == raw.count(b"\n")


def test_launcher_calls_one_click_environment(tmp_path):
    forge = tmp_path / "pkg" / "webui"
    forge.mkdir(parents=True)
    (tmp_path / "pkg" / "environment.bat").write_text("@echo off\n")
    lines = build_launcher_script(forge, 7860, False, "").splitlines()
    env_line = f'call "{tmp_path / "pkg" / "environment.bat"}"'
    assert env_line in lines and lines.index(env_line) < lines.index(f'cd /d "{forge}"')  # like run.bat does
    assert env_line not in build_launcher_script(tmp_path, 7860, False, "")  # plain installs are untouched


def test_launcher_without_user_bat(tmp_path):
    script = build_launcher_script(tmp_path, 7860, False, "")
    assert "--api --port 7860" in script and "--nowebui" not in script


def test_migration_v1_to_v2(tmp_path):
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.executescript("CREATE TABLE items (id INTEGER PRIMARY KEY, kind TEXT, path TEXT, added_at REAL, "
                       "rating TEXT, trashed_at REAL);")
    conn.execute("PRAGMA user_version=1")
    conn.execute("INSERT INTO items(kind, path, added_at, rating) VALUES ('art', 'a.png', 1, 'general')")
    conn.commit()
    conn.close()
    db = Database(path)
    cols = [r[1] for r in db.conn.execute("PRAGMA table_info(items)")]
    assert "meta" in cols
    assert db.conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION  # walked 1 -> 2 -> 3
    assert db.conn.execute("SELECT COUNT(*) FROM items").fetchone()[0] == 1  # data preserved


class FakeApi:
    def __init__(self, response):
        self.response, self.payload = response, None
        self.payloads: list[dict] = []

    def txt2img(self, payload):
        self.payload = payload
        self.payloads.append(payload)
        return self.response


def test_run_txt2img_skips_the_grid_image_within_one_call(tmp_path):
    """A batch *size* above 1 (several images from a single Forge call) can still come back with a leading grid
    image; index_of_first_image says where the real ones start."""
    info = {"index_of_first_image": 1, "all_seeds": [111, 222], "infotexts": ["grid", "one", "two"]}
    api = FakeApi({"images": [PNG, PNG, PNG], "info": json.dumps(info)})
    params = GenParams(prompt="1girl", model="m.safetensors [abc]", batch_size=2)
    results = run_txt2img(api, params, tmp_path / "gen")
    assert [r.seed for r in results] == [111, 222]
    assert [r.meta["infotext"] for r in results] == ["one", "two"]
    assert all(r.path.exists() and r.path.suffix == ".png" for r in results)
    assert len({r.path for r in results}) == 2
    assert len(api.payloads) == 1                                             # one call: batch_size, not n_iter
    assert api.payload["override_settings"] == {"sd_model_checkpoint": "m.safetensors [abc]"}
    assert api.payload["save_images"] is False and api.payload["n_iter"] == 1


def test_run_txt2img_splits_a_batch_count_into_one_call_each(tmp_path):
    """A batch *count* above 1 is sent as that many separate calls (one each), not one call with n_iter=2 -- so a
    caller can show each finished picture as it arrives instead of only once the whole batch is done."""
    info = {"all_seeds": [111], "infotexts": ["one"]}
    api = FakeApi({"images": [PNG], "info": json.dumps(info)})
    params = GenParams(prompt="1girl", model="m.safetensors [abc]", n_iter=2)
    results = run_txt2img(api, params, tmp_path / "gen")
    assert len(results) == 2 and len({r.path for r in results}) == 2
    assert all(r.path.exists() and r.path.suffix == ".png" for r in results)
    assert len(api.payloads) == 2 and all(p["n_iter"] == 1 for p in api.payloads)
    assert api.payload["override_settings"] == {"sd_model_checkpoint": "m.safetensors [abc]"}


def test_run_txt2img_no_images(tmp_path):
    try:
        run_txt2img(FakeApi({"images": [], "info": "{}"}), GenParams(), tmp_path)
    except ForgeError:
        return
    raise AssertionError("expected ForgeError")


def test_no_model_override_when_model_empty():
    assert "override_settings" not in GenParams().to_payload()


def test_prompt_tags():
    tags = prompt_tags("1girl, (blue hair:1.2), <lora:style:0.8>, BREAK, [solo], 1girl")
    assert tags == ["1girl", "blue_hair", "solo"]


def test_progress_text():
    frac, text = progress_text({"progress": 0.5, "eta_relative": 12.3,
                                "state": {"sampling_step": 10, "sampling_steps": 20, "job_no": 0, "job_count": 2}})
    assert frac == 0.5 and text == "1/2 · step 10/20 · ~12s"


def test_progress_text_while_loading_model():
    # Forge reports -1 counters, 0 steps and a nonsense ETA until sampling starts
    frac, text = progress_text({"progress": 0, "eta_relative": 300.0,
                                "state": {"sampling_step": 0, "sampling_steps": 0, "job_no": -1, "job_count": -1}})
    assert frac == 0.0 and text == ""


class NoHttp:
    pass


def test_save_generation(tmp_path):
    paths = LibraryPaths(tmp_path / "lib")
    paths.ensure()
    svc = LibraryService(Database(paths.db_file), paths, NoHttp())
    img = paths.sd / "generated" / "2026-01-01" / "a.png"
    img.parent.mkdir(parents=True)
    img.write_bytes(b"png-bytes")
    meta = {"prompt": "1girl, blue hair", "seed": 5, "width": 64, "height": 64}
    res = svc.save_generation(img, meta, "sensitive")
    assert res.status == "saved"
    row = svc.db.search_items(kind="sd", ratings=["sensitive"])[0]
    assert row["path"] == "sd/generated/2026-01-01/a.png" and json.loads(row["meta"])["seed"] == 5
    assert svc.db.item_tags(row["id"]) == ["1girl", "blue_hair"]
    assert svc.db.search_items(kind="art") == []                     # separate section from arts
    assert svc.save_generation(img, meta).status == "duplicate"
