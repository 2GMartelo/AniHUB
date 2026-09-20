import base64
import zipfile
from pathlib import Path

import pytest
from PySide6.QtCore import QBuffer, QIODevice
from PySide6.QtGui import QColor, QImage

from anihub.core.db import Database
from anihub.core.paths import LibraryPaths
from anihub.library.novel_store import NovelShelf, collect_books, cover_jpeg
from anihub.library.novels import BookError, decode_text, open_book, split_text


def png_bytes(color="#3366aa", w=40, h=60) -> bytes:
    img = QImage(w, h, QImage.Format.Format_RGB32)
    img.fill(QColor(color))
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    return bytes(buf.data())


def make_epub(path: Path, with_cover=True, nav=False) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    container = '<?xml version="1.0"?><container xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles>' \
                '<rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles></container>'
    opf = f"""<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf" version="2.0">
    <metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>Test Novel</dc:title><dc:creator>Jane Roe</dc:creator>
    {'<meta name="cover" content="cov"/>' if with_cover else ''}</metadata>
    <manifest><item id="c1" href="text/c1.xhtml" media-type="application/xhtml+xml"/>
    <item id="c2" href="text/c2.xhtml" media-type="application/xhtml+xml"/>
    <item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>
    <item id="cov" href="images/cover.png" media-type="image/png"/><item id="pic" href="images/pic.png" media-type="image/png"/>
    </manifest><spine toc="ncx"><itemref idref="c1"/><itemref idref="c2"/></spine></package>"""
    ncx = """<?xml version="1.0"?><ncx xmlns="http://www.daisy.org/z3986/2005/ncx/"><navMap>
    <navPoint id="a"><navLabel><text>The Beginning</text></navLabel><content src="text/c1.xhtml"/></navPoint>
    <navPoint id="b"><navLabel><text>The End</text></navLabel><content src="text/c2.xhtml#top"/></navPoint></navMap></ncx>"""
    c1 = '<html><head><style>p{color:red}</style></head><body><h1>One</h1><p style="color:red">Hello <i>world</i></p><img src="../images/pic.png"/></body></html>'
    c2 = "<html><body><p>Second &amp; last</p></body></html>"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("mimetype", "application/epub+zip")
        z.writestr("META-INF/container.xml", container)
        z.writestr("OEBPS/content.opf", opf)
        z.writestr("OEBPS/toc.ncx", ncx)
        z.writestr("OEBPS/text/c1.xhtml", c1)
        z.writestr("OEBPS/text/c2.xhtml", c2)
        z.writestr("OEBPS/images/cover.png", png_bytes("#aa3333"))
        z.writestr("OEBPS/images/pic.png", png_bytes("#33aa33"))
    return path


FB2 = """<?xml version="1.0" encoding="utf-8"?><FictionBook xmlns="http://www.gribuser.ru/xml/fictionbook/2.0" xmlns:l="http://www.w3.org/1999/xlink">
<description><title-info><author><first-name>Иван</first-name><last-name>Петров</last-name></author><book-title>Тестовая книга</book-title>
<coverpage><image l:href="#cover.png"/></coverpage></title-info></description>
<body><section><title><p>Глава первая</p></title><p>Привет, <emphasis>мир</emphasis>!</p><empty-line/><p>Второй абзац</p><image l:href="#pic.png"/></section>
<section><title><p>Глава вторая</p></title><p>Конец</p></section></body>
<body name="notes"><section><p>note</p></section></body>
<binary id="cover.png" content-type="image/png">{cover}</binary><binary id="pic.png" content-type="image/png">{pic}</binary></FictionBook>"""


def make_fb2(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(FB2.format(cover=base64.b64encode(png_bytes("#aa3333")).decode(), pic=base64.b64encode(png_bytes()).decode()),
                    encoding="utf-8")
    return path


def test_epub_metadata_chapters_titles_and_images(qapp, tmp_path):
    book = open_book(make_epub(tmp_path / "a.epub"))
    assert (book.title, book.author, len(book)) == ("Test Novel", "Jane Roe", 2)
    assert book.titles == ["The Beginning", "The End"]                       # from the NCX, fragment ignored
    first = book.chapter_html(0)
    assert "Hello <i>world</i>" in first and "style" not in first and "<style" not in first     # the book's own CSS is dropped
    assert 'src="book:OEBPS/images/pic.png"' in first                          # relative image resolved against the chapter
    assert "Second &amp; last" in book.chapter_html(1)
    assert book.resource("OEBPS/images/pic.png").startswith(b"\x89PNG") and book.resource("nope.png") is None
    assert book.cover and book.cover.startswith(b"\x89PNG")
    book.close()


def test_epub_without_cover_and_broken_files(qapp, tmp_path):
    assert open_book(make_epub(tmp_path / "b.epub", with_cover=False)).cover is None
    bad = tmp_path / "bad.epub"
    bad.write_bytes(b"not a zip")
    with pytest.raises(BookError):
        open_book(bad)
    with pytest.raises(BookError):
        open_book(tmp_path / "x.pdf")


def test_fb2_book(qapp, tmp_path):
    book = open_book(make_fb2(tmp_path / "a.fb2"))
    assert (book.title, book.author) == ("Тестовая книга", "Иван Петров")
    assert book.titles == ["Глава первая", "Глава вторая"] and len(book) == 2         # notes body is not a chapter
    html = book.chapter_html(0)
    assert "<h2>Глава первая</h2>" in html and "<i>мир</i>" in html and "<br>" in html and 'src="book:pic.png"' in html
    assert book.cover and book.resource("pic.png").startswith(b"\x89PNG")


def test_txt_encodings_and_chapter_splitting(tmp_path):
    assert decode_text("Привет".encode("cp1251")) == "Привет"
    assert decode_text("Привет".encode("utf-8-sig")) == "Привет" and decode_text("Hi".encode("utf-16")) == "Hi"
    text = "Пролог\nтекст\n\nГлава 1. Начало\nОдин\nдва\n\nГлава 2\nТри"
    parts = split_text(text)
    assert [t for t, _ in parts] == ["Пролог", "Глава 1. Начало", "Глава 2"]
    assert parts[1][1].strip() == "Один" + chr(10) + "два" and parts[0][1].strip() == "текст"
    long = "\n".join(f"Абзац номер {i} " + "слово " * 40 for i in range(400))
    chunks = split_text(long)
    assert len(chunks) > 1 and all(len(b) <= 18500 for _, b in chunks) and "".join(b for _, b in chunks).count("Абзац") == 400
    path = tmp_path / "n.txt"
    path.write_bytes("Глава 1\nПервая\n\nГлава 2\nВторая".encode("cp1251"))
    book = open_book(path)
    assert len(book) == 2 and "<h2>Глава 1</h2><p>Первая</p>" in book.chapter_html(0) and book.titles[1] == "Глава 2"
    single = tmp_path / "single.txt"
    single.write_text("Just a short story.", encoding="utf-8")
    assert open_book(single).titles == ["single"]


def make_shelf(tmp_path):
    paths = LibraryPaths(tmp_path / "lib")
    paths.ensure()
    return NovelShelf(Database(paths.db_file), paths), paths


def test_shelf_imports_dedups_and_keeps_covers(qapp, tmp_path):
    shelf, paths = make_shelf(tmp_path)
    epub, fb2 = make_epub(tmp_path / "src" / "a.epub"), make_fb2(tmp_path / "src" / "b.fb2")
    bad = tmp_path / "src" / "bad.epub"
    bad.write_bytes(b"junk")
    files = collect_books([tmp_path / "src"])
    assert [f.name for f in files] == ["a.epub", "b.fb2", "bad.epub"]
    assert shelf.import_books(files) == {"saved": 2, "duplicate": 0, "failed": 1}
    assert shelf.import_books([epub]) == {"saved": 0, "duplicate": 1, "failed": 0}
    rows = shelf.db.novels()
    assert {r["title"] for r in rows} == {"Test Novel", "Тестовая книга"}
    row = next(r for r in rows if r["ext"] == "epub")
    assert shelf.file_of(row).exists() and shelf.cover_of(row).exists() and row["chapters"] == 2
    assert QImage(str(shelf.cover_of(row))).height() <= 480
    assert not list((paths.novels).glob("*bad*"))                             # a broken file is never copied in
    assert [r["title"] for r in shelf.db.novels("петров")] == []              # author search is on the author column only
    assert [r["title"] for r in shelf.db.novels("roe")] == ["Test Novel"] and len(shelf.db.novels("книга")) == 1


def test_progress_finished_and_delete(qapp, tmp_path):
    shelf, _ = make_shelf(tmp_path)
    shelf.import_one(make_epub(tmp_path / "a.epub"))
    row = shelf.db.novels()[0]
    shelf.save_progress(row["id"], 0, 0.4, 2)
    got = shelf.db.novel_get(row["id"])
    assert (got["chapter_index"], round(got["scroll"], 1), got["finished"]) == (0, 0.4, 0) and got["last_read_at"]
    shelf.save_progress(row["id"], 1, 0.99, 2)
    assert shelf.db.novel_get(row["id"])["finished"] == 1
    shelf.save_progress(row["id"], 0, 0.1, 2)                                 # rereading does not un-finish it
    assert shelf.db.novel_get(row["id"])["finished"] == 1
    assert len(shelf.db.novels(unfinished=True)) == 0
    file, cover = shelf.file_of(row), shelf.cover_of(row)
    shelf.delete(row["id"])
    assert not file.exists() and not cover.exists() and shelf.db.novels() == []


def test_cover_jpeg_shrinks_and_rejects_garbage(qapp):
    assert cover_jpeg(None) is None and cover_jpeg(b"garbage") is None
    big = QImage(900, 1400, QImage.Format.Format_RGB32)
    big.fill(QColor("#123456"))
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    big.save(buf, "PNG")
    out = QImage.fromData(cover_jpeg(bytes(buf.data())))
    assert out.height() == 480 and out.width() < 900


def novel_ctx(tmp_path):
    from types import SimpleNamespace

    from anihub.core.config import Config

    shelf, paths = make_shelf(tmp_path)
    cfg = Config.load(tmp_path / "c.json")
    return SimpleNamespace(cfg=cfg, db=shelf.db, novels=shelf, paths=paths), shelf


def test_reader_restores_position_switches_chapters_and_saves(qapp, tmp_path):
    from anihub.ui import theme
    from anihub.ui.novels_page import NovelReader

    theme.apply_theme(qapp, "dark")
    ctx, shelf = novel_ctx(tmp_path)
    shelf.import_one(make_epub(tmp_path / "a.epub"))
    row = shelf.db.novels()[0]
    reader = NovelReader(ctx, row)
    reader.resize(900, 600)
    assert reader.index == 0 and "Hello world" in reader.browser.toPlainText()
    reader.next_btn.click()
    assert reader.index == 1 and "Second & last" in reader.browser.toPlainText() and not reader.next_btn.isEnabled()
    reader.set_font(24)
    assert ctx.cfg.get("novels.font_size") == 24 and reader.index == 1
    reader.set_theme("sepia")
    assert ctx.cfg.get("novels.theme") == "sepia"
    reader.close()
    saved = shelf.db.novel_get(row["id"])
    assert saved["chapter_index"] == 1 and saved["last_read_at"]
    again = NovelReader(ctx, saved)                                            # reopening continues where it stopped
    assert again.index == 1
    again.close()


def test_shelf_page_lists_books_and_marks_progress(qapp, tmp_path):
    from anihub.ui.novels_page import NovelsPage, placeholder_cover, progress_text

    ctx, shelf = novel_ctx(tmp_path)
    page = NovelsPage(ctx)
    assert page.grid.isHidden() and not page.empty.isHidden()                 # nothing yet: the empty state
    shelf.import_one(make_epub(tmp_path / "a.epub"))
    shelf.import_one(make_fb2(tmp_path / "b.fb2"))
    page.reload()
    assert page.grid.count() == 2 and not page.grid.isHidden() and page.empty.isHidden()
    page.filter.setText("roe")
    assert page.grid.count() == 1
    page.filter.clear()
    row = shelf.db.novels()[0]
    assert progress_text(row) == ""
    shelf.save_progress(row["id"], 1, 0.5, 2)
    assert progress_text(shelf.db.novel_get(row["id"])) == "75%"
    assert placeholder_cover("Книга без обложки", 180).height() == 180
