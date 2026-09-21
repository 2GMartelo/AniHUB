"""pixiv.net through the same JSON endpoints its own website uses (there is no public API for third-party apps).

- Safe works need nothing. R-18 works need the PHPSESSID cookie of a logged-in browser session (Settings > Credentials) and
  the 18+ age mode; without the cookie only all-ages works are requested.
- Images come from i.pximg.net, which answers 403 unless the request carries a pixiv Referer: registered once for the host.
- The listing has only thumbnails; the original file (png or jpg) is found lazily through /ajax/illust/<id>/pages.
- No tag on the site is English-only: underscores become spaces so pixiv's own tag translation can match "hatsune miku".
- An empty query shows the daily ranking. Ugoira (animations) and multi-page works show their first page only.
"""
from __future__ import annotations

from anihub.core import agemode
from anihub.net.http import HttpError
from anihub.sources.base import Post, Source, SourceError, url_ext

BASE = "https://www.pixiv.net"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"


def _norm(tag: str) -> str:
    return tag.strip().lower().replace(" ", "_")


def rating_of(x_restrict: int, sanity: int = 2) -> str:
    """xRestrict: 0 all ages, 1 R-18, 2 R-18G; sanity level 4-5 is 'suggestive' (swimsuits and the like)."""
    if x_restrict:
        return "explicit"
    return "questionable" if sanity >= 4 else "general"


def sample_of(thumb: str) -> str:
    """The 1200px 'master' rendition, derived from any thumbnail URL of the same work."""
    if "/img-master/" not in thumb:
        return ""
    tail = thumb.split("/img-master/", 1)[1].replace("_square1200", "_master1200").replace("_custom1200", "_master1200")
    return f"https://i.pximg.net/img-master/{tail}"


class Pixiv(Source):
    name = "pixiv"
    title = "Pixiv"
    credentials = [("cookie", "PHPSESSID cookie (for R-18)")]
    interval_ms = 700

    def __init__(self, http, cfg):
        super().__init__(http, cfg)
        http.add_host_headers("pximg.net", lambda: {"Referer": BASE + "/", "User-Agent": UA})
        http.add_host_headers("pixiv.net", self._site_headers)

    def _site_headers(self) -> dict[str, str]:
        headers = {"Referer": BASE + "/", "User-Agent": UA, "Accept-Language": "en"}
        cookie = self.cred("cookie").strip()
        if cookie:
            headers["Cookie"] = cookie if "=" in cookie else f"PHPSESSID={cookie}"
        return headers

    def _mode(self) -> str:
        wants_adult = "explicit" in agemode.RATINGS_BY_MODE[agemode.mode_of(self.cfg)]
        return "all" if wants_adult and self.cred("cookie").strip() else "safe"

    def _parse(self, raw: dict) -> Post | None:
        post_id = str(raw.get("id") or "")
        thumb = raw.get("url") or ""
        if not post_id or not thumb or raw.get("isMasked"):
            return None
        restrict = int(raw.get("xRestrict") or 0)
        tags = [(_norm(t), "general") for t in raw.get("tags", []) if t]
        if restrict:
            tags.append(("nsfw", "meta"))
        post = Post(
            site=self.name, id=post_id, file_url="", preview_url=thumb, sample_url=sample_of(thumb),
            page_url=f"{BASE}/artworks/{post_id}", source=f"{BASE}/artworks/{post_id}",
            rating=rating_of(restrict, int(raw.get("sl") or 2)), tags=tags, author=raw.get("userName") or "",
            title=raw.get("title") or "", width=int(raw.get("width") or 0), height=int(raw.get("height") or 0),
        )
        post.resolver = self._resolve
        return post

    def _parse_ranking(self, raw: dict) -> Post | None:
        content = raw.get("illust_content_type") or {}
        return self._parse({
            "id": raw.get("illust_id"), "url": raw.get("url"), "tags": raw.get("tags", []), "userName": raw.get("user_name"),
            "title": raw.get("title"), "width": raw.get("width"), "height": raw.get("height"),
            "xRestrict": 1 if raw.get("illust_x_restrict") or raw.get("attr") == "r18" else 0,
            "sl": 4 if content.get("sexual") else 2, "isMasked": raw.get("is_masked"),
        })

    def _resolve(self, post: Post) -> None:
        try:
            data = self.http.get_json(f"{BASE}/ajax/illust/{post.id}/pages", interval_ms=self.interval_ms)
        except (HttpError, ValueError) as exc:
            raise SourceError(f"Pixiv: cannot open #{post.id}: {exc}") from exc
        pages = data.get("body") if isinstance(data, dict) else None
        if not pages:
            raise SourceError(f"Pixiv: no file for #{post.id}")
        first = pages[0]
        post.file_url = first["urls"]["original"]
        post.ext = url_ext(post.file_url)
        post.width = int(first.get("width") or post.width)
        post.height = int(first.get("height") or post.height)

    def search(self, tags: list[str], page: int, limit: int) -> list[Post]:
        include = [t.replace("_", " ") for t in tags if not t.startswith("-")]
        exclude = {_norm(t[1:]) for t in tags if t.startswith("-") and len(t) > 1}
        try:
            if include:
                word = " ".join(include)
                data = self.http.get_json(
                    f"{BASE}/ajax/search/artworks/{word}",
                    params={"word": word, "order": "date_d", "mode": self._mode(), "p": page, "s_mode": "s_tag",
                            "type": "illust", "lang": "en"},
                    interval_ms=self.interval_ms)
                if data.get("error"):
                    raise SourceError(f"Pixiv: {data.get('message') or 'search failed'}")
                items = ((data.get("body") or {}).get("illustManga") or {}).get("data", [])
                posts = [self._parse(r) for r in items if r.get("illustType", 0) != 2]     # 2 = ugoira
            else:
                if page > 10:
                    return []
                data = self.http.get_json(f"{BASE}/ranking.php",
                                          params={"mode": "daily", "content": "illust", "format": "json", "p": page},
                                          interval_ms=self.interval_ms)
                posts = [self._parse_ranking(r) for r in data.get("contents", []) if str(r.get("illust_type")) != "2"]
        except HttpError as exc:
            hint = " (check the PHPSESSID cookie in Settings)" if exc.status in (401, 403) and self.cred("cookie") else ""
            raise SourceError(f"Pixiv: {exc}{hint}") from exc
        except ValueError as exc:
            raise SourceError("Pixiv: unexpected response (blocked or rate limited)") from exc
        result = [p for p in posts if p is not None]
        if exclude:
            result = [p for p in result if not exclude.intersection(p.tag_names)]
        return result[:limit]
