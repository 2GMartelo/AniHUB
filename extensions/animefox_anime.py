"""Anime catalogue of animefox.org (/anime/).

The site was not reachable from the machine this extension was written on, so the page layout is matched generically (covers, episode
numbers, .m3u8/.mp4 addresses, player frames). If the title list, episodes or playing fail, send the page's HTML to adjust the matching.
"""
from anihub.sources.anime.sitescrape import ScrapedSite

EXTENSION = {"id": "animefox_anime", "kind": "anime", "name": "AnimeFox", "lang": "multi", "version": "1.0",
             "description": "Anime catalogue of animefox.org (/anime/).", "nsfw": False}


class AnimeFoxAnime(ScrapedSite):
    name = "animefox_anime"
    title = "AnimeFox"
    lang = "multi"
    nsfw = False
    version = "1.0"
    site = "https://www.animefox.org"
    list_url = "https://www.animefox.org/anime/?page={page}"
    search_url = "https://www.animefox.org/search/?q={q}&page={page}"
    entry_re = r"^/anime/[^/?#]+/?$"
