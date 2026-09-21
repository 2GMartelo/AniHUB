"""Library statistics for the dashboard (раздел 8)."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime

from anihub.core.db import Database


@dataclass
class Stats:
    items: int = 0
    total_bytes: int = 0
    favorites: int = 0
    rated: int = 0                                   # items with the user's own stars
    trashed: int = 0
    by_kind: dict[str, int] = field(default_factory=dict)
    by_rating: dict[str, int] = field(default_factory=dict)
    by_source: list[tuple[str, int]] = field(default_factory=list)
    top_tags: list[tuple[str, int]] = field(default_factory=list)
    top_artists: list[tuple[str, int]] = field(default_factory=list)
    per_month: list[tuple[str, int]] = field(default_factory=list)      # oldest first, one entry per month incl. empty ones
    tags_total: int = 0
    collections: int = 0
    categories: int = 0
    novels: int = 0
    novels_finished: int = 0
    anime_by_status: dict[str, int] = field(default_factory=dict)
    episodes_watched: int = 0
    subscriptions: int = 0


def month_keys(now: float, months: int) -> list[str]:
    """['2026-05', ..., '2026-09'] ending with the month of `now`."""
    d = datetime.fromtimestamp(now)
    year, month, out = d.year, d.month, []
    for _ in range(months):
        out.append(f"{year:04d}-{month:02d}")
        month -= 1
        if month == 0:
            year, month = year - 1, 12
    return out[::-1]


def collect(db: Database, months: int = 12, top: int = 15, now: float | None = None) -> Stats:
    c = db.conn
    s = Stats()
    one = lambda sql, *a: c.execute(sql, a).fetchone()[0]  # noqa: E731
    s.items = one("SELECT COUNT(*) FROM items WHERE trashed_at IS NULL")
    s.total_bytes = one("SELECT COALESCE(SUM(size), 0) FROM items WHERE trashed_at IS NULL")
    s.favorites = one("SELECT COUNT(*) FROM items WHERE trashed_at IS NULL AND favorite=1")
    s.rated = one("SELECT COUNT(*) FROM items WHERE trashed_at IS NULL AND stars>0")
    s.trashed = one("SELECT COUNT(*) FROM items WHERE trashed_at IS NOT NULL")
    s.by_kind = {r[0]: r[1] for r in c.execute("SELECT kind, COUNT(*) FROM items WHERE trashed_at IS NULL GROUP BY kind")}
    s.by_rating = {r[0]: r[1] for r in c.execute("SELECT rating, COUNT(*) FROM items WHERE trashed_at IS NULL GROUP BY rating")}
    s.by_source = [(r[0], r[1]) for r in c.execute(
        "SELECT COALESCE(source_site, '?'), COUNT(*) n FROM items WHERE trashed_at IS NULL GROUP BY 1 ORDER BY n DESC, 1 LIMIT ?", (top,))]
    tag_rows = "SELECT t.name, COUNT(*) n FROM item_tags it JOIN tags t ON t.id=it.tag_id JOIN items i ON i.id=it.item_id " \
               "WHERE i.trashed_at IS NULL AND t.category{} 'artist' GROUP BY t.id ORDER BY n DESC, t.name LIMIT ?"
    s.top_tags = [(r[0], r[1]) for r in c.execute(tag_rows.format("!="), (top,))]
    s.top_artists = [(r[0], r[1]) for r in c.execute(tag_rows.format("="), (top,))]
    s.tags_total = one("SELECT COUNT(*) FROM tags")
    keys = month_keys(time.time() if now is None else now, months)
    counts = {r[0]: r[1] for r in c.execute(
        "SELECT strftime('%Y-%m', added_at, 'unixepoch', 'localtime') m, COUNT(*) FROM items WHERE trashed_at IS NULL "
        "AND added_at >= ? GROUP BY m", (datetime.strptime(keys[0], "%Y-%m").timestamp(),))}
    s.per_month = [(k, counts.get(k, 0)) for k in keys]
    s.collections = one("SELECT COUNT(*) FROM collections")
    s.categories = one("SELECT COUNT(*) FROM categories")
    s.novels = one("SELECT COUNT(*) FROM novels")
    s.novels_finished = one("SELECT COUNT(*) FROM novels WHERE finished=1")
    s.anime_by_status = {r[0]: r[1] for r in c.execute("SELECT status, COUNT(*) FROM anime_list GROUP BY status")}
    s.episodes_watched = one("SELECT COALESCE(SUM(progress), 0) FROM anime_list")
    s.subscriptions = one("SELECT COUNT(*) FROM subscriptions")
    return s


def human_size(n: int) -> str:
    value = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{n} B"
