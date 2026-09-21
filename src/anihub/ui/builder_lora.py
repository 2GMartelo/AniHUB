"""The LoRA tab of the prompt builder: every LoRA file of Forge's folder as a tile (its card picture), sorted into five fixed groups. The tab
itself cannot be edited (no deleting it, no creating tags inside): a LoRA is only moved between groups, by dragging or from the tile's menu."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap

from anihub.core.i18n import tr
from anihub.services import lora as lo

GROUPS = lo.CATEGORIES                       # style, character, pose, clothing, tool


def group_name(key: str | None) -> str:
    return tr("lora.cat.all") if key is None else tr("lora.cat.none") if key == "" else tr(f"lora.cat.{key}")


def lora_rows(root: Path, group: str | None) -> list[dict]:
    """Tiles of the LoRAs of one group (`None` = all of them, "" = not sorted yet). The rows look like catalogue tags where the builder
    needs it (`slot` is the paragraph a LoRA is written into)."""
    rows = []
    for path in lo.scan(root):
        card = lo.load(path, root)
        if group is not None and (card.category or "") != group:
            continue
        rows.append({"lora": True, "path": path, "text": path.stem, "label": "", "slot": "extra", "id": 0, "image": "", "group_id": 0,
                     "exclusive": 0, "category": card.category, "description": card.description, "folder": card.folder})
    return rows


def lora_pixmap(path: Path, size: int) -> QPixmap | None:
    """The card picture of a LoRA cut to a square, or None when it has none."""
    preview = lo.find_preview(path)
    pm = QPixmap(str(preview)) if preview else QPixmap()
    if pm.isNull():
        return None
    pm = pm.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
    return pm.copy((pm.width() - size) // 2, (pm.height() - size) // 2, size, size)


def group_of_entry(name: str) -> str:
    """The marker the builder puts on the prompt entries that came from a LoRA, so they can be found and removed again."""
    return f"lora:{name}"
