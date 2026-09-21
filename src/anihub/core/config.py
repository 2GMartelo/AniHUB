"""JSON config stored in %APPDATA%/AniHUB. Credentials are kept in plain text by design (personal app)."""
from __future__ import annotations

import copy
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from anihub import APP_NAME

DEFAULTS: dict[str, Any] = {
    "first_run_done": False,
    "language": "ru",
    "theme": "system",  # system | light | dark
    "library_path": "",
    "ratings": {"allowed": ["general"]},
    "age": {"mode": ""},                       # 12 | 16 | 18 (see core/agemode.py); empty = derived from ratings.allowed
    "filter": {"custom_tags": []},             # the user's own hidden tags, on top of the age mode's
    "network": {"proxy": "", "min_interval_ms": 250, "max_parallel": 6, "user_agent": "AniHUB/0.1"},
    "sources": {
        "danbooru": {"login": "", "api_key": ""},
        "rule34": {"user_id": "", "api_key": ""},
        "gelbooru": {"user_id": "", "api_key": ""},
        "zerochan": {"username": ""},
    },
    "forge": {"path": "", "port": 7860, "nowebui": False, "extra_args": "", "idle_minutes": 30, "backends": []},
    "sd": {"last": {}, "schedule": {}},
    "civitai": {"token": ""},
    "manga": {"port": 4567, "autostart": False, "poll_minutes": 30, "seen_chapter_id": -1,
              "reader": {"mode": "paged", "rtl": True, "double": False}},
    "browse": {"last_source": "danbooru", "page_size": 40},
    "ui": {"thumb_size": 180, "confirm_trash": True, "glass": True},
    "library": {"near_dedup": "warn", "near_threshold": 6, "trash_days": 7},
    "autotag": {"enabled": False, "general_threshold": 0.35, "character_threshold": 0.85},
}


def config_dir() -> Path:
    base = os.environ.get("APPDATA")
    root = Path(base) if base else Path.home() / ".config"
    return root / APP_NAME


def _merge(base: dict, override: dict) -> dict:
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _merge(base[key], value)
        else:
            base[key] = value
    return base


class Config:
    def __init__(self, data: dict[str, Any], path: Path):
        self._data = data
        self.path = path

    @classmethod
    def load(cls, path: Path | None = None) -> "Config":
        path = path or config_dir() / "config.json"
        data = copy.deepcopy(DEFAULTS)
        if path.exists():
            try:
                _merge(data, json.loads(path.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError):
                # Keep the broken file around instead of silently overwriting it.
                path.replace(path.with_suffix(".broken.json"))
        return cls(data, path)

    def get(self, key: str, default: Any = None) -> Any:
        node: Any = self._data
        for part in key.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def set(self, key: str, value: Any, save: bool = True) -> None:
        parts = key.split(".")
        node = self._data
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = value
        if save:
            self.save()

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(self._data, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, self.path)
