"""Generation request building and result handling. Every generated image is written to disk right away;
only the ones the user picks are added to the library (ТЗ 5.4). Every image is also logged in the history (ТЗ 5.6)."""
from __future__ import annotations

import base64
import json
import re
import struct
import zlib
from dataclasses import dataclass, field, fields, replace
from datetime import datetime
from pathlib import Path
from typing import Callable

from anihub.services.forge import ForgeApi, ForgeError


@dataclass
class GenParams:
    prompt: str = ""
    negative_prompt: str = ""
    model: str = ""  # checkpoint title; empty = keep Forge's current one
    vae: str = ""    # extra module file (VAE / text encoder); empty = Forge's own choice
    clip_skip: int = 0  # 0 = keep Forge's setting
    sampler_name: str = "Euler a"
    scheduler: str = "Automatic"
    steps: int = 28
    cfg_scale: float = 6.0
    width: int = 832
    height: int = 1216
    seed: int = -1
    subseed: int = -1
    subseed_strength: float = 0.0  # > 0 blends in a second seed (variations)
    n_iter: int = 1       # batch count
    batch_size: int = 1
    enable_hr: bool = False        # hires fix (txt2img only)
    hr_scale: float = 1.5
    hr_upscaler: str = "Latent"
    hr_steps: int = 0              # 0 = same as steps
    hr_denoise: float = 0.4
    init_image: str = ""           # path of the source picture: set -> img2img instead of txt2img
    denoising_strength: float = 0.6  # img2img strength
    mask_image: str = ""           # inpaint: path of a mask (white = redraw); needs init_image
    mask_blur: int = 4
    inpaint_fill: int = 1          # what is under the mask at the start: 0 fill, 1 original, 2 latent noise, 3 latent nothing
    inpaint_only_masked: bool = True  # redraw only the masked area at full resolution (needs less VRAM, keeps detail)

    def to_payload(self) -> dict:
        payload = {
            "prompt": self.prompt, "negative_prompt": self.negative_prompt,
            "sampler_name": self.sampler_name, "scheduler": self.scheduler, "steps": self.steps,
            "cfg_scale": self.cfg_scale, "width": self.width, "height": self.height, "seed": self.seed,
            "n_iter": self.n_iter, "batch_size": self.batch_size,
            "save_images": False,  # the app writes files itself; avoids duplicates in Forge's outputs folder
            "send_images": True,
        }
        if self.subseed_strength > 0:
            payload["subseed"] = self.subseed
            payload["subseed_strength"] = self.subseed_strength
        if self.init_image:
            payload["init_images"] = [base64.b64encode(Path(self.init_image).read_bytes()).decode()]
            payload["denoising_strength"] = self.denoising_strength
            payload["resize_mode"] = 0  # just resize: width/height above are what the user set
            if self.mask_image:
                payload.update(
                    mask=base64.b64encode(Path(self.mask_image).read_bytes()).decode(), mask_blur=self.mask_blur,
                    inpainting_fill=self.inpaint_fill, inpaint_full_res=int(self.inpaint_only_masked),
                    inpaint_full_res_padding=32, inpainting_mask_invert=0)
        elif self.enable_hr:
            payload.update(enable_hr=True, hr_scale=self.hr_scale, hr_upscaler=self.hr_upscaler,
                           hr_second_pass_steps=self.hr_steps, denoising_strength=self.hr_denoise,
                           # Forge does `'Use same choices' not in hr_additional_modules`: the API default None crashes it
                           hr_additional_modules=["Use same choices"])
        override: dict = {}
        if self.model:
            override["sd_model_checkpoint"] = self.model
        if self.vae:
            override["forge_additional_modules"] = [self.vae]
        if self.clip_skip:
            override["CLIP_stop_at_last_layers"] = self.clip_skip
        if override:
            payload["override_settings"] = override
            payload["override_settings_restore_afterwards"] = False  # keep the model loaded between runs
        return payload

    def summary(self, limit: int = 60) -> str:
        text = " ".join(self.prompt.split())
        return (text[:limit] + "…") if len(text) > limit else text


def params_from_dict(data: dict) -> GenParams:
    """Tolerant loader for presets/history: unknown keys are ignored, missing ones keep their defaults."""
    known = {f.name for f in fields(GenParams)}
    return GenParams(**{k: v for k, v in data.items() if k in known})


@dataclass
class GenResult:
    path: Path
    seed: int
    meta: dict = field(default_factory=dict)


def fit_size(width: int, height: int, target_area: int = 1024 * 1024, multiple: int = 64, limit: int = 2048) -> tuple[int, int]:
    """Size for img2img from a source picture: keeps its aspect ratio at about `target_area` pixels,
    rounded to what SD models like (multiples of 64)."""
    if width <= 0 or height <= 0:
        return 832, 1216
    scale = (target_area / (width * height)) ** 0.5

    def snap(v: float) -> int:
        return min(limit, max(multiple, round(v / multiple) * multiple))

    return snap(width * scale), snap(height * scale)


def _unique(day_dir: Path, name: str, suffix: str) -> Path:
    path = day_dir / f"{name}{suffix}"
    n = 1
    while path.exists():
        n += 1
        path = day_dir / f"{name}_{n}{suffix}"
    return path


def _images_from_response(data: dict, out_dir: Path, meta_base: dict, fallback_seed: int) -> list[GenResult]:
    images = data.get("images") or []
    try:
        info = json.loads(data.get("info") or "{}")
    except ValueError:
        info = {}
    # With batches Forge may prepend a preview grid; index_of_first_image tells where real images start.
    first = int(info.get("index_of_first_image", 0) or 0)
    images = images[first:]
    if not images:
        raise ForgeError("Forge returned no images")
    seeds = info.get("all_seeds") or []
    infotexts = info.get("infotexts") or []
    day_dir = out_dir / datetime.now().strftime("%Y-%m-%d")
    day_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%H%M%S")
    results = []
    for i, b64 in enumerate(images):
        seed = int(seeds[i]) if i < len(seeds) else fallback_seed
        path = _unique(day_dir, f"{stamp}_{seed}_{i + 1}", ".png")
        path.write_bytes(base64.b64decode(b64))
        meta = {**meta_base, "seed": seed}
        if i + first < len(infotexts):  # infotexts align with the full image list, grid included
            meta["infotext"] = infotexts[i + first]
        results.append(GenResult(path, seed, meta))
    return results


def run_generation(api: ForgeApi, params: GenParams, out_dir: Path,
                    on_batch: Callable[[list[GenResult]], None] | None = None,
                    should_stop: Callable[[], bool] | None = None) -> list[GenResult]:
    """Blocking: call Forge (img2img when an init image is set), write every returned image under out_dir/<date>/
    and return them all.

    A batch count (`n_iter`) above 1 is sent as that many separate Forge calls of one each, instead of a single call
    for the whole batch: Forge's API only answers once the whole batch is done, so with one call nothing appears
    until every image in it has finished, even though Forge itself is generating them one at a time. `on_batch`
    (if given) is called with each call's own images right after they are written, so a caller can show them as
    they arrive. `should_stop` (if given) is checked between calls so a cancelled batch does not start another one
    (Forge is still asked to interrupt the in-flight call the normal way; this only stops the *next* one)."""
    n_iter = max(1, params.n_iter)
    meta_base = params.__dict__
    all_results: list[GenResult] = []
    for i in range(n_iter):
        if should_stop is not None and should_stop():
            break
        if i == 0:
            call_params = params
        else:
            seed = params.seed + i * params.batch_size if params.seed != -1 else -1
            call_params = replace(params, n_iter=1, seed=seed)
        payload = call_params.to_payload()
        payload["n_iter"] = 1
        data = api.img2img(payload) if params.init_image else api.txt2img(payload)  # img2img also covers inpaint (mask in payload)
        results = _images_from_response(data, out_dir, meta_base, call_params.seed)
        all_results.extend(results)
        if on_batch is not None:
            on_batch(results)
    return all_results


run_txt2img = run_generation  # original name


def run_upscale(api: ForgeApi, source: Path, upscaler: str, scale: float, out_dir: Path, meta: dict | None = None) -> GenResult:
    """Extras upscale of one picture (ТЗ 3.8): returns the new file next to the other generations."""
    payload = {"image": base64.b64encode(source.read_bytes()).decode(), "upscaling_resize": scale,
               "upscaler_1": upscaler, "resize_mode": 0}
    data = api.extra_single(payload)
    image = data.get("image")
    if not image:
        raise ForgeError("Forge returned no image")
    day_dir = out_dir / datetime.now().strftime("%Y-%m-%d")
    day_dir.mkdir(parents=True, exist_ok=True)
    path = _unique(day_dir, f"{source.stem}_x{scale:g}", ".png")
    path.write_bytes(base64.b64decode(image))
    result_meta = {**(meta or {}), "upscaled_from": source.name, "upscaler": upscaler, "upscale_factor": scale}
    return GenResult(path, int(result_meta.get("seed", -1) or -1), result_meta)


def record_history(db, root: Path, results: list[GenResult], backend: str = "main") -> None:
    """Log generated images (relative paths) with their parameters."""
    rows = []
    for r in results:
        try:
            rel = r.path.resolve().relative_to(root.resolve()).as_posix()
        except ValueError:
            rel = r.path.as_posix()
        rows.append({"path": rel, "seed": r.seed, "model": r.meta.get("model", ""), "prompt": r.meta.get("prompt", ""),
                     "negative": r.meta.get("negative_prompt", ""), "params": r.meta, "backend": backend})
    if rows:
        db.add_history(rows)


# --- reading parameters back from images (PNG info) ------------------------------------------------------

def read_png_text(path: Path) -> dict[str, str]:
    """tEXt / zTXt / iTXt chunks of a PNG (Forge stores the infotext under 'parameters'). No third-party library."""
    data = path.read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        return {}
    out: dict[str, str] = {}
    pos = 8
    while pos + 8 <= len(data):
        length, kind = struct.unpack(">I4s", data[pos:pos + 8])
        body = data[pos + 8:pos + 8 + length]
        pos += 12 + length
        try:
            if kind == b"tEXt":
                key, _, text = body.partition(b"\0")
                out[key.decode("latin-1")] = text.decode("utf-8", "replace")
            elif kind == b"zTXt":
                key, _, rest = body.partition(b"\0")
                out[key.decode("latin-1")] = zlib.decompress(rest[1:]).decode("utf-8", "replace")
            elif kind == b"iTXt":
                key, _, rest = body.partition(b"\0")
                flag, rest = rest[0], rest[2:]
                _lang, _, rest = rest.partition(b"\0")
                _trans, _, text = rest.partition(b"\0")
                out[key.decode("utf-8", "replace")] = (zlib.decompress(text) if flag else text).decode("utf-8", "replace")
        except (ValueError, zlib.error, IndexError):
            continue
        if kind == b"IEND":
            break
    return out


_INFO_PAIR = re.compile(r'\s*([\w ]+):\s*("(?:\\.|[^\\"])*"|[^,]*)(?:,|$)')


def parse_infotext(text: str) -> dict:
    """A1111/Forge 'parameters' text -> GenParams field values (only what it contains)."""
    lines = text.strip().splitlines()
    result: dict = {}
    settings_line = ""
    if lines and re.match(r"^Steps: ", lines[-1]):
        settings_line = lines.pop()
    body = "\n".join(lines)
    prompt, sep, negative = body.partition("\nNegative prompt:")
    if not sep and body.startswith("Negative prompt:"):
        prompt, negative = "", body[len("Negative prompt:"):]
    result["prompt"] = prompt.strip()
    if negative:
        result["negative_prompt"] = negative.strip()
    pairs = {k.strip(): v.strip().strip('"') for k, v in _INFO_PAIR.findall(settings_line)}
    simple = {"Steps": ("steps", int), "Sampler": ("sampler_name", str), "Schedule type": ("scheduler", str),
              "CFG scale": ("cfg_scale", float), "Seed": ("seed", int), "Clip skip": ("clip_skip", int),
              "Variation seed": ("subseed", int), "Variation seed strength": ("subseed_strength", float),
              "Hires steps": ("hr_steps", int), "Hires upscaler": ("hr_upscaler", str), "Model": ("model", str),
              "Model hash": ("model_hash", str)}   # not a GenParams field -- harmless, params_from_dict() drops it;
                                                    # read back by model_hash_of() for "which model made this picture"
    for key, (name, cast) in simple.items():
        if key in pairs:
            try:
                result[name] = cast(pairs[key])
            except ValueError:
                pass
    if "Size" in pairs and re.match(r"^\d+x\d+$", pairs["Size"]):
        result["width"], result["height"] = (int(v) for v in pairs["Size"].split("x"))
    if "Hires upscale" in pairs:
        try:
            result["hr_scale"] = float(pairs["Hires upscale"])
            result["enable_hr"] = True
        except ValueError:
            pass
    if "Denoising strength" in pairs:
        try:
            value = float(pairs["Denoising strength"])
        except ValueError:
            value = None
        if value is not None:
            result["hr_denoise" if result.get("enable_hr") else "denoising_strength"] = value
    return result


def model_hash_of(path: Path) -> str:
    """The checkpoint hash Forge/A1111 stamps into a picture's own metadata ("" for a picture with no such text, or
    one not made by Forge/A1111 at all) -- the AUTOV2 short hash CivitAI's own by-hash lookup expects."""
    text = read_png_text(path).get("parameters", "")
    return parse_infotext(text).get("model_hash", "") if text else ""


# --- prompts / progress ----------------------------------------------------------------------------------

_WEIGHT = re.compile(r"[\(\)\[\]{}]|:\s*[\d.]+")
_ANGLE = re.compile(r"<[^>]*>")


def prompt_tags(prompt: str, limit: int = 60) -> list[str]:
    """Comma-separated prompt -> library tags (lower-case, underscores; LoRA/embedding tokens and weights removed)."""
    tags: list[str] = []
    for part in _ANGLE.sub("", prompt).split(","):
        tag = _WEIGHT.sub("", part).strip().lower().replace(" ", "_")
        if tag and tag not in tags and len(tag) <= 60 and tag != "break":
            tags.append(tag)
    return tags[:limit]


def progress_text(progress: dict) -> tuple[float, str]:
    """(0..1, human text) from /sdapi/v1/progress; empty text while Forge is still loading/preparing
    (steps == 0, job counters are -1 and the ETA is meaningless)."""
    state = progress.get("state") or {}
    frac = float(progress.get("progress") or 0)
    step, steps = state.get("sampling_step", 0), state.get("sampling_steps", 0)
    if not steps or steps <= 0:
        return 0.0, ""
    job_count = int(state.get("job_count", 0)) or 1
    job_no = min(int(state.get("job_no", 0)) + 1, job_count)
    eta = progress.get("eta_relative") or 0
    text = f"{job_no}/{job_count} · step {step}/{steps}" + (f" · ~{eta:.0f}s" if eta else "")
    return min(max(frac, 0.0), 1.0), text


def progress_line(progress: dict) -> tuple[float, str]:
    """(0..1, "37% · step 9/24 · ~12 s") for the progress bar in the top bar; empty text while Forge is still preparing."""
    from anihub.core.i18n import tr

    state = progress.get("state") or {}
    frac = min(max(float(progress.get("progress") or 0), 0.0), 1.0)
    step, steps = int(state.get("sampling_step", 0) or 0), int(state.get("sampling_steps", 0) or 0)
    if steps <= 0:
        return 0.0, ""
    eta = int(progress.get("eta_relative") or 0)
    job_count = int(state.get("job_count", 0)) or 1
    job_no = min(int(state.get("job_no", 0)) + 1, job_count)
    text = tr("sd.progress_line", pct=int(frac * 100), step=step, steps=steps, job=f"{job_no}/{job_count} · " if job_count > 1 else "",
              eta=(f" · ~{eta} " + tr("unit.sec")) if eta else "")
    return frac, text
