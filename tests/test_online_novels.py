import base64
import time

import pytest

from anihub.context import AppContext
from anihub.core import agemode
from anihub.core.config import Config
from anihub.library.epub_writer import write_epub
from anihub.library.novels import open_book
from anihub.library.online_novels import OnlineBook, download_epub, open_online, parse_remote, remote_json
from anihub.sources.novels.base import NovelChapter, NovelEntry, NovelSource

PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")


class FakeNovels(NovelSource):
    name = "fakenovels"
    title = "Fake"
    lang = "en"

    def __init__(self, http, cfg):
        super().__init__(http, cfg)
        self.fetched = []

    def search(self, query, page=1):
        return [NovelEntry("a", "Alpha", age=12), NovelEntry("b", "Beta", age=18), NovelEntry("c", "Gamma", age=16, tags=["gore_x"])], False

    def chapters(self, entry):
        return [NovelChapter(f"c{i}", f"Chapter {i}", float(i)) for i in range(1, 4)]

    def chapter_html(self, entry, chapter):
        self.fetched.append(chapter.id)
        return f'<p onclick="x()">Text of {chapter.title} &amp; more</p><img src="https://img.example/{chapter.id}.png"/><script>bad()</script>'


class Http:
    def get_bytes(self, url):
        if url.endswith("c2.png"):
            raise OSError("broken")
        return PNG


def make_book(tmp_path):
    cfg = Config.load(tmp_path / "c.json")
    source = FakeNovels(Http(), cfg)
    entry = NovelEntry("a", "Alpha", cover="https://img.example/cover.png", author="Au", age=12)
    return OnlineBook(source, entry, source.chapters(entry), Http()), source


def test_online_book_fetches_lazily_cleans_html_and_serves_pictures(tmp_path):
    book, source = make_book(tmp_path)
    assert len(book) == 3 and book.titles[0] == "Chapter 1" and not book.cached(0)
    with pytest.raises(Exception):
        book.chapter_html(0)                                             # not loaded: the reader must fetch first
    book.fetch(0)
    book.fetch(0)
    assert source.fetched == ["c1"] and book.cached(0)                   # fetched once
    html = book.chapter_html(0)
    assert "onclick" not in html and "<script" not in html and "Text of Chapter 1 &amp; more" in html
    name = html.split('src="book:')[1].split('"')[0]
    assert book.resource(name) == PNG and book.resource("book:" + name) == PNG
    book.fetch(1)                                                        # its picture fails: the chapter survives without it
    assert "<img" not in book.chapter_html(1) and "Chapter 2" in book.chapter_html(1)
    book.close()
    assert not book.cached(0)


def test_epub_writer_roundtrip_through_the_book_reader(tmp_path):
    epub = write_epub(tmp_path / "b.epub", "Тайтл", "Автор", [("Глава 1", "<p>Привет &amp; мир<br></p>"),
                      ("Глава 2", '<p>Pic</p><img src="images/a.png">')], cover=PNG, images={"images/a.png": PNG})
    book = open_book(epub)
    try:
        assert book.title == "Тайтл" and book.author == "Автор" and book.titles == ["Глава 1", "Глава 2"] and len(book) == 2
        assert "Привет &amp; мир" in book.chapter_html(0)
        assert "book:OEBPS/images/a.png" in book.chapter_html(1) and book.resource("OEBPS/images/a.png") == PNG
        assert book.cover == PNG
    finally:
        book.close()


def test_download_epub_of_an_online_book(tmp_path):
    book, source = make_book(tmp_path)
    seen = []
    epub = download_epub(book, tmp_path / "out.epub", progress=lambda d, t: seen.append((d, t)))
    assert seen[-1] == (3, 3) and source.fetched == ["c1", "c2", "c3"]
    local = open_book(epub)
    try:
        assert local.title == "Alpha" and len(local) == 3 and "Text of Chapter 3" in local.chapter_html(2)
        assert local.cover == PNG
    finally:
        local.close()


def make_ctx(tmp_path, mode="18"):
    cfg = Config.load(tmp_path / "c.json")
    cfg.set("library_path", str(tmp_path / "lib"), save=False)
    cfg.set("first_run_done", True, save=False)
    agemode.apply_mode(cfg, mode, save=False)
    ctx = AppContext.build(cfg)
    ctx.novel_sources["fakenovels"] = FakeNovels(Http(), cfg)
    ctx.http = Http()                                        # pictures come from the fake, never from the network
    return ctx


def test_shelf_keeps_online_titles_and_swaps_them_for_a_download(tmp_path):
    ctx = make_ctx(tmp_path)
    source = ctx.novel_sources["fakenovels"]
    entry = NovelEntry("a", "Alpha", author="Au", age=12)
    chapters = source.chapters(entry)
    first = ctx.novels.add_online("fakenovels", entry, chapters, PNG)
    assert ctx.novels.add_online("fakenovels", entry, chapters) == first                         # once
    row = ctx.db.novel_get(first)
    assert ctx.novels.is_online(row) and row["chapters"] == 3 and ctx.novels.cover_of(row).exists()
    assert parse_remote(row["remote"])[1][2].title == "Chapter 3"
    ctx.novels.save_progress(first, 1, 0.5, 3)
    book = open_online(ctx.novel_sources, ctx.http, ctx.db.novel_get(first))
    assert book.title == "Alpha" and len(book) == 3
    epub = download_epub(book, tmp_path / "d.epub")
    new_id = ctx.novels.replace_with_file(ctx.db.novel_get(first), epub)
    assert new_id and ctx.db.novel_get(first) is None                                            # the online row is gone
    new = ctx.db.novel_get(new_id)
    assert not ctx.novels.is_online(new) and (new["chapter_index"], new["scroll"]) == (1, 0.5)   # ...its progress moved
    del ctx.novel_sources["fakenovels"]
    gone = ctx.novels.add_online("fakenovels", entry, chapters)
    with pytest.raises(Exception, match="not installed"):
        open_online(ctx.novel_sources, ctx.http, ctx.db.novel_get(gone))


def pump(app, cond, limit=5.0):
    end = time.time() + limit
    while time.time() < end:
        app.processEvents()
        if cond():
            return True
        time.sleep(0.02)
    return False


def test_reader_loads_online_chapters_in_the_background_and_prefetches(qapp, tmp_path):
    from anihub.ui.novels_page import NovelReader

    ctx = make_ctx(tmp_path)
    source = ctx.novel_sources["fakenovels"]
    entry = NovelEntry("a", "Alpha", age=12)
    novel_id = ctx.novels.add_online("fakenovels", entry, source.chapters(entry))
    reader = NovelReader(ctx, ctx.db.novel_get(novel_id))
    try:
        assert pump(qapp, lambda: "Text of Chapter 1" in reader.browser.toPlainText())
        assert pump(qapp, lambda: reader.book.cached(1))                                            # the next one is prefetched
        before = len(source.fetched)
        reader.goto(1)
        assert "Text of Chapter 2" in reader.browser.toPlainText()                                  # cached: shown at once
        assert len(source.fetched) >= before
        assert pump(qapp, lambda: reader.book.cached(2))
    finally:
        reader.close()
    row = ctx.db.novel_get(novel_id)
    assert row["chapter_index"] == 1


def test_online_tab_hides_titles_above_the_age_mode_and_the_hub_lists_both_tabs(qapp, tmp_path):
    from anihub.ui.novels_online import NovelsHub

    ctx = make_ctx(tmp_path, mode="16")
    hub = NovelsHub(ctx)
    tab = hub.online
    assert hub.count() == 2 and hub.shelf is not None
    names = [tab.source_box.itemData(i) for i in range(tab.source_box.count())]
    assert "ranobelib" in names and "fakenovels" in names
    tab.source_box.setCurrentIndex(tab.source_box.findData("fakenovels"))
    tab.search()
    assert pump(qapp, lambda: tab.grid.count() > 0)
    titles = [tab.grid.item(i).data(0x100).title for i in range(tab.grid.count())]
    assert titles == ["Alpha", "Gamma"]                                                            # Beta is 18+
    assert "1" in tab.status.text()
    # the shelf follows the mode as well: an online 18+ title disappears when the mode drops
    ctx.novels.add_online("fakenovels", NovelEntry("b", "Beta", age=18), [NovelChapter("x", "X")])
    hub.shelf.reload()
    assert hub.shelf.grid.count() == 0
    agemode.apply_mode(ctx.cfg, "18", save=False)
    hub.shelf.reload()
    assert hub.shelf.grid.count() == 1


def test_watch_tab_filters_sources_by_language_and_hides_adult_ones(qapp, tmp_path):
    from anihub.sources.anime.base import AnimeSource
    from anihub.ui.anime_watch import WatchTab

    class EnSrc(AnimeSource):
        name, title, lang = "en_src", "EnSite", "en"

        def search(self, query, page=1):
            return [], False

        def episodes(self, entry):
            return []

        def streams(self, entry, episode):
            return []

    class Adult(EnSrc):
        name, title, nsfw = "adult_src", "AdultSite", True

    ctx = make_ctx(tmp_path, mode="12")
    ctx.anime_sources["en_src"] = EnSrc(ctx.http, ctx.cfg)
    ctx.anime_sources["adult_src"] = Adult(ctx.http, ctx.cfg)
    tab = WatchTab(ctx)
    names = lambda: [tab.source_box.itemData(i) for i in range(tab.source_box.count())]
    assert names() == ["local", "anilibria", "en_src"]                                             # adult one hidden at 12+
    ctx.cfg.set("anime.langs", ["ru"], save=False)
    tab.reload_sources()
    assert names() == ["local", "anilibria"]                                                       # only Russian (and local)
    ctx.cfg.set("anime.langs", [], save=False)
    agemode.apply_mode(ctx.cfg, "18", save=False)
    tab.reload_sources()
    assert "adult_src" in names()
    assert "Русский" in tab.source_box.itemText(names().index("anilibria"))


def test_remote_json_roundtrip():
    entry = NovelEntry("x", "T", tags=["a"], age=16)
    chapters = [NovelChapter("1", "One", 1.0)]
    assert parse_remote(remote_json(entry, chapters)) == (entry, chapters)
