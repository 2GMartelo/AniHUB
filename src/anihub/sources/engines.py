"""Shared booru engines: several sites speak the same API."""
from __future__ import annotations

from anihub.net.http import HttpError
from anihub.sources.base import Post, Source, SourceError, url_ext


class GelbooruEngine(Source):
    """Gelbooru 0.2 'dapi' (rule34.xxx, gelbooru.com)."""

    api_url: str
    page_url_tpl: str  # with {id}
    credentials = [("user_id", "user_id"), ("api_key", "API key")]
    rating_map = {"safe": "general", "general": "general", "sensitive": "sensitive",
                  "questionable": "questionable", "explicit": "explicit"}
    default_rating = "explicit"

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
        return [p for p in (self.parse(r) for r in data) if p]


class MoebooruEngine(Source):
    """Moebooru (yande.re, konachan.com)."""

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
        return [p for p in (self.parse(r) for r in data) if p]
