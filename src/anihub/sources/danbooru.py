from __future__ import annotations

from anihub.net.http import HttpError
from anihub.sources.base import Post, Source, SourceError

BASE = "https://danbooru.donmai.us"
RATING_MAP = {"g": "general", "s": "sensitive", "q": "questionable", "e": "explicit"}
TAG_FIELDS = (
    ("tag_string_artist", "artist"),
    ("tag_string_copyright", "copyright"),
    ("tag_string_character", "character"),
    ("tag_string_general", "general"),
    ("tag_string_meta", "meta"),
)


def parse_post(raw: dict) -> Post | None:
    file_url = raw.get("file_url") or ""
    if not file_url:  # banned / gold-only posts come without a file
        return None
    tags: list[tuple[str, str]] = []
    for key, category in TAG_FIELDS:
        tags += [(t, category) for t in (raw.get(key) or "").split()]
    artists = (raw.get("tag_string_artist") or "").split()
    return Post(
        site="danbooru",
        id=str(raw["id"]),
        file_url=file_url,
        preview_url=raw.get("preview_file_url") or raw.get("large_file_url") or file_url,
        sample_url=raw.get("large_file_url") or "",
        page_url=f"{BASE}/posts/{raw['id']}",
        rating=RATING_MAP.get(raw.get("rating", "g"), "general"),
        tags=tags,
        author=artists[0] if artists else "",
        source=raw.get("source") or "",
        width=int(raw.get("image_width") or 0),
        height=int(raw.get("image_height") or 0),
        ext=raw.get("file_ext") or "",
        score=int(raw.get("score") or 0),
    )


class Danbooru(Source):
    name = "danbooru"
    title = "Danbooru"
    credentials = [("login", "login"), ("api_key", "API key")]

    def search(self, tags: list[str], page: int, limit: int) -> list[Post]:
        params = {"tags": " ".join(tags), "limit": limit, "page": page}
        login = self.cred("login")
        key = self.cred("api_key")
        if login and key:
            params.update(login=login, api_key=key)
        try:
            data = self.http.get_json(f"{BASE}/posts.json", params=params)
        except HttpError as exc:
            if exc.status == 422:
                raise SourceError("Danbooru: too many tags for this account (free accounts: 2 tags)") from exc
            if exc.status in (401, 403):
                raise SourceError("Danbooru: authorization failed (check login / API key)") from exc
            raise SourceError(f"Danbooru: {exc}") from exc
        if isinstance(data, dict):  # error payload
            raise SourceError(f"Danbooru: {data.get('message') or data}")
        return [p for p in (parse_post(r) for r in data) if p]
