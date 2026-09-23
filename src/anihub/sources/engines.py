"""Shared booru engines: several sites speak the same API."""
from __future__ import annotations

from anihub.net.http import HttpError
from anihub.sources.base import Post, Source, SourceError, url_ext


class GelbooruEngine(Source):
    """Gelbooru 0.2 'dapi' (rule34.xxx, gelbooru.com). Both sites now require user_id + api_key for every request,
    not just tag search (a change on their end during 2025) -- search() surfaces that plainly instead of the API's
    own bare "Missing authentication" text."""

    api_url: str
    page_url_tpl: str  # with {id}
    credentials = [("user_id", "user_id"), ("api_key", "API key")]
    rating_map = {"safe": "general", "general": "general", "sensitive": "sensitive",
                  "questionable": "questionable", "explicit": "explicit"}
    default_rating = "explicit"
    # tag "type" -> category, from the dapi's own s=tag lookup. Verified against a live, unauthenticated Gelbooru-
    # engine deployment (safebooru.org); rule34.xxx documents its own API as using a *different* numbering for
    # character/copyright (2/3 instead of 4/3) in its own maintained client library, so it overrides this below --
    # this default is for gelbooru.com and any other stock deployment.
    TAG_TYPE_MAP = {0: "general", 1: "artist", 3: "copyright", 4: "character", 5: "meta"}

    @classmethod
    def parse(cls, raw: dict) -> Post | None:
        file_url = raw.get("file_url") or ""
        if not file_url:
            return None
        return Post(
            site=cls.name,
            id=str(raw["id"]),
            file_url=file_url,
            preview_url=raw.get("preview_url") or raw.get("sample_url") or file_url,
            sample_url=raw.get("sample_url") or "",
            page_url=cls.page_url_tpl.format(id=raw["id"]),
            rating=cls.rating_map.get(str(raw.get("rating", cls.default_rating)).lower(), cls.default_rating),
            tags=[(t, "general") for t in (raw.get("tags") or "").split()],
            source=raw.get("source") or "",
            width=int(raw.get("width") or 0),
            height=int(raw.get("height") or 0),
            ext=url_ext(file_url),
            score=int(raw.get("score") or 0),
        )

    def suggest_tags(self, prefix: str, limit: int = 12) -> list[tuple[str, int]]:
        user_id, key = self.cred("user_id"), self.cred("api_key")
        if not (user_id and key):                                  # these sites answer tag queries only with an API key
            return []
        params = {"page": "dapi", "s": "tag", "q": "index", "json": 1, "name_pattern": f"%{prefix}%", "orderby": "count", "limit": limit,
                  "user_id": user_id, "api_key": key}
        try:
            data = self.http.get_json(self.api_url, params=params)
        except (HttpError, ValueError):
            return []
        rows = data.get("tag") if isinstance(data, dict) else data
        return [(str(r["name"]), int(r.get("count") or 0)) for r in rows or [] if isinstance(r, dict) and r.get("name")]

    def search(self, tags: list[str], page: int, limit: int) -> list[Post]:
        params = {"page": "dapi", "s": "post", "q": "index", "json": 1,
                  "tags": " ".join(tags), "limit": limit, "pid": page - 1}  # pid is 0-based
        user_id, key = self.cred("user_id"), self.cred("api_key")
        if user_id and key:
            params.update(user_id=user_id, api_key=key)
        try:
            data = self.http.get_json(self.api_url, params=params)
        except HttpError as exc:
            if exc.status in (401, 403):
                raise SourceError(f"{self.title}: API key required or invalid (Settings → {self.title})") from exc
            raise SourceError(f"{self.title}: {exc}") from exc
        if isinstance(data, dict):
            if "post" in data:  # gelbooru.com wraps the list: {"@attributes": ..., "post": [...]}
                data = data["post"]
            else:
                raise SourceError(f"{self.title}: {data.get('message') or data.get('error') or data}")
        posts = [p for p in (self.parse(r) for r in data) if p]
        self._apply_categories(posts, user_id, key)
        return posts

    def _apply_categories(self, posts: list[Post], user_id: str, key: str) -> None:
        """Every tag comes back from search() as plain "general" text (the dapi's post list has no per-tag type);
        one extra s=tag lookup resolves the whole page's unique tags at once, same categories Danbooru gives natively.
        Best-effort: no credentials, a network hiccup, or an unrecognised type just leaves tags uncategorised."""
        if not (user_id and key):
            return
        names = sorted({name for p in posts for name, _cat in p.tags})
        if not names:
            return
        params = {"page": "dapi", "s": "tag", "q": "index", "json": 1, "names": " ".join(names), "limit": len(names),
                  "user_id": user_id, "api_key": key}
        try:
            data = self.http.get_json(self.api_url, params=params)
        except Exception:  # noqa: BLE001 - best-effort: any failure here just leaves tags uncategorised, never breaks search()
            return
        rows = data.get("tag") if isinstance(data, dict) else data
        if not isinstance(rows, list):
            return
        categories = {str(r["name"]): self.TAG_TYPE_MAP.get(int(r.get("type", 0)), "general")
                     for r in rows if isinstance(r, dict) and r.get("name")}
        if not categories:
            return
        for p in posts:
            p.tags = [(name, categories.get(name, cat)) for name, cat in p.tags]


class MoebooruEngine(Source):
    """Moebooru (yande.re, konachan.com)."""

    # verified live against yande.re's own tag.json (type:0 "corset" a plain tag, type:1 "corset_(artist)", type:3
    # "atelier_resleriana" a series/copyright, type:4 "alvina_zimlock" a character) -- matches Danbooru's numbering
    TAG_TYPE_MAP = {0: "general", 1: "artist", 3: "copyright", 4: "character", 5: "meta"}
    MAX_TAG_LOOKUPS = 30   # tag.json has no batch form, only one exact name per call: cap how many a page can cost

    def suggest_tags(self, prefix: str, limit: int = 12) -> list[tuple[str, int]]:
        try:
            data = self.http.get_json(f"{self.base_url}/tag.json", params={"name": prefix, "order": "count", "limit": limit})
        except (HttpError, ValueError):
            return []
        if not isinstance(data, list):
            return []
        return [(str(r["name"]), int(r.get("count") or 0)) for r in data if isinstance(r, dict) and r.get("name")]

    base_url: str
    rating_map = {"s": "general", "q": "questionable", "e": "explicit"}

    @classmethod
    def parse(cls, raw: dict) -> Post | None:
        file_url = raw.get("file_url") or ""
        if not file_url:
            return None
        return Post(
            site=cls.name,
            id=str(raw["id"]),
            file_url=file_url,
            preview_url=raw.get("preview_url") or file_url,
            sample_url=raw.get("sample_url") or "",
            page_url=f"{cls.base_url}/post/show/{raw['id']}",
            rating=cls.rating_map.get(raw.get("rating", "s"), "general"),
            tags=[(t, "general") for t in (raw.get("tags") or "").split()],
            source=raw.get("source") or "",
            width=int(raw.get("width") or 0),
            height=int(raw.get("height") or 0),
            ext=raw.get("file_ext") or url_ext(file_url),
            score=int(raw.get("score") or 0),
        )

    def search(self, tags: list[str], page: int, limit: int) -> list[Post]:
        params = {"tags": " ".join(tags), "limit": limit, "page": page}
        try:
            data = self.http.get_json(f"{self.base_url}/post.json", params=params)
        except HttpError as exc:
            raise SourceError(f"{self.title}: {exc}") from exc
        if isinstance(data, dict):
            raise SourceError(f"{self.title}: {data.get('message') or data}")
        posts = [p for p in (self.parse(r) for r in data) if p]
        self._apply_categories(posts)
        return posts

    def _apply_categories(self, posts: list[Post]) -> None:
        """Moebooru's post list has no per-tag type either, and tag.json only takes one exact name per call (no
        batch lookup) -- so this resolves at most MAX_TAG_LOOKUPS of the page's unique tags, favouring the ones
        that appear on the most posts (character/copyright tags tend to repeat across a page more than one-off
        general ones, so they're the most useful to get right first). Best-effort like the Gelbooru version."""
        counts: dict[str, int] = {}
        for p in posts:
            for name, _cat in p.tags:
                counts[name] = counts.get(name, 0) + 1
        names = sorted(counts, key=lambda n: -counts[n])[: self.MAX_TAG_LOOKUPS]
        categories: dict[str, str] = {}
        for name in names:
            try:
                data = self.http.get_json(f"{self.base_url}/tag.json", params={"name": name})
            except Exception:  # noqa: BLE001 - best-effort: skip this one tag, keep going, never break search()
                continue
            if isinstance(data, list) and data and isinstance(data[0], dict):
                categories[name] = self.TAG_TYPE_MAP.get(int(data[0].get("type", 0)), "general")
        if not categories:
            return
        for p in posts:
            p.tags = [(name, categories.get(name, cat)) for name, cat in p.tags]
