"""Training your own LoRA from a handful of arts: builds a kohya-ss (sd-scripts) dataset from captioned images and runs its
training script as a subprocess. AniHUB does not train anything itself (that needs PyTorch, xformers, a CUDA build...): it drives
sd-scripts the same way it drives Forge and Suwayomi -- an external program the user points it at, in Settings.

sd-scripts: https://github.com/kohya-ss/sd-scripts -- its own folder with its own Python (a venv with torch et al.), a plain git
clone with `pip install -r requirements.txt` (and the accelerate config it asks for once) is enough; no GUI needed."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
NEW_GROUP = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)

SD15_SCRIPT = "train_network.py"
SDXL_SCRIPT = "sdxl_train_network.py"
IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".bmp")

DEFAULT_TRAIN = {
    "resolution": 1024, "network_dim": 32, "network_alpha": 16, "learning_rate": 1e-4, "epochs": 10, "batch_size": 2,
    "repeats": 10, "save_every_n_epochs": 0, "seed": 42, "mixed_precision": "fp16",
}


# --- is this folder really sd-scripts, and which Python runs it -----------------------------------------------------------------

def find_script(sd_scripts_dir: Path, sdxl: bool) -> Path | None:
    name = SDXL_SCRIPT if sdxl else SD15_SCRIPT
    path = sd_scripts_dir / name
    return path if path.is_file() else None


def find_python(sd_scripts_dir: Path) -> Path | None:
    """sd-scripts needs its OWN Python (a venv with torch/xformers/etc.): AniHUB's own interpreter has none of that."""
    for rel in ("venv/Scripts/python.exe", ".venv/Scripts/python.exe", "venv/bin/python", ".venv/bin/python"):
        candidate = sd_scripts_dir / rel
        if candidate.is_file():
            return candidate
    return None


def check_install(sd_scripts_dir: Path) -> str | None:
    """Error message, or None when the folder looks usable (has either training script and a venv Python)."""
    if not sd_scripts_dir.is_dir():
        return "err.train.no_folder"
    if find_script(sd_scripts_dir, True) is None and find_script(sd_scripts_dir, False) is None:
        return "err.train.no_script"
    if find_python(sd_scripts_dir) is None:
        return "err.train.no_venv"
    return None


CHECKPOINT_EXTS = (".safetensors", ".ckpt")


def list_checkpoints(cfg) -> list[Path]:
    """Checkpoints already installed for Forge (`<forge.path>/models/Stable-diffusion`): trains from the same files
    Forge draws with, nothing is downloaded separately."""
    forge = cfg.get("forge.path") or ""
    folder = Path(forge) / "models" / "Stable-diffusion" if forge else None
    if not folder or not folder.is_dir():
        return []
    return sorted((p for p in folder.rglob("*") if p.suffix.lower() in CHECKPOINT_EXTS and p.is_file()),
                  key=lambda p: p.stem.lower())


# --- the dataset: images + captions in the layout sd-scripts expects --------------------------------------------------------------

BAD_FS_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def sanitize_name(name: str) -> str:
    """A LoRA name turned into a safe file/folder name: the same rule is used for the dataset folder and the trained
    file's --output_name, so the UI can predict the finished .safetensors' path before training even starts."""
    return BAD_FS_CHARS.sub("_", name).strip(" .") or "lora"


def caption_text(trigger: str, body: str) -> str:
    """The trigger word(s) always come first, then the rest of the caption; no dangling comma either way."""
    parts = [p.strip() for p in (trigger, body) if p and p.strip()]
    return ", ".join(parts)


def build_dataset(images: list[tuple[Path, str]], dest: Path, name: str, repeats: int) -> Path:
    """`dest/img/<repeats>_<name>/0001.ext` + a same-named `.txt` caption per image (the kohya-ss folder convention: the
    leading number is how many times each image is shown per epoch). Returns the `img` folder (sd-scripts' train_data_dir).
    Existing contents of that one subfolder are replaced, so training again after editing captions does not pile up old files."""
    safe = sanitize_name(name)
    folder = dest / "img" / f"{max(1, int(repeats))}_{safe}"
    if folder.is_dir():
        shutil.rmtree(folder)
    folder.mkdir(parents=True, exist_ok=True)
    for i, (path, caption) in enumerate(images, 1):
        ext = path.suffix.lower() if path.suffix.lower() in IMAGE_EXTS else ".png"
        target = folder / f"{i:04d}{ext}"
        shutil.copyfile(path, target)
        target.with_suffix(".txt").write_text(caption, encoding="utf-8")
    return folder.parent


# --- the training command -----------------------------------------------------------------------------------------------------

@dataclass
class TrainConfig:
    name: str                      # the output file's name (without .safetensors)
    trigger: str = ""              # activation word(s), written first in every caption
    base_model: str = ""           # checkpoint to train from (the same file Forge uses)
    sdxl: bool = True              # WAI-Illustrious and most current anime checkpoints are SDXL-based
    resolution: int = DEFAULT_TRAIN["resolution"]
    network_dim: int = DEFAULT_TRAIN["network_dim"]         # LoRA rank: higher = more detail, bigger file, more VRAM
    network_alpha: int = DEFAULT_TRAIN["network_alpha"]
    learning_rate: float = DEFAULT_TRAIN["learning_rate"]
    epochs: int = DEFAULT_TRAIN["epochs"]
    batch_size: int = DEFAULT_TRAIN["batch_size"]
    repeats: int = DEFAULT_TRAIN["repeats"]
    save_every_n_epochs: int = DEFAULT_TRAIN["save_every_n_epochs"]     # 0 = only the final file
    seed: int = DEFAULT_TRAIN["seed"]
    mixed_precision: str = DEFAULT_TRAIN["mixed_precision"]
    negative: str = ""             # not used by training itself; carried through to the finished LoRA's card
    template: str = ""             # how the finished LoRA is written into a prompt; "" = services.lora.DEFAULT_TEMPLATE


def build_command(python_exe: Path, script: Path, cfg: TrainConfig, train_data_dir: Path, output_dir: Path) -> list[str]:
    args = [str(python_exe), str(script),
            "--pretrained_model_name_or_path", cfg.base_model,
            "--train_data_dir", str(train_data_dir),
            "--output_dir", str(output_dir),
            "--output_name", sanitize_name(cfg.name),
            "--resolution", f"{cfg.resolution},{cfg.resolution}",
            "--network_module", "networks.lora",
            "--network_dim", str(cfg.network_dim),
            "--network_alpha", str(cfg.network_alpha),
            "--learning_rate", str(cfg.learning_rate),
            "--max_train_epochs", str(cfg.epochs),
            "--train_batch_size", str(cfg.batch_size),
            "--seed", str(cfg.seed),
            "--mixed_precision", cfg.mixed_precision,
            "--save_precision", cfg.mixed_precision,
            "--save_model_as", "safetensors",
            "--cache_latents",
            "--gradient_checkpointing",
            "--xformers",
            "--lr_scheduler", "cosine_with_restarts",
            "--optimizer_type", "AdamW8bit"]
    if cfg.save_every_n_epochs > 0:
        args += ["--save_every_n_epochs", str(cfg.save_every_n_epochs)]
    else:
        args += ["--save_last_n_epochs", "1"]
    return args


# --- running it, watching its log ------------------------------------------------------------------------------------------------

PROGRESS_RE = re.compile(r"^\s*steps:\s*(\d+)%\|.*?\|\s*(\d+)/(\d+)\s*\[([^,\]]*)(?:,\s*([^\]]*))?\]", re.M)
EPOCH_RE = re.compile(r"epoch\s+(\d+)/(\d+)", re.I)


def parse_progress(log_tail: str) -> dict:
    """The last progress line kohya-ss prints (a tqdm bar on `steps:`), read from the tail of the log. {} once nothing has
    printed yet; `frac` 0..1, `step`/`total_steps` the current bar, `epoch`/`total_epochs` when seen, `rate` kohya's own text
    (e.g. "1.05it/s, loss=0.0821")."""
    matches = list(PROGRESS_RE.finditer(log_tail))
    if not matches:
        return {}
    m = matches[-1]
    pct, step, total = int(m.group(1)), int(m.group(2)), int(m.group(3))
    out = {"frac": pct / 100, "step": step, "total_steps": total, "rate": (m.group(5) or "").strip()}
    epochs = list(EPOCH_RE.finditer(log_tail))
    if epochs:
        out["epoch"], out["total_epochs"] = int(epochs[-1].group(1)), int(epochs[-1].group(2))
    return out


class Trainer:
    """One training run. `state`: idle -> running -> done | failed | cancelled. Call from the GUI thread; `start` returns at
    once, the process itself is watched from a background thread."""

    def __init__(self, log_file: Path):
        self.log_file = log_file
        self.proc: subprocess.Popen | None = None
        self.state = "idle"
        self.error = ""
        self._lock = threading.Lock()

    def start(self, cmd: list[str], cwd: Path, env: dict | None = None) -> None:
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
        full_env = {**os.environ, "PYTHONUNBUFFERED": "1", **(env or {})}
        with self.log_file.open("wb") as fh:
            fh.write((" ".join(cmd) + "\r\n\r\n").encode("utf-8", errors="replace"))
        log_fh = self.log_file.open("ab")
        try:
            self.proc = subprocess.Popen(cmd, cwd=str(cwd), stdin=subprocess.DEVNULL, stdout=log_fh, stderr=subprocess.STDOUT,
                                         env=full_env, creationflags=NO_WINDOW | NEW_GROUP)
        except OSError as exc:
            log_fh.close()
            self.state, self.error = "failed", str(exc)
            return
        self.state = "running"
        threading.Thread(target=self._watch, args=(log_fh,), daemon=True).start()

    def _watch(self, log_fh) -> None:
        proc = self.proc
        code = proc.wait() if proc else 1
        log_fh.close()
        with self._lock:
            if self.state == "cancelled":
                return
            self.state = "done" if code == 0 else "failed"
            if code != 0:
                self.error = f"exit code {code}"

    def cancel(self) -> None:
        with self._lock:
            proc, self.state = self.proc, "cancelled"
        if proc is not None and proc.poll() is None:
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True, creationflags=NO_WINDOW)

    def log_tail(self, chars: int = 8000) -> str:
        try:
            with self.log_file.open("rb") as fh:
                fh.seek(0, os.SEEK_END)
                size = fh.tell()
                fh.seek(max(0, size - chars))
                return fh.read().decode("utf-8", errors="replace")
        except OSError:
            return ""

    def progress(self) -> dict:
        return parse_progress(self.log_tail())
