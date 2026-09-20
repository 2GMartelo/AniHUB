"""Generation backends: the primary Forge plus optional extra instances of the same installation, each pinned to a
GPU and listening on its own port (multi-GPU, ТЗ 5.9 / 5.11)."""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

from anihub.core.config import Config
from anihub.services.forge import ForgeManager
from anihub.services.procservice import NO_WINDOW


def gpu_list() -> list[tuple[int, str, float]]:
    """(index, name, VRAM GB) of the NVIDIA GPUs; empty without nvidia-smi."""
    exe = shutil.which("nvidia-smi")
    if not exe:
        return []
    try:
        out = subprocess.run([exe, "--query-gpu=index,name,memory.total", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=10, creationflags=NO_WINDOW).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    gpus = []
    for line in out.strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) == 3 and parts[0].isdigit():
            try:
                gpus.append((int(parts[0]), parts[1], float(parts[2]) / 1024))
            except ValueError:
                pass
    return gpus


def _safe_name(name: str) -> str:
    return re.sub(r"[^\w-]", "_", name.strip()) or "backend"


def build_backends(cfg: Config, work_dir: Path) -> list[ForgeManager]:
    """[main, *extra]. Extra ones come from forge.backends: [{name, port, gpu, enabled}]; invalid or clashing
    entries (same port / name as another backend) are skipped instead of breaking startup."""
    main = ForgeManager(cfg, work_dir, "main")
    backends = [main]
    ports, names = {main.port}, {"main"}
    for entry in cfg.get("forge.backends", []) or []:
        try:
            name, port = _safe_name(str(entry["name"])), int(entry["port"])
        except (KeyError, TypeError, ValueError):
            continue
        if not entry.get("enabled", True) or port in ports or name in names or not 1024 <= port <= 65535:
            continue
        gpu = entry.get("gpu")
        backends.append(ForgeManager(cfg, work_dir, name, port=port, gpu=int(gpu) if gpu is not None else None,
                                     nowebui=True))
        ports.add(port)
        names.add(name)
    return backends
