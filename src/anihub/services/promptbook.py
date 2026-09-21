"""The prompt builder's logic: the document (a paragraph of tags per slot), rendering it in the right order, parsing an existing prompt
back into slots, and the tag catalogue in the database (built-in entries plus the user's own categories, tags and pictures)."""
from __future__ import annotations

import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import QBuffer, QIODevice, Qt
from PySide6.QtGui import QImage

from anihub.services.promptbook_data import SLOTS, parse_catalog

SLOT_KEYS = [s[0] for s in SLOTS]
POSITIVE = [s[0] for s in SLOTS if not s[3]]
NEGATIVE = [s[0] for s in SLOTS if s[3]]
SLOT_NAMES = {key: (en, ru) for key, en, ru, _neg in SLOTS}
SEED_VERSION = 1
IMAGE_SIZE = 256
MIN_W, MAX_W, STEP_W = 0.1, 2.0, 0.1


def slot_name(key: str, lang: str = "en") -> str:
    en, ru = SLOT_NAMES.get(key, (key, key))
    return ru if lang == "ru" else en


def norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower().replace("_", " "))


# --- the document -----------------------------------------------------------------------------------------------------

@dataclass
class Entry:
    text: str
    weight: float = 1.0
    group: str = ""            # the catalogue category it came from: an exclusive category keeps only one entry
    tag_id: int = 0            # the catalogue tag (for its picture), 0 for typed-in ones

    def render(self) -> str:
        if abs(self.weight - 1.0) < 0.005:
            return self.text
        return f"({self.text}:{self.weight:.2f}".rstrip("0").rstrip(".") + ")"


@dataclass
class PromptDoc:
    slots: dict[str, list[Entry]] = field(default_factory=lambda: {k: [] for k in SLOT_KEYS})

    def entries(self, slot: str) -> list[Entry]:
        return self.slots.setdefault(slot, [])

    def find(self, slot: str, text: str) -> Entry | None:
        key = norm(text)
        return next((e for e in self.entries(slot) if norm(e.text) == key), None)

    def has(self, slot: str, text: str) -> bool:
        return self.find(slot, text) is not None

    def add(self, slot: str, text: str, *, group: str = "", exclusive: bool = False, tag_id: int = 0, weight: float = 1.0) -> Entry | None:
        """Puts a tag into the paragraph of `slot` (never twice). In an exclusive category the previous choice of that category is
        replaced. Returns the entry, or None when the text is empty or already there."""
        text = text.strip().strip(",").strip()
        if not text or self.has(slot, text):
            return None
        if exclusive and group:
            self.slots[slot] = [e for e in self.entries(slot) if e.group != group]
        entry = Entry(text, weight, group, tag_id)
        self.entries(slot).append(entry)
        return entry

    def remove(self, slot: str, text: str) -> bool:
        entry = self.find(slot, text)
        if entry is None:
            return False
        self.entries(slot).remove(entry)
        return True

    def toggle(self, slot: str, text: str, **kw) -> bool:
        """True when the tag is in the prompt afterwards."""
        if self.remove(slot, text):
            return False
        return self.add(slot, text, **kw) is not None

    def move(self, slot: str, text: str, delta: int) -> None:
        items = self.entries(slot)
        entry = self.find(slot, text)
        if entry is None:
            return
        i = items.index(entry)
        j = max(0, min(len(items) - 1, i + delta))
        items.insert(j, items.pop(i))

    def move_to_slot(self, slot: str, text: str, target: str) -> None:
        entry = self.find(slot, text)
        if entry is not None and slot != target and not self.has(target, text):
            self.entries(slot).remove(entry)
            entry.group, entry.tag_id = "", entry.tag_id
            self.entries(target).append(entry)

    def set_weight(self, slot: str, text: str, weight: float) -> None:
        entry = self.find(slot, text)
        if entry is not None:
            entry.weight = round(max(MIN_W, min(MAX_W, weight)), 2)

    def clear(self, negative: bool | None = None) -> None:
        for key in SLOT_KEYS:
            if negative is None or (key in NEGATIVE) == negative:
                self.slots[key] = []

    def is_empty(self) -> bool:
        return not any(self.slots.values())

    def paragraphs(self, keys: list[str]) -> list[str]:
        return [", ".join(e.render() for e in self.slots.get(k, [])) for k in keys if self.slots.get(k)]

    def positive(self) -> str:
        """One paragraph per slot, in writing order; each ends with a comma so the paragraphs read as one prompt."""
        return ",\n".join(self.paragraphs(POSITIVE))

    def negative(self) -> str:
        return ",\n".join(self.paragraphs(NEGATIVE))

    def count(self, keys: list[str]) -> int:
        return sum(len(self.slots.get(k, [])) for k in keys)


def estimate_tokens(text: str) -> int:
    """A rough CLIP token count (words plus punctuation): good enough to warn about the 75-token chunk."""
    return len(re.findall(r"[\w'’-]+|[^\w\s]", text))


# --- parsing an existing prompt ------------------------------------------------------------------------------------------

def split_top_level(text: str) -> list[str]:
    """Split on commas and newlines that are not inside (), [], <> (weights, LoRA tags)."""
    parts, depth, cur = [], 0, []
    for ch in text:
        if ch in "([<":
            depth += 1
        elif ch in ")]>":
            depth = max(0, depth - 1)
        if ch in ",\n" and depth == 0:
            parts.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    parts.append("".join(cur))
    return [p.strip() for p in parts if p.strip()]


_WEIGHTED = re.compile(r"^\(\s*(.+?)\s*:\s*(-?\d+(?:\.\d+)?)\s*\)$")


def parse_piece(piece: str) -> tuple[str, float]:
    """'(blue hair:1.3)' -> ('blue hair', 1.3); '(x)' -> ('x', 1.1); '[x]' -> ('x', 0.9); 'x' -> ('x', 1.0)."""
    m = _WEIGHTED.match(piece)
    if m:
        return m.group(1), max(MIN_W, min(MAX_W, float(m.group(2))))
    if piece.startswith("(") and piece.endswith(")") and len(piece) > 2:
        return piece[1:-1].strip(), 1.1
    if piece.startswith("[") and piece.endswith("]") and len(piece) > 2:
        return piece[1:-1].strip(), 0.9
    return piece, 1.0


def parse_prompt(text: str, lookup: dict[str, tuple[str, str]], negative: bool = False) -> PromptDoc:
    """Sorts the tags of a written prompt into slots by what the catalogue knows (`lookup`: normalised tag -> (slot, group));
    what it does not know goes to the "extra" paragraph (or "unwanted things" for a negative prompt)."""
    doc = PromptDoc()
    fallback = "neg_unwanted" if negative else "extra"
    for piece in split_top_level(text):
        tag, weight = parse_piece(piece)
        if not tag:
            continue
        slot, group = lookup.get(norm(tag), (fallback, ""))
        if (slot in NEGATIVE) != negative:                              # a positive tag in the negative prompt (or the reverse)
            slot, group = fallback, ""
        doc.add(slot, tag, group=group, weight=weight)
    return doc


def preview_prompt(slot: str, tag: str) -> tuple[str, str]:
    """What to generate for a tag's picture: the tag on a plain subject in the shot that shows it best."""
    quality = "masterpiece, best quality"
    negative = "lowres, bad anatomy, bad hands, text, watermark, worst quality"
    if slot in ("background",):
        return f"{quality}, no humans, scenery, {tag}", negative
    if slot in ("clothing", "pose"):
        return f"{quality}, 1girl, solo, {tag}, full body, simple background", negative
    if slot in ("appearance", "expression", "character"):
        return f"{quality}, 1girl, solo, {tag}, portrait, simple background", negative
    if slot in ("camera", "lighting", "style"):
        return f"{quality}, 1girl, solo, {tag}, standing, outdoors", negative
    return f"{quality}, 1girl, solo, {tag}, upper body, simple background", negative


# --- the catalogue in the database ---------------------------------------------------------------------------------------

def jpeg_bytes(image: QImage, size: int = IMAGE_SIZE) -> bytes:
    image = image.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
    x, y = max((image.width() - size) // 2, 0), max((image.height() - size) // 2, 0)
    image = image.copy(x, y, size, size).convertToFormat(QImage.Format.Format_RGB32)
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buf, "JPEG", 88)
    return bytes(buf.data())


class PromptBook:
    """Categories (`pb_nodes`) and tags (`pb_tags`). Built-in rows carry a stable `key` and are never physically deleted (they are
    hidden), so an update of the built-in catalogue can add new entries without bringing back what the user removed."""

    def __init__(self, db, root: Path):
        self.db, self.root = db, Path(root)
        self.image_dir = self.root / "promptbook" / "img"

    @property
    def conn(self):
        return self.db.conn

    # --- seeding ---------------------------------------------------------------------------------------------------

    def seed(self) -> None:
        """Insert the built-in categories and tags that are not in the database yet (keys are unique)."""
        c = self.conn
        have_nodes = {r["key"]: r["id"] for r in c.execute("SELECT id, key FROM pb_nodes WHERE key IS NOT NULL")}
        have_tags = {r["key"] for r in c.execute("SELECT key FROM pb_tags WHERE key IS NOT NULL")}
        with c:
            for pos, cat in enumerate(parse_catalog()):
                node_id = have_nodes.get(cat["key"])
                if node_id is None:
                    node_id = c.execute("INSERT INTO pb_nodes(parent_id, slot, name, name_ru, exclusive, position, key) "
                                        "VALUES (NULL, ?, ?, ?, ?, ?, ?)",
                                        (cat["slot"], cat["name"], cat["name_ru"], int(cat["exclusive"]), pos, cat["key"])).lastrowid
                    have_nodes[cat["key"]] = node_id
                for i, (text, label) in enumerate(cat["tags"]):
                    key = f"{cat['key']}.{text}"
                    if key not in have_tags:
                        c.execute("INSERT INTO pb_tags(node_id, text, label, position, key) VALUES (?, ?, ?, ?, ?)",
                                  (node_id, text, label, i, key))
                        have_tags.add(key)

    def restore_defaults(self) -> None:
        with self.conn:
            self.conn.execute("UPDATE pb_nodes SET hidden=0 WHERE key IS NOT NULL")
            self.conn.execute("UPDATE pb_tags SET hidden=0 WHERE key IS NOT NULL")
        self.seed()

    # --- reading ---------------------------------------------------------------------------------------------------

    def nodes(self, slot: str | None = None, include_hidden: bool = False) -> list[dict]:
        sql = "SELECT * FROM pb_nodes WHERE 1" + ("" if include_hidden else " AND hidden=0") + (" AND slot=?" if slot else "")
        rows = self.conn.execute(sql + " ORDER BY position, id", (slot,) if slot else ()).fetchall()
        return [dict(r) for r in rows]

    def node(self, node_id: int) -> dict | None:
        row = self.conn.execute("SELECT * FROM pb_nodes WHERE id=?", (node_id,)).fetchone()
        return dict(row) if row else None

    def subtree_ids(self, node_id: int) -> list[int]:
        ids, todo = [], [node_id]
        while todo:
            current = todo.pop()
            ids.append(current)
            todo += [r[0] for r in self.conn.execute("SELECT id FROM pb_nodes WHERE parent_id=? AND hidden=0", (current,))]
        return ids

    def tags(self, node_ids: list[int] | None = None, slot: str | None = None, query: str = "") -> list[dict]:
        """Visible tags of the given categories (with their subcategories' tags), of a slot, or matching a search text."""
        sql = ("SELECT t.*, n.slot AS slot, n.exclusive AS exclusive, n.id AS group_id FROM pb_tags t JOIN pb_nodes n ON n.id=t.node_id "
               "WHERE t.hidden=0 AND n.hidden=0")
        args: list = []
        if node_ids is not None:
            sql += f" AND t.node_id IN ({','.join('?' * len(node_ids)) or 'NULL'})"
            args += node_ids
        if slot:
            sql += " AND n.slot=?"
            args.append(slot)
        rows = [dict(r) for r in self.conn.execute(sql + " ORDER BY n.position, n.id, t.position, t.id", args)]
        if query.strip():
            needle = norm(query)
            rows = [r for r in rows if needle in norm(r["text"]) or needle in norm(r["label"])]
        return rows

    def tag(self, tag_id: int) -> dict | None:
        row = self.conn.execute("SELECT t.*, n.slot AS slot, n.exclusive AS exclusive, n.id AS group_id FROM pb_tags t "
                                "JOIN pb_nodes n ON n.id=t.node_id WHERE t.id=?", (tag_id,)).fetchone()
        return dict(row) if row else None

    def lookup(self) -> dict[str, tuple[str, str]]:
        """normalised tag text -> (slot, group id as text) over the whole catalogue, the first slot in writing order winning."""
        order = {k: i for i, k in enumerate(SLOT_KEYS)}
        table: dict[str, tuple[str, str]] = {}
        for r in sorted(self.tags(), key=lambda r: order.get(r["slot"], 99)):
            table.setdefault(norm(r["text"]), (r["slot"], str(r["group_id"]) if r["exclusive"] else ""))
        return table

    # --- editing ---------------------------------------------------------------------------------------------------

    def add_node(self, slot: str, name: str, parent_id: int | None = None, exclusive: bool = False) -> int:
        pos = self.conn.execute("SELECT COALESCE(MAX(position), 0) + 1 FROM pb_nodes").fetchone()[0]
        with self.conn:
            return self.conn.execute("INSERT INTO pb_nodes(parent_id, slot, name, name_ru, exclusive, position) VALUES (?, ?, ?, '', ?, ?)",
                                     (parent_id, slot, name.strip(), int(exclusive), pos)).lastrowid

    def rename_node(self, node_id: int, name: str) -> None:
        with self.conn:
            self.conn.execute("UPDATE pb_nodes SET name=?, name_ru='' WHERE id=?", (name.strip(), node_id))

    def set_exclusive(self, node_id: int, value: bool) -> None:
        with self.conn:
            self.conn.execute("UPDATE pb_nodes SET exclusive=? WHERE id=?", (int(value), node_id))

    def delete_node(self, node_id: int) -> None:
        """A user's category is deleted with its subcategories, tags and pictures; a built-in one is only hidden."""
        for nid in self.subtree_ids(node_id):
            row = self.node(nid)
            if row is None:
                continue
            if row["key"]:
                with self.conn:
                    self.conn.execute("UPDATE pb_nodes SET hidden=1 WHERE id=?", (nid,))
        user_nodes = [n for n in self.subtree_ids(node_id) if (self.node(n) or {}).get("key") is None and self.node(n)]
        for nid in user_nodes:
            for t in self.conn.execute("SELECT id FROM pb_tags WHERE node_id=?", (nid,)).fetchall():
                self._drop_image(t["id"])
        if user_nodes:
            with self.conn:
                self.conn.execute(f"DELETE FROM pb_nodes WHERE id IN ({','.join('?' * len(user_nodes))})", user_nodes)

    def add_tag(self, node_id: int, text: str, label: str = "") -> int | None:
        text = text.strip().strip(",").strip()
        if not text:
            return None
        pos = self.conn.execute("SELECT COALESCE(MAX(position), 0) + 1 FROM pb_tags WHERE node_id=?", (node_id,)).fetchone()[0]
        existing = self.conn.execute("SELECT id, hidden FROM pb_tags WHERE node_id=? AND lower(text)=lower(?)", (node_id, text)).fetchone()
        with self.conn:
            if existing:
                self.conn.execute("UPDATE pb_tags SET hidden=0, label=CASE WHEN ?<>'' THEN ? ELSE label END WHERE id=?", (label, label, existing["id"]))
                return existing["id"]
            return self.conn.execute("INSERT INTO pb_tags(node_id, text, label, position) VALUES (?, ?, ?, ?)", (node_id, text, label.strip(), pos)).lastrowid

    def edit_tag(self, tag_id: int, text: str, label: str) -> None:
        with self.conn:
            self.conn.execute("UPDATE pb_tags SET text=?, label=? WHERE id=?", (text.strip(), label.strip(), tag_id))

    def delete_tag(self, tag_id: int) -> None:
        row = self.conn.execute("SELECT key FROM pb_tags WHERE id=?", (tag_id,)).fetchone()
        if row is None:
            return
        with self.conn:
            if row["key"]:
                self.conn.execute("UPDATE pb_tags SET hidden=1 WHERE id=?", (tag_id,))
            else:
                self._drop_image(tag_id)
                self.conn.execute("DELETE FROM pb_tags WHERE id=?", (tag_id,))

    # --- pictures --------------------------------------------------------------------------------------------------

    def image_path(self, tag: dict) -> Path | None:
        return self.root / tag["image"] if tag.get("image") else None

    def set_image(self, tag_id: int, image: QImage | bytes | Path) -> Path | None:
        """Stores a picture for a tag (cropped to a square, 256 px). Accepts a QImage, raw bytes or a file path."""
        if isinstance(image, Path):
            image = QImage(str(image))
        elif isinstance(image, (bytes, bytearray)):
            image = QImage.fromData(bytes(image))
        if image.isNull():
            return None
        self.image_dir.mkdir(parents=True, exist_ok=True)
        dest = self.image_dir / f"{tag_id}.jpg"
        dest.write_bytes(jpeg_bytes(image))
        with self.conn:
            self.conn.execute("UPDATE pb_tags SET image=? WHERE id=?", (dest.relative_to(self.root).as_posix(), tag_id))
        return dest

    def clear_image(self, tag_id: int) -> None:
        self._drop_image(tag_id)
        with self.conn:
            self.conn.execute("UPDATE pb_tags SET image='' WHERE id=?", (tag_id,))

    def _drop_image(self, tag_id: int) -> None:
        (self.image_dir / f"{tag_id}.jpg").unlink(missing_ok=True)

    def wipe_images(self) -> None:
        shutil.rmtree(self.image_dir, ignore_errors=True)
