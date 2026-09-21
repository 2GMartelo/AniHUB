"""Anime source registry: the local source, the built-in online ones and user plugins from `<config>/plugins/anime/*.py`."""
from __future__ import annotations

from pathlib import Path

from anihub.core.config import Config
from anihub.net.http import HttpClient
from anihub.sources.anime.anilibria import AniLibria
from anihub.sources.anime.anime365 import Anime365
from anihub.sources.anime.base import AnimeSource
from anihub.sources.anime.local import LocalAnime
from anihub.sources.plugins import build_plugins, load_plugin_classes

BUILTIN_ONLINE: list[type[AnimeSource]] = [AniLibria, Anime365]


def load_plugins(folder: Path) -> list[type[AnimeSource]]:
    """Every AnimeSource subclass defined in the .py files of `folder`."""
    return load_plugin_classes(folder, AnimeSource, "anihub_anime_plugin")


def build_anime_sources(http: HttpClient, cfg: Config, library_anime_dir: Path, plugin_dir: Path) -> dict[str, AnimeSource]:
    sources: dict[str, AnimeSource] = {"local": LocalAnime(http, cfg, library_anime_dir)}
    for cls in BUILTIN_ONLINE:
        sources[cls.name] = cls(http, cfg)
    sources.update(build_plugins(load_plugins(plugin_dir), (http, cfg), set(sources)))
    return sources
