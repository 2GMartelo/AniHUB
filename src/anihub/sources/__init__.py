"""Source registry. Built-in sources are listed here; user plugins will be discovered in Stage 7."""
from __future__ import annotations

from anihub.core.config import Config
from anihub.net.http import HttpClient
from anihub.sources.base import Source
from anihub.sources.danbooru import Danbooru
from anihub.sources.gelbooru import Gelbooru
from anihub.sources.moebooru_sites import Konachan, Yandere
from anihub.sources.rule34 import Rule34
from anihub.sources.zerochan import Zerochan

BUILTIN: list[type[Source]] = [Danbooru, Gelbooru, Yandere, Konachan, Zerochan, Rule34]


def build_sources(http: HttpClient, cfg: Config) -> dict[str, Source]:
    return {cls.name: cls(http, cfg) for cls in BUILTIN}
