"""Application-wide services, built once after the setup wizard has run."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from anihub.core import agemode
from anihub.core.config import Config, config_dir
from anihub.core.db import Database
from anihub.core.paths import LibraryPaths
from anihub.library.media import MediaCache
from anihub.library.novel_store import NovelShelf
from anihub.library.service import LibraryService
from anihub.net.http import HttpClient
from anihub.services.anilist import AniList
from anihub.services.anime_watch import WatchService
from anihub.services.autotag import Autotagger, model_dir_default
from anihub.services.backends import build_backends
from anihub.services.downloads import DownloadManager
from anihub.services.forge import ForgeManager
from anihub.services.subscriptions import SubscriptionService
from anihub.services.updater import Updater
from anihub.services.suwayomi import SuwayomiManager
from anihub.sources import build_sources
from anihub.services.extensions import ExtensionManager
from anihub.sources.anime import build_anime_sources
from anihub.sources.novels import build_novel_sources
from anihub.sources.novels.base import NovelSource
from anihub.sources.anime.base import AnimeSource
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
    anime_sources: dict[str, AnimeSource]
    watch: WatchService
    updater: Updater
    downloads: DownloadManager
    subscriptions: SubscriptionService
    novel_sources: dict[str, NovelSource]
    extensions: ExtensionManager

    @classmethod
    def build(cls, cfg: Config) -> "AppContext":
        paths = LibraryPaths(Path(cfg.get("library_path")))
        paths.ensure()
        db = Database(paths.db_file)
        http = HttpClient(cfg)
        media = MediaCache(http, paths.media)
        media.prune(int(max(float(cfg.get("library.cache_limit_gb", 1) or 1), 0.1) * 1024**3))
        backends = build_backends(cfg, config_dir())
        ctx = cls(cfg, paths, db, http, build_sources(http, cfg), LibraryService(db, paths, http, cfg), media,
                  backends[0], backends,
                  SuwayomiManager(cfg, config_dir() / "suwayomi", paths.manga / "suwayomi", config_dir() / "logs"),
                  Autotagger(model_dir_default(config_dir())), AniList(http, cfg, db), NovelShelf(db, paths),
                  build_anime_sources(http, cfg, paths.anime, config_dir() / "plugins" / "anime"), None,
                  Updater(http, cfg), None, None, build_novel_sources(http, cfg, config_dir() / "plugins" / "novels"),
                  ExtensionManager(http, cfg, config_dir() / "plugins"))
        ctx.watch = WatchService(db, ctx.anilist)
        ctx.downloads = DownloadManager(ctx.library, http, cfg)
        ctx.subscriptions = SubscriptionService(db, ctx.sources, ctx.downloads, cfg)
        ctx.refresh_tagger()
        ctx.refresh_filter()
        return ctx

    @property
    def sd_enabled(self) -> bool:
        """False on a computer the first-run check found unsuitable for Stable Diffusion: the generation section is hidden.
        Old configs have no such key and keep generation."""
        return self.cfg.get("sd.enabled", True) is not False

    def reload_extensions(self) -> None:
        """Re-read the plugin folders (after an extension was installed, updated or removed)."""
        fresh = build_anime_sources(self.http, self.cfg, self.paths.anime, config_dir() / "plugins" / "anime")
        self.anime_sources.clear()
        self.anime_sources.update(fresh)
        novels = build_novel_sources(self.http, self.cfg, config_dir() / "plugins" / "novels")
        self.novel_sources.clear()
        self.novel_sources.update(novels)

    def refresh_filter(self) -> None:
        """Apply the age mode and the user's tag filter (call after either changed)."""
        blocker = agemode.blocker_for(self.cfg)
        self.db.set_blocked(blocker.exact, blocker.prefixes)

    @property
    def blocker(self) -> agemode.Blocker:
        return agemode.blocker_for(self.cfg)

    def refresh_tagger(self) -> None:
        """Apply the autotagger settings: the library only gets a tagger when it is enabled AND its model exists."""
        self.autotagger.general_threshold = float(self.cfg.get("autotag.general_threshold", 0.35))
        self.autotagger.character_threshold = float(self.cfg.get("autotag.character_threshold", 0.85))
        self.library.tagger = self.autotagger if self.cfg.get("autotag.enabled") and self.autotagger.available else None

    def allowed_ratings(self) -> list[str]:
        return list(agemode.RATINGS_BY_MODE[agemode.mode_of(self.cfg)])
