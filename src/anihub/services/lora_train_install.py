"""Installing sd-scripts (kohya-ss) itself: download its source, build its own Python venv, and install PyTorch (matched to
the NVIDIA driver's CUDA version) plus its own requirements -- automating the steps from its own Windows install guide
(https://github.com/kohya-ss/sd-scripts#windows-installation). Runs as ordinary subprocesses AniHUB drives and watches, the
same way Forge's own install (forge_install.py) and training itself (lora_train.py) do."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
import zipfile
from pathlib import Path
from typing import Callable

from anihub.net.http import HttpClient, HttpError
from anihub.services import procsuspend
from anihub.services.procservice import NEW_GROUP, NO_WINDOW

REPO_ZIP_URL = "https://github.com/kohya-ss/sd-scripts/archive/refs/heads/main.zip"
NEED_FREE_GB = 12.0                          # source + venv + torch wheels
MIN_PY, MAX_PY = (3, 10), (3, 12)            # sd-scripts' own documented range (3.10 required, 3.11/3.12 "will work")

# driver CUDA version -> PyTorch wheel index tag, highest first. No exact torch/torchvision version is pinned here on
# purpose: an exact pin (what this used to do) goes stale the moment PyTorch stops publishing wheels for it under a
# given CUDA tag -- cu121, for one, is frozen at torch 2.5.1, already below sd-scripts' own stated 2.6.0 minimum, and
# pinning to 2.6.0 there made every install fail outright. `install()` instead asks pip for "torch>=2.6.0" and an
# unpinned torchvision, so it keeps resolving to whatever that channel's actual latest is.
MIN_TORCH = "2.6.0"                    # sd-scripts' own stated minimum
CUDA_TAGS = [(12.9, "cu129"), (12.8, "cu128"), (12.6, "cu126"), (12.4, "cu124"), (11.8, "cu118")]
DEFAULT_CUDA_TAG = "cu124"             # the driver's CUDA version could not be read: sd-scripts' own documented default


class InstallError(Exception):
    """User-presentable error."""


def driver_cuda_version() -> float | None:
    """The CUDA version an installed NVIDIA driver supports, read from `nvidia-smi`'s own header line. Older drivers
    print "CUDA Version: 12.8"; newer ones (seen on a real RTX 50-series/Blackwell machine) print "CUDA UMD Version:
    13.4" instead -- matching only the former silently fell back to a default torch build with no compiled kernels
    for that GPU's architecture at all ("CUDA error: no kernel image is available for execution on the device")."""
    exe = shutil.which("nvidia-smi")
    if not exe:
        return None
    try:
        out = subprocess.run([exe], capture_output=True, text=True, timeout=10, creationflags=NO_WINDOW).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    m = re.search(r"CUDA (?:UMD )?Version:\s*([\d.]+)", out)
    return float(m.group(1)) if m else None


def pick_torch(cuda_version: float | None) -> str:
    """The PyTorch wheel index tag (e.g. "cu124") to install from."""
    if cuda_version is None:
        return DEFAULT_CUDA_TAG
    for needs, tag in CUDA_TAGS:
        if cuda_version >= needs:
            return tag
    return DEFAULT_CUDA_TAG


def find_system_python() -> list[str] | None:
    """The command prefix for a Python sd-scripts can build its own venv from (3.10-3.12). AniHUB's own bundled interpreter
    is never offered here: reusing it would mix a heavy ML stack (torch et al.) into AniHUB's own runtime."""
    candidates: list[list[str]] = []
    launcher = shutil.which("py")
    if launcher:
        candidates += [[launcher, f"-3.{minor}"] for minor in (11, 10, 12)]
    for name in ("python3.11", "python3.10", "python3.12", "python3", "python"):
        found = shutil.which(name)
        if found:
            candidates.append([found])
    for cmd in candidates:
        try:
            out = subprocess.run(cmd + ["--version"], capture_output=True, text=True, timeout=10, creationflags=NO_WINDOW)
        except (OSError, subprocess.SubprocessError):
            continue
        m = re.search(r"Python (\d+)\.(\d+)", out.stdout + out.stderr)
        if m and MIN_PY <= (int(m.group(1)), int(m.group(2))) <= MAX_PY:
            return cmd
    return None


def _run_step(cmd: list[str], cwd: Path, log_path: Path, cancelled: Callable[[], bool] | None,
             paused: Callable[[], bool] | None = None) -> None:
    """One subprocess step of the install, its output appended to the shared log; polls `cancelled` so a slow pip install
    can still be stopped (the same polling loop forge_install.extract() uses, for the same reason). `paused`, if given,
    is polled the same way: while it says yes, the whole step (and any child of its own -- see procsuspend) is kept
    suspended in place, and this call simply does not return until it says no again."""
    with log_path.open("ab") as log:
        log.write((" ".join(cmd) + "\r\n").encode("utf-8", errors="replace"))
        log.flush()
        proc = subprocess.Popen(cmd, cwd=str(cwd), stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                                env={**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"},
                                creationflags=NO_WINDOW | NEW_GROUP)
        watch: procsuspend.Suspend | None = None
        while proc.poll() is None:
            if cancelled and cancelled():
                if watch is not None:
                    watch.stop()
                subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True, creationflags=NO_WINDOW)
                raise InstallError("cancelled")
            if paused and paused():
                if watch is None:
                    watch = procsuspend.Suspend(proc.pid)
            elif watch is not None:
                watch.stop()
                watch = None
            try:
                proc.wait(timeout=0.5)
            except subprocess.TimeoutExpired:
                pass
        if watch is not None:
            watch.stop()
        code = proc.returncode
    if code != 0:
        raise InstallError(f"{Path(cmd[0]).name} exited with {code} (see {log_path.name})")


def _extract(archive: Path, dest: Path) -> None:
    """The zip holds one top-level `sd-scripts-<branch>/` folder; its contents are moved up so `dest` itself is the
    sd-scripts folder AniHUB expects (what lora_train.py's find_script()/find_python() look inside)."""
    with zipfile.ZipFile(archive) as zf:
        zf.extractall(dest)
    roots = [p for p in dest.iterdir() if p.is_dir() and p.name.lower().startswith("sd-scripts")]
    if not roots:
        raise InstallError("the archive did not contain a sd-scripts folder")
    root = roots[0]
    for item in root.iterdir():
        target = dest / item.name
        if target.exists():
            shutil.rmtree(target) if target.is_dir() else target.unlink()
        shutil.move(str(item), str(target))
    root.rmdir()


def install(http: HttpClient, dest_dir: Path, progress: Callable[[str, int, int], None] | None = None,
           cancelled: Callable[[], bool] | None = None, paused: Callable[[], bool] | None = None) -> Path:
    """Downloads sd-scripts' source, builds its own venv, installs PyTorch (matched to the driver) and its requirements.
    Returns `dest_dir` (what to store as lora_train.sd_scripts_path). progress(stage, done, total). `paused`, if given,
    is polled throughout: this call simply blocks (never returns early, unlike a plain download) for as long as it
    says yes, so pausing partway through any step -- download or subprocess -- behaves the same way everywhere."""
    def report(stage: str, done: int = 0, total: int = 0) -> None:
        if progress:
            progress(stage, done, total)

    def check_cancel() -> None:
        if cancelled and cancelled():
            raise InstallError("cancelled")

    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    log_path = dest_dir / "install.log"

    report("preflight")
    free_gb = shutil.disk_usage(dest_dir).free / 1024**3
    if free_gb < NEED_FREE_GB:
        raise InstallError(f"not enough free disk space: {free_gb:.1f} GB (need about {NEED_FREE_GB:.0f} GB)")
    python_cmd = find_system_python()
    if python_cmd is None:
        raise InstallError("no suitable Python found (need 3.10-3.12 on PATH as 'py' or 'python' -- install one from "
                           "python.org, then try again)")
    check_cancel()

    report("download")
    archive = dest_dir / "sd-scripts.zip"
    try:
        while True:
            http.download(REPO_ZIP_URL, archive, progress=lambda d, t: report("download", d, t),
                          cancelled=cancelled, paused=paused)
            if archive.exists():
                break
            check_cancel()  # stopped because `paused` said so, not because cancelled -- wait it out, then retry
            while paused and paused():
                time.sleep(0.5)
    except HttpError as exc:
        raise InstallError(str(exc)) from exc
    check_cancel()

    report("extract")
    try:
        _extract(archive, dest_dir)
    finally:
        archive.unlink(missing_ok=True)
    check_cancel()

    venv_dir = dest_dir / "venv"
    report("venv")
    _run_step(python_cmd + ["-m", "venv", str(venv_dir)], dest_dir, log_path, cancelled, paused)
    venv_python = venv_dir / "Scripts" / "python.exe"
    check_cancel()

    report("pip")
    _run_step([str(venv_python), "-m", "pip", "install", "--upgrade", "pip"], dest_dir, log_path, cancelled, paused)
    check_cancel()

    report("torch")
    tag = pick_torch(driver_cuda_version())
    _run_step([str(venv_python), "-m", "pip", "install", f"torch>={MIN_TORCH}", "torchvision",
              "--index-url", f"https://download.pytorch.org/whl/{tag}"], dest_dir, log_path, cancelled, paused)
    check_cancel()

    report("requirements")
    _run_step([str(venv_python), "-m", "pip", "install", "--upgrade", "-r", "requirements.txt"], dest_dir, log_path, cancelled, paused)
    check_cancel()

    report("accelerate")
    try:
        _run_step([str(venv_python), "-m", "accelerate", "config", "default", "--mixed_precision", "fp16"],
                  dest_dir, log_path, cancelled, paused)
    except InstallError:
        pass          # best-effort: the training scripts run fine without a config too; "accelerate config" by hand still works

    report("done")
    return dest_dir
