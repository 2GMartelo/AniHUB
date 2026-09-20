"""nhentai.net through its v2 JSON API (the old /api/gallery endpoints now answer 403).

Like E-Hentai, a post is a whole gallery: the cover thumbnail in the feed, the FIRST page when you view or save it (the gallery
detail — tags, artist, page list — is fetched lazily, one request, when that happens). All content is adult ('explicit'), so the
source refuses to search unless the 'explicit' rating is enabled.
"""
from __future__ import annotations

from anihub.net.http import HttpError
from anihub.sources.base import Post, Source, SourceError, url_ext

BASE = "https://nhentai.net"
API = f"{BASE}/api/v2"
IMAGES = "https://i1.nhentai.net/"
THUMBS = "https://t1.nhentai.net/"
NAMESPACES = {"artist", "group", "parody", "character", "language", "category", "tag"}
TYPE_CATEGORY = {"artist": "artist", "group": "artist", "parody": "copyright", "character": "character",
                 "language": "meta", "category": "meta", "tag": "general"}


def search_token(tag: str) -> str:
    """booru-style tag -> nhentai query syntax: `tag:"big breasts"`, `artist:"name"`, exclusion with '-'."""
    negative = tag.startswith("-")
    text = (tag[1:] if negative else tag).replace("_", " ").strip()
    if not text:
        return ""
    namespace, sep, name = text.partition(":")
    if sep and namespace in NAMESPACES:
        token = f'{namespace}:"{name.strip()}"'
    else:
        token = f'tag:"{text}"'
    return ("-" if negative else "") + token


def parse_tags(raw_tags: list[dict]) -> tuple[list[tuple[str, str]], str]:
    tags: list[tuple[str, str]] = []
    artists: list[str] = []
    for t in raw_tags:
        name = (t.get("name") or "").strip().replace(" ", "_")
        category = TYPE_CATEGORY.get(t.get("type", "tag"), "general")
        if name and (name, category) not in tags:
            tags.append((name, category))
        if t.get("type") == "artist" and name:
            artists.append(name)
    return tags, " ".join(artists)


class NHentai(Source):
    name = "nhentai"
    title = "nhentai"
    interval_ms = 1200

    def _get(self, url: str, params: dict | None = None):
        try:
            return self.http.get_json(url, params=params, interval_ms=self.interval_ms)
        except HttpError as exc:
            raise SourceError(f"nhentai: {exc}") from exc
        except ValueError as exc:
            raise SourceError("nhentai: unexpected response (blocked or rate limited)") from exc

    def search(self, tags: list[str], page: int, limit: int) -> list[Post]:
        if "explicit" not in set(self.cfg.get("ratings.allowed", ["general"])):
            raise SourceError("nhentai: adult content only. Enable the 'explicit' rating in Settings.")
        query = " ".join(t for t in (search_token(t) for t in tags) if t)
        # no query = the newest galleries; the search endpoint refuses an empty string
        data = self._get(f"{API}/search", {"query": query, "page": page}) if query else self._get(f"{API}/galleries", {"page": page})
        if not isinstance(data, dict) or "result" not in data:
            raise SourceError("nhentai: unexpected API response")
        return [self._parse(g) for g in data["result"] if not g.get("blacklisted")]

    def _parse(self, g: dict) -> Post:
        gid = str(g["id"])
        post = Post(site=self.name, id=gid, file_url="", preview_url=THUMBS + g.get("thumbnail", ""), page_url=f"{BASE}/g/{gid}/",
                    rating="explicit", score=int(g.get("num_favorites") or 0),
                    title=g.get("english_title") or g.get("japanese_title") or "")
        post.resolver = self._resolve
        return post

    def _resolve(self, post: Post) -> None:
        data = self._get(f"{API}/galleries/{post.id}")
        pages = data.get("pages") or []
        if not pages:
            raise SourceError(f"nhentai: gallery #{post.id} has no pages")
        first = pages[0]
        post.file_url = IMAGES + first["path"]
        post.ext = url_ext(post.file_url)
        post.width, post.height = int(first.get("width") or 0), int(first.get("height") or 0)
        post.tags, post.author = parse_tags(data.get("tags", []))
        post.title = (data.get("title") or {}).get("english") or post.title
