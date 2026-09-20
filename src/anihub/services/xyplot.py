"""X/Y grid (ТЗ 5.8): the same picture generated while one or two parameters vary, laid out as a table."""
from __future__ import annotations

import random
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen

from anihub.services.forge import ForgeApi
from anihub.services.generation import GenParams, GenResult, run_generation

MAX_CELLS = 64

# axis -> value kind. "prompt_sr" is prompt search/replace: the first value is the text to find in the prompt,
# every value (including the first) is then what it is replaced with, so the first cell is the unchanged prompt.
AXES: dict[str, str] = {
    "steps": "int", "cfg_scale": "float", "sampler_name": "str", "scheduler": "str", "seed": "int",
    "denoising_strength": "float", "clip_skip": "int", "model": "str", "prompt_sr": "str",
}


def _number(token: str, kind: str):
    value = float(token)
    if kind == "int":
        if value != int(value):
            raise ValueError(f"{token}: whole number expected")
        return int(value)
    return round(value, 4)


def parse_values(axis: str, text: str) -> list:
    """'20, 30, 40' or a range 'start:stop:step' (inclusive) for numbers; comma separated names otherwise."""
    kind = AXES[axis]
    tokens = [t.strip() for t in text.replace(";", ",").split(",") if t.strip()]
    if not tokens:
        raise ValueError("no values")
    if kind == "str":
        return tokens
    values: list = []
    for token in tokens:
        if ":" in token:
            parts = token.split(":")
            if len(parts) != 3:
                raise ValueError(f"{token}: use start:stop:step")
            start, stop, step = float(parts[0]), float(parts[1]), float(parts[2])
            if step == 0 or (stop - start) * step < 0:
                raise ValueError(f"{token}: the step never reaches the end")
            n = int(abs((stop - start) / step) + 1e-9) + 1
            values.extend(_number(str(start + i * step), kind) for i in range(n))
        else:
            values.append(_number(token, kind))
        if len(values) > MAX_CELLS:
            raise ValueError(f"more than {MAX_CELLS} values")
    return values


def apply_axis(params: GenParams, axis: str, value, first_value=None) -> GenParams:
    """`params` with one axis value applied. For prompt_sr, `first_value` is the search text."""
    if axis == "prompt_sr":
        needle = str(first_value)
        if needle not in params.prompt:
            raise ValueError(f"'{needle}' is not in the prompt")
        return replace(params, prompt=params.prompt.replace(needle, str(value)))
    return replace(params, **{axis: value})


@dataclass
class Cell:
    row: int
    col: int
    params: GenParams


@dataclass
class XYPlan:
    x_axis: str
    x_values: list
    y_axis: str | None
    y_values: list
    cells: list[Cell]

    @property
    def rows(self) -> int:
        return max(len(self.y_values), 1)

    @property
    def cols(self) -> int:
        return len(self.x_values)


def build_plan(base: GenParams, x_axis: str, x_values: list, y_axis: str | None = None,
               y_values: list | None = None) -> XYPlan:
    y_values = list(y_values or [])
    if y_axis is None:
        y_values = []
    if y_axis == x_axis:
        raise ValueError("X and Y must be different parameters")
    total = len(x_values) * max(len(y_values), 1)
    if total > MAX_CELLS:
        raise ValueError(f"{total} pictures is too many (limit {MAX_CELLS})")
    seed = base.seed if base.seed != -1 else random.randint(0, 2**31 - 1)   # every cell must share the seed
    fixed = replace(base, seed=seed, n_iter=1, batch_size=1, enable_hr=base.enable_hr)
    cells = []
    for r in range(max(len(y_values), 1)):
        for c, xv in enumerate(x_values):
            p = apply_axis(fixed, x_axis, xv, x_values[0])
            if y_axis:
                p = apply_axis(p, y_axis, y_values[r], y_values[0])
            cells.append(Cell(r, c, p))
    return XYPlan(x_axis, list(x_values), y_axis, y_values, cells)


def run_xy(api: ForgeApi, plan: XYPlan, out_dir: Path, progress: Callable[[int, int], None] | None = None,
           cancelled: Callable[[], bool] | None = None) -> dict[tuple[int, int], GenResult]:
    """Blocking: generate every cell in order. Returns what was made (fewer cells when cancelled)."""
    made: dict[tuple[int, int], GenResult] = {}
    for i, cell in enumerate(plan.cells):
        if cancelled and cancelled():
            break
        try:
            results = run_generation(api, cell.params, out_dir)
        except Exception:
            if cancelled and cancelled():       # Stop interrupts the running picture: Forge then returns nothing
                break
            raise
        made[(cell.row, cell.col)] = results[0]
        if progress:
            progress(i + 1, len(plan.cells))
    return made


def label_for(axis: str, value, first_value=None) -> str:
    if axis == "prompt_sr":
        return f"{first_value} → {value}" if str(value) != str(first_value) else str(value)
    return f"{axis}: {value}"


def compose_grid(plan: XYPlan, images: dict[tuple[int, int], QImage], cell: int = 384, dark: bool = True) -> QImage:
    """Table of the generated pictures with the axis values as headers. Missing cells stay empty (cancelled run)."""
    font = QFont()
    font.setPixelSize(15)
    font.setWeight(QFont.Weight.DemiBold)
    x_labels = [label_for(plan.x_axis, v, plan.x_values[0]) for v in plan.x_values]
    y_labels = [label_for(plan.y_axis, v, plan.y_values[0]) for v in plan.y_values] if plan.y_axis else []
    probe = QImage(1, 1, QImage.Format.Format_ARGB32)
    p0 = QPainter(probe)
    p0.setFont(font)
    metrics = p0.fontMetrics()
    left = (max(metrics.horizontalAdvance(t) for t in y_labels) + 24) if y_labels else 0
    p0.end()
    top = 40
    gap = 6
    sizes = [img.size().scaled(cell, cell, Qt.AspectRatioMode.KeepAspectRatio) for img in images.values()] or []
    cw = max((s.width() for s in sizes), default=cell)
    ch = max((s.height() for s in sizes), default=cell)
    width = left + plan.cols * (cw + gap) + gap
    height = top + plan.rows * (ch + gap) + gap
    bg, fg = (QColor("#101216"), QColor("#e8ebf1")) if dark else (QColor("#ffffff"), QColor("#1b2030"))
    out = QImage(width, height, QImage.Format.Format_RGB32)
    out.fill(bg)
    p = QPainter(out)
    p.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform
                     | QPainter.RenderHint.TextAntialiasing)
    p.setFont(font)
    p.setPen(QPen(fg))
    for c, text in enumerate(x_labels):
        p.drawText(QRectF(left + gap + c * (cw + gap), 0, cw, top), Qt.AlignmentFlag.AlignCenter, text)
    for r, text in enumerate(y_labels):
        p.drawText(QRectF(4, top + gap + r * (ch + gap), left - 8, ch), Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, text)
    for (r, c), img in images.items():
        scaled = img.scaled(cw, ch, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        x = left + gap + c * (cw + gap) + (cw - scaled.width()) // 2
        y = top + gap + r * (ch + gap) + (ch - scaled.height()) // 2
        p.drawImage(x, y, scaled)
    p.end()
    return out
