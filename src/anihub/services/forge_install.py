"""Download and unpack the Stable Diffusion Forge "one-click package" (a .7z of about 1.8 GB from the project's GitHub release).

Windows 10/11 ship `tar.exe` (bsdtar), which reads .7z archives, so no extra tool is needed. The package unpacks into a folder that
holds `webui/` (the Forge path AniHUB stores) next to `environment.bat`, `run.bat` and the bundled Python.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Callable

from anihub.net.http import HttpClient, HttpError
from anihub.services.procservice import NO_WINDOW

RELEASE_URL = "https://api.github.com/repos/lllyasviel/stable-diffusion-webui-forge/releases/tags/latest"
NEED_FREE_GB = 12.0


class ForgeInstallError(Exception):
    """User-presentable error."""


def _version_key(name: str) -> tuple:
    cu = re.search(r"cu(\d+)", name)
    torch = re.search(r"torch(\d+)", name)
    return (int(cu.group(1)) if cu else 0, int(torch.group(1)) if torch else 0)


def pick_asset(release: dict) -> dict:
    """The newest one-click package (highest CUDA, then torch version) among the release's .7z assets."""
    packages = [a for a in release.get("assets", []) if str(a.get("name", "")).endswith(".7z") and "forge" in a["name"].lower()]
    if not packages:
        raise ForgeInstallError("no Forge package found in the release")
    return max(packages, key=lambda a: _version_key(a["name"]))


def tar_exe() -> str | None:
    """Windows' own bsdtar (the one that reads 7z); GNU tar from Git for Windows does not."""
    system = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "tar.exe"
    if system.exists():
        return str(system)
    return shutil.which("tar") if sys.platform != "win32" else None


def find_package_root(folder: Path) -> Path | None:
    """The directory (at most two levels down) that contains webui/webui.bat: the package root."""
    folder = Path(folder)
    for candidate in [folder, *sorted(p for p in folder.iterdir() if p.is_dir())] if folder.is_dir() else []:
        if (candidate / "webui" / "webui.bat").exists():
            return candidate
    return None


def forge_path_of(folder: str | Path) -> Path | None:
    """What AniHUB stores as `forge.path` for a user-chosen folder: the `webui` directory. Accepts the package folder, the
    `webui` folder itself, or a folder that holds the package one level down."""
    p = Path(folder)
    if (p / "webui.bat").exists():
        return p
    root = find_package_root(p)
    return root / "webui" if root else None


def extract(archive: Path, dest: Path, cancelled: Callable[[], bool] | None = None) -> None:
    exe = tar_exe()
    if exe is None:
        raise ForgeInstallError("tar.exe was not found (Windows 10 1803 or newer is needed to unpack the .7z)")
    dest.mkdir(parents=True, exist_ok=True)
    proc = subprocess.Popen([exe, "-xf", str(archive), "-C", str(dest)], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            creationflags=NO_WINDOW)
    while proc.poll() is None:
        if cancelled and cancelled():
            proc.kill()
            raise ForgeInstallError("cancelled")
        try:
            proc.wait(timeout=0.5)
        except subprocess.TimeoutExpired:
            pass
    if proc.returncode != 0:
        raise ForgeInstallError((proc.stderr.read() or b"").decode("utf-8", "replace").strip()[:300] or f"tar exited with {proc.returncode}")


def install(http: HttpClient, dest_dir: Path, progress: Callable[[str, int, int], None] | None = None,
            cancelled: Callable[[], bool] | None = None, paused: Callable[[], bool] | None = None) -> Path | None:
    """Download + unpack into `dest_dir`; returns the `webui` folder to store as forge.path. progress(stage, done, total).
    None means `paused` said stop: only the download itself can pause (extracting the archive cannot be safely
    resumed partway through, so once that starts a cancel is the only way out) -- the partial archive is kept via
    HttpClient.download's own .part file, and a later call resumes it."""
    def report(stage: str, done: int = 0, total: int = 0) -> None:
        if progress:
            progress(stage, done, total)

    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    free_gb = shutil.disk_usage(dest_dir).free / 1024**3
    if free_gb < NEED_FREE_GB:
        raise ForgeInstallError(f"not enough free disk space: {free_gb:.1f} GB (need about {NEED_FREE_GB:.0f} GB)")
    if tar_exe() is None:
        raise ForgeInstallError("tar.exe was not found (Windows 10 1803 or newer is needed to unpack the .7z)")
    report("release")
    try:
        release = http.get_json(RELEASE_URL, headers={"Accept": "application/vnd.github+json"})
    except (HttpError, ValueError) as exc:
        raise ForgeInstallError(str(exc)) from exc
    asset = pick_asset(release)
    archive = dest_dir / asset["name"]
    try:
        http.download(asset["browser_download_url"], archive, progress=lambda d, t: report("download", d, t or int(asset.get("size", 0))),
                      cancelled=cancelled, paused=paused)
    except HttpError as exc:
        raise ForgeInstallError(str(exc)) from exc
    if paused and paused():
        return None
    report("extract")
    try:
        extract(archive, dest_dir, cancelled)
    finally:
        archive.unlink(missing_ok=True)
    root = find_package_root(dest_dir)
    if root is None:
        raise ForgeInstallError("the archive did not contain a Forge package (webui/webui.bat is missing)")
    report("done")
    return root / "webui"
