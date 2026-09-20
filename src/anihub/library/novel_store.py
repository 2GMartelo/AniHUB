"""The light-novel shelf: import books into the library folder, keep reading progress."""
from __future__ import annotations

import hashlib
import re
import shutil
import time
from pathlib import Path
from typing import Iterable

from PySide6.QtCore import QBuffer, QIODevice, Qt
from PySide6.QtGui import QImage

from anihub.core.db import Database
from anihub.core.paths import LibraryPaths
from anihub.library.novels import BOOK_EXTS, BookError, open_book

COVER_HEIGHT = 480


def _safe(name: str) -> str:
    return re.sub(r"[^\w.-]", "_", name)[:80]


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def collect_books(paths: Iterable[Path]) -> list[Path]:
    """Files and folders (recursively) -> book files, sorted, without duplicates."""
    found: dict[Path, None] = {}
    for p in map(Path, paths):
        for f in (p.rglob("*") if p.is_dir() else [p]):
            if f.is_file() and f.suffix.lstrip(".").lower() in BOOK_EXTS:
                found[f] = None
    return sorted(found)


def cover_jpeg(data: bytes | None) -> bytes | None:
    """Scale a cover down and re-encode it as JPEG (covers of published books can be huge)."""
    if not data:
        return None
    image = QImage.fromData(data)
    if image.isNull():
        return None
    if image.height() > COVER_HEIGHT:
        image = image.scaledToHeight(COVER_HEIGHT, Qt.TransformationMode.SmoothTransformation)
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    image.convertToFormat(QImage.Format.Format_RGB32).save(buf, "JPEG", 85)
    return bytes(buf.data())


class NovelShelf:
    def __init__(self, db: Database, paths: LibraryPaths):
        self.db, self.paths = db, paths

    def import_books(self, files: Iterable[Path], progress=None) -> dict[str, int]:
        files = list(files)
        counts = {"saved": 0, "duplicate": 0, "failed": 0}
        for i, src in enumerate(files, 1):
            try:
                counts[self.import_one(Path(src))] += 1
            except Exception:  # noqa: BLE001 - one broken file must not stop the batch
                counts["failed"] += 1
            if progress:
                progress(i, len(files))
        return counts

    def import_one(self, src: Path) -> str:
        sha = _sha256(src)
        if self.db.novel_by_hash(sha):
            return "duplicate"
        book = open_book(src)            # parses first: a file that is not a readable book is rejected before it is copied
        try:
            if not len(book):
                raise BookError("no chapters")
            self.paths.novels.mkdir(parents=True, exist_ok=True)
            dest = self.paths.novels / f"{sha[:12]}_{_safe(src.stem)}{src.suffix.lower()}"
            if not dest.exists():
                shutil.copy2(src, dest)
            novel_id = self.db.novel_add(title=book.title or src.stem, author=book.author or None,
                                         path=dest.relative_to(self.paths.root).as_posix(), ext=src.suffix.lstrip(".").lower(),
                                         sha256=sha, chapters=len(book))
            jpeg = cover_jpeg(book.cover)
            if jpeg:
                cover = self.paths.novels / "covers" / f"{novel_id}.jpg"
                cover.parent.mkdir(parents=True, exist_ok=True)
                cover.write_bytes(jpeg)
                self.db.novel_update(novel_id, cover=cover.relative_to(self.paths.root).as_posix())
        finally:
            book.close()
        return "saved"

    def file_of(self, row) -> Path:
        return self.paths.root / row["path"]

    def cover_of(self, row) -> Path | None:
        return self.paths.root / row["cover"] if row["cover"] else None

    def save_progress(self, novel_id: int, chapter_index: int, scroll: float, chapters: int) -> None:
        """Called while reading. The book counts as finished when its last chapter is read to the end."""
        row = self.db.novel_get(novel_id)
        reached_end = chapter_index >= chapters - 1 and scroll >= 0.97
        finished = 1 if (reached_end or (row is not None and row["finished"])) else 0        # rereading does not undo it
        self.db.novel_update(novel_id, chapter_index=chapter_index, scroll=max(0.0, min(scroll, 1.0)),
                             last_read_at=time.time(), finished=finished)

    def delete(self, novel_id: int) -> None:
        row = self.db.novel_get(novel_id)
        if row is None:
            return
        self.db.novel_delete(novel_id)
        for rel in (row["path"], row["cover"]):
            if rel:
                (self.paths.root / rel).unlink(missing_ok=True)
