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
