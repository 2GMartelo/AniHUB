"""Subscriptions (ТЗ 3.8): follow a tag search on a site; new posts are counted, shown, and optionally saved by themselves."""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

from anihub.core.db import Database
from anihub.sources.base import Post, Source, SourceError

log = logging.getLogger(__name__)

PAGE_LIMIT = 40
MAX_PAGES = 3                     # a check looks at most this many pages back for new posts


def post_number(post: Post) -> int:
    """Booru ids grow with time; a non-numeric id never counts as new."""
    try:
        return int(post.id)
    except (TypeError, ValueError):
        return 0


@dataclass
class CheckResult:
    sub_id: int
    new: list[Post] = field(default_factory=list)
    error: str = ""
    saved: int = 0


class SubscriptionService:
    def __init__(self, db: Database, sources: dict[str, Source], downloads, cfg):
        self.db, self.sources, self.downloads, self.cfg = db, sources, downloads, cfg

    # --- helpers -------------------------------------------------------------------------------------------

    def _allowed(self) -> set[str]:
        return set(self.cfg.get("ratings.allowed", ["general"]))

    def _tags(self, query: str) -> list[str]:
        return query.split()

    def _fetch_new(self, source: Source, query: str, since: int) -> list[Post]:
        """Posts newer than `since` matching the query and the user's rating setting, newest first."""
        allowed, found = self._allowed(), []
        for page in range(1, MAX_PAGES + 1):
            posts = source.search(self._tags(query), page, PAGE_LIMIT)
            if not posts:
                break
            fresh = [p for p in posts if post_number(p) > since]
            found += [p for p in fresh if p.rating in allowed]
            if len(fresh) < len(posts):          # reached posts we have already seen
                break
        found.sort(key=post_number, reverse=True)
        return found

    # --- API ------------------------------------------------------------------------------------------------

    def subscribe(self, source_name: str, query: str, name: str = "", auto_save: bool = False) -> int:
        """Follows the query from now on: what is already on the site does not count as new."""
        source = self.sources[source_name]
        newest = max((post_number(p) for p in source.search(self._tags(query), 1, PAGE_LIMIT)), default=0)
        return self.db.add_subscription(name.strip() or f"{source.title}: {query}".strip(), source_name, query.strip(), newest, auto_save)

    def check(self, sub_id: int) -> CheckResult:
        """Looks for new posts; updates the counters; saves them when the subscription says so."""
        row = self.db.subscription(sub_id)
        result = CheckResult(sub_id)
        if row is None:
            return result
        try:
            source = self.sources[row["source"]]
            result.new = self._fetch_new(source, row["query"], row["last_seen_id"])
            error = ""
        except Exception as exc:  # noqa: BLE001 - a dead site must not stop the other subscriptions
            result.error = error = str(exc) or type(exc).__name__
            log.info("subscription %s failed: %s", row["name"], error)
        if not result.error and row["auto_save"] and result.new:
            self.downloads.submit(result.new)
            result.saved = len(result.new)
            self.mark_seen(sub_id, result.new)
        else:
            self.db.update_subscription(sub_id, new_count=len(result.new) if not result.error else row["new_count"])
        self.db.update_subscription(sub_id, last_check=time.time(), last_error=error)
        return result

    def check_all(self, only_enabled: bool = True) -> list[CheckResult]:
        return [self.check(r["id"]) for r in self.db.subscriptions() if r["enabled"] or not only_enabled]

    def mark_seen(self, sub_id: int, posts: list[Post] | None = None) -> None:
        """Everything up to the newest of `posts` is looked at (all current new ones when `posts` is None)."""
        row = self.db.subscription(sub_id)
        if row is None:
            return
        if posts is None:
            posts = self._fetch_new(self.sources[row["source"]], row["query"], row["last_seen_id"])
        newest = max((post_number(p) for p in posts), default=row["last_seen_id"])
        self.db.update_subscription(sub_id, last_seen_id=max(newest, row["last_seen_id"]), new_count=0)

    def total_new(self) -> int:
        return sum(r["new_count"] for r in self.db.subscriptions() if r["enabled"])

    def is_due(self, now: float | None = None) -> bool:
        minutes = max(float(self.cfg.get("subscriptions.poll_minutes", 60) or 60), 5)
        last = float(self.cfg.get("subscriptions.last_poll", 0) or 0)
        return (time.time() if now is None else now) - last >= minutes * 60
