"""Library folder layout. Files live on disk; the DB only stores the index and metadata."""
from __future__ import annotations

from pathlib import Path


class LibraryPaths:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.arts = self.root / "arts"
        self.manga = self.root / "manga"
        self.sd = self.root / "sd"
        self.novels = self.root / "novels"
        self.anime = self.root / "anime"
        self.trash = self.root / "trash"
        self.cache = self.root / "cache"
        self.thumbs = self.cache / "thumbs"
        self.media = self.cache / "media"
        self.db_file = self.root / "db" / "anihub.db"

    def ensure(self) -> None:
        for p in (self.arts, self.manga, self.sd, self.novels, self.novels / "covers", self.anime, self.trash, self.thumbs, self.media, self.db_file.parent):
            p.mkdir(parents=True, exist_ok=True)

    def preview_file(self, item_id: int) -> Path:
        """Site preview image kept for items Qt cannot thumbnail (video)."""
        return self.thumbs / f"preview_{item_id}.jpg"
