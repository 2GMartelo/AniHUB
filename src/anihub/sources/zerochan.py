"""zerochan.net via its ?json listing.

Quirks handled here:
- the listing has no file URL: it is resolved lazily from /<id>?json (Post.resolver);
- thumbnails are AVIF (Qt cannot decode it) - the same path with .jpg exists;
- no negative tags and no rating info: '-tag' is applied client-side, all posts count as 'general';
- Zerochan asks for a username in the User-Agent and rate-limits aggressively.
"""
from __future__ import annotations

from urllib.parse import quote

from anihub.net.http import HttpError
from anihub.sources.base import Post, Source, SourceError, url_ext

BASE = "https://www.zerochan.net"


def _norm(tag: str) -> str:
    return tag.strip().lower().replace(" ", "_")


class Zerochan(Source):
    name = "zerochan"
    title = "Zerochan"
    credentials = [("username", "username (for User-Agent)")]
    interval_ms = 1000

    def _headers(self) -> dict[str, str]:
        return {"User-Agent": f"AniHUB - {self.cred('username') or 'anonymous'}"}

    def _parse(self, raw: dict) -> Post:
        post_id = str(raw["id"])
        post = Post(
            site=self.name,
            id=post_id,
            file_url="",
            preview_url=(raw.get("thumbnail") or "").replace(".avif", ".jpg"),
            page_url=f"{BASE}/{post_id}",
            rating="general",
            tags=[(_norm(t), "general") for t in raw.get("tags", [])],
            source=raw.get("source") or "",
            width=int(raw.get("width") or 0),
            height=int(raw.get("height") or 0),
        )
        post.resolver = self._resolve
        return post

    def _resolve(self, post: Post) -> None:
        try:
            data = self.http.get_json(f"{BASE}/{post.id}", params={"json": 1}, headers=self._headers(),
                                      interval_ms=self.interval_ms)
        except (HttpError, ValueError) as exc:
            raise SourceError(f"Zerochan: cannot resolve #{post.id}: {exc}") from exc
        full = data.get("full") if isinstance(data, dict) else None
        if not full:
            raise SourceError(f"Zerochan: no file for #{post.id}")
        post.file_url = full
        post.ext = url_ext(full)
        post.width = int(data.get("width") or post.width)
        post.height = int(data.get("height") or post.height)

    def search(self, tags: list[str], page: int, limit: int) -> list[Post]:
        include = [t.replace("_", " ") for t in tags if not t.startswith("-")]
        exclude = {_norm(t[1:]) for t in tags if t.startswith("-") and len(t) > 1}
        path = quote(",".join(include), safe=",") if include else ""
        params = {"json": 1, "p": page, "l": min(limit, 100), "s": "id"}
        try:
            data = self.http.get_json(f"{BASE}/{path}", params=params, headers=self._headers(),
                                      interval_ms=self.interval_ms)
        except HttpError as exc:
            raise SourceError(f"Zerochan: {exc}") from exc
        except ValueError as exc:  # HTML instead of JSON: unknown tag or blocked
            raise SourceError("Zerochan: unexpected response (unknown tag, or rate limited)") from exc
        items = data.get("items", []) if isinstance(data, dict) else []
        posts = [self._parse(r) for r in items]
        if exclude:
            posts = [p for p in posts if not exclude.intersection(p.tag_names)]
        return posts
