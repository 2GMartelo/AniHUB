"""A small HTML-scraping helper for anime sources that have no API (used by the extensions in `extensions/`).

It does not know any site: a subclass names the catalogue / search addresses and, if needed, narrows which links are titles
(`entry_re`) and episodes (`episode_re`). Titles are the links around a cover picture, episodes are links with an episode number,
streams are the .m3u8 / .mp4 addresses found in the episode page or in the player frames (iframes) it embeds.
"""
from __future__ import annotations

import html
import re
from html.parser import HTMLParser
from urllib.parse import quote_plus, urljoin, urlparse

from anihub.net.http import HttpError
from anihub.sources.anime.base import AnimeEntry, AnimeSource, AnimeSourceError, Episode, Stream

NOT_TITLES = {"page", "genre", "genres", "tag", "tags", "category", "categories", "search", "login", "register", "user", "users",
              "news", "contact", "contacts", "dmca", "rules", "faq", "feed", "schedule", "top", "random", "year", "years", "studio"}
MEDIA = re.compile(r"""https?://[^\s"'<>\\()]+?\.(?:m3u8|mp4|webm)(?:\?[^\s"'<>\\()]*)?""", re.I)
IFRAME = re.compile(r"""<iframe\b[^>]*?\b(?:data-src|src)\s*=\s*["']([^"']+)["']""", re.I)
EPISODE_NUMBER = re.compile(r"(?:episode|ep|seriya|seria|серия|серии|эпизод|e)[\s_/\-.:]*(\d{1,4}(?:\.\d)?)\b", re.I)
QUALITY = re.compile(r"(\d{3,4})p", re.I)


class _Anchor:
    def __init__(self, href: str, title: str):
        self.href, self.title, self.text, self.img, self.alt = href, title, "", "", ""


class _Links(HTMLParser):
    """Every <a href> with its title attribute, visible text and the first <img> inside it."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.anchors: list[_Anchor] = []
        self.rel_next = False
        self._open: _Anchor | None = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "a" and a.get("href"):
            self._open = _Anchor(a["href"], (a.get("title") or "").strip())
            self.anchors.append(self._open)
            if "next" in (a.get("rel") or "").split():
                self.rel_next = True
        elif tag == "img" and self._open is not None and not self._open.img:
            self._open.img = a.get("data-src") or a.get("data-original") or a.get("data-lazy-src") or a.get("src") or ""
            self._open.alt = (a.get("alt") or "").strip()

    def handle_endtag(self, tag):
        if tag == "a":
            self._open = None

    def handle_data(self, data):
        if self._open is not None:
            self._open.text += data


def parse_links(page: str) -> _Links:
    parser = _Links()
    parser.feed(page)
    return parser


def media_urls(text: str) -> list[str]:
    """Video addresses in a page (also those inside JSON strings with escaped slashes), best-looking quality first."""
    text = html.unescape(text).replace("\\/", "/").replace("\\u0026", "&")
    found = list(dict.fromkeys(MEDIA.findall(text)))
    return sorted(found, key=lambda u: -int((QUALITY.search(u) or [0, 0])[1] or 0))


class ScrapedSite(AnimeSource):
    site = ""                      # "https://example.org"
    list_url = ""                  # first catalogue page; "{page}" is replaced by the page number
    search_url = ""                # "{q}" is the URL-quoted query, "{page}" the page number
    entry_re = r"^/[^/]+/[^/?#]+/?$"      # which paths are titles (the link must also contain a cover picture)
    episode_re = r""               # which paths are episodes (empty = any link with an episode number in it)
    interval_ms = 800

    # --- helpers ------------------------------------------------------------------------------------------------------

    def _get(self, url: str, referer: str = "") -> str:
        try:
            return self.http.get_text(url, headers={"Referer": referer} if referer else None, interval_ms=self.interval_ms)
        except HttpError as exc:
            raise AnimeSourceError(f"{self.title}: {exc}") from exc

    def _absolute(self, href: str, base: str = "") -> str:
        return urljoin(base or self.site + "/", html.unescape(href.strip()))

    def _is_title(self, path: str) -> bool:
        parts = [p for p in path.split("/") if p]
        return bool(re.search(self.entry_re, path)) and parts and parts[0].lower() not in NOT_TITLES and parts[-1].lower() not in NOT_TITLES \
            and not re.fullmatch(r"\d+", parts[-1]) and not path.lower().startswith(("/page", "/?"))

    def _entries(self, page: str) -> tuple[list[AnimeEntry], _Links]:
        links = parse_links(page)
        found: dict[str, AnimeEntry] = {}
        for a in links.anchors:
            url = self._absolute(a.href)
            parsed = urlparse(url)
            if parsed.netloc != urlparse(self.site).netloc or not self._is_title(parsed.path):
                continue
            title = a.title or a.alt or " ".join(a.text.split())
            cover = self._absolute(a.img) if a.img and not a.img.startswith("data:") else ""
            old = found.get(parsed.path)
            if old is None and not cover:
                continue                                    # only links around a cover start an entry; a text link just names it
            if old is None:
                found[parsed.path] = AnimeEntry(id=parsed.path, title=title or parsed.path.strip("/").split("/")[-1], cover=cover, url=url)
            else:
                old.title = old.title if len(old.title) >= len(title) and " " in old.title else (title or old.title)
                old.cover = old.cover or cover
        return list(found.values()), links

    @staticmethod
    def _has_next(links: _Links, page: int) -> bool:
        pattern = re.compile(rf"(?:[?&]page={page + 1}\b|/page/{page + 1}/?(?:$|\?))")
        return links.rel_next or any(pattern.search(a.href) for a in links.anchors)

    # --- AnimeSource ------------------------------------------------------------------------------------------------

    def search(self, query: str, page: int = 1) -> tuple[list[AnimeEntry], bool]:
        query = query.strip()
        if query and self.search_url:
            entries, links = self._entries(self._get(self.search_url.format(q=quote_plus(query), page=page)))
            if entries:
                return entries, self._has_next(links, page)
        entries, links = self._entries(self._get(self.list_url.format(page=page)))
        if query:                                           # the site's search found nothing (or there is none): filter what the page shows
            entries = [e for e in entries if query.lower() in e.title.lower()]
        return entries, self._has_next(links, page)

    def episodes(self, entry: AnimeEntry) -> list[Episode]:
        page = self._get(entry.url or self._absolute(entry.id))
        episodes: dict[str, Episode] = {}
        for a in parse_links(page).anchors:
            url = self._absolute(a.href, entry.url or self.site + "/")
            parsed = urlparse(url)
            if parsed.netloc != urlparse(self.site).netloc or parsed.path.rstrip("/") == entry.id.rstrip("/"):
                continue
            if self.episode_re and not re.search(self.episode_re, parsed.path):
                continue
            label = " ".join(a.text.split()) or a.title
            match = EPISODE_NUMBER.search(parsed.path) or EPISODE_NUMBER.search(label)
            if match and parsed.path not in episodes:
                episodes[parsed.path] = Episode(id=parsed.path, number=float(match.group(1)), title="" if label.lower().startswith(("серия", "episode", "ep")) else label)
        if not episodes:                                    # a single video on the title page (a film / OVA)
            return [Episode(id=entry.id, number=1.0, title=entry.title)]
        return sorted(episodes.values(), key=lambda e: e.number)

    def streams(self, entry: AnimeEntry, episode: Episode) -> list[Stream]:
        url = self._absolute(episode.id)
        page = self._get(url, self.site + "/")
        found: list[tuple[str, str]] = [(u, url) for u in media_urls(page)]        # (video address, page it came from)
        if not found:
            for frame in list(dict.fromkeys(IFRAME.findall(html.unescape(page))))[:4]:
                frame_url = self._absolute(frame, url)
                try:
                    found += [(u, frame_url) for u in media_urls(self._get(frame_url, url))]
                except AnimeSourceError:
                    continue
        if not found:
            raise AnimeSourceError(f"{self.title}: no video address found on the episode page (the player may be protected or need a login)")
        streams = []
        for video, origin in found:
            quality = QUALITY.search(video)
            label = f"{quality.group(1)}p" if quality else video.rsplit(".", 1)[-1].split("?")[0].upper()
            referer = f"{urlparse(origin).scheme}://{urlparse(origin).netloc}/"
            streams.append(Stream(video, label, {"Referer": referer}))
        return streams
