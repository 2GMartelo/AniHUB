"""Adult catalogue of animefox.org (/hentai/), 18+ age mode only.

The site was not reachable from the machine this extension was written on, so the page layout is matched generically (covers, episode
numbers, .m3u8/.mp4 addresses, player frames). If the title list, episodes or playing fail, send the page's HTML to adjust the matching.
"""
from anihub.sources.anime.sitescrape import ScrapedSite

EXTENSION = {"id": "animefox_hentai", "kind": "anime", "name": "AnimeFox 18+", "lang": "multi", "version": "1.0",
             "description": "Adult catalogue of animefox.org (/hentai/), 18+ age mode only.", "nsfw": True}


class AnimeFoxHentai(ScrapedSite):
    name = "animefox_hentai"
    title = "AnimeFox 18+"
    lang = "multi"
    nsfw = True
    version = "1.0"
    site = "https://www.animefox.org"
    list_url = "https://www.animefox.org/hentai/?page={page}"
    search_url = "https://www.animefox.org/search/?q={q}&page={page}"
    entry_re = r"^/hentai/[^/?#]+/?$"
