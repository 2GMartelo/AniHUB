"""Application-wide services, built once after the setup wizard has run."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from anihub.core.config import Config, config_dir
from anihub.core.db import Database
from anihub.core.paths import LibraryPaths
from anihub.library.media import MediaCache
from anihub.library.novel_store import NovelShelf
from anihub.library.service import LibraryService
from anihub.net.http import HttpClient
from anihub.services.anilist import AniList
from anihub.services.autotag import Autotagger, model_dir_default
from anihub.services.backends import build_backends
from anihub.services.forge import ForgeManager
from anihub.services.suwayomi import SuwayomiManager
from anihub.sources import build_sources
from anihub.sources.base import Source


@dataclass
class AppContext:
    cfg: Config
    paths: LibraryPaths
    db: Database
    http: HttpClient
    sources: dict[str, Source]
    library: LibraryService
    media: MediaCache
    forge: ForgeManager
    backends: list[ForgeManager]
    suwayomi: SuwayomiManager
    autotagger: Autotagger
    anilist: AniList
    novels: NovelShelf

    @classmethod
    def build(cls, cfg: Config) -> "AppContext":
        paths = LibraryPaths(Path(cfg.get("library_path")))
        paths.ensure()
        db = Database(paths.db_file)
        http = HttpClient(cfg)
        media = MediaCache(http, paths.media)
        media.prune()
        backends = build_backends(cfg, config_dir())
        ctx = cls(cfg, paths, db, http, build_sources(http, cfg), LibraryService(db, paths, http, cfg), media,
                  backends[0], backends,
                  SuwayomiManager(cfg, config_dir() / "suwayomi", paths.manga / "suwayomi", config_dir() / "logs"),
                  Autotagger(model_dir_default(config_dir())), AniList(http, cfg, db), NovelShelf(db, paths))
        ctx.refresh_tagger()
        return ctx

    def refresh_tagger(self) -> None:
        """Apply the autotagger settings: the library only gets a tagger when it is enabled AND its model exists."""
        self.autotagger.general_threshold = float(self.cfg.get("autotag.general_threshold", 0.35))
        self.autotagger.character_threshold = float(self.cfg.get("autotag.character_threshold", 0.85))
        self.library.tagger = self.autotagger if self.cfg.get("autotag.enabled") and self.autotagger.available else None

    def allowed_ratings(self) -> list[str]:
        return list(self.cfg.get("ratings.allowed", ["general"]))
