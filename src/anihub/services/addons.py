"""Generation addons: optional Forge extensions AniHUB knows how to detect and install, the same way it already
handles Forge and sd-scripts themselves (services/forge_install.py, services/lora_train_install.py) -- a plain
branch-archive download, no git required.

Detection goes through Forge's own /sdapi/v1/scripts (ForgeApi.scripts()), which lists every txt2img/img2img script
it currently has loaded, built-in or from an extension. An addon here is "installed" once its script name shows up
there -- which also means Forge has to actually be running (and restarted since the extension was added) for the
check to say yes.

ControlNet and Regional Prompter are deliberately not in this registry yet: ControlNet ships inside Forge itself
(nothing to install), and Regional Prompter needs its own zone-editor UI before an install button is worth adding.
This starts with the one addon that is useful the moment it is installed, with no extra UI: ADetailer."""
from __future__ import annotations

import shutil
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from anihub.net.http import HttpClient
from anihub.services.forge import ForgeApi


class AddonError(Exception):
    """User-presentable addon problem."""


@dataclass(frozen=True)
class Addon:
    key: str
    script_name: str            # what to look for in ForgeApi.scripts()["txt2img"]
    repo: str                   # "owner/name" on GitHub
    branch: str = "main"


ADDONS: dict[str, Addon] = {
    "adetailer": Addon(key="adetailer", script_name="ADetailer", repo="Bing-su/adetailer", branch="main"),
}


def is_installed(api: ForgeApi, key: str) -> bool:
    addon = ADDONS[key]
    names = {n.lower() for n in (api.scripts().get("txt2img") or [])}
    return addon.script_name.lower() in names


def install(http: HttpClient, forge_dir: Path, key: str, progress: Callable[[int, int], None] | None = None,
           cancelled: Callable[[], bool] | None = None, paused: Callable[[], bool] | None = None) -> Path | None:
    """Downloads the addon's source into `forge_dir/extensions/<key>/`. Forge needs a restart afterwards to pick
    it up (the same as installing an extension by hand). None means `paused` said stop partway through the
    download: the partial .zip.part is kept in extensions/ and a later call resumes it."""
    addon = ADDONS[key]
    extensions_dir = Path(forge_dir) / "extensions"
    dest = extensions_dir / key
    if (dest / "scripts").is_dir() or (dest / "install.py").is_file():
        return dest  # already there
    extensions_dir.mkdir(parents=True, exist_ok=True)
    archive = extensions_dir / f"{key}.zip"
    url = f"https://github.com/{addon.repo}/archive/refs/heads/{addon.branch}.zip"
    http.download(url, archive, progress=progress, cancelled=cancelled, paused=paused)
    if not archive.exists():
        return None  # stopped by `paused`, not finished: the .zip.part is kept for the next call to resume
    try:
        _extract(archive, dest, addon.repo.split("/")[-1])
    finally:
        archive.unlink(missing_ok=True)
    return dest


def _extract(archive: Path, dest: Path, repo_name: str) -> None:
    with zipfile.ZipFile(archive) as zf:
        zf.extractall(dest.parent)
    roots = [p for p in dest.parent.iterdir() if p.is_dir() and p.name.lower().startswith(repo_name.lower() + "-")]
    if not roots:
        raise AddonError(f"the archive did not contain a {repo_name} folder")
    if dest.exists():
        shutil.rmtree(dest)
    roots[0].rename(dest)
