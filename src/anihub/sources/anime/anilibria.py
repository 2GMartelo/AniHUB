"""AniLibria (anilibria.top): Russian voice-over releases, through the team's public API v1 (https://anilibria.top/api/docs/v1).

Streams are HLS (m3u8) in 480p / 720p / 1080p and need no special headers. Releases that are blocked for the visitor's
country or by the rights holders come with no streams, and the source says so.
"""
from __future__ import annotations

from anihub.net.http import HttpError
from anihub.sources.anime.base import AnimeEntry, AnimeSource, AnimeSourceError, Episode, Stream

SITE = "https://anilibria.top"
API = SITE + "/api/v1"
PER_PAGE = 30


class AniLibria(AnimeSource):
    name = "anilibria"
    title = "AniLibria"
    lang = "ru"

    def _get(self, path: str, params: dict | None = None):
        try:
            return self.http.get_json(API + path, params=params, interval_ms=300)
        except (HttpError, ValueError) as exc:
            raise AnimeSourceError(f"AniLibria: {exc}") from exc

    @staticmethod
    def _cover(raw: dict) -> str:
        poster = raw.get("poster") or {}
        path = (poster.get("optimized") or {}).get("preview") or poster.get("preview") or poster.get("src") or ""
        return path if path.startswith("http") else (SITE + path if path else "")

    def _entry(self, raw: dict) -> AnimeEntry:
        name = raw.get("name") or {}
        return AnimeEntry(id=str(raw["id"]), title=name.get("main") or name.get("english") or str(raw["id"]),
                          cover=self._cover(raw), url=f"{SITE}/anime/releases/release/{raw.get('alias', '')}",
                          description=(raw.get("description") or "").strip())

    def search(self, query: str, page: int = 1) -> tuple[list[AnimeEntry], bool]:
        if query.strip():
            data = self._get("/app/search/releases", {"query": query.strip()})       # one page, best matches first
            return [self._entry(r) for r in data if isinstance(r, dict) and "id" in r], False
        data = self._get("/anime/catalog/releases", {"page": page, "limit": PER_PAGE})
        pagination = (data.get("meta") or {}).get("pagination") or {}
        more = int(pagination.get("current_page") or page) < int(pagination.get("total_pages") or 0)
        return [self._entry(r) for r in data.get("data", [])], more

    def _release(self, entry: AnimeEntry) -> dict:
        data = self._get(f"/anime/releases/{entry.id}")
        if not isinstance(data, dict) or "episodes" not in data:
            raise AnimeSourceError("AniLibria: unexpected answer")
        return data

    def episodes(self, entry: AnimeEntry) -> list[Episode]:
        release = self._release(entry)
        eps = [Episode(id=e["id"], number=float(e.get("ordinal") or 0), title=e.get("name") or "")
               for e in release.get("episodes", []) if e.get("id")]
        return sorted(eps, key=lambda e: e.number)

    def streams(self, entry: AnimeEntry, episode: Episode) -> list[Stream]:
        for raw in self._release(entry).get("episodes", []):
            if raw.get("id") == episode.id:
                found = [Stream(raw[key], label) for key, label in (("hls_1080", "1080p"), ("hls_720", "720p"), ("hls_480", "480p"))
                         if raw.get(key)]
                return found
        return []
