"""pinterest.com without an account, through what the public website itself uses. Fragile by nature: Pinterest offers third
parties no API, so any of this may stop working when the site changes.

Queries:
- plain words             -> the pin search of the site (paged by opaque bookmarks that we remember per query);
- user:<name>             -> the user's public feed (RSS, the newest ~25 pins, one page);
- board:<user>/<board>    -> a public board (RSS, one page); a pasted pinterest.com/<user>[/<board>] link works too.
Pinterest has no tags or ratings: the words of a pin's title and description stand in for tags (so the tag filter still
works), all pins count as 'general' and Pinterest's own SafeSearch is what keeps adult pins out. '-word' excludes a word.
"""
from __future__ import annotations

import html
import json
import re
import unicodedata
import xml.etree.ElementTree as ET
from urllib.parse import quote, unquote, urlsplit

from anihub.net.http import HttpError
from anihub.sources.base import Post, Source, SourceError, url_ext

BASE = "https://www.pinterest.com"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
_IMG = re.compile(r'<img[^>]+src=["\']([^"\']+)["\']', re.I)
_WORD = re.compile(r"[^\W\d_]{3,}", re.UNICODE)
_STOP = frozenset("the and for with this that from you your are was our can has have not but all out one get more".split())
_MAX_TAGS = 25


def words_of(*texts: str) -> list[str]:
    seen: dict[str, None] = {}
    for text in texts:
        for w in _WORD.findall(unicodedata.normalize("NFKC", text or "").lower()):
            if w not in _STOP:
                seen.setdefault(w, None)
    return list(seen)[:_MAX_TAGS]


def original_of(image_url: str) -> str:
    """Any size rendition (236x, 474x, 736x...) -> the original file of the same pin."""
    return re.sub(r"(i\.pinimg\.com)/\d+x/", r"\1/originals/", image_url, count=1) if "/originals/" not in image_url else image_url


def route_of(token: str) -> tuple[str, str] | None:
    """'user:x' / 'board:x/y' / a pinterest.com link -> ('rss', url); anything else -> None."""
    token = token.strip()
    low = token.lower()
    if low.startswith("user:") and len(token) > 5:
        return "rss", f"{BASE}/{quote(token[5:].strip('/'))}/feed.rss"
    if low.startswith("board:") and "/" in token[6:]:
        user, board = token[6:].strip("/").split("/", 1)
        return "rss", f"{BASE}/{quote(user)}/{quote(board.strip('/'))}.rss"
    if "pinterest." in low and low.startswith(("http://", "https://")):
        parts = [unquote(p) for p in urlsplit(token).path.split("/") if p]
        if len(parts) == 1 and parts[0] not in ("pin", "search", "ideas"):
            return "rss", f"{BASE}/{quote(parts[0])}/feed.rss"
        if len(parts) >= 2 and parts[0] not in ("pin", "search", "ideas", "today"):
            return "rss", f"{BASE}/{quote(parts[0])}/{quote(parts[1])}.rss"
    return None


class Pinterest(Source):
    name = "pinterest"
    title = "Pinterest"
    interval_ms = 800
    hint_key = "hint.pinterest"

    def __init__(self, http, cfg):
        super().__init__(http, cfg)
        self._bookmarks: dict[str, list[str | None]] = {}      # query -> bookmark that opens page 1, 2, 3...
        self._last: dict[str, int] = {}                        # query -> its last page, once known

    # --- parsing ---------------------------------------------------------------------------------------------------

    def _post(self, pin_id: str, image_url: str, title: str, description: str, author: str = "", width: int = 0,
              height: int = 0, file_url: str = "") -> Post | None:
        if not pin_id or not image_url:
            return None
        file_url = file_url or original_of(image_url)
        text = " ".join(x for x in (title, description) if x and x.strip())
        return Post(site=self.name, id=str(pin_id), file_url=file_url, preview_url=image_url,
                    sample_url=re.sub(r"/\d+x/", "/736x/", image_url) if "/originals/" not in file_url else "",
                    page_url=f"{BASE}/pin/{pin_id}/", source=f"{BASE}/pin/{pin_id}/", rating="general",
                    tags=[(w, "general") for w in words_of(title, description)], author=author,
                    title=(title or text).strip()[:120], width=width, height=height, ext=url_ext(file_url))

    def _from_pin(self, pin: dict) -> Post | None:
        if pin.get("type") != "pin" or pin.get("is_promoted") or pin.get("is_downstream_promotion"):
            return None
        images = pin.get("images") or {}
        thumb = (images.get("236x") or images.get("474x") or {}).get("url", "")
        orig = images.get("orig") or {}
        video = ""
        for entry in ((pin.get("videos") or {}).get("video_list") or {}).values():
            if str(entry.get("url", "")).endswith(".mp4"):
                video = entry["url"]
                break
        return self._post(pin.get("id", ""), thumb, pin.get("grid_title") or pin.get("title") or "",
                          pin.get("description") or "", (pin.get("pinner") or {}).get("username", ""),
                          int(orig.get("width") or 0), int(orig.get("height") or 0), file_url=video or orig.get("url", ""))

    @staticmethod
    def parse_rss(text: str) -> list[dict]:
        root = ET.fromstring(text)
        pins = []
        for item in root.iter("item"):
            link = (item.findtext("link") or "").strip()
            m = re.search(r"/pin/(\d+)", link)
            description = html.unescape(item.findtext("description") or "")
            img = _IMG.search(description)
            if not (m and img):
                continue
            plain = re.sub(r"<[^>]+>", " ", description).strip()
            pins.append({"id": m.group(1), "image": img.group(1), "title": (item.findtext("title") or "").strip(), "text": plain})
        return pins

    # --- fetching --------------------------------------------------------------------------------------------------

    def _search_page(self, query: str, bookmark: str | None) -> tuple[list[dict], str | None]:
        source_url = "/search/pins/?q=" + quote(query)
        options = {"query": query, "scope": "pins", "page_size": 25, "bookmarks": [bookmark] if bookmark else [],
                   "rs": "typed", "auto_correction_disabled": False}
        data = self.http.get_json(
            f"{BASE}/resource/BaseSearchResource/get/",
            params={"source_url": source_url, "data": json.dumps({"options": options, "context": {}}, separators=(",", ":"))},
            headers={"User-Agent": UA, "X-Requested-With": "XMLHttpRequest", "X-Pinterest-AppState": "active",
                     "Accept": "application/json, text/javascript, */*, q=0.01", "X-Pinterest-Source-Url": source_url,
                     "X-Pinterest-PWS-Handler": "www/search/[scope].js", "Accept-Language": "en-US,en;q=0.9"},
            interval_ms=self.interval_ms)
        response = data.get("resource_response") or {}
        results = (response.get("data") or {}).get("results") or []
        nxt = response.get("bookmark")
        return results, (None if not nxt or nxt == "-end-" else nxt)

    def search(self, tags: list[str], page: int, limit: int) -> list[Post]:
        include = [t for t in tags if not t.startswith("-")]
        exclude = {t[1:].lower().replace("_", " ") for t in tags if t.startswith("-") and len(t) > 1}
        route = next((r for r in map(route_of, include) if r), None)
        try:
            if route:
                if page > 1:
                    return []
                text = self.http.get_text(route[1], headers={"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"},
                                          interval_ms=self.interval_ms)
                posts = [self._post(p["id"], p["image"], p["title"], p["text"]) for p in self.parse_rss(text)]
            else:
                query = " ".join(t.replace("_", " ") for t in include).strip()
                if not query:
                    raise SourceError("Pinterest: type a search, user:<name> or board:<user>/<board>")
                marks = self._bookmarks.setdefault(query, [None])
                if page > self._last.get(query, page):
                    return []
                while len(marks) < page:                                            # the bookmark for page N is in page N-1
                    _, nxt = self._search_page(query, marks[-1])
                    if nxt is None:
                        self._last[query] = len(marks)
                        return []
                    marks.append(nxt)
                results, nxt = self._search_page(query, marks[page - 1])
                if nxt is None:
                    self._last[query] = page
                elif len(marks) == page:
                    marks.append(nxt)
                posts = [self._from_pin(r) for r in results]
        except HttpError as exc:
            raise SourceError(f"Pinterest: {exc}") from exc
        except (ValueError, ET.ParseError) as exc:
            raise SourceError("Pinterest: unexpected response (the site changed, or the user/board is private or does not exist)") from exc
        result = [p for p in posts if p is not None]
        if exclude:
            result = [p for p in result if not any(w in exclude for w in p.tag_names) and not any(e in p.title.lower() for e in exclude)]
        return result[:limit]
