"""ComfyUI-See-through integration (jtydhr88/ComfyUI-See-through, MIT; wraps the see-through research project by
shitagaki-lab): turns one anime illustration into a layered PSD -- Stage 3 of ТЗ_rasshirenie_prilozheniya.md.

Node class names, their inputs/outputs and the SavePSD output shape below are taken from the plugin's own nodes.py
(github.com/jtydhr88/ComfyUI-See-through) rather than guessed.

Nothing here calls the plugin's "Download PSD" button: that only runs client-side JS (ag-psd) in ComfyUI's own web
page, which an API-only caller like AniHUB never opens. Instead, `collect_output()` reads the layer PNGs + a JSON
sidecar the SavePSD node itself writes straight into ComfyUI's output folder (both processes run on the same
machine, so no /view round trip is needed either) and `run()` reassembles them into a real PSD itself, via
services/psd_writer.py.

VRAM (confirmed live on this project's own RTX 5070, 12 GB): the plugin's own README benchmark shows ~14 GB
*reserved* for LayerDiff alone at the default settings and resolution=1280 -- does not fit. `group_offload=True`
brings reserved VRAM to ~7.3 GB total (LayerDiff + Marigold), matching a real run (peak 7.47 GB, 25:47 wall clock,
vs. the README's 138s without it -- the 2-3x slowdown is real too); SeeThroughSettings defaults it off, since a
caller building a workflow for a card known to have more headroom has no reason to pay the speed cost. `run()`'s
`scheduler` parameter is services/gpu_scheduler.py's GpuScheduler, the same instance sd_queue.py's QueueController
uses, so Forge and a See-through job never run at once on a shared GPU."""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np
from PySide6.QtGui import QImage

from anihub.services.comfyui import ComfyApi, run_workflow
from anihub.services.gpu_scheduler import GpuScheduler
from anihub.services.psd_writer import PsdLayer, write_psd

# ComfyUI-See-through's own node class names (nodes.py NODE_CLASS_MAPPINGS) -- named constants so a typo shows up
# as an import-time NameError instead of a silent "unknown node type" from ComfyUI at submit time.
LOAD_LAYERDIFF = "SeeThrough_LoadLayerDiffModel"
LOAD_DEPTH = "SeeThrough_LoadDepthModel"
GENERATE_LAYERS = "SeeThrough_GenerateLayers"
GENERATE_DEPTH = "SeeThrough_GenerateDepth"
POST_PROCESS = "SeeThrough_PostProcess"
SAVE_PSD = "SeeThrough_SavePSD"
REQUIRED_NODES = (LOAD_LAYERDIFF, LOAD_DEPTH, GENERATE_LAYERS, GENERATE_DEPTH, POST_PROCESS, SAVE_PSD)

# HuggingFace repos the plugin downloads these from automatically on first use (see its README's Models table).
DEFAULT_LAYERDIFF_MODEL = "layerdifforg/seethroughv0.0.2_layerdiff3d"
DEFAULT_DEPTH_MODEL = "layerdifforg/seethroughv0.0.1_marigold"


class SeeThroughError(Exception):
    """User-presentable See-through problem (missing custom node, unparsable output, ...)."""


@dataclass
class SeeThroughSettings:
    resolution: int = 1280          # plugin default; the "recommended" example workflow
    steps: int = 30
    tblr_split: bool = True         # split eyes/ears/handwear into left/right
    use_lama: bool = True           # better hair front/back split; falls back to OpenCV inpainting if unavailable
    group_offload: bool = False     # see module docstring -- turn on for a 10-12 GB card
    resolution_depth: int = -1      # -1 = same as `resolution`
    seed: int = 42
    layerdiff_model: str = DEFAULT_LAYERDIFF_MODEL
    depth_model: str = DEFAULT_DEPTH_MODEL


def is_installed(api: ComfyApi) -> bool:
    """Whether the See-through custom-node pack is actually loaded by the running ComfyUI (not just that ComfyUI
    itself is up) -- the equivalent of services/addons.py's Forge-side installed-addon checks."""
    try:
        info = api.object_info()
    except Exception:  # noqa: BLE001 - ComfyUI down/unreachable counts as "not installed" here
        return False
    return all(node in info for node in REQUIRED_NODES)


def build_workflow(image_name: str, filename_prefix: str, settings: SeeThroughSettings | None = None) -> dict:
    """The API-format graph for the plugin's own "basic" example workflow (workflows/seethrough-basic.json):
    LoadImage -> the two model loaders -> Generate Layers -> Generate Depth -> Post Process -> Save PSD.

    `image_name` is a filename already sitting in ComfyUI's input/ folder (ComfyApi.upload_image's return value).
    `filename_prefix` should be unique per job: collect_output() globs by it to find this job's own files among
    however many previous runs are sitting in the output folder."""
    s = settings or SeeThroughSettings()
    return {
        "1": {"class_type": "LoadImage", "inputs": {"image": image_name}},
        "2": {"class_type": LOAD_LAYERDIFF, "inputs": {
            "model": s.layerdiff_model, "quant_mode": "none", "cache_tag_embeds": True,
            "group_offload": s.group_offload, "auto_download": True,
        }},
        "3": {"class_type": LOAD_DEPTH, "inputs": {
            "model": s.depth_model, "quant_mode": "none", "cache_tag_embeds": True,
            "group_offload": s.group_offload, "auto_download": True,
        }},
        "4": {"class_type": GENERATE_LAYERS, "inputs": {
            "image": ["1", 0], "layerdiff_model": ["2", 0], "seed": s.seed,
            "resolution": s.resolution, "num_inference_steps": s.steps,
        }},
        "5": {"class_type": GENERATE_DEPTH, "inputs": {
            "layers": ["4", 0], "depth_model": ["3", 0], "seed": s.seed,
            "resolution_depth": s.resolution_depth,
        }},
        "6": {"class_type": POST_PROCESS, "inputs": {
            "layers_depth": ["5", 0], "tblr_split": s.tblr_split, "use_lama": s.use_lama,
        }},
        "7": {"class_type": SAVE_PSD, "inputs": {"parts": ["6", 0], "filename_prefix": filename_prefix}},
    }


@dataclass
class SeeThroughResult:
    layers: list[PsdLayer]  # top-to-bottom (see psd_writer.PsdLayer) -- ready for write_psd
    width: int
    height: int
    tags: list[str] = field(default_factory=list)  # layer names, in the same order, for a UI checklist


def _load_rgba(path: Path) -> np.ndarray:
    """A PNG on disk -> an owned (H, W, 4) uint8 numpy array, straight alpha.

    `.copy()`, not `ascontiguousarray()`: when a row has no stride padding (common for RGBA8888 -- width % 4 == 0
    already makes each row a whole number of pixels), the sliced/reshaped view IS already contiguous, so
    ascontiguousarray returns it as-is instead of copying. That view still aliases the QImage's own pixel buffer, and
    once `image` goes out of scope here nothing else keeps the QImage alive, so the array ends up reading freed
    memory -- garbage pixels at best, a segfault at worst the first time something (pytoshop, in this module's own
    real-data test) actually reads every byte instead of just a corner pixel. `.copy()` always allocates fresh,
    independent memory, unconditionally."""
    image = QImage(str(path)).convertToFormat(QImage.Format.Format_RGBA8888)
    if image.isNull():
        raise SeeThroughError(f"could not read layer picture {path.name}")
    w, h = image.width(), image.height()
    stride = image.bytesPerLine()
    raw = np.frombuffer(image.constBits(), dtype=np.uint8, count=stride * h).reshape(h, stride)
    return raw[:, : w * 4].reshape(h, w, 4).copy()


def collect_output(output_dir: Path, filename_prefix: str) -> SeeThroughResult:
    """After run_workflow() finishes, load this job's own layers straight from ComfyUI's output folder. Raises
    SeeThroughError if the expected JSON sidecar is not there (the job's own filename_prefix was not found, or
    SeeThrough_SavePSD's own layer output was empty -- e.g. a picture with nothing recognisable in it)."""
    matches = sorted(output_dir.glob(f"{filename_prefix}_*_layers.json"))
    if not matches:
        raise SeeThroughError(f"no See-through output found for this job in {output_dir}")
    data = json.loads(matches[-1].read_text(encoding="utf-8"))
    entries = data.get("layers") or []
    if not entries:
        raise SeeThroughError("See-through found no layers in this picture")

    # The JSON lists layers back-to-front (SeeThrough_SavePSD sorts by depth_median, largest/farthest first); a PSD
    # wants them top-to-bottom (frontmost first) -- see psd_writer.PsdLayer.
    layers, tags = [], []
    for entry in reversed(entries):
        image = _load_rgba(output_dir / entry["filename"])
        layers.append(PsdLayer(name=entry["name"], image=image, x=int(entry["left"]), y=int(entry["top"])))
        tags.append(entry["name"])
    return SeeThroughResult(layers=layers, width=int(data["width"]), height=int(data["height"]), tags=tags)


def run(api: ComfyApi, output_dir: Path, image_path: Path, psd_path: Path,
       settings: SeeThroughSettings | None = None, on_progress: Callable[[dict], None] | None = None,
       should_stop: Callable[[], bool] | None = None, scheduler: GpuScheduler | None = None, gpu: int = 0,
       free_others: Callable[[], None] | None = None) -> SeeThroughResult:
    """Blocking end-to-end: upload `image_path`, run the decomposition, write the layered PSD to `psd_path`. Returns
    the same SeeThroughResult that was written, so a caller can also show the layer list without re-reading the PSD.

    `output_dir` is this ComfyUI's own output folder (ComfyManager.comfy_dir / "output" by default) -- collect_output
    reads the plugin's files straight from there, see the module docstring for why.

    `scheduler`, if given, is the same GpuScheduler instance sd_queue.py's QueueController uses: acquired for `gpu`
    (blocking -- call this off the GUI thread) before anything is submitted, and released once this job is done --
    every call releases its own slot immediately rather than holding it like Forge does between queued jobs, because
    See-through's own nodes already unload each stage's model back to CPU as they finish (seen live: "GenerateLayers
    offloaded to CPU", "Marigold offloaded to CPU"), so there is nothing left in VRAM worth holding the slot for.
    `free_others`, if given, is called right after the slot is acquired, before the workflow starts: the caller's own
    way of asking whichever *other* backend (Forge) might still be sitting on this GPU to unload its checkpoint --
    services/seethrough.py deliberately does not import forge.py itself to make that call directly."""
    if not is_installed(api):
        raise SeeThroughError("ComfyUI-See-through is not installed in this ComfyUI")
    owner = "comfyui"
    if scheduler is not None:
        scheduler.acquire(gpu, owner)
    try:
        if free_others is not None:
            free_others()
        image_name = api.upload_image(image_path)
        prefix = f"anihub_{uuid.uuid4().hex[:12]}"
        workflow = build_workflow(image_name, prefix, settings)
        run_workflow(api, workflow, on_progress=on_progress, should_stop=should_stop, poll_interval=1.0)
        result = collect_output(output_dir, prefix)
        write_psd(psd_path, result.layers, result.width, result.height)
        return result
    finally:
        if scheduler is not None:
            scheduler.release(gpu, owner)
