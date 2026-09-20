import hashlib
import time
from pathlib import Path

import pytest

from anihub.core.config import Config
from anihub.net.http import HttpError
from anihub.services.updater import (
    CHECK_EVERY_S, Release, UpdateError, Updater, is_newer, parse_release, parse_version,
)

REPO = "2GMartelo/AniHUB"


def raw(tag, prerelease=False, draft=False, size=100, digest=None, name=None, url=None, assets=True):
    asset_name = name or f"AniHUB-Setup-{tag.lstrip('v')}.exe"
    asset = {"name": asset_name, "size": size, "state": "uploaded",
             "browser_download_url": url or f"https://github.com/{REPO}/releases/download/{tag}/{asset_name}"}
    if digest:
        asset["digest"] = digest
    return {"tag_name": tag, "name": f"AniHUB {tag}", "body": f"notes {tag}", "html_url": f"https://github.com/{REPO}/releases/tag/{tag}",
            "published_at": "2026-09-21T10:00:00Z", "prerelease": prerelease, "draft": draft, "assets": [asset] if assets else [
                {"name": "source.zip", "browser_download_url": "x", "size": 1}]}


class FakeHttp:
    def __init__(self, releases=None, payload=b"x" * 100, error=None):
        self.releases, self.payload, self.error, self.calls = releases or [], payload, error, []

    def get_json(self, url, params=None, **kw):
        self.calls.append(("get", url, params))
        if self.error:
            raise self.error
        return self.releases

    def download(self, url, dest, progress=None, cancelled=None, headers=None):
        self.calls.append(("download", url))
        if self.error:
            raise self.error
        dest.write_bytes(self.payload)
        if progress:
            progress(len(self.payload), len(self.payload))


def make(tmp_path, current="0.3.0", **kw):
    cfg = Config.load(tmp_path / "c.json")
    return Updater(FakeHttp(**kw), cfg, current), cfg


def test_version_parsing_and_comparison():
    assert parse_version("v0.3.0") == (0, 3, 0) and parse_version("1.10") == (1, 10) and parse_version("junk") == (0,)
    assert is_newer("0.4.0", "0.3.0") and is_newer("0.10.0", "0.9.9") and is_newer("1.0", "0.9.9")
    assert not is_newer("0.3.0", "0.3.0") and not is_newer("0.3", "0.3.0") and not is_newer("0.2.9", "0.3.0")
    assert not is_newer("0.4.0-beta", "0.4.0") and is_newer("0.4.0", "0.4.0-beta")


def test_release_parsing_picks_the_installer_and_digest():
    r = parse_release(raw("v0.4.0", digest="sha256:ABCDEF"))
    assert (r.version, r.asset_name, r.sha256, r.installable) == ("0.4.0", "AniHUB-Setup-0.4.0.exe", "abcdef", True)
    assert r.published == "2026-09-21" and r.notes == "notes v0.4.0"
    assert not parse_release(raw("v0.4.0", assets=False)).installable
    assert not parse_release(raw("v0.4.0", name="evil.exe")).installable          # only AniHUB-Setup-*.exe counts


def test_latest_skips_drafts_prereleases_and_old_versions(tmp_path):
    up, _ = make(tmp_path, releases=[raw("v0.5.0", prerelease=True), raw("v0.4.0"), raw("v0.3.0"), raw("v0.9.0", draft=True)])
    assert up.latest().version == "0.4.0"
    assert make(tmp_path, releases=[raw("v0.3.0"), raw("v0.2.0")])[0].latest() is None          # up to date
    assert make(tmp_path, releases=[raw("v0.4.0", assets=False), raw("v0.3.5")])[0].latest().version == "0.3.5"   # no installer: next one
    assert [r.version for r in make(tmp_path, releases=[raw("v0.2.0"), raw("v0.10.0"), raw("v0.3.0")])[0].releases()] == ["0.10.0", "0.3.0", "0.2.0"]


def test_automatic_check_is_daily_switchable_and_respects_skips(tmp_path):
    up, cfg = make(tmp_path, releases=[raw("v0.4.0")])
    assert up.check().version == "0.4.0" and len(up.http.calls) == 1
    assert up.check() is None and len(up.http.calls) == 1                         # asked less than a day ago
    cfg.set("update.last_check", time.time() - CHECK_EVERY_S - 5, save=False)
    up.skip(up.latest())
    assert up.check() is None                                                     # the user skipped 0.4.0
    assert up.check(force=True).version == "0.4.0"                                # "check now" ignores the skip
    cfg.set("update.auto", False, save=False)
    cfg.set("update.last_check", 0, save=False)
    n = len(up.http.calls)
    assert up.check() is None and len(up.http.calls) == n                         # automatic checks switched off


def test_network_errors_become_update_errors(tmp_path):
    up, _ = make(tmp_path, error=HttpError(403, "rate limit"))
    with pytest.raises(UpdateError):
        up.latest()
    with pytest.raises(UpdateError):
        make(tmp_path, releases={"message": "not a list"})[0].releases()


def test_download_verifies_size_checksum_and_origin(tmp_path):
    payload = b"installer" * 20
    good = parse_release(raw("v0.4.0", size=len(payload), digest="sha256:" + hashlib.sha256(payload).hexdigest()))
    up, _ = make(tmp_path, payload=payload)
    path = up.download(good, tmp_path / "dl")
    assert path.read_bytes() == payload and path.name == "AniHUB-Setup-0.4.0.exe"
    bad_sum = parse_release(raw("v0.4.0", size=len(payload), digest="sha256:" + "0" * 64))
    with pytest.raises(UpdateError, match="checksum"):
        up.download(bad_sum, tmp_path / "dl2")
    assert not (tmp_path / "dl2" / "AniHUB-Setup-0.4.0.exe").exists()             # a failed download leaves nothing behind
    with pytest.raises(UpdateError, match="incomplete"):
        up.download(parse_release(raw("v0.4.0", size=len(payload) + 5)), tmp_path / "dl3")
    foreign = parse_release(raw("v0.4.0", url="https://evil.example/AniHUB-Setup-0.4.0.exe"))
    with pytest.raises(UpdateError, match="repository"):
        up.download(foreign, tmp_path / "dl4")
    with pytest.raises(UpdateError, match="no installer"):
        up.download(parse_release(raw("v0.4.0", assets=False)), tmp_path / "dl5")
    with pytest.raises(UpdateError):
        make(tmp_path, error=HttpError(0, "cancelled"))[0].download(good, tmp_path / "dl6")


def test_cleanup_keeps_only_the_newest_installer(tmp_path):
    up, _ = make(tmp_path)
    folder = tmp_path / "u"
    folder.mkdir()
    for i, name in enumerate(("AniHUB-Setup-0.1.0.exe", "AniHUB-Setup-0.2.0.exe", "AniHUB-Setup-0.3.0.exe")):
        f = folder / name
        f.write_bytes(b"x")
        import os

        os.utime(f, (1000 + i, 1000 + i))
    (folder / "other.txt").write_text("keep")
    up.cleanup(folder)
    assert sorted(p.name for p in folder.iterdir()) == ["AniHUB-Setup-0.3.0.exe", "other.txt"]
    up.cleanup(tmp_path / "missing")                                              # no folder: nothing to do


def test_release_panel_shows_notes_and_button_labels(qapp, tmp_path):
    from anihub.core.i18n import tr
    from anihub.ui.update_dialog import ReleasePanel

    up, _ = make(tmp_path, current="0.3.0")
    panel = ReleasePanel(up, lambda: None)
    panel.show_release(parse_release(raw("v0.4.0")))
    assert panel.install_btn.text() == tr("update.install") and "notes v0.4.0" in panel.notes.toPlainText()
    panel.show_release(parse_release(raw("v0.2.0")))
    assert panel.install_btn.text() == tr("update.rollback") and panel.install_btn.isEnabled()
    panel.show_release(parse_release(raw("v0.3.0")))
    assert panel.install_btn.text() == tr("update.reinstall") and "0.3.0" in panel.title.text()
    panel.show_release(parse_release(raw("v0.4.0", assets=False)))
    assert not panel.install_btn.isEnabled() and panel.message.text() == tr("update.no_installer")
    panel.show_release(None)
    assert not panel.install_btn.isEnabled()


def test_installing_downloads_starts_the_installer_and_quits(qapp, tmp_path, monkeypatch):
    from anihub.ui import update_dialog
    from anihub.ui.update_dialog import ReleasePanel

    payload = b"z" * 50
    up, _ = make(tmp_path, payload=payload)
    monkeypatch.setattr(update_dialog, "downloads_dir", lambda: tmp_path / "dl")
    started, quit_calls = [], []
    monkeypatch.setattr(Updater, "launch", staticmethod(lambda path: started.append(path)))
    panel = ReleasePanel(up, lambda: quit_calls.append(1))
    panel.show_release(parse_release(raw("v0.4.0", size=len(payload))))
    panel._install()
    end = time.time() + 5
    while time.time() < end and not quit_calls:
        qapp.processEvents()
        time.sleep(0.01)
    assert quit_calls == [1] and started[0].name == "AniHUB-Setup-0.4.0.exe" and started[0].read_bytes() == payload
