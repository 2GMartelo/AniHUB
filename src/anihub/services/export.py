"""Export and sharing (п. 6.16 / 6.18): a pack another AniHUB can import, or a static HTML gallery anyone can open."""
from __future__ import annotations

import html
import json
import re
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage

from anihub import __version__
from anihub.core.db import Database
from anihub.core.paths import LibraryPaths

PACK_FORMAT = 1
PACK_JSON = "pack.json"
IMAGE_EXTS = {"png", "jpg", "jpeg", "webp", "gif", "bmp"}
THUMB = 360


class ExportError(Exception):
    pass


def _safe(name: str) -> str:
    return re.sub(r"[^\w.\-]", "_", name)[:60] or "item"


def _rows(db: Database, paths: LibraryPaths, item_ids: list[int]):
    rows = [r for r in db.get_items(item_ids) if r["trashed_at"] is None and (paths.root / r["path"]).is_file()]
    if not rows:
        raise ExportError("nothing to export: no items with files")
    return sorted(rows, key=lambda r: r["id"])


def export_pack(db: Database, paths: LibraryPaths, item_ids: list[int], dest: Path, name: str,
                progress: Callable[[int, int], None] | None = None) -> int:
    """A zip with the files and pack.json (tags, rating, author, source...). Returns how many items went in."""
    rows = _rows(db, paths, item_ids)
    items = []
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_STORED) as z:           # pictures are compressed already
        for i, r in enumerate(rows, 1):
            src = paths.root / r["path"]
            arc = f"files/{r['id']}_{_safe(src.name)}"
            z.write(src, arc)
            items.append({"file": arc, "kind": r["kind"], "rating": r["rating"], "author": r["author"], "source_site": r["source_site"],
                          "source_post_id": r["source_post_id"], "source_url": r["source_url"], "page_url": r["page_url"],
                          "stars": r["stars"], "favorite": r["favorite"], "tags": [list(t) for t in db.item_tags_categorized(r["id"])]})
            if progress:
                progress(i, len(rows))
        z.writestr(PACK_JSON, json.dumps({"format": PACK_FORMAT, "app_version": __version__, "name": name, "items": items},
                                         ensure_ascii=False, indent=1))
    return len(rows)


def import_pack(db: Database, library, zip_path: Path, progress: Callable[[int, int], None] | None = None) -> dict:
    """Adds a pack to the library (duplicates by content are skipped but still get the pack's collection). Returns
    {'name', 'saved', 'duplicate', 'failed', 'collection_id'}."""
    try:
        z = zipfile.ZipFile(zip_path)
        meta = json.loads(z.read(PACK_JSON))
    except (zipfile.BadZipFile, KeyError, ValueError) as exc:
        raise ExportError("this is not an AniHUB pack") from exc
    if meta.get("format") != PACK_FORMAT:
        raise ExportError(f"unsupported pack format: {meta.get('format')}")
    name = str(meta.get("name") or zip_path.stem)
    counts = {"saved": 0, "duplicate": 0, "failed": 0}
    with z, tempfile.TemporaryDirectory() as tmp:
        collection = next((c["id"] for c in db.collections("art") if c["name"] == name), None) or db.create_collection(name, "art")
        entries = meta.get("items", [])
        for i, entry in enumerate(entries, 1):
            try:
                arc = entry["file"]
                if arc not in z.namelist() or arc.startswith(("/", "..")) or ".." in Path(arc).parts:
                    raise ValueError("bad path in pack")
                extracted = Path(tmp) / Path(arc).name
                with z.open(arc) as src, extracted.open("wb") as out:
                    shutil.copyfileobj(src, out)
                sha = library_sha(extracted)
                item = db.find_by_hash(sha)
                outcome = "duplicate"
                if item is None:
                    result = library.import_files([extracted], rating=entry.get("rating") or "general", use_tagger=False)
                    item = db.find_by_hash(sha)
                    outcome = "saved" if result["saved"] and item is not None else "failed"
                counts[outcome] += 1
                if item is None:
                    continue
                if outcome == "saved":
                    _merge_metadata(db, item["id"], entry)
                db.add_to_collection([item["id"]], collection)
            except Exception:  # noqa: BLE001 - one bad entry must not stop the rest
                counts["failed"] += 1
            if progress:
                progress(i, len(entries))
    return {"name": name, "collection_id": collection, **counts}


def library_sha(path: Path) -> str:
    from anihub.library.service import _sha256

    return _sha256(path)


def _merge_metadata(db: Database, item_id: int, entry: dict) -> None:
    """Tags, stars, favourite, rating, author and source links of a packed item onto the freshly imported one."""
    tags = [(str(t[0]), str(t[1]) if len(t) > 1 else "general") for t in entry.get("tags", []) if t]
    if tags:
        db.add_tags([item_id], tags)
    if entry.get("stars"):
        db.set_field([item_id], "stars", int(entry["stars"]))
    if entry.get("favorite"):
        db.set_field([item_id], "favorite", 1)
    if entry.get("rating"):
        db.set_field([item_id], "rating", entry["rating"])
    if entry.get("author"):
        db.update_fields(item_id, author=entry["author"])
    links = {k: entry[k] for k in ("source_url", "page_url") if entry.get(k)}
    if links:
        with db.conn:
            db.conn.execute("UPDATE items SET " + ", ".join(f"{k}=?" for k in links) + " WHERE id=?", [*links.values(), item_id])


def _thumb_bytes(path: Path) -> bytes | None:
    from PySide6.QtCore import QBuffer, QIODevice

    image = QImage(str(path))
    if image.isNull():
        return None
    if max(image.width(), image.height()) > THUMB:
        image = image.scaled(THUMB, THUMB, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    image.convertToFormat(QImage.Format.Format_RGB32).save(buf, "JPEG", 82)
    return bytes(buf.data())


PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title><style>
body{{margin:0;background:#101216;color:#e8ebf1;font:15px system-ui,sans-serif}}
header{{padding:22px 28px}}h1{{margin:0 0 4px;font-size:22px}}p.sub{{margin:0;color:#a0a9b7}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:12px;padding:0 28px 40px}}
.grid a{{display:block;background:#1a1e26;border-radius:10px;overflow:hidden}}.grid img{{width:100%;height:240px;object-fit:cover;display:block}}
.grid span{{display:block;padding:6px 10px;font-size:12px;color:#a0a9b7;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
#box{{position:fixed;inset:0;background:rgba(0,0,0,.92);display:none;align-items:center;justify-content:center}}
#box img{{max-width:96vw;max-height:94vh}}
</style></head><body><header><h1>{title}</h1><p class="sub">{count} pictures · made with AniHUB {version}</p></header>
<div class="grid">{cards}</div><div id="box" onclick="this.style.display='none'"><img id="big" alt=""></div>
<script>document.querySelectorAll('.grid a').forEach(a=>a.addEventListener('click',e=>{{e.preventDefault();
document.getElementById('big').src=a.href;document.getElementById('box').style.display='flex'}}));
document.addEventListener('keydown',e=>{{if(e.key==='Escape')document.getElementById('box').style.display='none'}});</script></body></html>"""


def export_html(db: Database, paths: LibraryPaths, item_ids: list[int], dest: Path, title: str,
                progress: Callable[[int, int], None] | None = None) -> int:
    """A zip with index.html, small previews and the pictures: unzip anywhere and open index.html. Videos are left out."""
    rows = [r for r in _rows(db, paths, item_ids) if (r["ext"] or "").lower() in IMAGE_EXTS]
    if not rows:
        raise ExportError("nothing to export: no pictures")
    cards = []
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_STORED) as z:
        for i, r in enumerate(rows, 1):
            src = paths.root / r["path"]
            stem = f"{r['id']}_{_safe(src.stem)}"
            full, thumb = f"images/{stem}{src.suffix.lower()}", f"thumbs/{stem}.jpg"
            z.write(src, full)
            data = _thumb_bytes(src)
            z.writestr(thumb, data if data else src.read_bytes())
            tags = ", ".join(t for t, _ in db.item_tags_categorized(r["id"])[:8])
            cards.append(f'<a href="{full}"><img loading="lazy" src="{thumb}" alt=""><span>{html.escape(tags or src.name)}</span></a>')
            if progress:
                progress(i, len(rows))
        z.writestr("index.html", PAGE.format(title=html.escape(title), count=len(rows), version=__version__, cards="".join(cards)))
    return len(rows)
