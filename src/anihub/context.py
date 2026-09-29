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
from anihub.services.comfyui import ComfyManager
from anihub.services.forge import ForgeManager
from anihub.services.gpu_scheduler import GpuScheduler
from anihub.core.notifications import NotificationCenter
from anihub.services import promptbook
from anihub.core.undo import UndoStack
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
    gpu_scheduler: GpuScheduler  # the shared "one heavy model in VRAM at a time" slot: sd_queue.py's QueueController
                                 # and a ComfyUI job (services/seethrough.py's run()) both acquire this same instance
    comfy: ComfyManager  # video/sound/2D-VTube backend (ТЗ_rasshirenie_prilozheniya.md); always constructed, like
                         # `forge` -- comfyui.path empty just means check_install() reports it as not set up yet
    notifications: NotificationCenter  # in-app notification history; the UI wires on_notify/on_change to Qt signals
    undo: UndoStack  # Ctrl+Z/Ctrl+Y for library trash/restore (ui/library_view.py's LibraryView._file_op)

    @classmethod
    def build(cls, cfg: Config) -> "AppContext":
        paths = LibraryPaths(Path(cfg.get("library_path")), cfg)
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
                  ExtensionManager(http, cfg, config_dir() / "plugins"), GpuScheduler(), ComfyManager(cfg, config_dir()),
                  NotificationCenter(), UndoStack())
        ctx.watch = WatchService(db, ctx.anilist)
        ctx.downloads = DownloadManager(ctx.library, http, cfg)
        ctx.subscriptions = SubscriptionService(db, ctx.sources, ctx.downloads, cfg)
        ctx.refresh_tagger()
        ctx.refresh_filter()
        promptbook.apply_custom_slots(cfg)
        return ctx

    @property
    def sd_enabled(self) -> bool:
        """False on a computer the first-run check found unsuitable for Stable Diffusion (or the user turned it off):
        the generation section is hidden. Old configs have no such key and keep generation.

        Also False when Forge itself is not actually set up yet (no folder picked, and no download queued from the
        wizard) -- there is nothing useful to do in an empty Generation tab, so it stays out of the way, the same as
        it does on an unsuitable PC, until a folder exists. `sd.install_pending` keeps this True across the wizard's
        own "download Forge now" flow (main_window.maybe_install_forge), which itself only runs while this is True."""
        if self.cfg.get("sd.enabled", True) is False:
            return False
        return bool(self.cfg.get("forge.path")) or bool(self.cfg.get("sd.install_pending"))

    @property
    def lora_train_enabled(self) -> bool:
        """Off by default (unlike sd_enabled): training needs a separate program (sd-scripts) nobody has installed by
        chance, so the tab only appears once the user turns it on in Settings AND actually points it at a folder --
        same switch either way, "Обучение LoRA"."""
        return self.sd_enabled and bool(self.cfg.get("lora_train.enabled", False)) and bool(self.cfg.get("lora_train.sd_scripts_path"))

    @property
    def vtube_enabled(self) -> bool:
        """The "VTube" tab (picture -> ComfyUI-See-through -> layered PSD) only appears once a ComfyUI folder is
        actually set in Settings -- same on/off switch as sd_enabled uses for forge.path, no separate toggle."""
        return self.sd_enabled and bool(self.cfg.get("comfyui.path"))

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
