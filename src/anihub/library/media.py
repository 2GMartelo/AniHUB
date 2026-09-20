"""Disk cache for full-size media opened in the viewer (so videos/GIFs can be played from a local file)."""
from __future__ import annotations

import hashlib
from pathlib import Path
from urllib.parse import unquote, urlsplit

from anihub.net.http import HttpClient

MAX_CACHE_BYTES = 1024**3


class MediaCache:
    def __init__(self, http: HttpClient, directory: Path):
        self.http = http
        self.dir = directory
        self.dir.mkdir(parents=True, exist_ok=True)

    def path_for(self, url: str) -> Path:
        suffix = Path(unquote(urlsplit(url).path)).suffix.lower()[:8]
        return self.dir / (hashlib.sha1(url.encode()).hexdigest()[:20] + suffix)

    def get(self, url: str) -> Path:
        """Blocking; returns the local path, downloading on a cache miss."""
        path = self.path_for(url)
        if not path.exists():
            self.http.download(url, path)
        return path

    def prune(self, limit: int = MAX_CACHE_BYTES) -> None:
        """Delete least recently modified files until the cache fits `limit`."""
        files = [(p.stat().st_mtime, p.stat().st_size, p) for p in self.dir.iterdir() if p.is_file()]
        total = sum(size for _, size, _ in files)
        for _, size, path in sorted(files):
            if total <= limit:
                break
            path.unlink(missing_ok=True)
            total -= size
