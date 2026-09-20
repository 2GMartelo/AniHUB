"""Downloads and unpacks Suwayomi-Server (the Windows build ships its own JRE, so no Java install is needed)."""
from __future__ import annotations

import hashlib
import json
import shutil
import sys
import zipfile
from pathlib import Path
from typing import Callable

from anihub.net.http import HttpClient

RELEASES_API = "https://api.github.com/repos/Suwayomi/Suwayomi-Server/releases/latest"
ASSET_SUFFIX = {"win32": "windows-x64.zip", "linux": "linux-x64.tar.gz", "darwin": "macOS-x64.tar.gz"}


class InstallError(Exception):
    pass


def pick_assets(release: dict, platform: str = sys.platform) -> tuple[dict, dict | None]:
    """(server archive asset, checksums asset or None) for the platform."""
    suffix = ASSET_SUFFIX.get(platform)
    assets = release.get("assets", [])
    archive = next((a for a in assets if suffix and a["name"].endswith(suffix)), None)
    if archive is None:
        raise InstallError(f"No Suwayomi build for platform {platform!r}")
    if not archive["name"].endswith(".zip"):
        raise InstallError("Automatic install is implemented for Windows only")
    return archive, next((a for a in assets if a["name"] == "Checksums.sha256"), None)


def parse_checksums(text: str) -> dict[str, str]:
    result = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 2:
            result[parts[-1].lstrip("*")] = parts[0].lower()
    return result


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def installed_version(install_dir: Path) -> str | None:
    marker = install_dir / "version.json"
    try:
        return json.loads(marker.read_text(encoding="utf-8"))["version"]
    except (OSError, ValueError, KeyError):
        return None


def find_runtime(server_dir: Path) -> tuple[Path, Path] | None:
    """(java executable, server jar) inside the unpacked build. The bundled JRE is preferred; a system Java is
    only a fallback."""
    for jar in server_dir.rglob("Suwayomi-Server.jar"):
        bundled = jar.parent.parent / "jre" / "bin" / "java.exe"
        if bundled.exists():
            return bundled, jar
        system = shutil.which("java")
        if system:
            return Path(system), jar
    return None


def install(http: HttpClient, install_dir: Path, progress: Callable[[str, int, int], None] | None = None,
            cancelled: Callable[[], bool] | None = None) -> str:
    """Blocking. progress(stage, done, total). Returns the installed version tag."""
    def report(stage: str, done: int = 0, total: int = 0) -> None:
        if progress:
            progress(stage, done, total)

    report("release")
    release = http.get_json(RELEASES_API)
    archive, checksums = pick_assets(release)
    expected = None
    if checksums:
        text = http.get_bytes(checksums["browser_download_url"]).decode("utf-8", "replace")
        expected = parse_checksums(text).get(archive["name"])

    install_dir.mkdir(parents=True, exist_ok=True)
    zip_path = install_dir / archive["name"]
    try:
        http.download(archive["browser_download_url"], zip_path,
                      progress=lambda d, t: report("download", d, t or archive.get("size", 0)), cancelled=cancelled)
        report("verify")
        if expected and sha256_file(zip_path) != expected:
            raise InstallError("Checksum mismatch: the download is corrupted, try again")
        report("extract")
        staging = install_dir / "server.new"
        shutil.rmtree(staging, ignore_errors=True)
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(staging)
        target = install_dir / "server"
        shutil.rmtree(target, ignore_errors=True)
        staging.replace(target)
    finally:
        zip_path.unlink(missing_ok=True)
    version = release.get("tag_name", "unknown")
    (install_dir / "version.json").write_text(json.dumps({"version": version}), encoding="utf-8")
    report("done")
    return version
