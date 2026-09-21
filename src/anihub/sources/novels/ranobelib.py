"""RanobeLib (ranobelib.me): Russian-language novels and fan translations, through the JSON API the site itself uses
(the LibGraph API, `Site-Id: 3` selects RanobeLib). No login is needed for reading.

The site marks every title with an age restriction (none / 6+ / 12+ / 16+ / 18+): `NovelEntry.age` carries it, so the age mode of
AniHUB decides what is shown. Chapters exist in several translation branches; the first branch of a chapter is used.
"""
from __future__ import annotations

import re

from anihub.net.http import HttpError
from anihub.sources.novels.base import NovelChapter, NovelEntry, NovelSource, NovelSourceError

API = "https://api2.mangalib.me/api"
SITE = "https://ranobelib.me"
SITE_ID = 3
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
HEADERS = {"Site-Id": str(SITE_ID), "Referer": SITE + "/", "Origin": SITE, "Accept": "application/json"}


def age_of(raw: dict) -> int:
    """'16+' -> 16; no restriction -> 0."""
    label = str((raw.get("ageRestriction") or {}).get("label") or "")
    m = re.match(r"(\d+)\+", label)
    return int(m.group(1)) if m else 0


class RanobeLib(NovelSource):
    name = "ranobelib"
    title = "RanobeLib"
    lang = "ru"

    def __init__(self, http, cfg):
        super().__init__(http, cfg)
        register = getattr(http, "add_host_headers", None)
        if register:                                    # covers (cdnlibs.org) and chapter pictures answer 403 without the site's Referer
            for host in ("cdnlibs.org", "ranobelib.me", "mangalib.me", "cdnlib.link"):
                register(host, lambda: {"Referer": SITE + "/", "User-Agent": UA})

    def _get(self, path: str, params=None):
        try:
            data = self.http.get_json(API + path, params=params, headers=HEADERS, interval_ms=350)
        except (HttpError, ValueError) as exc:
            raise NovelSourceError(f"RanobeLib: {exc}") from exc
        if not isinstance(data, dict) or "data" not in data:
            raise NovelSourceError("RanobeLib: unexpected answer")
        return data

    def _entry(self, raw: dict) -> NovelEntry:
        name = raw.get("rus_name") or raw.get("eng_name") or raw.get("name") or str(raw.get("id"))
        cover = raw.get("cover") or {}
        slug = raw.get("slug_url") or str(raw.get("id"))
        return NovelEntry(id=slug, title=name, cover=cover.get("default") or cover.get("md") or cover.get("thumbnail") or "",
                          url=f"{SITE}/ru/book/{slug}", age=age_of(raw))

    def search(self, query: str, page: int = 1) -> tuple[list[NovelEntry], bool]:
        params: list[tuple[str, object]] = [("site_id[]", SITE_ID), ("page", page)]
        if query.strip():
            params.append(("q", query.strip()))
        else:
            params.append(("sort_by", "rate_avg"))
        data = self._get("/manga", params)
        more = bool((data.get("meta") or {}).get("has_next_page"))
        return [self._entry(r) for r in data["data"] if isinstance(r, dict)], more

    def details(self, entry: NovelEntry) -> NovelEntry:
        data = self._get(f"/manga/{entry.id}", [("fields[]", "summary"), ("fields[]", "genres"), ("fields[]", "tags"),
                                                ("fields[]", "authors")])["data"]
        summary = data.get("summary") or ""
        if isinstance(summary, dict):                     # a ProseMirror document
            summary = re.sub(r"<[^>]+>", "", prosemirror_html(summary, {}).replace("</p>", "\n"))
        entry.description = re.sub(r"[ \t]+\n", "\n", str(summary)).strip()
        entry.tags = [t["name"] for key in ("genres", "tags") for t in (data.get(key) or []) if isinstance(t, dict) and t.get("name")]
        authors = [a["name"] for a in (data.get("authors") or []) if isinstance(a, dict) and a.get("name")]
        entry.author = ", ".join(authors[:3])
        entry.age = age_of(data) or entry.age
        return entry

    def chapters(self, entry: NovelEntry) -> list[NovelChapter]:
        chapters = []
        for raw in self._get(f"/manga/{entry.id}/chapters")["data"]:
            volume, number = str(raw.get("volume") or "1"), str(raw.get("number") or "0")
            branches = raw.get("branches") or []
            branch = branches[0].get("branch_id") if branches else None
            title = f"Том {volume}. Глава {number}" + (f". {raw['name']}" if raw.get("name") else "")
            try:
                value = float(number)
            except ValueError:
                value = 0.0
            chapters.append(NovelChapter(id=f"{volume}/{number}/{branch or ''}", title=title, number=value))
        return chapters

    def chapter_html(self, entry: NovelEntry, chapter: NovelChapter) -> str:
        volume, number, branch = (chapter.id.split("/") + ["", "", ""])[:3]
        params = [("volume", volume), ("number", number)] + ([("branch_id", branch)] if branch else [])
        data = self._get(f"/manga/{entry.id}/chapter", params)["data"]
        content = data.get("content")
        if isinstance(content, str):
            html = content
        else:                                           # a ProseMirror document: rarely, for some titles
            attachments = {str(a.get("name") or a.get("filename")): a.get("url", "") for a in data.get("attachments") or []}
            html = prosemirror_html(content, attachments)
        html = re.sub(r'src="/(?!/)', f'src="{SITE}/', html)
        return html or f"<p>{data.get('name') or ''}</p>"


def prosemirror_html(node, attachments: dict[str, str]) -> str:
    """Minimal ProseMirror -> HTML: paragraphs, headings, marks, images (attachments by name)."""
    if not isinstance(node, dict):
        return ""
    kind = node.get("type")
    inner = "".join(prosemirror_html(c, attachments) for c in node.get("content") or [])
    if kind == "text":
        text = str(node.get("text") or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        for mark in node.get("marks") or []:
            tag = {"bold": "b", "italic": "i", "underline": "u", "strike": "s"}.get(mark.get("type"))
            if tag:
                text = f"<{tag}>{text}</{tag}>"
        return text
    if kind == "paragraph":
        return f"<p>{inner}</p>"
    if kind == "heading":
        level = min(max(int((node.get("attrs") or {}).get("level") or 2), 1), 4)
        return f"<h{level}>{inner}</h{level}>"
    if kind == "hardBreak":
        return "<br/>"
    if kind == "horizontalRule":
        return "<hr/>"
    if kind == "blockquote":
        return f"<blockquote>{inner}</blockquote>"
    if kind == "image":
        images = (node.get("attrs") or {}).get("images") or []
        urls = [attachments.get(str(i.get("image")), "") for i in images if isinstance(i, dict)]
        return "".join(f'<p><img src="{SITE + u if u.startswith("/") else u}"/></p>' for u in urls if u)
    return inner
