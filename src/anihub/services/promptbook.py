"""The prompt builder's logic: the document (a paragraph of tags per slot), rendering it in the right order, parsing an existing prompt
back into slots, and the tag catalogue in the database (built-in entries plus the user's own categories, tags and pictures)."""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import zipfile
import zlib
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
PACK_FILE = Path(__file__).resolve().parents[1] / "data" / "promptbook_pack.zip"     # the pictures of the built-in tags that ship with the app
IMAGE_SIZE = 256
MIN_W, MAX_W, STEP_W = 0.1, 2.0, 0.1


def slot_name(key: str, lang: str = "en") -> str:
    en, ru = SLOT_NAMES.get(key, (key, key))
    return ru if lang == "ru" else en


# --- user-created sections --------------------------------------------------------------------------------------
# SLOT_KEYS/POSITIVE/NEGATIVE/SLOT_NAMES above are the built-in sections (quality, character, clothing...); the
# user can add their own on top, and reorder ALL of them (built-in and custom together). These four names are
# reassigned wholesale by set_custom_slots() -- the same "global mutable state, rebuilt from config" pattern
# ui/theme.py already uses for custom colours -- rather than threading a "slots" argument through PromptDoc,
# PromptBuilder and catalog_picker.py, which already reference them as plain module constants in a dozen places.

def is_custom_slot(key: str) -> bool:
    return not any(s[0] == key for s in SLOTS)


def custom_slot_key(existing: set[str], label: str) -> str:
    """A short, stable, unique key for a user-typed section name."""
    base = "custom_" + re.sub(r"[^a-z0-9]+", "_", label.strip().lower()).strip("_")
    base = base if base != "custom_" else "custom_section"
    key, n = base, 2
    while key in existing:
        key = f"{base}_{n}"
        n += 1
    return key


def set_custom_slots(custom: list[dict], order: list[str]) -> None:
    """Rebuilds SLOT_KEYS/POSITIVE/NEGATIVE/SLOT_NAMES from the built-ins plus `custom` ({key, label, negative}
    dicts), in `order` (missing keys are appended in their original order)."""
    global SLOT_KEYS, POSITIVE, NEGATIVE, SLOT_NAMES
    by_key = {s[0]: s for s in SLOTS}
    for c in custom:
        by_key[c["key"]] = (c["key"], c["label"], c["label"], bool(c.get("negative", False)))
    keys = [k for k in order if k in by_key] + [k for k in by_key if k not in order]
    entries = [by_key[k] for k in keys]
    SLOT_KEYS = [e[0] for e in entries]
    POSITIVE = [e[0] for e in entries if not e[3]]
    NEGATIVE = [e[0] for e in entries if e[3]]
    SLOT_NAMES = {e[0]: (e[1], e[2]) for e in entries}


def apply_custom_slots(cfg) -> None:
    """Call once when the app (or a test) starts, and again whenever the user's sections change."""
    set_custom_slots(cfg.get("promptbuilder.custom_slots", []) or [], cfg.get("promptbuilder.slot_order", []) or [])


def add_custom_slot(cfg, label: str, negative: bool) -> str:
    custom = list(cfg.get("promptbuilder.custom_slots", []) or [])
    existing = {s[0] for s in SLOTS} | {c["key"] for c in custom}
    key = custom_slot_key(existing, label)
    custom.append({"key": key, "label": label.strip(), "negative": negative})
    cfg.set("promptbuilder.custom_slots", custom, save=False)
    # Appended after the CURRENT effective order (SLOT_KEYS), not the possibly empty/stale one in cfg: a fresh
    # config with no stored slot_order yet must still put a new section at the very end, not first.
    order = list(SLOT_KEYS) + [key]
    cfg.set("promptbuilder.slot_order", order)
    apply_custom_slots(cfg)
    return key


def rename_custom_slot(cfg, key: str, label: str) -> None:
    custom = list(cfg.get("promptbuilder.custom_slots", []) or [])
    for c in custom:
        if c["key"] == key:
            c["label"] = label.strip()
    cfg.set("promptbuilder.custom_slots", custom)
    apply_custom_slots(cfg)


def delete_custom_slot(cfg, key: str, doc: "PromptDoc | None" = None) -> None:
    """Removes a user-created section. Any tags it held move to "extra" / "neg_unwanted", the same fallback
    parse_prompt() already uses for text it does not recognise."""
    custom = [c for c in cfg.get("promptbuilder.custom_slots", []) or [] if c["key"] != key]
    cfg.set("promptbuilder.custom_slots", custom, save=False)
    order = [k for k in (cfg.get("promptbuilder.slot_order", []) or []) if k != key]
    cfg.set("promptbuilder.slot_order", order)
    if doc is not None:
        fallback = "neg_unwanted" if key in NEGATIVE else "extra"
        doc.entries(fallback).extend(doc.entries(key))
        doc.slots.pop(key, None)
    apply_custom_slots(cfg)


def reorder_slot(cfg, key: str, before: str | None) -> None:
    """Moves `key` to sit right before `before` in the user's slot order (or to the very end when `before` is
    None or not a known slot)."""
    order = [k for k in SLOT_KEYS if k != key]
    if before is not None and before in order:
        order.insert(order.index(before), key)
    else:
        order.append(key)
    cfg.set("promptbuilder.slot_order", order)
    apply_custom_slots(cfg)


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


PREVIEW_QUALITY = "masterpiece, best quality, very aesthetic, sfw"
PREVIEW_NEGATIVE = "lowres, bad anatomy, bad hands, text, error, worst quality, jpeg artifacts, signature, watermark, nsfw"
FULL_BODY = {"clothing.outfit", "clothing.footwear", "clothing.legwear", "clothing.swimwear", "appearance.body", "pose.body_pose", "pose.action"}
WAIST_UP = {"clothing.tops", "clothing.bottoms"}
PORTRAIT = {"appearance.hair_color", "appearance.hair_length", "appearance.hairstyle", "appearance.eye_color", "appearance.eye_shape",
            "appearance.features", "appearance.age", "expression.mood", "expression.eyes_state"}
CHEST_TAGS = {"flat chest", "small breasts", "medium breasts", "large breasts"}
SKIN_TAGS = {"pale skin", "tan", "dark skin", "freckles", "mole", "mole under eye", "scar"}
NEEDS_PARTNER = {"hugging", "holding hands"}
SUBJECT_ITSELF = re.compile(r"^\d|^multiple |^crowd$|^no humans$")
NO_PICTURE_TAGS = {"nsfw", "explicit", "child"}       # tags that are never illustrated (their tile keeps the letters)
VARIED_SEED_SLOTS = {"quality", "extra"} | set(NEGATIVE)   # nothing to compare between tiles: each gets its own seed, so they are not clones


DEFAULT_CHARACTER = {"hair": "short brown hair", "eyes": "brown eyes", "top": "white t-shirt", "bottom": "pleated skirt", "shorts": "denim shorts",
                     "extra": "", "negative": "", "model": "", "seed": 12345, "size": 832, "steps": 24, "cfg": 5.5, "sampler": "Euler a"}


def character_from(data: dict | None) -> dict:
    """The standard character (the girl every tag picture is drawn on): the saved settings over the defaults."""
    out = dict(DEFAULT_CHARACTER)
    for key, value in (data or {}).items():
        if key in out and value is not None:
            try:
                out[key] = str(value).strip() if isinstance(DEFAULT_CHARACTER[key], str) else type(DEFAULT_CHARACTER[key])(value)
            except (TypeError, ValueError):
                pass                                                  # a bad value: the default stays
    return out


def _plain_look(slot: str, category: str, ch: dict | None = None) -> str:
    """The standard character, so the tiles look alike: every part of her look is left out when the tag itself is about that part."""
    ch = ch or DEFAULT_CHARACTER
    parts = []
    if not category.startswith("appearance.hair") and category != "appearance.features":
        parts.append(ch["hair"])
    if category not in ("appearance.eye_color", "appearance.eye_shape", "expression.eyes_state"):
        parts.append(ch["eyes"])
    if slot != "clothing" or category in ("clothing.headwear", "clothing.accessories", "clothing.bottoms"):
        parts.append(ch["top"])
    if category in ("clothing.footwear", "clothing.legwear"):
        parts += [ch["top"], ch["bottom"]]
    elif category == "clothing.tops":
        parts.append(ch["bottom"])
    elif category in ("pose.body_pose", "pose.action"):
        parts.append(ch["shorts"])
    parts.append(ch["extra"])
    return "".join(", " + p for p in dict.fromkeys(p for p in parts if p))


def _escape(tag: str) -> str:
    return tag.replace("(", "\\(").replace(")", "\\)")


def preview_prompt(slot: str, tag: str, category: str = "", character: dict | None = None) -> tuple[str, str]:
    """What to generate for a tag's picture: the tag on a plain subject in the shot that shows it best. `category` (the built-in
    category key, e.g. "clothing.footwear") refines the shot; without it the slot decides."""
    ch = character or DEFAULT_CHARACTER
    look = lambda: _plain_look(slot, category, ch)                # noqa: E731
    q, negative = PREVIEW_QUALITY, PREVIEW_NEGATIVE
    if ch.get("negative") and slot not in NEGATIVE:
        negative += ", " + ch["negative"]
    if category not in ("appearance.body", "clothing.swimwear"):
        negative += ", cleavage, large breasts"
    if slot in NEGATIVE:                       # what a negative tag names is shown as it is; the tile then shows what the tag keeps away
        hands = ", hands up" if slot == "neg_anatomy" else ""
        return f"{tag}, sfw, 1girl, solo{look()}{hands}, upper body, simple background", "nsfw"
    if slot == "quality":
        if tag.startswith("rating_"):          # written out, a rating tag makes the model draw an "R-18" badge and text: show a safe picture instead
            return f"sfw, 1girl, solo{look()}, upper body, simple background", "nsfw, text, watermark, logo"
        return f"({_escape(tag)}:1.3), sfw, 1girl, solo{look()}, upper body, simple background", negative
    if tag == "BREAK":
        return f"{q}, split screen, two panels, 1girl, solo{look()}, upper body, simple background", negative
    if tag == "no humans":
        return f"{q}, no humans, scenery, nature", negative
    if slot == "background" and category != "background.simple" or category == "lighting.time":
        return f"{q}, no humans, scenery, {tag}", negative
    if slot == "subject":
        if SUBJECT_ITSELF.search(tag):
            who = "" if tag in ("crowd", "no humans") else f", {ch['hair']}, {ch['top']}"
            return f"{q}, {tag}{who}, {'street, ' if tag == 'crowd' else ''}upper body, simple background", negative
        return f"{q}, 1girl, {tag}{look()}, upper body, simple background", negative
    if slot == "character":
        return f"{q}, {tag}, solo, upper body, simple background", negative
    if slot == "style":                       # the art style has to win over the usual polished look: first, stressed, no booster tags
        return f"({_escape(tag)}:1.4), sfw, best quality, 1girl, solo{look()}, upper body", negative
    who = "2girls" if tag in NEEDS_PARTNER else "1girl, solo"
    who += look()
    if tag == "from below":
        return f"{q}, {who}, {tag}, upper body, outdoors", negative + ", underwear, crotch"
    if category == "camera.shot":
        return f"{q}, {who}, {tag}, standing, outdoors", negative
    standing = ""
    if tag in CHEST_TAGS or tag in SKIN_TAGS:
        shot, bg = ("upper body" if tag in CHEST_TAGS else "portrait"), "simple background"
    elif category in FULL_BODY or (not category and slot in ("clothing", "pose")):
        shot, bg = "full body", "simple background"
        if not category.startswith("pose."):
            standing = "standing, "
            negative += ", sitting, spread legs, squatting"
    elif category in WAIST_UP:
        shot, bg = "cowboy shot", "simple background"
    elif category in PORTRAIT or (not category and slot in ("appearance", "expression")):
        shot, bg = "portrait", "simple background"
    elif slot in ("camera", "lighting"):
        return f"{q}, {who}, {tag}, standing, outdoors", negative
    else:
        shot, bg = "upper body", "simple background"
    return f"{q}, {who}, {tag}, {standing}{shot}, {bg}", negative


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
        self.apply_pack()

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

    def subtree_ids(self, node_id: int, hidden: bool = False) -> list[int]:
        ids, todo = [], [node_id]
        while todo:
            current = todo.pop()
            ids.append(current)
            todo += [r[0] for r in self.conn.execute("SELECT id FROM pb_nodes WHERE parent_id=?" + ("" if hidden else " AND hidden=0"), (current,))]
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

    def find_tag(self, text: str) -> dict | None:
        """The catalogue tag whose text matches `text` exactly (case/spacing insensitive), or None: lets a caller that has a real
        tag from somewhere else (an art's own tags) know whether it is already in the catalogue before offering to add it."""
        needle = norm(text)
        return next((r for r in self.tags(query=text) if norm(r["text"]) == needle), None)

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

    def move_tag(self, tag_id: int, node_id: int) -> bool:
        """Moves a tag into another category (its slot follows the category). False when the category already has that tag."""
        tag, node = self.tag(tag_id), self.node(node_id)
        if tag is None or node is None or tag["node_id"] == node_id:
            return False
        if self.conn.execute("SELECT 1 FROM pb_tags WHERE node_id=? AND lower(text)=lower(?) AND hidden=0 AND id<>?",
                             (node_id, tag["text"], tag_id)).fetchone():
            return False
        pos = self.conn.execute("SELECT COALESCE(MAX(position), 0) + 1 FROM pb_tags WHERE node_id=?", (node_id,)).fetchone()[0]
        with self.conn:
            self.conn.execute("UPDATE pb_tags SET node_id=?, position=? WHERE id=?", (node_id, pos, tag_id))
        return True

    def move_node(self, node_id: int, parent_id: int | None, slot: str | None = None) -> bool:
        """Makes a category a subcategory of `parent_id` (None = a category of `slot` itself). A subcategory follows its parent's slot, and
        so does everything below the moved category. False when that would put a category inside itself."""
        node = self.node(node_id)
        if node is None:
            return False
        if parent_id is not None:
            parent = self.node(parent_id)
            if parent is None or parent_id in self.subtree_ids(node_id, hidden=True):
                return False
            slot = parent["slot"]
        if not slot:
            return False
        ids = self.subtree_ids(node_id, hidden=True)
        pos = self.conn.execute("SELECT COALESCE(MAX(position), 0) + 1 FROM pb_nodes").fetchone()[0]
        with self.conn:
            self.conn.execute("UPDATE pb_nodes SET parent_id=?, position=? WHERE id=?", (parent_id, pos, node_id))
            self.conn.execute(f"UPDATE pb_nodes SET slot=? WHERE id IN ({','.join('?' * len(ids))})", [slot, *ids])
        return True

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
        self.applied_file.unlink(missing_ok=True)

    # --- the picture pack (pictures of the built-in tags that come with the app) ---------------------------------------------------

    @property
    def applied_file(self) -> Path:
        return self.root / "promptbook" / "pack_applied.json"

    @staticmethod
    def _crc32_of(path: Path) -> int:
        return zlib.crc32(path.read_bytes())

    def export_pack(self, dest: Path) -> int:
        """Writes the pictures of all built-in tags to a zip (`index.json`: tag key -> file). This is the file that is shipped with the app
        as `data/promptbook_pack.zip`. Returns the number of pictures."""
        rows = self.conn.execute("SELECT key, image FROM pb_tags WHERE key IS NOT NULL AND image <> '' ORDER BY id").fetchall()
        index: dict[str, str] = {}
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(dest.name + ".tmp")
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_STORED) as zf:                       # jpegs do not compress
            for r in rows:
                path = self.root / r["image"]
                if path.is_file():
                    name = f"{len(index) + 1:04d}.jpg"
                    zf.write(path, name)
                    index[r["key"]] = name
            zf.writestr("index.json", json.dumps({"version": 1, "pictures": index}, ensure_ascii=False, indent=1))
        tmp.replace(dest)
        return len(index)

    def apply_pack(self, pack: Path | None = None, overwrite: bool = False) -> int:
        """Gives the built-in tags the pictures of a pack. Without `overwrite` (the automatic case) a picture is only put where the user
        has none: a tag the user gave their own picture, or whose picture they removed, is left alone; a picture that came from an earlier
        pack and was not touched is replaced by the pack's newer one. Returns the number of pictures written."""
        pack = Path(pack) if pack else PACK_FILE
        if not pack.is_file():
            return 0
        try:
            applied = json.loads(self.applied_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            applied = {}
        written = 0
        try:
            with zipfile.ZipFile(pack) as zf:
                pictures = json.loads(zf.read("index.json")).get("pictures", {})
                rows = {r["key"]: r for r in self.conn.execute("SELECT id, key, image FROM pb_tags WHERE key IS NOT NULL AND hidden=0")}
                changed = False
                self.image_dir.mkdir(parents=True, exist_ok=True)
                for key, member in pictures.items():
                    row = rows.get(key)
                    if row is None:
                        continue
                    # CRC32 from the zip's central directory identifies the picture without decompressing it: on a normal, already-applied
                    # startup every key matches its stored digest and the loop below never has to read a single picture.
                    digest = f"{zf.getinfo(member).CRC:08x}"
                    dest = self.image_dir / f"{row['id']}.jpg"
                    previous = applied.get(key)
                    if not overwrite:
                        if previous == digest or previous == "":
                            continue
                        if previous is None:
                            if row["image"]:                                          # the user's own picture: never replaced
                                applied[key], changed = "", True
                                continue
                        elif not (row["image"] and dest.is_file() and f"{self._crc32_of(dest):08x}" == previous):
                            continue                                                # changed or removed by the user since
                    dest.write_bytes(zf.read(member))
                    with self.conn:
                        self.conn.execute("UPDATE pb_tags SET image=? WHERE id=?", (dest.relative_to(self.root).as_posix(), row["id"]))
                    applied[key], changed = digest, True
                    written += 1
        except (OSError, ValueError, KeyError, zipfile.BadZipFile):
            return written
        if changed:
            self.applied_file.parent.mkdir(parents=True, exist_ok=True)
            self.applied_file.write_text(json.dumps(applied), encoding="utf-8")
        return written
