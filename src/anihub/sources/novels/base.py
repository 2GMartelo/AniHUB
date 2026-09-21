"""Light-novel source plugins: a source finds a novel, lists its chapters and returns the text of a chapter as HTML.

Like anime sources, they are small Python classes; built-in ones live in this package and user plugins in
`%APPDATA%\\AniHUB\\plugins\\novels\\*.py` (or installed from an extension repository). A source gets `http` (HttpClient:
proxy, rate limit, offline switch) and `cfg`; it must not open connections by itself.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from anihub.core.config import Config
from anihub.net.http import HttpClient


class NovelSourceError(Exception):
    """User-presentable error from a novel source."""


@dataclass
class NovelEntry:
    id: str                        # source-specific, stable
    title: str
    cover: str = ""                # URL
    url: str = ""                  # page on the site
    author: str = ""
    description: str = ""
    age: int = 0                   # minimum age the site marks the title with (0, 12, 16, 18); drives the age-mode filter
    tags: list[str] = field(default_factory=list)


@dataclass
class NovelChapter:
    id: str
    title: str                     # "Volume 1. Chapter 3. The name"
    number: float = 0.0


class NovelSource(ABC):
    name: str
    title: str
    lang: str = "multi"
    nsfw: bool = False             # adult site: hidden unless the 18+ age mode is on
    needs_network: bool = True
    version: str = "1"
    credentials: list[tuple[str, str]] = []            # (key under sources.<name>, label) shown in the extension's settings

    def __init__(self, http: HttpClient, cfg: Config):
        self.http, self.cfg = http, cfg

    def cred(self, key: str) -> str:
        return str(self.cfg.get(f"sources.{self.name}.{key}") or "")

    @abstractmethod
    def search(self, query: str, page: int = 1) -> tuple[list[NovelEntry], bool]:
        """(entries, has_next_page). An empty query means 'popular / latest'."""

    @abstractmethod
    def chapters(self, entry: NovelEntry) -> list[NovelChapter]:
        """All chapters, first to last."""

    @abstractmethod
    def chapter_html(self, entry: NovelEntry, chapter: NovelChapter) -> str:
        """The chapter body as simple HTML (<p>, <h2>, <img src="absolute url">); scripts and styles are ignored."""

    def details(self, entry: NovelEntry) -> NovelEntry:
        """Optional: the entry with the fields the listing lacks (description, tags, author). Default: unchanged."""
        return entry
