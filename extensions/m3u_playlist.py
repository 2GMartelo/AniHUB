"""Your own M3U playlist as an anime source: a playlist from your media server (Jellyfin, Plex via an exporter, a NAS, an
IPTV/VOD provider you subscribe to). Titles are grouped by the `group-title` attribute of the entries, or by the name before
" - 01" when there is none. Put the playlist address (http/https) or a local .m3u/.m3u8 path in the extension's settings.

This file is also a small template for writing a source: copy it, change `EXTENSION` and the three methods.
"""
import re
from pathlib import Path

from anihub.sources.anime.base import AnimeEntry, AnimeSource, AnimeSourceError, Episode, Stream

EXTENSION = {"id": "m3u_playlist", "kind": "anime", "name": "M3U playlist", "lang": "multi", "version": "1.0",
             "description": "Your own M3U/M3U8 playlist (media server, NAS or a service you subscribe to). Set its address in the extension settings."}

_INF = re.compile(r'#EXTINF:[^,]*?(?:group-title="([^"]*)")?[^,]*,(.*)')
_NUMBER = re.compile(r"(?:ep(?:isode)?\.?\s*|e|#|\s-\s)(\d{1,4})\b", re.I)


class M3UPlaylist(AnimeSource):
    name = "m3u_playlist"
    title = "M3U playlist"
    lang = "multi"
    version = "1.0"
    credentials = [("url", "Playlist address (http/https or a file path)")]

    def _items(self) -> list[tuple[str, str, str]]:
        """[(group, episode title, url)]"""
        location = str(self.cfg.get("sources.m3u_playlist.url") or "").strip()
        if not location:
            raise AnimeSourceError("M3U playlist: set the playlist address in the extension settings")
        text = self.http.get_text(location) if location.startswith("http") else Path(location).read_text(encoding="utf-8", errors="replace")
        items, pending = [], None
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("#EXTINF"):
                m = _INF.match(line)
                pending = (m.group(1) or "", m.group(2).strip()) if m else ("", "")
            elif line and not line.startswith("#") and pending is not None:
                group, title = pending
                items.append((group or re.split(r"\s+-\s+", title)[0].strip() or title, title, line))
                pending = None
        return items

    def search(self, query, page=1):
        groups: dict[str, int] = {}
        for group, _title, _url in self._items():
            groups[group] = groups.get(group, 0) + 1
        needle = query.strip().lower()
        entries = [AnimeEntry(id=g, title=g) for g in groups if not needle or needle in g.lower()]
        return entries, False

    def episodes(self, entry):
        eps = []
        for i, (group, title, url) in enumerate(self._items()):
            if group == entry.id:
                m = _NUMBER.search(title)
                eps.append(Episode(id=url, number=float(m.group(1)) if m else float(len(eps) + 1), title=title))
        return sorted(eps, key=lambda e: e.number)

    def streams(self, entry, episode):
        return [Stream(episode.id, "playlist")]
