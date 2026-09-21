"""OST library (п. 12.1): `<library>/music/<Title>/<tracks>`; a folder is the title the tracks belong to."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

AUDIO_EXTS = {".mp3", ".flac", ".ogg", ".opus", ".m4a", ".aac", ".wav", ".wma"}


@dataclass
class Track:
    path: Path
    title: str
    number: int | None = None


@dataclass
class Album:
    name: str
    folder: Path
    tracks: list[Track]

    def __len__(self) -> int:
        return len(self.tracks)


def natural_key(text: str) -> list:
    return [int(p) if p.isdigit() else p.lower() for p in re.split(r"(\d+)", text)]


_NUMBERED = re.compile(r"^\s*(?:disc\s*\d+\W+)?(\d{1,3})\s*[-_.)\]]*\s*(.*)$", re.I)


def track_of(path: Path) -> Track:
    """'03 - Main Theme.mp3' -> number 3, title 'Main Theme'."""
    stem = path.stem
    m = _NUMBERED.match(stem)
    if m and m.group(2).strip():
        return Track(path, m.group(2).strip(), int(m.group(1)))
    return Track(path, stem.strip(), None)


def scan(root: Path) -> list[Album]:
    """Every sub-folder that holds audio files (also nested ones: the top folder is the album name)."""
    if not root.is_dir():
        return []
    albums = []
    for folder in sorted((p for p in root.iterdir() if p.is_dir()), key=lambda p: natural_key(p.name)):
        files = sorted((f for f in folder.rglob("*") if f.is_file() and f.suffix.lower() in AUDIO_EXTS),
                       key=lambda f: natural_key(f.relative_to(folder).as_posix()))
        if files:
            albums.append(Album(folder.name, folder, [track_of(f) for f in files]))
    loose = sorted((f for f in root.iterdir() if f.is_file() and f.suffix.lower() in AUDIO_EXTS), key=lambda f: natural_key(f.name))
    if loose:
        albums.append(Album("", root, [track_of(f) for f in loose]))            # files directly in music/: one nameless album
    return albums


def match_title(album: Album, titles: list[str]) -> str | None:
    """The watch-list title an album belongs to, by name (case-insensitive, either contains the other)."""
    name = album.name.lower().strip()
    if len(name) < 3:
        return None
    for t in titles:
        low = t.lower()
        if name == low or name in low or low in name:
            return t
    return None
