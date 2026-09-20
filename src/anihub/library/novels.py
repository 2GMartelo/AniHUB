"""Light novels (ТЗ 11): read EPUB, FB2 and plain-text books. Nothing here needs Qt: a Book gives chapter titles, chapter HTML
(images point at `book:` URLs the reader resolves through Book.resource) and the cover."""
from __future__ import annotations

import base64
import html
import posixpath
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import unquote
from xml.etree import ElementTree as ET

BOOK_EXTS = {"epub", "fb2", "txt"}
CHUNK_CHARS = 18000                     # plain text without chapter headings is cut into parts of about this size


class BookError(Exception):
    pass


@dataclass
class Book:
    title: str = ""
    author: str = ""
    titles: list[str] = field(default_factory=list)
    cover: bytes | None = None
    _chapter: "callable" = None          # index -> html
    _resource: "callable" = None         # path -> bytes | None
    _close: "callable" = None

    def __len__(self) -> int:
        return len(self.titles)

    def chapter_html(self, index: int) -> str:
        return self._chapter(index)

    def resource(self, path: str) -> bytes | None:
        return self._resource(path) if self._resource else None

    def close(self) -> None:
        if self._close:
            self._close()


def open_book(path: Path) -> Book:
    ext = Path(path).suffix.lstrip(".").lower()
    try:
        if ext == "epub":
            return _open_epub(Path(path))
        if ext == "fb2":
            return _open_fb2(Path(path))
        if ext == "txt":
            return _open_txt(Path(path))
    except BookError:
        raise
    except (zipfile.BadZipFile, ET.ParseError, KeyError, OSError, ValueError) as exc:
        raise BookError(f"{Path(path).name}: {exc}") from exc
    raise BookError(f"unsupported format: .{ext}")


# --- helpers ---------------------------------------------------------------------------------------------

def decode_text(data: bytes) -> str:
    """UTF-8 (with or without BOM), UTF-16 with BOM, else Windows-1251 (the usual encoding of Russian .txt books)."""
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16")
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp1251", errors="replace")


_TAG = re.compile(r"<[^>]+>")


def _strip_tags(text: str) -> str:
    return html.unescape(_TAG.sub("", text)).strip()


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


# --- plain text ----------------------------------------------------------------------------------------------

_HEADING = re.compile(r"^\s*((глава|часть|том|пролог|эпилог|chapter|part|prologue|epilogue)\b.{0,80})$", re.I | re.M)


def split_text(text: str) -> list[tuple[str, str]]:
    """[(title, body)]: at chapter headings when there are any, otherwise into parts of ~CHUNK_CHARS at paragraph ends."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    marks = list(_HEADING.finditer(text))
    if len(marks) >= 2:
        parts = []
        if text[:marks[0].start()].strip():
            parts.append(("", text[:marks[0].start()]))
        for i, m in enumerate(marks):
            end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
            parts.append((m.group(1).strip(), text[m.end():end]))
        return [(title or "…", body) for title, body in parts]
    if len(text) <= CHUNK_CHARS:
        return [("", text)]
    parts, start = [], 0
    while start < len(text):
        end = min(start + CHUNK_CHARS, len(text))
        if end < len(text):
            cut = text.rfind("\n", start + CHUNK_CHARS // 2, end)
            end = cut if cut > 0 else end
        parts.append(("", text[start:end]))
        start = end
    return parts


def text_to_html(body: str) -> str:
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n|\n", body) if p.strip()]
    return "".join(f"<p>{html.escape(p)}</p>" for p in paragraphs)


def _open_txt(path: Path) -> Book:
    parts = split_text(decode_text(path.read_bytes()))
    titles = [t or f"{i + 1}" for i, (t, _) in enumerate(parts)]
    if len(parts) == 1:
        titles = [path.stem]
    bodies = [(f"<h2>{html.escape(t)}</h2>" if t and len(parts) > 1 else "") + text_to_html(b) for t, b in parts]
    return Book(title=path.stem, titles=titles, _chapter=lambda i: bodies[i])


# --- FB2 -------------------------------------------------------------------------------------------------------

def _fb2_text(el) -> str:
    """Inline content of a p/subtitle element as HTML."""
    out = [html.escape(el.text or "")]
    for child in el:
        tag = _local(child.tag)
        inner = _fb2_text(child)
        if tag in ("emphasis", "i"):
            out.append(f"<i>{inner}</i>")
        elif tag in ("strong", "b"):
            out.append(f"<b>{inner}</b>")
        elif tag == "strikethrough":
            out.append(f"<s>{inner}</s>")
        elif tag == "image":
            out.append(_fb2_image(child))
        else:
            out.append(inner)
        out.append(html.escape(child.tail or ""))
    return "".join(out)


def _fb2_image(el) -> str:
    href = next((v for k, v in el.attrib.items() if _local(k) == "href"), "")
    return f'<img src="book:{html.escape(href.lstrip("#"))}">' if href else ""


def _fb2_section_html(section) -> str:
    out = []
    for el in section:
        tag = _local(el.tag)
        if tag == "title":
            out.append(f"<h2>{' '.join(_fb2_text(p).strip() for p in el if _local(p.tag) == 'p')}</h2>")
        elif tag == "p":
            out.append(f"<p>{_fb2_text(el)}</p>")
        elif tag == "subtitle":
            out.append(f"<h3>{_fb2_text(el)}</h3>")
        elif tag == "empty-line":
            out.append("<br>")
        elif tag == "image":
            out.append(f"<p>{_fb2_image(el)}</p>")
        elif tag in ("epigraph", "cite", "poem"):
            out.append(f"<blockquote>{_fb2_section_html(el)}</blockquote>")
        elif tag == "v":
            out.append(f"<p>{_fb2_text(el)}</p>")
        elif tag == "stanza":
            out.append(_fb2_section_html(el))
        elif tag == "section":
            out.append(_fb2_section_html(el))
    return "".join(out)


def _open_fb2(path: Path) -> Book:
    data = path.read_bytes()
    root = ET.fromstring(data)
    ns = {"f": root.tag[1:].split("}")[0]} if root.tag.startswith("{") else {}
    q = (lambda t: f"f:{t}") if ns else (lambda t: t)

    def find(el, tag):
        return el.find(q(tag), ns) if ns else el.find(tag)

    info = find(find(root, "description"), "title-info")
    title = _strip_tags(ET.tostring(find(info, "book-title"), encoding="unicode")) if info is not None and find(info, "book-title") is not None else path.stem
    author = ""
    if info is not None:
        a = find(info, "author")
        if a is not None:
            author = " ".join(filter(None, (getattr(find(a, n), "text", "") for n in ("first-name", "middle-name", "last-name")))).strip()
    binaries = {}
    for b in root.iter():
        if _local(b.tag) == "binary" and b.get("id") and b.text:
            try:
                binaries[b.get("id")] = base64.b64decode(b.text)
            except ValueError:
                pass
    cover = None
    if info is not None:
        cp = find(info, "coverpage")
        if cp is not None:
            for img in cp:
                href = next((v for k, v in img.attrib.items() if _local(k) == "href"), "").lstrip("#")
                cover = binaries.get(href) or cover
    bodies = [b for b in root if _local(b.tag) == "body" and b.get("name") != "notes"]
    if not bodies:
        raise BookError("FB2 without a body")
    sections = [s for s in bodies[0] if _local(s.tag) == "section"]
    if len(sections) == 1 and any(_local(x.tag) == "section" for x in sections[0]):
        sections = [s for s in sections[0] if _local(s.tag) == "section"]     # one wrapper section: its children are the chapters
    if not sections:
        sections = [bodies[0]]
    titles = []
    for i, s in enumerate(sections):
        t = next((_strip_tags(_fb2_text(p)) for tt in s if _local(tt.tag) == "title" for p in tt if _local(p.tag) == "p"), "")
        titles.append(t or f"{i + 1}")
    return Book(title=title, author=author, titles=titles, cover=cover, _chapter=lambda i: _fb2_section_html(sections[i]),
                _resource=lambda name: binaries.get(unquote(name)))


# --- EPUB -------------------------------------------------------------------------------------------------------

_BODY = re.compile(r"<body[^>]*>(.*)</body>", re.S | re.I)
_DROP = re.compile(r"<(script|style)\b.*?</\1\s*>|<link\b[^>]*>|<meta\b[^>]*>", re.S | re.I)
_STYLE_ATTR = re.compile(r'\s(style|class)="[^"]*"', re.I)
_IMG_SRC = re.compile(r'(<img\b[^>]*?\bsrc=)"([^"]+)"', re.I)
_SVG_IMAGE = re.compile(r'<image\b[^>]*?href="([^"]+)"[^>]*/?>', re.I)


def _epub_body(raw: str, base_dir: str) -> str:
    m = _BODY.search(raw)
    body = m.group(1) if m else raw
    body = _DROP.sub("", body)
    body = _STYLE_ATTR.sub("", body)
    body = re.sub(r"<svg\b.*?</svg>", lambda mm: "".join(f'<img src="{h}">' for h in _SVG_IMAGE.findall(mm.group(0))), body, flags=re.S | re.I)
    return _IMG_SRC.sub(lambda mm: f'{mm.group(1)}"book:{posixpath.normpath(posixpath.join(base_dir, unquote(mm.group(2))))}"', body)


def _open_epub(path: Path) -> Book:
    zf = zipfile.ZipFile(path)
    container = ET.fromstring(zf.read("META-INF/container.xml"))
    opf_path = next(el.get("full-path") for el in container.iter() if _local(el.tag) == "rootfile")
    opf = ET.fromstring(zf.read(opf_path))
    base = posixpath.dirname(opf_path)
    manifest, title, author, cover_id = {}, "", "", ""
    for el in opf.iter():
        tag = _local(el.tag)
        if tag == "title" and not title and el.text:
            title = el.text.strip()
        elif tag == "creator" and not author and el.text:
            author = el.text.strip()
        elif tag == "meta" and el.get("name") == "cover":
            cover_id = el.get("content", "")
        elif tag == "item":
            manifest[el.get("id")] = {"href": unquote(el.get("href", "")), "type": el.get("media-type", ""),
                                      "props": el.get("properties", "")}
    spine = [manifest[r.get("idref")] for r in opf.iter() if _local(r.tag) == "itemref" and r.get("idref") in manifest
             and r.get("linear", "yes") != "no"]
    spine = [s for s in spine if "html" in s["type"] or s["href"].endswith((".xhtml", ".html", ".htm"))]
    if not spine:
        raise BookError("EPUB without readable chapters")
    toc = _epub_toc(zf, base, manifest)
    names = set(zf.namelist())

    def full(href: str) -> str:
        return posixpath.normpath(posixpath.join(base, href))

    titles = []
    for i, item in enumerate(spine):
        titles.append(toc.get(full(item["href"])) or f"{i + 1}")
    cover = None
    cover_item = manifest.get(cover_id) or next((m for m in manifest.values() if "cover-image" in m["props"]), None)
    if cover_item and full(cover_item["href"]) in names:
        cover = zf.read(full(cover_item["href"]))

    def chapter(i: int) -> str:
        name = full(spine[i]["href"])
        return _epub_body(decode_text(zf.read(name)), posixpath.dirname(name))

    def resource(name: str) -> bytes | None:
        name = posixpath.normpath(unquote(name))
        return zf.read(name) if name in names else None

    return Book(title=title or path.stem, author=author, titles=titles, cover=cover, _chapter=chapter, _resource=resource,
                _close=zf.close)


def _epub_toc(zf: zipfile.ZipFile, base: str, manifest: dict) -> dict[str, str]:
    """{chapter file path: title} from the NCX or the EPUB3 nav document (best effort)."""
    toc: dict[str, str] = {}

    def add(src: str, label: str, folder: str) -> None:
        src = unquote(src.split("#")[0])
        label = re.sub(r"\s+", " ", label).strip()
        if src and label:
            toc.setdefault(posixpath.normpath(posixpath.join(folder, src)), label)

    for item in manifest.values():
        name = posixpath.normpath(posixpath.join(base, item["href"]))
        try:
            if item["type"] == "application/x-dtbncx+xml":
                for point in ET.fromstring(zf.read(name)).iter():
                    if _local(point.tag) == "navPoint":
                        label = next((t.text or "" for t in point.iter() if _local(t.tag) == "text"), "")
                        content = next((c for c in point if _local(c.tag) == "content"), None)
                        if content is not None:
                            add(content.get("src", ""), label, posixpath.dirname(name))
            elif "nav" in item["props"]:
                page = decode_text(zf.read(name))
                for href, label in re.findall(r'<a\b[^>]*href="([^"]+)"[^>]*>(.*?)</a>', page, re.S | re.I):
                    add(href, _strip_tags(label), posixpath.dirname(name))
        except (KeyError, ET.ParseError):
            continue
    return toc
