"""Reading light novels from online sources: a Book-like object that fetches chapters lazily, and download to EPUB."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict
from pathlib import Path

from anihub.library.epub_writer import write_epub
from anihub.library.novels import BookError
from anihub.sources.novels.base import NovelChapter, NovelEntry, NovelSource

_IMG_SRC = re.compile(r'(<img\b[^>]*?\bsrc=)"([^"]+)"', re.I)
_DROP = re.compile(r"<(script|style|iframe|object|embed)\b.*?</\1>", re.S | re.I)
_HANDLERS = re.compile(r'\s(?:on\w+|style)="[^"]*"', re.I)
MAX_IMAGES = 40


def remote_json(entry: NovelEntry, chapters: list[NovelChapter]) -> str:
    return json.dumps({"entry": asdict(entry), "chapters": [asdict(c) for c in chapters]}, ensure_ascii=False)


def parse_remote(text: str) -> tuple[NovelEntry, list[NovelChapter]]:
    data = json.loads(text)
    return NovelEntry(**data["entry"]), [NovelChapter(**c) for c in data["chapters"]]


class OnlineBook:
    """Same surface as library.novels.Book, except that reading a chapter that is not cached yet needs the network:
    `fetch(i)` does that (call it from a worker thread), `chapter_html(i)` then returns the cached text."""

    remote = True

    def __init__(self, source: NovelSource, entry: NovelEntry, chapters: list[NovelChapter], http):
        self.source, self.entry, self.chapters, self.http = source, entry, chapters, http
        self.title, self.author, self.cover = entry.title, entry.author, None
        self.titles = [c.title for c in chapters]
        self._html: dict[int, str] = {}
        self._images: dict[str, bytes] = {}

    def __len__(self) -> int:
        return len(self.chapters)

    def cached(self, index: int) -> bool:
        return index in self._html

    def fetch(self, index: int) -> None:
        """Download chapter `index` with its pictures (blocking)."""
        if index in self._html or not 0 <= index < len(self.chapters):
            return
        body = self.source.chapter_html(self.entry, self.chapters[index])
        body, pictures = self.localise_images(body, f"c{index}")
        self._images.update(pictures)
        self._html[index] = body

    def localise_images(self, body: str, prefix: str) -> tuple[str, dict[str, bytes]]:
        """Cleans the HTML and replaces picture addresses by `book:<name>`; the pictures are downloaded (failures are dropped)."""
        body = _HANDLERS.sub("", _DROP.sub("", body))
        pictures: dict[str, bytes] = {}

        def repl(m: re.Match) -> str:
            url = m.group(2)
            if not url.startswith("http") or len(pictures) >= MAX_IMAGES:
                return ""
            name = f"images/{prefix}_{hashlib.sha1(url.encode()).hexdigest()[:10]}.{(url.rsplit('.', 1)[-1] or 'jpg')[:4]}"
            try:
                pictures[name] = self.http.get_bytes(url)
            except Exception:  # noqa: BLE001 - a missing picture must not lose the chapter
                return ""
            return f'{m.group(1)}"book:{name}"'

        body = _IMG_SRC.sub(repl, body)
        body = re.sub(r"<img\b(?![^>]*\bsrc=)[^>]*>", "", body, flags=re.I)              # pictures we could not fetch
        return body, pictures

    def chapter_html(self, index: int) -> str:
        if index not in self._html:
            raise BookError("chapter not loaded yet")
        return self._html[index]

    def resource(self, path: str) -> bytes | None:
        return self._images.get(path.removeprefix("book:"))

    def close(self) -> None:
        self._html.clear()
        self._images.clear()


def open_online(sources: dict, http, row) -> OnlineBook:
    """The shelf row of an online novel -> a readable book. Fails clearly when the source plugin is gone."""
    source = sources.get(row["source"])
    if source is None:
        raise BookError(f"the source '{row['source']}' is not installed")
    entry, chapters = parse_remote(row["remote"])
    return OnlineBook(source, entry, chapters, http)


def download_epub(book: OnlineBook, dest: Path, progress=None, cancelled=None) -> Path:
    """Every chapter of `book` -> one EPUB at `dest` (with pictures and the cover). progress(done, total)."""
    chapters: list[tuple[str, str]] = []
    images: dict[str, bytes] = {}
    total = len(book)
    for i in range(total):
        if cancelled and cancelled():
            raise BookError("cancelled")
        if not book.cached(i):
            book.fetch(i)
        body = book.chapter_html(i)
        pictures = {name: book.resource(name) for name in re.findall(r'book:(images/[^"]+)', body)}
        images.update({n: d for n, d in pictures.items() if d})
        chapters.append((book.titles[i], body.replace('"book:images/', '"images/')))
        if progress:
            progress(i + 1, total)
    cover = None
    if book.entry.cover:
        try:
            cover = book.http.get_bytes(book.entry.cover)
        except Exception:  # noqa: BLE001
            cover = None
    return write_epub(dest, book.title, book.author, chapters, cover, images)
