"""Example anime source plugin. Copy it to  %APPDATA%\\AniHUB\\plugins\\anime\\  and restart AniHUB:
a "Sample site" entry then appears in the source list of Anime -> Watch.

A plugin is a class with three methods (see src/anihub/sources/anime/base.py). Use `self.http` for every request: it applies the
proxy, the rate limit and the offline switch. This example talks to a made-up JSON API; adapt the URLs and fields to the real site.
Only put your own code here: plugins run with your user rights.
"""
from anihub.net.http import HttpError
from anihub.sources.anime.base import AnimeEntry, AnimeSource, AnimeSourceError, Episode, Stream

BASE = "https://example.invalid/api"


class SampleSite(AnimeSource):
    name = "sample"                 # unique key
    title = "Sample site"           # shown in the UI

    def search(self, query, page=1):
        try:
            data = self.http.get_json(f"{BASE}/search", params={"q": query, "page": page})
        except HttpError as exc:
            raise AnimeSourceError(f"Sample site: {exc}") from exc
        entries = [AnimeEntry(id=str(x["id"]), title=x["title"], cover=x.get("poster", ""), url=x.get("url", ""))
                   for x in data.get("results", [])]
        return entries, bool(data.get("has_next"))

    def episodes(self, entry):
        data = self.http.get_json(f"{BASE}/anime/{entry.id}/episodes")
        return [Episode(id=str(e["id"]), number=float(e["number"]), title=e.get("title", "")) for e in data["episodes"]]

    def streams(self, entry, episode):
        data = self.http.get_json(f"{BASE}/episode/{episode.id}/streams")
        # `headers` (for example Referer) are only used by the external player: the built-in one cannot send them
        return [Stream(url=s["url"], label=s.get("quality", ""), headers=s.get("headers", {})) for s in data["streams"]]
