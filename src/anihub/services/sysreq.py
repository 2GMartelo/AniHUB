"""System requirement checks: Java (Suwayomi), NVIDIA VRAM (Stable Diffusion), free disk space."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0


@dataclass
class Check:
    ok: bool
    detail: str = ""
    value: float = 0.0  # GB for disk / VRAM


def _run(cmd: list[str]) -> str | None:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=10, creationflags=_NO_WINDOW)
    except (OSError, subprocess.SubprocessError):
        return None
    return (proc.stdout + proc.stderr).strip()


def _find_java() -> str | None:
    found = shutil.which("java")
    if found:
        return found
    home = os.environ.get("JAVA_HOME")
    if home and (Path(home) / "bin" / "java.exe").exists():
        return str(Path(home) / "bin" / "java.exe")
    for base in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)")):
        if not base:
            continue
        for vendor in ("Java", "Eclipse Adoptium", "Microsoft", "Amazon Corretto", "Zulu"):
            for exe in Path(base, vendor).glob("*/bin/java.exe"):
                return str(exe)
    return None


def check_java() -> Check:
    exe = _find_java()
    if not exe:
        return Check(False)
    out = _run([exe, "-version"]) or ""
    first = out.splitlines()[0] if out else exe
    return Check(True, first)


def check_gpu() -> Check:
    exe = shutil.which("nvidia-smi")
    if not exe:
        return Check(False)
    out = _run([exe, "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"])
    if not out:
        return Check(False)
    gpus, best = [], 0.0
    for line in out.splitlines():
        name, _, mem = line.rpartition(",")
        try:
            gb = float(mem.strip()) / 1024
        except ValueError:
            continue
        gpus.append(f"{name.strip()} ({gb:.0f} GB)")
        best = max(best, gb)
    return Check(best > 0, "; ".join(gpus), best)


def check_disk(path: str | Path) -> Check:
    p = Path(path) if path else Path.home()
    while not p.exists() and p != p.parent:
        p = p.parent
    free_gb = shutil.disk_usage(p).free / 1024**3
    return Check(free_gb >= 20, "", free_gb)


# --- Stable Diffusion Forge: does this computer suit it? ------------------------------------------------------------------

MIN_VRAM_GB = 4.0            # below this Forge does not run at a usable speed (SD 1.5 needs about 4 GB)
GOOD_VRAM_GB = 6.0
MIN_RAM_GB = 8.0
GOOD_RAM_GB = 16.0
MIN_DISK_GB = 15.0           # the one-click package unpacks to several GB, checkpoints and outputs come on top


def total_ram_gb() -> float:
    """Installed physical memory in GB (0 when it cannot be read)."""
    if sys.platform != "win32":
        try:
            return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 1024**3
        except (ValueError, OSError, AttributeError):
            return 0.0
    import ctypes

    class MemoryStatus(ctypes.Structure):
        _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong), ("total_phys", ctypes.c_ulonglong),
                    ("avail_phys", ctypes.c_ulonglong), ("total_page", ctypes.c_ulonglong), ("avail_page", ctypes.c_ulonglong),
                    ("total_virtual", ctypes.c_ulonglong), ("avail_virtual", ctypes.c_ulonglong), ("ext", ctypes.c_ulonglong)]

    status = MemoryStatus()
    status.length = ctypes.sizeof(MemoryStatus)
    try:
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
    except (OSError, AttributeError):
        return 0.0
    return status.total_phys / 1024**3


@dataclass
class ForgeAssessment:
    suitable: bool
    level: str                       # "ok" | "low" (runs, but slowly or with limits) | "no"
    gpu: str = ""
    vram_gb: float = 0.0
    ram_gb: float = 0.0
    disk_gb: float = 0.0
    problems: tuple[str, ...] = ()   # why not / what is weak: sys.forge.* i18n keys


def judge_forge(gpu: str, vram_gb: float, ram_gb: float, disk_gb: float) -> ForgeAssessment:
    """The verdict from the measured numbers (pure, so it can be tested). Needs an NVIDIA GPU (CUDA) with enough VRAM and enough
    RAM; little disk space or a weak-but-working setup only lowers the level."""
    problems: list[str] = []
    fatal = False
    if vram_gb <= 0:
        problems.append("sys.forge.no_gpu")
        fatal = True
    elif vram_gb < MIN_VRAM_GB:
        problems.append("sys.forge.small_gpu")
        fatal = True
    elif vram_gb < GOOD_VRAM_GB:
        problems.append("sys.forge.weak_gpu")
    if ram_gb and ram_gb < MIN_RAM_GB:
        problems.append("sys.forge.small_ram")
        fatal = True
    elif ram_gb and ram_gb < GOOD_RAM_GB:
        problems.append("sys.forge.weak_ram")
    if disk_gb < MIN_DISK_GB:
        problems.append("sys.forge.low_disk")
    level = "no" if fatal else ("low" if problems else "ok")
    return ForgeAssessment(not fatal, level, gpu, vram_gb, ram_gb, disk_gb, tuple(problems))


def assess_forge(install_path: str | Path = "") -> ForgeAssessment:
    gpu = check_gpu()
    disk = check_disk(install_path)
    return judge_forge(gpu.detail if gpu.ok else "", gpu.value if gpu.ok else 0.0, total_ram_gb(), disk.value)
