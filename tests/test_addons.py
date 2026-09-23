import zipfile
from pathlib import Path

import pytest

from anihub.services import addons


class FakeApi:
    def __init__(self, txt2img=()):
        self.txt2img = list(txt2img)

    def scripts(self):
        return {"txt2img": self.txt2img, "img2img": self.txt2img}


def test_is_installed_matches_case_insensitively():
    api = FakeApi(["Refiner", "ADetailer", "Seed"])
    assert addons.is_installed(api, "adetailer")
    assert not addons.is_installed(FakeApi(["Refiner", "Seed"]), "adetailer")
    assert addons.is_installed(FakeApi(["forge couple"]), "forge_couple")   # Forge's own script-title casing varies


def make_repo_zip(tmp_path: Path, repo_name: str = "adetailer", branch: str = "main") -> Path:
    src = tmp_path / f"{repo_name}-{branch}"
    (src / "scripts").mkdir(parents=True)
    (src / "scripts" / "!adetailer.py").write_text("# addon entry point")
    (src / "README.md").write_text("hi")
    archive = tmp_path / "src.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        for f in src.rglob("*"):
            if f.is_file():
                zf.write(f, f.relative_to(tmp_path))
    return archive


class FakeHttp:
    def __init__(self, archive_src: Path):
        self.archive_src = archive_src
        self.calls = 0

    def download(self, url, dest, progress=None, cancelled=None, paused=None):
        self.calls += 1
        if paused and paused():
            return
        dest.write_bytes(self.archive_src.read_bytes())
        if progress:
            progress(dest.stat().st_size, dest.stat().st_size)


def test_install_extracts_into_extensions_and_strips_the_repo_prefix(tmp_path):
    forge_dir = tmp_path / "forge"
    http = FakeHttp(make_repo_zip(tmp_path))
    dest = addons.install(http, forge_dir, "adetailer")
    assert dest == forge_dir / "extensions" / "adetailer"
    assert (dest / "scripts" / "!adetailer.py").is_file()
    assert not (forge_dir / "extensions" / "adetailer.zip").exists()          # cleaned up


def test_install_is_a_no_op_when_already_present(tmp_path):
    forge_dir = tmp_path / "forge"
    dest = forge_dir / "extensions" / "adetailer"
    (dest / "scripts").mkdir(parents=True)
    http = FakeHttp(make_repo_zip(tmp_path))
    result = addons.install(http, forge_dir, "adetailer")
    assert result == dest and http.calls == 0                                 # never even tried to download


def test_install_returns_none_when_paused_and_keeps_the_partial_download(tmp_path):
    forge_dir = tmp_path / "forge"
    http = FakeHttp(make_repo_zip(tmp_path))
    result = addons.install(http, forge_dir, "adetailer", paused=lambda: True)
    assert result is None
    assert not (forge_dir / "extensions" / "adetailer" / "scripts").exists()


def test_install_works_for_a_second_registered_addon(tmp_path):
    forge_dir = tmp_path / "forge"
    http = FakeHttp(make_repo_zip(tmp_path, repo_name="sd-forge-couple"))
    dest = addons.install(http, forge_dir, "forge_couple")
    assert dest == forge_dir / "extensions" / "forge_couple"
    assert (dest / "scripts").is_dir()


def test_extract_raises_when_the_archive_has_no_matching_top_level_folder(tmp_path):
    bad = tmp_path / "bad.zip"
    with zipfile.ZipFile(bad, "w") as zf:
        zf.writestr("unrelated/file.txt", "x")
    with pytest.raises(addons.AddonError):
        addons._extract(bad, tmp_path / "dest", "adetailer")
