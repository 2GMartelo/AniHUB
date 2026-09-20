"""Local files as an anime source: `<library>/anime/<Title>/<episode files>` (mkv, mp4, avi, webm...).

Episode numbers come from the file names ('Show - 05 [1080p].mkv' -> 5); files without a number keep their sorted order.
"""
from __future__ import annotations

import re
from pathlib import Path

from anihub.sources.anime.base import AnimeEntry, AnimeSource, AnimeSourceError, Episode, Stream

VIDEO_EXTS = {".mkv", ".mp4", ".avi", ".webm", ".mov", ".m4v", ".ts", ".flv"}
_NOISE = re.compile(r"\b(?:\d{3,4}p|\d{3,4}x\d{3,4}|[xh]\.?26[45]|hevc|10-?bit|8-?bit|aac|flac|ac3|web-?dl|web-?rip|bd-?rip|bluray|hdr)\b"
                    r"|\[[^\]]*\]|\([^)]*\)|\bv\d\b", re.I)
_NUMBER = re.compile(r"(?<![\w.])(\d{1,4})(?:\.(\d))?(?![\w])")


def episode_number(stem: str) -> float | None:
    """The episode number in a file name, ignoring resolutions, codecs, hashes and years in brackets."""
    text = _NOISE.sub(" ", stem)
    explicit = re.search(r"(?:\bs\d{1,2}e|\bep?\.?\s*|\bepisode\s*|серия\s*|\b#)(\d{1,4}(?:\.\d)?)", text, re.I)
    if explicit:
        return float(explicit.group(1))
    found = _NUMBER.findall(text)
    if not found:
        return None
    whole, frac = found[-1]
    return float(f"{whole}.{frac}" if frac else whole)


class LocalAnime(AnimeSource):
    name = "local"
    title = "Локальные файлы"
    needs_network = False

    def __init__(self, http, cfg, root: Path):
        super().__init__(http, cfg)
        self.root = Path(root)

    def _titles(self) -> list[Path]:
        if not self.root.exists():
            return []
        return sorted((p for p in self.root.iterdir() if p.is_dir()), key=lambda p: p.name.lower())

    def search(self, query: str, page: int = 1) -> tuple[list[AnimeEntry], bool]:
        if page > 1:
            return [], False
        needle = query.strip().lower()
        found = [AnimeEntry(id=p.name, title=p.name, url=str(p)) for p in self._titles() if needle in p.name.lower()]
        return found, False

    def _files(self, entry: AnimeEntry) -> list[Path]:
        folder = self.root / entry.id
        if not folder.is_dir():
            raise AnimeSourceError(f"Папка не найдена: {folder}")
        return sorted((f for f in folder.rglob("*") if f.is_file() and f.suffix.lower() in VIDEO_EXTS),
                      key=lambda f: f.relative_to(folder).as_posix().lower())

    def episodes(self, entry: AnimeEntry) -> list[Episode]:
        files = self._files(entry)
        numbers = [episode_number(f.stem) for f in files]
        if len({n for n in numbers if n is not None}) != len(files):        # missing or repeated numbers: fall back to order
            numbers = [float(i + 1) for i in range(len(files))]
        episodes = [Episode(id=f.relative_to(self.root / entry.id).as_posix(), number=n, title=f.stem)
                    for f, n in zip(files, numbers)]
        return sorted(episodes, key=lambda e: e.number)

    def streams(self, entry: AnimeEntry, episode: Episode) -> list[Stream]:
        path = self.root / entry.id / episode.id
        if not path.is_file():
            raise AnimeSourceError(f"Файл не найден: {path}")
        return [Stream(url=str(path), label=path.suffix.lstrip(".").upper())]
