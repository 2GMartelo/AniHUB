"""Autotagger: WD14 (SmilingWolf wd-vit-tagger-v3) ONNX model on CPU (no VRAM, no Forge needed)."""
from __future__ import annotations

import csv
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage, QPainter

from anihub.net.http import HttpClient

log = logging.getLogger(__name__)

REPO = "https://huggingface.co/SmilingWolf/wd-vit-tagger-v3/resolve/main"
MODEL_FILES = {"model.onnx": f"{REPO}/model.onnx", "selected_tags.csv": f"{REPO}/selected_tags.csv"}
RATINGS = ("general", "sensitive", "questionable", "explicit")
CATEGORY_NAMES = {0: "general", 4: "character", 9: "rating"}


@dataclass
class TagResult:
    tags: list[tuple[str, str]] = field(default_factory=list)  # (name, category), most confident first
    rating: str = "general"


def model_dir_default(config_dir: Path) -> Path:
    return config_dir / "models" / "wd14"


def preprocess(image: QImage, size: int) -> np.ndarray:
    """Letterbox onto a white square, RGB -> BGR, float32 0..255, NHWC (what the WD14 v3 models expect)."""
    scaled = image.convertToFormat(QImage.Format.Format_RGB888).scaled(
        size, size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
    canvas = QImage(size, size, QImage.Format.Format_RGB888)
    canvas.fill(QColor("white"))
    painter = QPainter(canvas)
    painter.drawImage((size - scaled.width()) // 2, (size - scaled.height()) // 2, scaled)
    painter.end()
    stride = canvas.bytesPerLine()
    raw = np.frombuffer(canvas.constBits(), dtype=np.uint8, count=stride * size).reshape(size, stride)
    rgb = raw[:, : size * 3].reshape(size, size, 3)
    return np.ascontiguousarray(rgb[:, :, ::-1], dtype=np.float32)[None, ...]


class Autotagger:
    def __init__(self, model_dir: Path, general_threshold: float = 0.35, character_threshold: float = 0.85):
        self.model_dir = model_dir
        self.general_threshold = general_threshold
        self.character_threshold = character_threshold
        self._session = None
        self._tags: list[tuple[str, int]] = []  # (name, category id) in model output order
        self._size = 448

    @property
    def available(self) -> bool:
        return all((self.model_dir / name).exists() for name in MODEL_FILES)

    def _load(self):
        if self._session is None:
            import onnxruntime as ort  # heavy import: only when tagging is actually used
            opts = ort.SessionOptions()
            opts.log_severity_level = 3
            session = ort.InferenceSession(str(self.model_dir / "model.onnx"), sess_options=opts,
                                           providers=["CPUExecutionProvider"])
            with (self.model_dir / "selected_tags.csv").open(encoding="utf-8", newline="") as fh:
                self._tags = [(row["name"], int(row["category"])) for row in csv.DictReader(fh)]
            self._size = int(session.get_inputs()[0].shape[1])
            self._session = session
        return self._session

    def tag_image(self, image: QImage) -> TagResult:
        session = self._load()
        probs = session.run(None, {session.get_inputs()[0].name: preprocess(image, self._size)})[0][0]
        return self.interpret(probs)

    def interpret(self, probs) -> TagResult:
        rating_scores: dict[str, float] = {}
        scored: list[tuple[float, str, str]] = []
        for (name, cat), p in zip(self._tags, probs):
            if cat == 9:
                rating_scores[name] = float(p)
            elif cat == 0 and p >= self.general_threshold:
                scored.append((float(p), name, "general"))
            elif cat == 4 and p >= self.character_threshold:
                scored.append((float(p), name, "character"))
        scored.sort(reverse=True)
        rating = max(RATINGS, key=lambda r: rating_scores.get(r, 0.0)) if rating_scores else "general"
        return TagResult([(name, cat) for _, name, cat in scored], rating)

    def tag_file(self, path: Path) -> TagResult | None:
        image = QImage(str(path))
        return None if image.isNull() else self.tag_image(image)


def download_model(http: HttpClient, model_dir: Path, progress: Callable[[str, int, int], None] | None = None,
                   cancelled: Callable[[], bool] | None = None) -> None:
    """Blocking. progress(file name, done, total)."""
    model_dir.mkdir(parents=True, exist_ok=True)
    for name, url in MODEL_FILES.items():
        target = model_dir / name
        if target.exists():
            continue
        http.download(url, target, progress=(lambda d, t, n=name: progress(n, d, t)) if progress else None,
                      cancelled=cancelled)
