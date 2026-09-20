"""Source plugin interface. A source turns a tag query into a page of Post objects."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Callable

from anihub.core.config import Config
from anihub.net.http import HttpClient

RATINGS = ("general", "sensitive", "questionable", "explicit")
VIDEO_EXTS = {"mp4", "webm", "mkv", "mov"}
ANIMATED_BADGES = {"mp4": "▶", "webm": "▶", "mkv": "▶", "mov": "▶", "zip": "▶", "gif": "GIF"}


class SourceError(Exception):
    """User-presentable error from a source."""


def badge_for_ext(ext: str) -> str:
    """Short overlay text for thumbnails of animated / video posts (empty for still images)."""
    return ANIMATED_BADGES.get((ext or "").lower(), "")


def url_ext(url: str) -> str:
    return url.rsplit("/", 1)[-1].rsplit(".", 1)[-1].split("?")[0].lower() if "." in url.rsplit("/", 1)[-1] else ""


@dataclass
class Post:
    site: str
    id: str
    file_url: str
    preview_url: str
    sample_url: str = ""
    page_url: str = ""
    rating: str = "general"
    tags: list[tuple[str, str]] = field(default_factory=list)  # (name, category)
    author: str = ""
    source: str = ""
    width: int = 0
    height: int = 0
    ext: str = ""
    score: int = 0
    # Sources whose listing lacks the file URL (e.g. Zerochan) fill it lazily through this hook.
    resolver: Callable[["Post"], None] | None = field(default=None, repr=False, compare=False)

    @property
    def tag_names(self) -> list[str]:
        return [name for name, _ in self.tags]

    @property
    def badge(self) -> str:
        return badge_for_ext(self.ext)

    def ensure_file(self) -> None:
        """Blocking network call for lazy sources; call from a worker thread."""
        if not self.file_url and self.resolver:
            self.resolver(self)

    def display_url(self) -> str:
        """What the viewer should fetch: a sample for big stills, the file itself for video/gif."""
        self.ensure_file()
        ext = self.ext.lower()
        if ext in VIDEO_EXTS or ext == "gif":
            return self.file_url
        if ext == "zip":  # Danbooru ugoira: the sample is a playable webm
            return self.sample_url or self.file_url
        return self.sample_url or self.file_url


class Source(ABC):
    name: str  # registry key, also used as the library subfolder
    title: str
    # (config key under sources.<name>, label) pairs shown in Settings
    credentials: list[tuple[str, str]] = []
    # Minimum delay between API calls for this site (the global setting is a lower bound)
    interval_ms: int = 0

    def __init__(self, http: HttpClient, cfg: Config):
        self.http = http
        self.cfg = cfg

    def cred(self, key: str) -> str:
        return str(self.cfg.get(f"sources.{self.name}.{key}") or "")

    @abstractmethod
    def search(self, tags: list[str], page: int, limit: int) -> list[Post]:
        """Return one page (1-based). An empty list means there are no more results."""
