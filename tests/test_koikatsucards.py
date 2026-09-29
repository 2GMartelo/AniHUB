"""koikatsucards.com scraping (services/koikatsucards.py): parsing the search results grid and a card's own
download link out of the site's real server-rendered HTML (samples below are trimmed copies of what the live
site actually returns, captured 2026-09-29), plus the "not signed in" detection on download."""
from pathlib import Path

import pytest

from anihub.services import koikatsucards as kkc

SEARCH_HTML = """
<div class="grid content-grid search-results-grid">
<a class="card content-navigation-feedback-module__gu81OW__contentCardLink" href="/contents/pixiv-142234253-axilya-aragella">
<div class="content-card-media"><img alt="Axilya Aragella" loading="lazy" src="https://pub-x.r2.dev/contents/pixiv-142234253-axilya-aragella/01.webp"/></div>
<div class="card-body"><div class="eyebrow">Original</div><h3>Axilya Aragella</h3><p class="muted">Sinnai</p></div>
</a>
<a class="card content-navigation-feedback-module__gu81OW__contentCardLink" href="/contents/pixiv-131439518-xinghui">
<div class="content-card-media"><img alt="Xinghui" loading="lazy" src="https://pub-x.r2.dev/contents/pixiv-131439518-xinghui/01.webp"/></div>
<div class="card-body"><div class="eyebrow">Strinova</div><h3>Xinghui (Countryside Stroll)</h3><p class="muted">As-sin</p></div>
</a>
</div>
"""

DETAIL_HTML = """
<h1>Axilya Aragella</h1>
<div>Download Links</div>
<a href="https://t.me/somebot?start=abc">TG Download</a>
<a href="/api/downloads/content-file/token/djE6NDIxNw.f2d14ae01705aadba9d7d0773877719c1282a555a381a1b49ed12ccea0f02600">Website Download</a>
"""


class FakeHttp:
    def __init__(self, texts: dict[str, str] | None = None, bytes_: dict[str, bytes] | None = None):
        self.texts, self.bytes_, self.calls = texts or {}, bytes_ or {}, []

    def get_text(self, url, params=None, headers=None, interval_ms=None):
        self.calls.append(("text", url))
        for key, value in self.texts.items():
            if key in url:
                return value
        raise AssertionError(url)

    def get_bytes(self, url):
        self.calls.append(("bytes", url))
        for key, value in self.bytes_.items():
            if key in url:
                return value
        raise AssertionError(url)


def test_search_parses_every_card_off_the_real_results_markup():
    http = FakeHttp(texts={"/search": SEARCH_HTML})
    cards = kkc.search(http, "genshin")
    assert len(cards) == 2
    a, b = cards
    assert a.slug == "pixiv-142234253-axilya-aragella" and a.title == "Axilya Aragella" and a.work == "Original" and a.author == "Sinnai"
    assert b.slug == "pixiv-131439518-xinghui" and b.title == "Xinghui (Countryside Stroll)" and b.work == "Strinova"
    assert a.thumb.startswith("https://pub-x.r2.dev/")
    assert "tag=genshin" in http.calls[0][1]


def test_search_with_no_query_lists_everything_and_pages():
    http = FakeHttp(texts={"/search": SEARCH_HTML})
    kkc.search(http, "", page=2)
    url = http.calls[0][1]
    assert "tag=" not in url and "page=2" in url


def test_download_url_finds_the_website_download_link_not_the_telegram_one():
    http = FakeHttp(texts={"/contents/pixiv-142234253-axilya-aragella": DETAIL_HTML})
    url = kkc.download_url(http, "pixiv-142234253-axilya-aragella")
    assert url == ("https://koikatsucards.com/api/downloads/content-file/token/"
                   "djE6NDIxNw.f2d14ae01705aadba9d7d0773877719c1282a555a381a1b49ed12ccea0f02600")


def test_download_url_raises_a_clear_error_when_no_link_is_present():
    http = FakeHttp(texts={"/contents/missing": "<h1>Not found</h1>"})
    with pytest.raises(kkc.KoikatsuCardsError):
        kkc.download_url(http, "missing")


def test_download_card_saves_the_real_file(tmp_path):
    http = FakeHttp(texts={"/contents/pixiv-142234253-axilya-aragella": DETAIL_HTML},
                    bytes_={"/api/downloads/content-file/token/": b"\x89PNG\r\n\x1a\nfake-card-bytes"})
    dest = kkc.download_card(http, "pixiv-142234253-axilya-aragella", tmp_path / "cards")
    assert dest == tmp_path / "cards" / "pixiv-142234253-axilya-aragella.png"
    assert dest.read_bytes() == b"\x89PNG\r\n\x1a\nfake-card-bytes"


def test_download_card_detects_a_not_signed_in_redirect_instead_of_saving_a_login_page(tmp_path):
    http = FakeHttp(texts={"/contents/pixiv-142234253-axilya-aragella": DETAIL_HTML},
                    bytes_={"/api/downloads/content-file/token/": b"<!DOCTYPE html><html><body>Please sign in</body></html>"})
    with pytest.raises(kkc.KoikatsuCardsError, match="sign in"):
        kkc.download_card(http, "pixiv-142234253-axilya-aragella", tmp_path / "cards")
    assert not (tmp_path / "cards" / "pixiv-142234253-axilya-aragella.png").exists()
