"""Download and unpack VSeeFace (free face-tracking VTuber software, emilianavt/VSeeFaceReleases on GitHub) --
a portable ~190 MB .zip, no installer, no separate archive tool needed (unlike Forge's .7z)."""
from __future__ import annotations

import shutil
import zipfile
from pathlib import Path
from typing import Callable

from anihub.net.http import HttpClient, HttpError

RELEASE_URL = "https://api.github.com/repos/emilianavt/VSeeFaceReleases/releases/latest"
NEED_FREE_GB = 1.0


class VSeeFaceInstallError(Exception):
    """User-presentable error."""


def pick_asset(release: dict) -> dict:
    """The release's own download page always links the LAST .zip asset (incremental hotfix patches -c2, -c3...
    are uploaded after the base version, so the GitHub API's own upload-order array ends with the newest)."""
    zips = [a for a in release.get("assets", []) if str(a.get("name", "")).lower().endswith(".zip")]
    if not zips:
        raise VSeeFaceInstallError("no VSeeFace package found in the release")
    return zips[-1]


def find_package_root(folder: Path) -> Path | None:
    """The directory (at most two levels down) that holds VSeeFace.exe."""
    folder = Path(folder)
    for candidate in [folder, *sorted(p for p in folder.iterdir() if p.is_dir())] if folder.is_dir() else []:
        if (candidate / "VSeeFace.exe").exists():
            return candidate
    return None


def install(http: HttpClient, dest_dir: Path, progress: Callable[[str, int, int], None] | None = None,
            cancelled: Callable[[], bool] | None = None, paused: Callable[[], bool] | None = None) -> Path | None:
    """Download + unpack into `dest_dir`; returns the folder holding VSeeFace.exe. progress(stage, done, total).
    None means `paused` said stop, same convention as forge_install.install()."""
    def report(stage: str, done: int = 0, total: int = 0) -> None:
        if progress:
            progress(stage, done, total)

    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    free_gb = shutil.disk_usage(dest_dir).free / 1024**3
    if free_gb < NEED_FREE_GB:
        raise VSeeFaceInstallError(f"not enough free disk space: {free_gb:.1f} GB (need about {NEED_FREE_GB:.0f} GB)")
    report("release")
    try:
        release = http.get_json(RELEASE_URL, headers={"Accept": "application/vnd.github+json"})
    except (HttpError, ValueError) as exc:
        raise VSeeFaceInstallError(str(exc)) from exc
    asset = pick_asset(release)
    archive = dest_dir / asset["name"]
    try:
        http.download(asset["browser_download_url"], archive, progress=lambda d, t: report("download", d, t or int(asset.get("size", 0))),
                      cancelled=cancelled, paused=paused)
    except HttpError as exc:
        raise VSeeFaceInstallError(str(exc)) from exc
    if paused and paused():
        return None
    report("extract")
    try:
        with zipfile.ZipFile(archive) as zf:
            zf.extractall(dest_dir)
    except zipfile.BadZipFile as exc:
        raise VSeeFaceInstallError(f"bad archive: {exc}") from exc
    finally:
        archive.unlink(missing_ok=True)
    root = find_package_root(dest_dir)
    if root is None:
        raise VSeeFaceInstallError("the archive did not contain VSeeFace.exe")
    report("done")
    return root
