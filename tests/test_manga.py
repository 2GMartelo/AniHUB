from pathlib import Path

import pytest
from PySide6.QtGui import QImage

from anihub.core.config import Config
from anihub.services.suwayomi import conf_values, set_conf_values
from anihub.services.suwayomi_install import InstallError, parse_checksums, pick_assets
from anihub.ui.manga_reader import spread_at, step_back

DEFAULT_CONF = '''# Network
server.ip = "0.0.0.0" # default: "0.0.0.0"
server.port = 4567 # default: 4567 ; range: [1, 65535]
server.webUIEnabled = true # default: true
server.socksProxyEnabled = false # default: false
server.downloadAsCbz = false # default: false
'''


def test_set_conf_values_replaces_and_keeps_comments():
    out = set_conf_values(DEFAULT_CONF, {"server.ip": '"127.0.0.1"', "server.webUIEnabled": "false"})
    assert 'server.ip = "127.0.0.1" # default: "0.0.0.0"' in out
    assert "server.webUIEnabled = false # default: true" in out
    assert "server.port = 4567 # default" in out  # untouched


def test_set_conf_values_appends_missing_and_handles_empty_file():
    assert set_conf_values("", {"server.ip": '"127.0.0.1"'}).strip() == 'server.ip = "127.0.0.1"'
    out = set_conf_values("server.port = 1\n", {"server.systemTrayEnabled": "false"})
    assert out.endswith("server.systemTrayEnabled = false\n")


def test_set_conf_values_is_idempotent():
    once = set_conf_values(DEFAULT_CONF, {"server.port": "4600"})
    assert set_conf_values(once, {"server.port": "4600"}) == once


def test_conf_binds_localhost_and_disables_web_ui(tmp_path):
    values = conf_values(Config.load(tmp_path / "c.json"))
    assert values["server.ip"] == '"127.0.0.1"' and values["server.webUIEnabled"] == "false"
    assert values["server.socksProxyEnabled"] == "false" and values["server.downloadAsCbz"] == "true"


def test_conf_maps_socks_proxy_only(tmp_path):
    cfg = Config.load(tmp_path / "c.json")
    cfg.set("network.proxy", "socks5://user:pw@127.0.0.1:1080", save=False)
    v = conf_values(cfg)
    assert v["server.socksProxyEnabled"] == "true" and v["server.socksProxyHost"] == '"127.0.0.1"'
    assert v["server.socksProxyPort"] == '"1080"' and v["server.socksProxyUsername"] == '"user"'
    cfg.set("network.proxy", "http://127.0.0.1:8080", save=False)  # Suwayomi cannot use an HTTP proxy
    assert conf_values(cfg)["server.socksProxyEnabled"] == "false"


RELEASE = {"tag_name": "v9", "assets": [
    {"name": "Checksums.sha256", "browser_download_url": "u0"},
    {"name": "Suwayomi-Server-v9-linux-x64.tar.gz", "browser_download_url": "u1"},
    {"name": "Suwayomi-Server-v9-windows-x64.msi", "browser_download_url": "u2"},
    {"name": "Suwayomi-Server-v9-windows-x64.zip", "browser_download_url": "u3"}]}


def test_pick_assets_windows_zip():
    archive, checksums = pick_assets(RELEASE, "win32")
    assert archive["browser_download_url"] == "u3" and checksums["browser_download_url"] == "u0"


def test_pick_assets_other_platforms_fail_clearly():
    with pytest.raises(InstallError):
        pick_assets(RELEASE, "linux")  # archive found but auto-install is Windows-only
    with pytest.raises(InstallError):
        pick_assets({"assets": []}, "win32")


def test_parse_checksums():
    text = "AAA111  Suwayomi-Server-v9-windows-x64.zip\nbbb222 *other.jar\n\n"
    assert parse_checksums(text) == {"Suwayomi-Server-v9-windows-x64.zip": "aaa111", "other.jar": "bbb222"}


def img(w: int, h: int) -> QImage:
    return QImage(w, h, QImage.Format.Format_RGB32)


def test_spreads_cover_alone_then_pairs():
    imgs = {i: img(100, 150) for i in range(6)}
    assert spread_at(imgs, 6, 0, True) == [0]      # cover stands alone
    assert spread_at(imgs, 6, 1, True) == [1, 2]
    assert spread_at(imgs, 6, 3, True) == [3, 4]
    assert spread_at(imgs, 6, 5, True) == [5]      # last page has no partner
    assert spread_at(imgs, 6, 1, False) == [1]     # single-page mode never pairs


def test_spreads_wide_pages_and_unloaded_pages_stand_alone():
    imgs = {i: img(100, 150) for i in range(5)}
    imgs[2] = img(300, 150)                        # a double-page spread in the source
    assert spread_at(imgs, 5, 1, True) == [1]
    assert spread_at(imgs, 5, 2, True) == [2]
    del imgs[4]
    assert spread_at(imgs, 5, 3, True) == [3]      # partner not loaded yet


def test_step_back_mirrors_pairs():
    imgs = {i: img(100, 150) for i in range(7)}
    assert step_back(imgs, 7, 5, True) == 3
    assert step_back(imgs, 7, 3, True) == 1
    assert step_back(imgs, 7, 1, True) == 0
    assert step_back(imgs, 7, 5, False) == 4
    imgs[3] = img(300, 150)
    assert step_back(imgs, 7, 5, True) == 4        # (3,4) cannot be a pair: 3 is wide
