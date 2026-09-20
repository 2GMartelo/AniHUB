"""Anime source registry: the built-in local source plus user plugins from `<config>/plugins/anime/*.py`."""
from __future__ import annotations

import importlib.util
import inspect
import logging
from pathlib import Path

from anihub.core.config import Config
from anihub.net.http import HttpClient
from anihub.sources.anime.base import AnimeSource
from anihub.sources.anime.local import LocalAnime

log = logging.getLogger(__name__)


def load_plugins(folder: Path) -> list[type[AnimeSource]]:
    """Every AnimeSource subclass defined in the .py files of `folder`. A broken plugin is skipped (and logged),
    it never stops the app. Plugins are ordinary Python run with the user's rights: only put your own files there."""
    found: list[type[AnimeSource]] = []
    if not folder.is_dir():
        return found
    for file in sorted(folder.glob("*.py")):
        try:
            spec = importlib.util.spec_from_file_location(f"anihub_anime_plugin_{file.stem}", file)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        except Exception as exc:  # noqa: BLE001
            log.warning("anime plugin %s failed to load: %s", file.name, exc)
            continue
        for _, cls in inspect.getmembers(module, inspect.isclass):
            if (issubclass(cls, AnimeSource) and cls is not AnimeSource and not inspect.isabstract(cls)
                    and cls.__module__ == module.__name__):
                found.append(cls)
    return found


def build_anime_sources(http: HttpClient, cfg: Config, library_anime_dir: Path, plugin_dir: Path) -> dict[str, AnimeSource]:
    sources: dict[str, AnimeSource] = {"local": LocalAnime(http, cfg, library_anime_dir)}
    for cls in load_plugins(plugin_dir):
        try:
            source = cls(http, cfg)
        except Exception as exc:  # noqa: BLE001
            log.warning("anime plugin %s could not start: %s", cls.__name__, exc)
            continue
        if source.name in sources:
            log.warning("anime plugin %s: the name '%s' is taken", cls.__name__, source.name)
            continue
        sources[source.name] = source
    return sources
