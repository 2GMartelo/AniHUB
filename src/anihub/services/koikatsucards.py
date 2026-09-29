"""koikatsucards.com: browsing and downloading Koikatsu character cards. The site has no public API -- HTML
scraping like sources/pinterest.py, fragile by nature (may break if the site's markup changes).

Downloading a card needs the visitor to be signed in: the site's own "Website Download" link answers a plain
anonymous request with a redirect to /login instead of the file. This reuses the SAME generic cookie jar every
other source already reads (net/http.py's HttpClient._merged_headers, cfg["cookie.jar"]) -- once the user imports
their browser's koikatsucards.com cookies through the existing "Import logins from a file" feature (ui/settings.py,
ui/cookie_import.py), downloads here start working with no extra plumbing."""
from __future__ import annotations

import html as html_lib
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

from anihub.net.http import HttpClient, HttpError

BASE = "https://koikatsucards.com"
_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
_CARD = re.compile(
    r'contentCardLink[^>]*href="(?P<href>/contents/[^"]+)"[^>]*>.*?'
    r'<img[^>]*alt="(?P<alt>[^"]*)"[^>]*src="(?P<src>[^"]+)"[^>]*/>.*?'
    r'<div class="eyebrow">(?P<work>[^<]*)</div>\s*<h3>(?P<title>[^<]*)</h3>\s*'
    r'(?:<p class="muted">(?P<author>[^<]*)</p>)?',
    re.S,
)
_TOKEN = re.compile(r'href="(/api/downloads/content-file/token/[\w.\-]+)"')


class KoikatsuCardsError(Exception):
    pass


@dataclass
class Card:
    slug: str        # the /contents/<slug> path segment: the stable id this site uses
    title: str
    work: str         # franchise/series, "Original" for an original character
    author: str
    thumb: str        # a small preview picture: no login needed to view this


def _unescape(text: str) -> str:
    return html_lib.unescape(text or "").strip()


def search(http: HttpClient, query: str = "", page: int = 1) -> list[Card]:
    """Character cards. `query` is matched against the site's own tag index (its search has no free-text mode);
    an empty query lists everything, newest/most relevant first as the site itself orders it."""
    url = f"{BASE}/search?types=type-character-card"
    if query.strip():
        url += f"&tag={quote(query.strip())}"
    if page > 1:
        url += f"&page={page}"
    try:
        text = http.get_text(url, headers={"User-Agent": _UA})
    except HttpError as exc:
        raise KoikatsuCardsError(str(exc)) from exc
    cards = []
    for m in _CARD.finditer(text):
        slug = m.group("href").rsplit("/", 1)[-1]
        cards.append(Card(slug=slug, title=_unescape(m.group("title")) or _unescape(m.group("alt")),
                          work=_unescape(m.group("work")), author=_unescape(m.group("author")), thumb=m.group("src")))
    return cards


def download_url(http: HttpClient, slug: str) -> str:
    """The card's own download link, read off its page (server-rendered, same for every visitor -- only actually
    fetching it needs to be signed in)."""
    try:
        text = http.get_text(f"{BASE}/contents/{slug}", headers={"User-Agent": _UA})
    except HttpError as exc:
        raise KoikatsuCardsError(str(exc)) from exc
    m = _TOKEN.search(text)
    if not m:
        raise KoikatsuCardsError("No download link found on the card's page")
    return BASE + m.group(1)


def download_card(http: HttpClient, slug: str, dest_dir: Path) -> Path:
    """Downloads one card into `dest_dir`. Raises KoikatsuCardsError (mentioning the sign-in requirement) when the
    response is HTML instead of a card file -- the tell-tale sign of the site's own not-signed-in redirect, since
    HttpClient follows redirects automatically and would otherwise silently save a login page as the "card"."""
    url = download_url(http, slug)
    try:
        data = http.get_bytes(url)
    except HttpError as exc:
        raise KoikatsuCardsError(str(exc)) from exc
    if data[:15].lstrip()[:1] in (b"<", b"") or b"<html" in data[:200].lower():
        raise KoikatsuCardsError("koikatsucards.com asked to sign in -- import its cookies in Settings first "
                                 "(Network & sources -> Import logins from a file)")
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{slug}.png"
    dest.write_bytes(data)
    return dest
