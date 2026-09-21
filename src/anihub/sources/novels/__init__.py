"""Light-novel source registry: built-in online sources plus user plugins from `<config>/plugins/novels/*.py`."""
from __future__ import annotations

from pathlib import Path

from anihub.core.config import Config
from anihub.net.http import HttpClient
from anihub.sources.novels.base import NovelSource
from anihub.sources.novels.ranobelib import RanobeLib
from anihub.sources.plugins import build_plugins, load_plugin_classes

BUILTIN_NOVELS: list[type[NovelSource]] = [RanobeLib]


def load_novel_plugins(folder: Path) -> list[type[NovelSource]]:
    return load_plugin_classes(folder, NovelSource, "anihub_novel_plugin")


def build_novel_sources(http: HttpClient, cfg: Config, plugin_dir: Path) -> dict[str, NovelSource]:
    sources: dict[str, NovelSource] = {cls.name: cls(http, cfg) for cls in BUILTIN_NOVELS}
    sources.update(build_plugins(load_novel_plugins(plugin_dir), (http, cfg), set(sources)))
    return sources
