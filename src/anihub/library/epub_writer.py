"""A minimal EPUB 2 writer: turns downloaded online chapters into a book file that the shelf and the reader already understand."""
from __future__ import annotations

import re
import uuid
import zipfile
from html import escape
from pathlib import Path

_IMG = re.compile(r'(<img\b[^>]*?\bsrc=)"([^"]+)"([^>]*?)/?>', re.I)
_DROP = re.compile(r"<(script|style|iframe|object|embed)\b.*?</\1>", re.S | re.I)
_ATTRS = re.compile(r'\s(?:on\w+|style|class|data-[\w-]+)="[^"]*"', re.I)


def xhtml_body(html: str) -> str:
    """Chapter HTML -> well-formed XHTML body: no scripts/styles/handlers, self-closed void tags."""
    html = _DROP.sub("", html)
    html = _ATTRS.sub("", html)
    html = re.sub(r"<(br|hr)\s*/?>", r"<\1/>", html, flags=re.I)
    html = _IMG.sub(lambda m: f'{m.group(1)}"{m.group(2)}"{m.group(3)} alt=""/>' if 'alt=' not in m.group(0) else f'{m.group(1)}"{m.group(2)}"{m.group(3)}/>', html)
    html = re.sub(r"&(?!(?:amp|lt|gt|quot|apos|#\d+|#x[0-9a-f]+);)", "&amp;", html)
    return html


def write_epub(path: Path, title: str, author: str, chapters: list[tuple[str, str]], cover: bytes | None = None,
               images: dict[str, bytes] | None = None) -> Path:
    """chapters: [(title, html)]. `images`: {"images/a.jpg": bytes} referenced from the chapter HTML as such (relative to the OEBPS folder)."""
    images = dict(images or {})
    book_id = f"urn:uuid:{uuid.uuid4()}"
    manifest, spine, nav = [], [], []
    for i, (chapter_title, _) in enumerate(chapters, 1):
        manifest.append(f'<item id="c{i}" href="c{i}.xhtml" media-type="application/xhtml+xml"/>')
        spine.append(f'<itemref idref="c{i}"/>')
        nav.append(f'<navPoint id="n{i}" playOrder="{i}"><navLabel><text>{escape(chapter_title)}</text></navLabel>'
                   f'<content src="c{i}.xhtml"/></navPoint>')
    for j, name in enumerate(images):
        kind = "image/png" if name.lower().endswith(".png") else "image/gif" if name.lower().endswith(".gif") else "image/jpeg"
        manifest.append(f'<item id="i{j}" href="{escape(name)}" media-type="{kind}"/>')
    cover_meta = ""
    if cover:
        images_cover = "images/cover.jpg"
        manifest.append(f'<item id="cover-image" href="{images_cover}" media-type="image/jpeg"/>')
        cover_meta = '<meta name="cover" content="cover-image"/>'
    opf = ('<?xml version="1.0" encoding="utf-8"?><package xmlns="http://www.idpf.org/2007/opf" version="2.0" unique-identifier="id">'
           f'<metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>{escape(title)}</dc:title>'
           f'<dc:creator>{escape(author or "")}</dc:creator><dc:identifier id="id">{book_id}</dc:identifier><dc:language>und</dc:language>'
           f'{cover_meta}</metadata><manifest><item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>'
           f'{"".join(manifest)}</manifest><spine toc="ncx">{"".join(spine)}</spine></package>')
    ncx = ('<?xml version="1.0" encoding="utf-8"?><ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">'
           f'<head><meta name="dtb:uid" content="{book_id}"/></head><docTitle><text>{escape(title)}</text></docTitle>'
           f'<navMap>{"".join(nav)}</navMap></ncx>')
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        zf.writestr("META-INF/container.xml",
                    '<?xml version="1.0"?><container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
                    '<rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles></container>',
                    compress_type=zipfile.ZIP_DEFLATED)
        zf.writestr("OEBPS/content.opf", opf, compress_type=zipfile.ZIP_DEFLATED)
        zf.writestr("OEBPS/toc.ncx", ncx, compress_type=zipfile.ZIP_DEFLATED)
        for i, (chapter_title, html) in enumerate(chapters, 1):
            page = ('<?xml version="1.0" encoding="utf-8"?><html xmlns="http://www.w3.org/1999/xhtml"><head>'
                    f'<title>{escape(chapter_title)}</title></head><body>{xhtml_body(html)}</body></html>')
            zf.writestr(f"OEBPS/c{i}.xhtml", page, compress_type=zipfile.ZIP_DEFLATED)
        for name, data in images.items():
            zf.writestr(f"OEBPS/{name}", data, compress_type=zipfile.ZIP_STORED)
        if cover:
            zf.writestr("OEBPS/images/cover.jpg", cover, compress_type=zipfile.ZIP_STORED)
    return path
