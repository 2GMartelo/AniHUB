"""E-Hentai (e-hentai.org): galleries as posts.

- The search page (HTML) only yields gallery ids; details come from the official JSON API (api.e-hentai.org, `gdata`,
  25 galleries per request): title, category, thumbnail, tags with namespaces, rating.
- A gallery has many pages; the post stands for the gallery: its thumbnail is the cover and saving/viewing takes the
  FIRST page image (resolved lazily: gallery page -> first image page -> image URL). The gallery page opens in the browser.
- Everything on the site is adult content: 'Non-H' galleries count as 'sensitive', all others as 'explicit'. Without the
  'explicit' rating enabled the search is restricted to Non-H, so no adult thumbnail is ever fetched.
- Be gentle: the site bans IPs that hit it too fast (interval 1.5 s, one request per page).
"""
from __future__ import annotations

import re

from anihub.net.http import HttpError
from anihub.sources.base import Post, Source, SourceError, url_ext

BASE = "https://e-hentai.org"
API = "https://api.e-hentai.org/api.php"
HEADERS = {"Cookie": "nw=1"}                       # skips the "offensive content" interstitial of a gallery
ALL_CATEGORIES = 1023                              # f_cats is a bitmask of the categories to EXCLUDE
NON_H = 256
NAMESPACE_CATEGORY = {"artist": "artist", "group": "artist", "parody": "copyright", "character": "character",
                      "language": "meta", "other": "meta", "reclass": "meta", "cosplayer": "artist"}

_GALLERY = re.compile(r"/g/(\d+)/([0-9a-f]{10})/")
_IMAGE_PAGE = r"https://e-hentai\.org/s/[0-9a-f]+/%s-1"
_IMG = re.compile(r'<img[^>]+id="img"[^>]+src="([^"]+)"')


def search_token(tag: str) -> str:
    """A booru-style tag (underscores) -> e-hentai search syntax: namespace:"two words$", exclusion with '-'."""
    negative = tag.startswith("-")
    text = (tag[1:] if negative else tag).replace("_", " ").strip()
    if not text:
        return ""
    if ":" in text:
        namespace, _, name = text.partition(":")
        token = f'{namespace}:"{name}$"' if " " in name else f"{namespace}:{name}$"
    else:
        token = f'"{text}"' if " " in text else text
    return ("-" if negative else "") + token


def parse_tag(raw: str) -> tuple[str, str]:
    """'female:big breasts' -> ('big_breasts', 'general'); 'artist:foo bar' -> ('foo_bar', 'artist')."""
    namespace, sep, name = raw.partition(":")
    if not sep:
        namespace, name = "", raw
    return name.strip().replace(" ", "_"), NAMESPACE_CATEGORY.get(namespace, "general")


class EHentai(Source):
    name = "ehentai"
    title = "E-Hentai"
    interval_ms = 1500

    # --- search ---------------------------------------------------------------------------------

    def _categories(self) -> tuple[int, str]:
        """(f_cats bitmask, rating of what the mask lets through) for the user's content-rating setting."""
        allowed = set(self.cfg.get("ratings.allowed", ["general"]))
        if "explicit" in allowed or "questionable" in allowed:
            return 0, "explicit"
        if "sensitive" in allowed:
            return ALL_CATEGORIES - NON_H, "sensitive"
        raise SourceError("E-Hentai: adult content only. Enable the 'sensitive' or 'explicit' rating in Settings.")

    def _rating(self, category: str) -> str:
        return "sensitive" if category.lower() == "non-h" else "explicit"

    def search(self, tags: list[str], page: int, limit: int) -> list[Post]:
        cats, _ = self._categories()
        query = " ".join(t for t in (search_token(t) for t in tags) if t)
        params = {"f_search": query, "page": max(page - 1, 0)}
        if cats:
            params["f_cats"] = cats
        try:
            html = self.http.get_text(f"{BASE}/", params=params, headers=HEADERS, interval_ms=self.interval_ms)
        except HttpError as exc:
            raise SourceError(f"E-Hentai: {exc}") from exc
        if "temporarily banned" in html:
            raise SourceError("E-Hentai: your IP is temporarily banned for too many requests; wait a while.")
        ids = list(dict.fromkeys(_GALLERY.findall(html)))
        if not ids:
            return []
        return self._details(ids)

    def _details(self, ids: list[tuple[str, str]]) -> list[Post]:
        try:
            data = self.http.post_json(API, {"method": "gdata", "gidlist": [[int(g), t] for g, t in ids[:25]], "namespace": 1},
                                       interval_ms=self.interval_ms)
        except HttpError as exc:
            raise SourceError(f"E-Hentai: {exc}") from exc
        if not isinstance(data, dict) or "gmetadata" not in data:
            raise SourceError("E-Hentai: unexpected API response")
        by_id = {str(g["gid"]): g for g in data["gmetadata"] if "error" not in g}
        return [self._parse(by_id[gid]) for gid, _ in ids if gid in by_id and not by_id[gid].get("expunged")]

    def _parse(self, g: dict) -> Post:
        gid = str(g["gid"])
        tags, artists = [], []
        for raw in g.get("tags", []):
            name, category = parse_tag(raw)
            if name and (name, category) not in tags:
                tags.append((name, category))
            if category == "artist" and raw.startswith("artist:"):
                artists.append(name)
        try:
            score = round(float(g.get("rating") or 0) * 2)          # 0..5 stars -> 0..10
        except ValueError:
            score = 0
        post = Post(
            site=self.name, id=gid, file_url="", preview_url=g.get("thumb") or "", page_url=f"{BASE}/g/{gid}/{g['token']}/",
            rating=self._rating(g.get("category", "")), tags=tags, author=" ".join(artists), score=score,
            title=g.get("title", ""))
        post.resolver = lambda p, token=g["token"]: self._resolve(p, token)
        return post

    # --- first page image -----------------------------------------------------------------------

    def _resolve(self, post: Post, token: str) -> None:
        try:
            gallery = self.http.get_text(post.page_url, headers=HEADERS, interval_ms=self.interval_ms)
            match = re.search(_IMAGE_PAGE % re.escape(post.id), gallery)
            if not match:
                raise SourceError(f"E-Hentai: no pages found in gallery #{post.id}")
            page = self.http.get_text(match.group(0), headers=HEADERS, interval_ms=self.interval_ms)
        except HttpError as exc:
            raise SourceError(f"E-Hentai: cannot open gallery #{post.id}: {exc}") from exc
        found = _IMG.search(page)
        if not found:
            raise SourceError(f"E-Hentai: no image on the first page of #{post.id} (image limit reached?)")
        post.file_url = found.group(1).replace("&amp;", "&")
        post.ext = url_ext(post.file_url)
