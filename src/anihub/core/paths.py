"""Library folder layout. Files live on disk; the DB only stores the index and metadata.

A handful of the busier subfolders (generations, VTube output, music) can be redirected independently of the
whole library root -- a "standard folder, chosen automatically, overridable if you want" pattern (config keys
under "paths.*"), rather than forcing everything to live under one root the user picked once during setup."""
from __future__ import annotations

from pathlib import Path


class LibraryPaths:
    def __init__(self, root: Path, cfg=None):
        self.root = Path(root)
        self.cfg = cfg
        self.arts = self.root / "arts"
        self.manga = self.root / "manga"
        self.sd = self.root / "sd"
        self.novels = self.root / "novels"
        self.anime = self.root / "anime"
        self.trash = self.root / "trash"
        self.cache = self.root / "cache"
        self.thumbs = self.cache / "thumbs"
        self.media = self.cache / "media"
        self.db_file = self.root / "db" / "anihub.db"

    def _overridable(self, key: str, default: Path) -> Path:
        override = self.cfg.get(f"paths.{key}") if self.cfg is not None else None
        return Path(override) if override else default

    @property
    def apps(self) -> Path:
        """Where the in-app installers (Forge, ComfyUI, sd-scripts...) put a fresh download by default --
        ui/settings.py's "Download" buttons start their folder picker here, pointing an existing install
        elsewhere is untouched by this."""
        return self._overridable("apps", self.root / "apps")

    @property
    def generations(self) -> Path:
        """Where Stable Diffusion results are written (sd_page.py's GenerateView)."""
        return self._overridable("generations", self.sd / "generated")

    @property
    def vtube_out(self) -> Path:
        """Where VTube's layered PSDs are written (ui/vtube_view.py)."""
        return self._overridable("vtube", self.root / "vtube")

    @property
    def music(self) -> Path:
        """The local OST library MusicTab scans (ui/music_tab.py, ui/music_search.py's downloads)."""
        return self._overridable("music", self.root / "music")

    def ensure(self) -> None:
        for p in (self.arts, self.manga, self.sd, self.novels, self.novels / "covers", self.anime, self.trash, self.thumbs, self.media,
                  self.db_file.parent, self.apps, self.generations, self.vtube_out, self.music):
            p.mkdir(parents=True, exist_ok=True)

    def preview_file(self, item_id: int) -> Path:
        """Site preview image kept for items Qt cannot thumbnail (video)."""
        return self.thumbs / f"preview_{item_id}.jpg"
