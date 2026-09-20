import pytest

from anihub.core.config import Config
from anihub.net.http import HttpClient, HttpError, OfflineError, is_local
from anihub.services.forge import build_launcher_script


def test_local_hosts_are_recognised():
    assert is_local("http://127.0.0.1:4567/api") and is_local("http://localhost:7860") and is_local("http://[::1]:1/x")
    assert not is_local("https://danbooru.donmai.us/posts.json") and not is_local("http://127.0.0.1.evil.com/")


def test_offline_blocks_every_request_kind(tmp_path):
    cfg = Config.load(tmp_path / "c.json")
    cfg.set("network.offline", True, save=False)
    http = HttpClient(cfg)
    assert http.offline
    for call in (lambda: http.get_json("https://example.com/a.json"), lambda: http.get_bytes("https://example.com/a.png"),
                 lambda: http.download("https://example.com/a.png", tmp_path / "a.png")):
        with pytest.raises(OfflineError):
            call()
    assert not (tmp_path / "a.png").exists() and not (tmp_path / "a.png.part").exists()
    assert issubclass(OfflineError, HttpError)          # existing `except HttpError` paths report it as an error


def test_online_mode_does_not_block(tmp_path):
    cfg = Config.load(tmp_path / "c.json")
    http = HttpClient(cfg)
    http._check_online("https://example.com")           # no exception


def test_forge_launcher_gets_offline_variables(tmp_path):
    assert "HF_HUB_OFFLINE" not in build_launcher_script(tmp_path, 7860, False, "")
    script = build_launcher_script(tmp_path, 7860, False, "", offline=True)
    assert "set HF_HUB_OFFLINE=1" in script and "set TRANSFORMERS_OFFLINE=1" in script
    assert script.index("HF_HUB_OFFLINE") < script.index("webui.bat")     # set before Forge starts
