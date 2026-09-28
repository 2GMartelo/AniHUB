"""services/comfyui_install.py: downloading + unpacking the ComfyUI portable build -- mirrors test_sd_gate.py's
Forge-install tests. No real network or 7z archive involved."""
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from anihub.services import comfyui_install


def make_portable(root: Path) -> Path:
    """<root>/ComfyUI/main.py + <root>/python_embeded/python.exe -- the real portable layout."""
    (root / "ComfyUI").mkdir(parents=True, exist_ok=True)
    (root / "ComfyUI" / "main.py").write_text("")
    (root / "python_embeded").mkdir(exist_ok=True)
    (root / "python_embeded" / "python.exe").write_bytes(b"")
    return root


class FakeHttp:
    def __init__(self):
        self.calls = []

    def download(self, url, dest, progress=None, cancelled=None, paused=None):
        self.calls.append(url)
        dest.write_bytes(b"7z")
        if progress:
            progress(50, 100)


# --- comfy_dir_of ----------------------------------------------------------------------------------------------

def test_comfy_dir_of_the_comfyui_folder_itself(tmp_path):
    make_portable(tmp_path)
    assert comfyui_install.comfy_dir_of(tmp_path / "ComfyUI") == tmp_path / "ComfyUI"


def test_comfy_dir_of_a_parent_holding_the_extracted_archive(tmp_path):
    make_portable(tmp_path / "ComfyUI_windows_portable")
    assert comfyui_install.comfy_dir_of(tmp_path) == tmp_path / "ComfyUI_windows_portable" / "ComfyUI"


def test_comfy_dir_of_none_without_python_embeded(tmp_path):
    (tmp_path / "ComfyUI").mkdir()
    (tmp_path / "ComfyUI" / "main.py").write_text("")
    assert comfyui_install.comfy_dir_of(tmp_path / "ComfyUI") is None


def test_comfy_dir_of_none_for_an_unrelated_folder(tmp_path):
    assert comfyui_install.comfy_dir_of(tmp_path) is None


# --- extract -----------------------------------------------------------------------------------------------------

def test_extract_unpacks_a_real_7z(tmp_path):
    pkg = make_portable(tmp_path / "src" / "ComfyUI_windows_portable")
    archive = tmp_path / "src" / "a.7z"
    subprocess.run([comfyui_install.tar_exe(), "--format", "7zip", "-cf", str(archive), "-C", str(pkg.parent),
                   pkg.name], check=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    dest = tmp_path / "out"

    comfyui_install.extract(archive, dest)

    assert comfyui_install.comfy_dir_of(dest) == dest / "ComfyUI_windows_portable" / "ComfyUI"


def test_extract_raises_for_a_missing_archive(tmp_path):
    with pytest.raises(comfyui_install.ComfyInstallError):
        comfyui_install.extract(tmp_path / "missing.7z", tmp_path / "out")


# --- install -------------------------------------------------------------------------------------------------

def test_install_downloads_unpacks_and_reports_progress(tmp_path, monkeypatch):
    def fake_extract(archive, dest, cancelled=None):
        make_portable(dest / "ComfyUI_windows_portable")

    monkeypatch.setattr(comfyui_install, "extract", fake_extract)
    monkeypatch.setattr(comfyui_install, "tar_exe", lambda: "tar")
    http = FakeHttp()
    stages = []

    result = comfyui_install.install(http, tmp_path / "dest", lambda s, d, t: stages.append((s, d, t)))

    assert result == tmp_path / "dest" / "ComfyUI_windows_portable" / "ComfyUI"
    assert http.calls == [comfyui_install.PORTABLE_URL]
    assert [s for s, _d, _t in stages][0] == "download" and ("download", 50, 100) in stages and stages[-1][0] == "done"
    assert not any(p.suffix == ".7z" for p in (tmp_path / "dest").iterdir())          # the archive is removed


def test_install_raises_when_disk_is_low(tmp_path, monkeypatch):
    monkeypatch.setattr(comfyui_install.shutil, "disk_usage", lambda p: SimpleNamespace(free=1 * 1024**3))
    monkeypatch.setattr(comfyui_install, "tar_exe", lambda: "tar")
    with pytest.raises(comfyui_install.ComfyInstallError, match="disk"):
        comfyui_install.install(FakeHttp(), tmp_path / "dest")


def test_install_raises_without_tar(tmp_path, monkeypatch):
    monkeypatch.setattr(comfyui_install, "tar_exe", lambda: None)
    with pytest.raises(comfyui_install.ComfyInstallError, match="tar.exe"):
        comfyui_install.install(FakeHttp(), tmp_path / "dest")


def test_install_returns_none_when_paused_before_extracting(tmp_path, monkeypatch):
    called_extract = []
    monkeypatch.setattr(comfyui_install, "extract", lambda *a, **k: called_extract.append(1))
    monkeypatch.setattr(comfyui_install, "tar_exe", lambda: "tar")

    result = comfyui_install.install(FakeHttp(), tmp_path / "dest", paused=lambda: True)

    assert result is None and not called_extract


def test_install_raises_when_the_archive_has_the_wrong_layout(tmp_path, monkeypatch):
    monkeypatch.setattr(comfyui_install, "extract", lambda *a, **k: None)  # extracts nothing useful
    monkeypatch.setattr(comfyui_install, "tar_exe", lambda: "tar")
    with pytest.raises(comfyui_install.ComfyInstallError, match="layout"):
        comfyui_install.install(FakeHttp(), tmp_path / "dest")
