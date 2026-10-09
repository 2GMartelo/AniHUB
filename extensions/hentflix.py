"""Adult catalogue of hentflix.org, 18+ age mode only.

The site was not reachable from the machine this extension was written on, so the page layout is matched generically (covers, episode
numbers, .m3u8/.mp4 addresses, player frames). If the title list, episodes or playing fail, send the page's HTML to adjust the matching.
"""
from anihub.sources.anime.sitescrape import ScrapedSite

EXTENSION = {"id": "hentflix", "kind": "anime", "name": "Hentflix", "lang": "multi", "version": "1.0",
             "description": "Adult catalogue of hentflix.org, 18+ age mode only.", "nsfw": True}


class Hentflix(ScrapedSite):
    name = "hentflix"
    title = "Hentflix"
    lang = "multi"
    nsfw = True
    version = "1.0"
    site = "https://v2.hentflix.org"
    list_url = "https://v2.hentflix.org/?page={page}"
    search_url = "https://v2.hentflix.org/?s={q}"
    entry_re = r"^/[^/]+/[^/?#]+/?$"
