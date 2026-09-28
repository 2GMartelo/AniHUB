"""Download and unpack the official ComfyUI Windows portable build (a ~1.9 GB .7z with a bundled Python + CUDA
PyTorch, from the project's own GitHub release) -- mirrors services/forge_install.py.

Windows 10/11 ship `tar.exe` (bsdtar), which reads .7z archives, so no extra tool is needed. The archive unpacks into
a folder holding `ComfyUI/` (main.py) next to `python_embeded/` (the bundled interpreter) -- exactly the layout
services/comfyui.py's find_python() already looks for."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Callable

from anihub.net.http import HttpClient, HttpError
from anihub.services.procservice import NO_WINDOW

PORTABLE_URL = "https://github.com/comfyanonymous/ComfyUI/releases/latest/download/ComfyUI_windows_portable_nvidia.7z"
NEED_FREE_GB = 6.0


class ComfyInstallError(Exception):
    """User-presentable error."""


def tar_exe() -> str | None:
    """Windows' own bsdtar (the one that reads 7z); GNU tar from Git for Windows does not."""
    system = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "tar.exe"
    if system.exists():
        return str(system)
    return shutil.which("tar") if sys.platform != "win32" else None


def comfy_dir_of(folder: str | Path) -> Path | None:
    """What AniHUB stores as `comfyui.path`: the `ComfyUI` directory (holding main.py) next to `python_embeded/`.
    Accepts the extracted package folder, the `ComfyUI` folder itself, or a folder that holds the package one level
    down (the archive's own top-level folder, e.g. `ComfyUI_windows_portable`)."""
    p = Path(folder)
    if (p / "main.py").exists() and (p.parent / "python_embeded").exists():
        return p
    if p.is_dir():
        for candidate in sorted(c for c in p.iterdir() if c.is_dir()):
            sub = candidate / "ComfyUI"
            if (sub / "main.py").exists() and (candidate / "python_embeded").exists():
                return sub
    return None


def extract(archive: Path, dest: Path, cancelled: Callable[[], bool] | None = None) -> None:
    exe = tar_exe()
    if exe is None:
        raise ComfyInstallError("tar.exe was not found (Windows 10 1803 or newer is needed to unpack the .7z)")
    dest.mkdir(parents=True, exist_ok=True)
    proc = subprocess.Popen([exe, "-xf", str(archive), "-C", str(dest)], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            creationflags=NO_WINDOW)
    while proc.poll() is None:
        if cancelled and cancelled():
            proc.kill()
            raise ComfyInstallError("cancelled")
        try:
            proc.wait(timeout=0.5)
        except subprocess.TimeoutExpired:
            pass
    if proc.returncode != 0:
        raise ComfyInstallError((proc.stderr.read() or b"").decode("utf-8", "replace").strip()[:300]
                                or f"tar exited with {proc.returncode}")


def install(http: HttpClient, dest_dir: Path, progress: Callable[[str, int, int], None] | None = None,
           cancelled: Callable[[], bool] | None = None, paused: Callable[[], bool] | None = None) -> Path | None:
    """Download + unpack into `dest_dir`; returns the `ComfyUI` folder to store as comfyui.path. progress(stage,
    done, total). None means `paused` said stop: only the download itself can pause (extracting the archive cannot
    be safely resumed partway through, so once that starts a cancel is the only way out) -- the partial archive is
    kept via HttpClient.download's own .part file, and a later call resumes it."""
    def report(stage: str, done: int = 0, total: int = 0) -> None:
        if progress:
            progress(stage, done, total)

    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    free_gb = shutil.disk_usage(dest_dir).free / 1024**3
    if free_gb < NEED_FREE_GB:
        raise ComfyInstallError(f"not enough free disk space: {free_gb:.1f} GB (need about {NEED_FREE_GB:.0f} GB)")
    if tar_exe() is None:
        raise ComfyInstallError("tar.exe was not found (Windows 10 1803 or newer is needed to unpack the .7z)")
    archive = dest_dir / "ComfyUI_windows_portable_nvidia.7z"
    report("download")
    try:
        http.download(PORTABLE_URL, archive, progress=lambda d, t: report("download", d, t), cancelled=cancelled,
                      paused=paused)
    except HttpError as exc:
        raise ComfyInstallError(str(exc)) from exc
    if paused and paused():
        return None
    report("extract")
    try:
        extract(archive, dest_dir, cancelled)
    finally:
        archive.unlink(missing_ok=True)
    comfy_dir = comfy_dir_of(dest_dir)
    if comfy_dir is None:
        raise ComfyInstallError("the archive did not contain the expected ComfyUI/ + python_embeded/ layout")
    report("done")
    return comfy_dir
