"""Anime365 (smotret-anime.org): the big Russian anime site. Its translations are what makes it useful here: Russian SUBTITLES (fansub and
official ones), Russian voice-over and the raw episode, for almost every title.

The catalogue and the list of translations are open (public API). The video itself is only given to a logged-in visitor, so streams need the
site's cookies: export them from the browser and import the file (Settings > Credentials > "Import logins from a cookies file", or just
drop the file on the window). Without them the titles and episodes are listed and playing says what is missing."""
from __future__ import annotations

import html
import json
import re

from anihub.net.http import HttpError
from anihub.sources.anime.base import AnimeEntry, AnimeSource, AnimeSourceError, Episode, Stream

SITE = "https://smotret-anime.org"
API = SITE + "/api"
PER_PAGE = 30
# what a translation is called on the site -> (order in the list, label). Russian subtitles first: that is why this source exists.
KINDS = {"subRu": (0, "RU sub"), "voiceRu": (1, "RU voice"), "subEn": (2, "EN sub"), "voiceEn": (3, "EN voice"), "raw": (4, "RAW")}
MAX_PER_KIND = {"subRu": 3, "voiceRu": 2, "subEn": 1, "voiceEn": 0, "raw": 1}
EPISODE_TYPES = {"tv", "movie", "ova", "ona", "special", "tv-special"}


class Anime365(AnimeSource):
    name = "anime365"
    title = "Anime365 (RU subs)"
    lang = "ru"

    def _get(self, path: str, params: dict | None = None):
        try:
            data = self.http.get_json(API + path, params=params, interval_ms=300)
        except (HttpError, ValueError) as exc:
            raise AnimeSourceError(f"Anime365: {exc}") from exc
        if isinstance(data, dict) and data.get("error"):
            raise AnimeSourceError(f"Anime365: {(data['error'] or {}).get('message', 'error')}")
        return data.get("data") if isinstance(data, dict) else data

    @staticmethod
    def _entry(raw: dict) -> AnimeEntry:
        titles = raw.get("titles") or {}
        descriptions = raw.get("descriptions") or []
        text = next((d.get("value", "") for d in descriptions if isinstance(d, dict)), "") if isinstance(descriptions, list) else ""
        return AnimeEntry(id=str(raw["id"]), title=titles.get("ru") or titles.get("romaji") or titles.get("en") or str(raw["id"]),
                          cover=raw.get("posterUrl") or "", url=raw.get("url") or f"{SITE}/catalog/{raw['id']}",
                          description=re.sub(r"<[^>]+>|\[[^\]]*\]", "", html.unescape(text)).strip())

    def search(self, query: str, page: int = 1) -> tuple[list[AnimeEntry], bool]:
        params = {"limit": PER_PAGE, "offset": (page - 1) * PER_PAGE, "fields": "id,titles,posterUrl,url,isHentai,descriptions"}
        if query.strip():
            params["query"] = query.strip()
        rows = self._get("/series/", params) or []
        entries = [self._entry(r) for r in rows if isinstance(r, dict) and "id" in r and not r.get("isHentai")]
        return entries, len(rows) >= PER_PAGE

    def episodes(self, entry: AnimeEntry) -> list[Episode]:
        series = self._get(f"/series/{entry.id}")
        if not isinstance(series, dict):
            raise AnimeSourceError("Anime365: unexpected answer")
        eps = []
        for raw in series.get("episodes") or []:
            if not raw.get("isActive", 1) or (raw.get("episodeType") or "tv") not in EPISODE_TYPES:
                continue                                                # trailers and the like
            number = float(raw.get("episodeInt") or 0)
            full = str(raw.get("episodeFull") or "")
            eps.append(Episode(id=str(raw["id"]), number=number, title=raw.get("episodeTitle") or ("" if full.endswith("серия") else full)))
        return sorted(eps, key=lambda e: e.number)

    def _translations(self, episode: Episode) -> list[dict]:
        data = self._get(f"/episodes/{episode.id}")
        chosen: list[dict] = []
        for kind, (_order, _label) in sorted(KINDS.items(), key=lambda kv: kv[1][0]):
            same = [t for t in (data or {}).get("translations", []) if t.get("type") == kind and t.get("isActive", 1)]
            same.sort(key=lambda t: (-int(t.get("height") or 0), -int(t.get("priority") or 0)))
            chosen += same[:MAX_PER_KIND[kind]]
        return chosen

    @staticmethod
    def parse_embed(page: str) -> tuple[list[tuple[int, str]], str, str]:
        """(video sources [(height, url)], subtitles url (vtt), subtitles url (ass)) out of an embed page's <video> tag."""
        tag = re.search(r"<video\b[^>]*>", page)
        attrs = {k: html.unescape(v) for k, v in re.findall(r'\b(data-[a-z-]+)="([^"]*)"', tag.group(0))} if tag else {}
        sources: list[tuple[int, str]] = []
        try:
            raw = json.loads(attrs.get("data-sources") or "[]")
        except ValueError:
            raw = []
        for item in raw if isinstance(raw, list) else []:
            if not isinstance(item, dict):
                continue
            urls = item.get("urls") or ([item["url"]] if item.get("url") else []) or ([item["src"]] if item.get("src") else [])
            if urls:
                sources.append((int(item.get("height") or 0), str(urls[0])))
        absolute = lambda p: p if p.startswith("http") else (SITE + p if p else "")            # noqa: E731
        return sorted(sources, reverse=True), absolute(attrs.get("data-vtt", "")), absolute(attrs.get("data-subtitles", ""))

    def streams(self, entry: AnimeEntry, episode: Episode) -> list[Stream]:
        found: list[Stream] = []
        locked = False
        for t in self._translations(episode):
            try:
                page = self.http.get_text(t.get("embedUrl") or f"{SITE}/translations/embed/{t['id']}", interval_ms=300)
            except HttpError as exc:
                raise AnimeSourceError(f"Anime365: {exc}") from exc
            sources, vtt, _ass = self.parse_embed(page)
            if not sources:
                locked = True
                continue
            kind_label = KINDS[t["type"]][1]
            author = (t.get("authorsSummary") or "").strip()
            for height, url in sources[:1]:                              # the best quality of each translation; others are separate rows
                label = " · ".join(p for p in (kind_label, author, f"{height}p" if height else "") if p)
                found.append(Stream(url, label, {"Referer": SITE + "/"}, [("ru" if t.get("typeLang") == "ru" else t.get("typeLang", ""), vtt)] if vtt and t["type"].startswith("sub") else []))
        if not found:
            raise AnimeSourceError("Anime365: log in to watch: import your cookies (Settings > Credentials > Import logins from a cookies file)."
                                   if locked else "Anime365: no translations for this episode")
        return found
