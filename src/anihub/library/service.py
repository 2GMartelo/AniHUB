"""Library operations: saving posts and generations, importing folders, the trash, duplicate detection."""
from __future__ import annotations

import hashlib
import json
import logging
import re
import shutil
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable

from PySide6.QtGui import QImage

from anihub.core.config import Config
from anihub.core.db import Database
from anihub.core.paths import LibraryPaths
from anihub.library.phash import dhash, find_near, similar_groups
from anihub.library.rules import RuleEngine
from anihub.net.http import HttpClient
from anihub.services.generation import prompt_tags
from anihub.sources.base import Post, url_ext

log = logging.getLogger(__name__)

IMAGE_EXTS = {"png", "jpg", "jpeg", "webp", "gif", "bmp", "tif", "tiff"}
VIDEO_EXTS = {"mp4", "webm", "mkv", "mov"}
NEAR_THRESHOLD = 6


@dataclass
class SaveResult:
    status: str  # saved | duplicate | failed
    item_id: int | None = None
    error: str = ""
    similar: list[int] = field(default_factory=list)  # ids of visually similar items that already existed


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _safe(name: str) -> str:
    return re.sub(r"[^\w.-]", "_", name)


def collect_image_files(paths: Iterable[Path]) -> list[Path]:
    """Files and folders (recursively) -> image files, sorted, without duplicates."""
    found: dict[Path, None] = {}
    for p in paths:
        p = Path(p)
        candidates = p.rglob("*") if p.is_dir() else [p]
        for f in candidates:
            if f.is_file() and f.suffix.lstrip(".").lower() in IMAGE_EXTS:
                found[f] = None
    return sorted(found)


class LibraryService:
    def __init__(self, db: Database, paths: LibraryPaths, http: HttpClient, cfg: Config | None = None):
        self.db = db
        self.paths = paths
        self.http = http
        self.cfg = cfg
        self.tagger = None  # an Autotagger when enabled and its model is installed (set by the app context)
        self.rules = RuleEngine(db)

    # --- settings --------------------------------------------------------------

    def _opt(self, key: str, default):
        return self.cfg.get(key, default) if self.cfg else default

    def _near_mode(self) -> str:
        return self._opt("library.near_dedup", "warn")  # warn | skip | off

    def _near(self, phash: int | None, kind: str) -> list[int]:
        if phash is None or self._near_mode() == "off":
            return []
        return find_near(self.db.phash_rows(kind), phash, int(self._opt("library.near_threshold", NEAR_THRESHOLD)))

    # --- saving ----------------------------------------------------------------

    def _finish_new_item(self, item_id: int, kind: str) -> None:
        default = self.db.default_category(kind)
        if default is not None:
            self.db.set_item_categories([item_id], add=[default])
        self._apply_rules([item_id])

    def _apply_rules(self, item_ids: list[int]) -> None:
        """Automatic rules (ТЗ 6.4) run on every new item; a broken rule must never lose a download."""
        if not self._opt("library.auto_rules", True):
            return
        try:
            self.rules.apply(item_ids)
        except Exception as exc:  # noqa: BLE001
            log.warning("auto rules failed for %s: %s", item_ids, exc)

    def _autotag(self, path: Path, ext: str):
        if self.tagger is None or ext.lower() in VIDEO_EXTS:
            return None
        try:
            return self.tagger.tag_file(path)
        except Exception as exc:  # noqa: BLE001 - a tagging failure must never lose the download
            log.warning("autotag failed for %s: %s", path, exc)
            return None

    def save_post(self, post: Post) -> SaveResult:
        existing = self.db.find_by_source(post.site, post.id)
        if existing is not None:
            if existing["trashed_at"] is None:
                return SaveResult("duplicate")
            self.restore([existing["id"]])  # the user saves something they once trashed: bring it back
            return SaveResult("saved", existing["id"])
        dest: Path | None = None
        try:
            post.ensure_file()  # lazy sources (Zerochan) learn the real file URL here
            ext = _safe(post.ext or url_ext(post.file_url) or "bin")
            rel = Path("arts") / _safe(post.site) / f"{_safe(post.site)}_{_safe(post.id)}.{ext}"
            dest = self.paths.root / rel
            self.http.download(post.file_url, dest)
            sha = _sha256(dest)
            if self.db.find_by_hash(sha):
                dest.unlink(missing_ok=True)
                return SaveResult("duplicate")
            image = QImage(str(dest)) if ext.lower() not in VIDEO_EXTS else QImage()
            phash = dhash(image)
            similar = self._near(phash, "art")
            if similar and self._near_mode() == "skip":
                dest.unlink(missing_ok=True)
                return SaveResult("duplicate", similar=similar)
            tags = list(post.tags)
            if not tags:  # e.g. Twitter: nothing came with the file, ask the tagger
                tagged = self._autotag(dest, ext)
                if tagged:
                    tags = tagged.tags
            item_id = self.db.add_item(
                tags=tags,
                kind="art",
                path=rel.as_posix(),
                sha256=sha,
                phash=phash,
                width=post.width or (image.width() or None),
                height=post.height or (image.height() or None),
                size=dest.stat().st_size,
                ext=ext,
                rating=post.rating,
                score=post.score,
                source_site=post.site,
                source_post_id=post.id,
                source_url=post.source,
                page_url=post.page_url,
                author=post.author or None,
            )
        except Exception as exc:  # noqa: BLE001 - reported to the user per item
            log.warning("save_post failed for %s/%s: %s", post.site, post.id, exc)
            if dest is not None:
                dest.unlink(missing_ok=True)
            return SaveResult("failed", error=str(exc))
        self._finish_new_item(item_id, "art")
        if post.badge and ext not in ("gif",):
            self._save_preview(item_id, post)
        return SaveResult("saved", item_id, similar=similar)

    def save_generation(self, path: Path, meta: dict, rating: str = "general") -> SaveResult:
        """Add an already-written SD image (inside the library folder) to the library, with its parameters."""
        try:
            sha = _sha256(path)
            if self.db.find_by_hash(sha):
                return SaveResult("duplicate")
            item_id = self.db.add_item(
                tags=[(t, "general") for t in prompt_tags(meta.get("prompt", ""))],
                kind="sd",
                path=path.resolve().relative_to(self.paths.root.resolve()).as_posix(),
                sha256=sha,
                phash=dhash(QImage(str(path))),
                width=meta.get("width"),
                height=meta.get("height"),
                size=path.stat().st_size,
                ext=path.suffix.lstrip(".").lower(),
                rating=rating,
                source_site="forge",
                source_post_id=sha[:16],
                author=None,
                meta=json.dumps(meta, ensure_ascii=False),
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("save_generation failed for %s: %s", path, exc)
            return SaveResult("failed", error=str(exc))
        self._finish_new_item(item_id, "sd")
        return SaveResult("saved", item_id)

    def _save_preview(self, item_id: int, post: Post) -> None:
        """Video files cannot be thumbnailed by Qt, so keep the site's preview image next to the cache."""
        try:
            self.paths.preview_file(item_id).write_bytes(self.http.get_bytes(post.preview_url))
        except Exception as exc:  # noqa: BLE001 - a missing thumbnail must not fail the save
            log.info("no preview for %s/%s: %s", post.site, post.id, exc)

    def save_posts(
        self, posts: Iterable[Post], progress: Callable[[int, int], None] | None = None
    ) -> dict[str, int]:
        posts = list(posts)
        counts = {"saved": 0, "duplicate": 0, "failed": 0, "similar": 0}
        for i, post in enumerate(posts, 1):
            result = self.save_post(post)
            counts[result.status] += 1
            if result.status == "saved" and result.similar:
                counts["similar"] += 1
            if progress:
                progress(i, len(posts))
        return counts

    # --- importing local files -------------------------------------------------

    def import_files(self, files: Iterable[Path], *, rating: str = "general", use_tagger: bool = True,
                     category_id: int | None = None, progress: Callable[[int, int], None] | None = None,
                     cancelled: Callable[[], bool] | None = None) -> dict[str, int]:
        """Copies image files into the library (arts/local/<yyyy-mm>/), with dedup, hashing and autotagging."""
        files = list(files)
        counts = {"saved": 0, "duplicate": 0, "failed": 0, "similar": 0, "cancelled": 0}
        folder = self.paths.arts / "local" / datetime.now().strftime("%Y-%m")
        for i, src in enumerate(files, 1):
            if cancelled and cancelled():
                counts["cancelled"] = len(files) - i + 1
                break
            try:
                counts[self._import_one(src, folder, rating, use_tagger, category_id, counts)] += 1
            except Exception as exc:  # noqa: BLE001
                log.warning("import failed for %s: %s", src, exc)
                counts["failed"] += 1
            if progress:
                progress(i, len(files))
        return counts

    def _import_one(self, src: Path, folder: Path, rating: str, use_tagger: bool, category_id: int | None,
                    counts: dict[str, int]) -> str:
        sha = _sha256(src)
        if self.db.find_by_hash(sha):
            return "duplicate"
        image = QImage(str(src))
        if image.isNull():
            return "failed"
        phash = dhash(image)
        similar = self._near(phash, "art")
        if similar and self._near_mode() == "skip":
            return "duplicate"
        folder.mkdir(parents=True, exist_ok=True)
        dest = folder / _safe(src.name)
        n = 1
        while dest.exists():
            n += 1
            dest = folder / f"{_safe(src.stem)}_{n}{src.suffix.lower()}"
        shutil.copy2(src, dest)
        tags: list[tuple[str, str]] = []
        item_rating = rating
        if use_tagger and self.tagger is not None:
            tagged = self._autotag(dest, dest.suffix.lstrip("."))
            if tagged:
                tags, item_rating = tagged.tags, tagged.rating
        item_id = self.db.add_item(
            tags=tags, kind="art", path=dest.relative_to(self.paths.root).as_posix(), sha256=sha, phash=phash,
            width=image.width(), height=image.height(), size=dest.stat().st_size,
            ext=dest.suffix.lstrip(".").lower(), rating=item_rating, source_site="local",
            source_post_id=sha[:16], source_url=str(src))
        if category_id is not None:
            self.db.set_item_categories([item_id], add=[category_id])
            self._apply_rules([item_id])
        else:
            self._finish_new_item(item_id, "art")
        if similar:
            counts["similar"] += 1
        return "saved"

    # --- tagging existing items -------------------------------------------------

    def autotag_items(self, item_ids: Iterable[int], *, set_rating: bool = False,
                      progress: Callable[[int, int], None] | None = None) -> int:
        """Run the autotagger over existing items and add the tags it finds. Returns how many were tagged."""
        if self.tagger is None:
            return 0
        rows = self.db.get_items(item_ids)
        done = 0
        for i, row in enumerate(rows, 1):
            result = self._autotag(self.paths.root / row["path"], row["ext"] or "")
            if result:
                self.db.add_tags([row["id"]], result.tags)
                if set_rating:
                    self.db.set_field([row["id"]], "rating", result.rating)
                done += 1
            if progress:
                progress(i, len(rows))
        if done:
            self._apply_rules([r["id"] for r in rows])  # the new tags may satisfy a rule
        return done

    # --- trash -----------------------------------------------------------------

    def _trash_file(self, row) -> Path:
        return self.paths.trash / f"{row['id']}{Path(row['path']).suffix}"

    def trash(self, item_ids: Iterable[int]) -> int:
        """Move to the in-app trash: the file goes to <library>/trash, the row stays (restorable)."""
        moved = 0
        for row in self.db.get_items(item_ids):
            if row["trashed_at"] is not None:
                continue
            src, dst = self.paths.root / row["path"], None
            if src.exists():
                dst = self._trash_file(row)
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(src), str(dst))
            self.db.update_fields(row["id"], trashed_at=time.time(), trash_path=dst.relative_to(self.paths.root).as_posix() if dst else None)
            moved += 1
        return moved

    def restore(self, item_ids: Iterable[int]) -> int:
        restored = 0
        for row in self.db.get_items(item_ids):
            if row["trashed_at"] is None:
                continue
            if row["trash_path"]:
                src, dst = self.paths.root / row["trash_path"], self.paths.root / row["path"]
                if src.exists():
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(src), str(dst))
            self.db.update_fields(row["id"], trashed_at=None, trash_path=None)
            restored += 1
        return restored

    def purge(self, item_ids: Iterable[int]) -> int:
        """Delete for good: files, thumbnails and the row."""
        rows = self.db.get_items(item_ids)
        for row in rows:
            for rel in (row["trash_path"], row["path"] if row["trashed_at"] is None else None):
                if rel:
                    (self.paths.root / rel).unlink(missing_ok=True)
            for thumb in self.paths.thumbs.glob(f"{row['id']}_*.jpg"):
                thumb.unlink(missing_ok=True)
            self.paths.preview_file(row["id"]).unlink(missing_ok=True)
        self.db.delete_items(r["id"] for r in rows)
        return len(rows)

    def empty_trash(self, kind: str | None = None) -> int:
        return self.purge(r["id"] for r in self.db.all_trashed(kind))

    def auto_purge(self, days: float | None = None) -> int:
        """Called on startup: anything that sat in the trash longer than `days` (default 7) is deleted."""
        days = self._opt("library.trash_days", 7) if days is None else days
        if not days:
            return 0
        return self.purge(r["id"] for r in self.db.trashed_before(time.time() - days * 86400))

    # --- duplicates ------------------------------------------------------------

    def backfill_phash(self, kind: str = "art", progress: Callable[[int, int], None] | None = None) -> int:
        rows = self.db.items_without_phash(kind)
        for i, row in enumerate(rows, 1):
            path = self.paths.root / row["path"]
            if path.exists():
                self.db.update_fields(row["id"], phash=dhash(QImage(str(path))))
            if progress:
                progress(i, len(rows))
        return len(rows)

    def duplicate_groups(self, kind: str = "art", threshold: int = NEAR_THRESHOLD,
                         progress: Callable[[int, int], None] | None = None) -> list[list]:
        """Groups of visually similar items (rows), the largest file of each group first."""
        self.backfill_phash(kind, progress)
        groups = similar_groups(self.db.phash_rows(kind), threshold)
        result = []
        for ids in groups:
            rows = sorted(self.db.get_items(ids), key=lambda r: (r["size"] or 0), reverse=True)
            result.append(rows)
        result.sort(key=lambda g: -len(g))
        return result
