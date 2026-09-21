"""LoRA files on disk: what Forge shows on a LoRA card (description, keywords, preferred weight, picture) lives in files NEXT TO the model
(`name.json` and `name.preview.png`), so the editor works without a running Forge and Forge sees the same data. Renaming a model
renames those files with it. The safetensors header is only read (training tags, base model) and never rewritten."""
from __future__ import annotations

import json
import os
import re
import struct
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import QBuffer, QIODevice, Qt
from PySide6.QtGui import QImage

MODEL_EXTS = (".safetensors", ".pt", ".ckpt")
PICTURE_EXTS = ("png", "jpg", "jpeg", "webp", "gif")
SIDE_SUFFIXES = ("json", "civitai.info", "metadata.json", "txt") + PICTURE_EXTS + tuple(f"preview.{e}" for e in PICTURE_EXTS)
DEFAULT_TEMPLATE = "<lora:{name}:{weight}>, {keywords}"
TEMPLATE_KEY = "anihub template"              # our own key in the card's json (Forge ignores keys it does not know)
BAD_NAME = re.compile(r'[<>:"/\\|?*,\x00-\x1f]')
MAX_PICTURE = 768
MAX_HEADER = 32 * 1024 * 1024


class LoraError(Exception):
    """A problem worth telling the user (name taken, bad characters, file in use)."""


@dataclass
class Lora:
    path: Path
    root: Path
    description: str = ""
    keywords: str = ""                 # "activation text": comma separated words that summon the LoRA
    weight: float = 0.8                # "preferred weight"
    negative: str = ""                 # "negative text"
    base: str = ""                     # "sd version": SD1, SDXL, Pony...
    template: str = ""                 # how it is written into the prompt; empty = DEFAULT_TEMPLATE
    extra: dict = field(default_factory=dict)      # the other keys of the json, kept when saving

    @property
    def name(self) -> str:
        return self.path.stem

    @property
    def folder(self) -> str:
        """The sub-folder inside the LoRA root ("" for the root itself)."""
        try:
            rel = self.path.parent.relative_to(self.root)
        except ValueError:
            return ""
        return "" if str(rel) == "." else rel.as_posix()

    @property
    def size(self) -> int:
        try:
            return self.path.stat().st_size
        except OSError:
            return 0

    def preview(self) -> Path | None:
        return find_preview(self.path)

    def prompt_text(self, weight: float | None = None) -> str:
        return render_template(self.template or DEFAULT_TEMPLATE, self.name, self.weight if weight is None else weight, self.keywords)


def json_path(model: Path) -> Path:
    return model.with_suffix(".json")


def find_preview(model: Path) -> Path | None:
    """Same search order as the Forge / A1111 extra-networks cards: `name.ext` first, then `name.preview.ext`."""
    for ext in PICTURE_EXTS:
        for suffix in (f".{ext}", f".preview.{ext}"):
            candidate = model.with_name(model.stem + suffix)
            if candidate.is_file():
                return candidate
    return None


def scan(root: Path) -> list[Path]:
    """Every model file under the root (sub-folders too), unfinished downloads left out."""
    if not root.is_dir():
        return []
    found = [p for p in root.rglob("*") if p.suffix.lower() in MODEL_EXTS and p.is_file()]
    return sorted(found, key=lambda p: p.relative_to(root).as_posix().lower())


def load(model: Path, root: Path) -> Lora:
    data: dict = {}
    try:
        raw = json.loads(json_path(model).read_text(encoding="utf-8"))
        data = raw if isinstance(raw, dict) else {}
    except (OSError, ValueError):
        pass
    known = {"description", "activation text", "preferred weight", "negative text", "sd version", TEMPLATE_KEY}
    try:
        weight = float(data.get("preferred weight") or 0.8)
    except (TypeError, ValueError):
        weight = 0.8
    return Lora(model, root, description=str(data.get("description") or ""), keywords=str(data.get("activation text") or ""),
                weight=weight, negative=str(data.get("negative text") or ""), base=str(data.get("sd version") or ""),
                template=str(data.get(TEMPLATE_KEY) or ""), extra={k: v for k, v in data.items() if k not in known})


def save(lora: Lora) -> None:
    """Writes the card's json (the keys Forge reads, plus ours) and keeps whatever else was in the file."""
    data = dict(lora.extra)
    data.update({"description": lora.description.strip(), "activation text": lora.keywords.strip(), "preferred weight": round(lora.weight, 3),
                 "negative text": lora.negative.strip(), "sd version": lora.base.strip()})
    if lora.template.strip() and lora.template.strip() != DEFAULT_TEMPLATE:
        data[TEMPLATE_KEY] = lora.template.strip()
    else:
        data.pop(TEMPLATE_KEY, None)
    target = json_path(lora.path)
    tmp = target.with_name(target.name + ".tmp")
    try:
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=4), encoding="utf-8")
        os.replace(tmp, target)
    except OSError as exc:
        tmp.unlink(missing_ok=True)
        raise LoraError(str(exc)) from exc


# --- the prompt text -------------------------------------------------------------------------------------------------------

def render_template(template: str, name: str, weight: float, keywords: str) -> str:
    """`{name}`, `{weight}` and `{keywords}` filled in; commas left dangling by an empty part are cleaned away."""
    text = template.replace("{name}", name).replace("{weight}", f"{weight:g}").replace("{keywords}", keywords.strip().strip(","))
    text = re.sub(r"\s*,(\s*,)+", ",", text)
    return text.strip().strip(",").strip()


def clean_keywords(text: str) -> str:
    """"a,  b ,, c" -> "a, b, c" (one keyword may hold spaces)."""
    words: list[str] = []
    for part in re.split(r"[,\n]", text):
        part = part.strip()
        if part and part.lower() not in {w.lower() for w in words}:
            words.append(part)
    return ", ".join(words)


# --- names and files -----------------------------------------------------------------------------------------------------------

def check_name(stem: str) -> str:
    stem = stem.strip().strip(".")
    if not stem:
        raise LoraError("empty")
    if BAD_NAME.search(stem):
        raise LoraError("chars")
    return stem


def sidecars(model: Path) -> list[Path]:
    """Files that belong to the model by name: its card json, picture, info files."""
    out = []
    for suffix in SIDE_SUFFIXES:
        candidate = model.with_name(f"{model.stem}.{suffix}")
        if candidate.is_file():
            out.append(candidate)
    return out


def rename(model: Path, new_stem: str) -> Path:
    """Renames the model and its sidecar files together. Nothing is changed if any target name is taken."""
    new_stem = check_name(new_stem)
    if new_stem == model.stem:
        return model
    moves = [(model, model.with_name(new_stem + model.suffix))]
    for side in sidecars(model):
        moves.append((side, side.with_name(new_stem + side.name[len(model.stem):])))
    for src, dst in moves:
        if dst.exists() and dst.resolve() != src.resolve():              # (a change of letter case only is the same file)
            raise LoraError("exists")
    done: list[tuple[Path, Path]] = []
    try:
        for src, dst in moves:
            os.replace(src, dst)
            done.append((src, dst))
    except OSError as exc:
        for src, dst in reversed(done):                                  # put everything back
            try:
                os.replace(dst, src)
            except OSError:
                pass
        raise LoraError(str(exc)) from exc
    return moves[0][1]


# --- the picture ---------------------------------------------------------------------------------------------------------------

def _png_bytes(image: QImage) -> bytes:
    if max(image.width(), image.height()) > MAX_PICTURE:
        image = image.scaled(MAX_PICTURE, MAX_PICTURE, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buf, "PNG")
    return bytes(buf.data())


def set_preview(model: Path, image: QImage | bytes | Path) -> Path:
    """The picture on the card: `name.preview.png` (largest side 768 px). Older pictures of the model are removed so they cannot win."""
    if isinstance(image, Path):
        image = QImage(str(image))
    elif isinstance(image, (bytes, bytearray)):
        image = QImage.fromData(bytes(image))
    if image.isNull():
        raise LoraError("picture")
    target = model.with_name(model.stem + ".preview.png")
    data = _png_bytes(image)
    try:
        clear_preview(model)
        target.write_bytes(data)
    except OSError as exc:
        raise LoraError(str(exc)) from exc
    return target


def clear_preview(model: Path) -> None:
    for ext in PICTURE_EXTS:
        for suffix in (f".{ext}", f".preview.{ext}"):
            model.with_name(model.stem + suffix).unlink(missing_ok=True)


# --- what the file itself knows --------------------------------------------------------------------------------------------------

def header_metadata(model: Path) -> dict[str, str]:
    """The `__metadata__` block of a safetensors header (trainers put the output name, base model and tag counts there)."""
    if model.suffix.lower() != ".safetensors":
        return {}
    try:
        with model.open("rb") as fh:
            (size,) = struct.unpack("<Q", fh.read(8))
            if not 0 < size <= MAX_HEADER:
                return {}
            meta = json.loads(fh.read(size)).get("__metadata__") or {}
    except (OSError, ValueError, struct.error, AttributeError):
        return {}
    return {str(k): str(v) for k, v in meta.items()} if isinstance(meta, dict) else {}


def suggested_keywords(model: Path, limit: int = 15) -> list[str]:
    """Words that probably summon the LoRA: CivitAI's trained words when a `.civitai.info` sits beside it, otherwise the most used
    training tags of the file's header."""
    words: list[str] = []
    try:
        info = json.loads(model.with_name(model.stem + ".civitai.info").read_text(encoding="utf-8"))
        words = [str(w).strip() for w in (info.get("trainedWords") or []) if str(w).strip()]
    except (OSError, ValueError, AttributeError):
        pass
    if not words:
        try:
            frequency = json.loads(header_metadata(model).get("ss_tag_frequency", "{}"))
            counts: dict[str, int] = {}
            for tags in frequency.values():
                for tag, n in tags.items():
                    counts[tag.strip()] = counts.get(tag.strip(), 0) + int(n)
            words = [t for t, _n in sorted(counts.items(), key=lambda kv: -kv[1]) if t][:limit]
        except (ValueError, AttributeError, TypeError):
            words = []
    return words[:limit]


def base_from_header(model: Path) -> str:
    meta = header_metadata(model)
    return meta.get("ss_base_model_version") or ""
