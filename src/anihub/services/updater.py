"""Updates through GitHub Releases (раздел 9): check, read the changelog, download and verify the installer, roll back to
an older release. Only the installer of a release published in the project's repository is ever downloaded."""
from __future__ import annotations

import hashlib
import logging
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from anihub import __version__
from anihub.core.config import Config
from anihub.net.http import HttpClient, HttpError

log = logging.getLogger(__name__)

DEFAULT_REPO = "2GMartelo/AniHUB"
API = "https://api.github.com/repos/{repo}/releases"
INSTALLER = re.compile(r"^AniHUB-Setup-[\w.\-]+\.exe$")
CHECK_EVERY_S = 24 * 3600


class UpdateError(Exception):
    pass


def parse_version(text: str) -> tuple[int, ...]:
    """'v0.3.0' -> (0, 3, 0). A suffix such as '-beta' sorts before the plain release (0, 4, 0, -1)."""
    m = re.match(r"^\s*v?(\d+(?:\.\d+)*)(.*)$", text or "")
    if not m:
        return (0,)
    numbers = tuple(int(x) for x in m.group(1).split("."))
    return numbers + ((-1,) if m.group(2).strip().startswith(("-", "+", "a", "b", "rc")) else ())


def is_newer(candidate: str, current: str) -> bool:
    a, b = parse_version(candidate), parse_version(current)
    width = max(len(a), len(b))
    pad = lambda v: v + (0,) * (width - len(v))  # noqa: E731
    return pad(a) > pad(b)


@dataclass
class Release:
    version: str
    name: str
    notes: str
    page: str
    published: str = ""
    prerelease: bool = False
    asset_name: str = ""
    asset_url: str = ""
    asset_size: int = 0
    sha256: str = ""                   # from GitHub's asset digest when it has one
    extra: dict = field(default_factory=dict)

    @property
    def installable(self) -> bool:
        return bool(self.asset_url)


def parse_release(raw: dict) -> Release:
    asset = next((a for a in raw.get("assets", []) if INSTALLER.match(a.get("name", "")) and a.get("state", "uploaded") == "uploaded"), None)
    digest = (asset or {}).get("digest") or ""
    return Release(
        version=str(raw.get("tag_name", "")).lstrip("v"), name=raw.get("name") or raw.get("tag_name", ""),
        notes=raw.get("body") or "", page=raw.get("html_url", ""), published=(raw.get("published_at") or "")[:10],
        prerelease=bool(raw.get("prerelease")), asset_name=(asset or {}).get("name", ""),
        asset_url=(asset or {}).get("browser_download_url", ""), asset_size=int((asset or {}).get("size") or 0),
        sha256=digest.split(":", 1)[1].lower() if digest.startswith("sha256:") else "")


class Updater:
    def __init__(self, http: HttpClient, cfg: Config, current: str = __version__):
        self.http, self.cfg, self.current = http, cfg, current

    @property
    def repo(self) -> str:
        return str(self.cfg.get("update.repo", DEFAULT_REPO) or DEFAULT_REPO)

    # --- asking GitHub ---------------------------------------------------------------------------------

    def releases(self, limit: int = 20) -> list[Release]:
        """Published releases, newest first (drafts never show up in this API call)."""
        try:
            data = self.http.get_json(API.format(repo=self.repo), params={"per_page": limit})
        except HttpError as exc:
            raise UpdateError(str(exc)) from exc
        if not isinstance(data, list):
            raise UpdateError("unexpected answer from GitHub")
        found = [parse_release(r) for r in data if not r.get("draft")]
        return sorted(found, key=lambda r: parse_version(r.version), reverse=True)

    def latest(self) -> Release | None:
        """The newest stable release that has an installer and is newer than this build; None when up to date."""
        for release in self.releases():
            if release.prerelease or not release.installable:
                continue
            return release if is_newer(release.version, self.current) else None
        return None

    def check(self, force: bool = False) -> Release | None:
        """Automatic check: at most once a day, never for a version the user skipped. Remembers when it ran."""
        if not force:
            if not self.cfg.get("update.auto", True):
                return None
            if time.time() - float(self.cfg.get("update.last_check", 0) or 0) < CHECK_EVERY_S:
                return None
        release = self.latest()
        self.cfg.set("update.last_check", time.time())
        if release is None:
            return None
        if not force and release.version == self.cfg.get("update.skipped", ""):
            return None
        return release

    def skip(self, release: Release) -> None:
        self.cfg.set("update.skipped", release.version)

    # --- getting the installer ---------------------------------------------------------------------------

    def download(self, release: Release, folder: Path, progress: Callable[[int, int], None] | None = None,
                 cancelled: Callable[[], bool] | None = None) -> Path:
        """Downloads the installer and checks size and SHA-256 (when GitHub published one). Returns its path."""
        if not release.installable:
            raise UpdateError("this release has no installer")
        if not release.asset_url.startswith("https://github.com/" + self.repo + "/"):
            raise UpdateError("the installer is not hosted in the project repository")
        folder.mkdir(parents=True, exist_ok=True)
        dest = folder / release.asset_name
        try:
            self.http.download(release.asset_url, dest, progress=progress, cancelled=cancelled)
        except HttpError as exc:
            raise UpdateError(str(exc)) from exc
        size = dest.stat().st_size
        if release.asset_size and size != release.asset_size:
            dest.unlink(missing_ok=True)
            raise UpdateError(f"incomplete download: {size} of {release.asset_size} bytes")
        if release.sha256:
            h = hashlib.sha256()
            with dest.open("rb") as fh:
                for chunk in iter(lambda: fh.read(1 << 20), b""):
                    h.update(chunk)
            if h.hexdigest() != release.sha256:
                dest.unlink(missing_ok=True)
                raise UpdateError("the installer does not match its published checksum")
        return dest

    @staticmethod
    def launch(installer: Path) -> None:
        """Starts the installer (it closes a running AniHUB itself); the caller quits the app right after."""
        os.startfile(str(installer))

    def cleanup(self, folder: Path, keep: int = 1) -> None:
        """Old downloaded installers are not needed once installed."""
        files = sorted(folder.glob("AniHUB-Setup-*.exe"), key=lambda p: p.stat().st_mtime, reverse=True) if folder.exists() else []
        for old in files[keep:]:
            old.unlink(missing_ok=True)
