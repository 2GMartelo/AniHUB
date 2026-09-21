"""Anime source plugins (ТЗ 10.2): a source finds a title, lists its episodes and gives playable stream URLs.

Aniyomi extensions cannot run here (they are Android code), so AniHUB has its own small Python interface. A source is a
class with the three methods below; drop a .py file with such a class into `%APPDATA%\\AniHUB\\plugins\\anime\\`
and it appears in the Watch tab (see sources/anime/__init__.py). A source gets `http` (HttpClient: proxy, rate limit, offline
switch) and `cfg`; it must not open connections by itself.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from anihub.core.config import Config
from anihub.net.http import HttpClient


class AnimeSourceError(Exception):
    """User-presentable error from an anime source."""


@dataclass
class AnimeEntry:
    id: str                        # source-specific, stable
    title: str
    cover: str = ""                # URL or local path of a cover image
    url: str = ""                  # page on the site (opened by "open in browser")
    description: str = ""


@dataclass
class Episode:
    id: str
    number: float                  # 1, 2, 12.5 ...; used to order and to sync progress
    title: str = ""


@dataclass
class Stream:
    url: str                       # mp4 / m3u8 / local file path
    label: str = ""                # "1080p", "Sub", ...
    headers: dict[str, str] = field(default_factory=dict)   # e.g. Referer; the built-in player cannot send them
    subtitles: list[tuple[str, str]] = field(default_factory=list)   # (language, url)


class AnimeSource(ABC):
    name: str                      # registry key
    title: str                     # shown in the UI
    needs_network: bool = True     # False = works in offline mode
    lang: str = "multi"            # ISO 639-1 code of the audio/subtitles the site offers ("en", "ru", "ja"...) or "multi"
    nsfw: bool = False             # adult site: hidden unless the 18+ age mode is on
    version: str = "1"

    def __init__(self, http: HttpClient, cfg: Config):
        self.http, self.cfg = http, cfg

    @abstractmethod
    def search(self, query: str, page: int = 1) -> tuple[list[AnimeEntry], bool]:
        """(entries, has_next_page). An empty query means 'popular / latest' if the site has that, otherwise everything."""

    @abstractmethod
    def episodes(self, entry: AnimeEntry) -> list[Episode]:
        """All episodes, oldest first."""

    @abstractmethod
    def streams(self, entry: AnimeEntry, episode: Episode) -> list[Stream]:
        """Playable URLs for one episode, best first."""
