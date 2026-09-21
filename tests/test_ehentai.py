import pytest

from anihub.core.config import Config
from anihub.net.http import HttpError
from anihub.sources import build_sources
from anihub.sources.base import SourceError
from anihub.sources.ehentai import EHentai, parse_tag, search_token

SEARCH_HTML = """<table class="itg gltc"><tr><td><a href="https://e-hentai.org/g/101/aaaaaaaaaa/">x</a></td>
<td><a href="https://e-hentai.org/g/102/bbbbbbbbbb/">y</a></td><td><a href="https://e-hentai.org/g/101/aaaaaaaaaa/">dup</a></td>
<td><a href="https://e-hentai.org/g/103/cccccccccc/">z</a></td></table>"""

GALLERY = {"gid": 101, "token": "aaaaaaaaaa", "title": "First", "category": "Manga", "thumb": "https://ehgt.org/a.webp",
           "rating": "4.5", "tags": ["artist:foo bar", "female:big breasts", "parody:some show", "language:english", "solo"]}
GALLERY2 = {"gid": 102, "token": "bbbbbbbbbb", "title": "Second", "category": "Non-H", "thumb": "https://ehgt.org/b.webp",
            "rating": "3.0", "tags": []}


class FakeHttp:
    def add_host_headers(self, suffix, headers):
        pass

    def __init__(self, html=SEARCH_HTML, gdata=None):
        self.html, self.calls = html, []
        self.gdata = gdata if gdata is not None else {"gmetadata": [GALLERY, GALLERY2, {"gid": 103, "error": "Key missing"}]}

    def get_text(self, url, params=None, headers=None, interval_ms=None):
        self.calls.append(("get", url, params, headers))
        if "/s/" in url:
            return '<html><img id="img" src="https://h.example:60512/h/abc/keystamp=1;a=b&amp;c=d/Page_001.webp" style="x"/></html>'
        if "/g/101/" in url:
            return '<a href="https://e-hentai.org/s/49f0ccf344/101-2">p2</a><a href="https://e-hentai.org/s/31d3aa4a4c/101-1">p1</a>'
        return self.html

    def post_json(self, url, payload, headers=None, interval_ms=None):
        self.calls.append(("post", url, payload))
        return self.gdata


def make(tmp_path, ratings=("general", "sensitive", "explicit"), **kw):
    cfg = Config.load(tmp_path / "c.json")
    cfg.set("ratings.allowed", list(ratings), save=False)
    return EHentai(FakeHttp(**kw), cfg)


def test_search_tokens_use_e_hentai_syntax():
    assert search_token("landscape") == "landscape" and search_token("-landscape") == "-landscape"
    assert search_token("big_breasts") == '"big breasts"'
    assert search_token("female:stockings") == "female:stockings$"
    assert search_token("artist:foo_bar") == 'artist:"foo bar$"' and search_token("-female:big_breasts") == '-female:"big breasts$"'
    assert search_token("-") == ""


def test_tag_parsing_maps_namespaces():
    assert parse_tag("female:big breasts") == ("big_breasts", "general")
    assert parse_tag("artist:foo bar") == ("foo_bar", "artist")
    assert parse_tag("parody:some show") == ("some_show", "copyright") and parse_tag("character:x y") == ("x_y", "character")
    assert parse_tag("language:english") == ("english", "meta") and parse_tag("solo") == ("solo", "general")


def test_search_builds_posts_from_gallery_metadata(tmp_path):
    src = make(tmp_path)
    posts = src.search(["big_breasts", "-yaoi"], 3, 40)
    get = src.http.calls[0]
    assert get[2] == {"f_search": '"big breasts" -yaoi', "page": 2} and get[3] == {"Cookie": "nw=1"}
    api = src.http.calls[1]
    assert api[2]["method"] == "gdata" and api[2]["gidlist"] == [[101, "aaaaaaaaaa"], [102, "bbbbbbbbbb"], [103, "cccccccccc"]]
    assert [p.id for p in posts] == ["101", "102"]                     # #103 had an API error and is skipped
    first, second = posts
    assert (first.title, first.rating, first.score) == ("First", "explicit", 9) and second.rating == "sensitive"
    assert first.author == "foo_bar" and ("foo_bar", "artist") in first.tags and ("big_breasts", "general") in first.tags
    assert first.page_url == "https://e-hentai.org/g/101/aaaaaaaaaa/" and first.preview_url == "https://ehgt.org/a.webp"


def test_rating_setting_limits_what_is_requested(tmp_path):
    only_sensitive = make(tmp_path, ratings=("general", "sensitive"))
    only_sensitive.search([], 1, 40)
    assert only_sensitive.http.calls[0][2]["f_cats"] == 1023 - 256          # everything except Non-H is excluded
    explicit = make(tmp_path, ratings=("explicit",))
    explicit.search([], 1, 40)
    assert "f_cats" not in explicit.http.calls[0][2]
    with pytest.raises(SourceError, match="adult"):
        make(tmp_path, ratings=("general",)).search([], 1, 40)


def test_empty_and_banned_pages(tmp_path):
    assert make(tmp_path, html="<html>No hits found</html>").search(["zzz"], 1, 40) == []
    with pytest.raises(SourceError, match="banned"):
        make(tmp_path, html="Your IP address has been temporarily banned").search([], 1, 40)
    with pytest.raises(SourceError):
        make(tmp_path, gdata={"nonsense": 1}).search([], 1, 40)


def test_first_page_image_is_resolved_lazily(tmp_path):
    src = make(tmp_path)
    post = src.search([], 1, 40)[0]
    assert post.file_url == ""
    post.ensure_file()
    assert post.file_url == "https://h.example:60512/h/abc/keystamp=1;a=b&c=d/Page_001.webp" and post.ext == "webp"
    assert [c[1] for c in src.http.calls[-2:]] == ["https://e-hentai.org/g/101/aaaaaaaaaa/", "https://e-hentai.org/s/31d3aa4a4c/101-1"]


def test_resolve_failures_are_readable(tmp_path):
    src = make(tmp_path)
    post = src.search([], 1, 40)[0]
    src.http.get_text = lambda *a, **k: "<html>nothing</html>"
    with pytest.raises(SourceError, match="no pages"):
        post.ensure_file()

    def broken(*a, **k):
        raise HttpError(509, "limit")

    src.http.get_text = broken
    with pytest.raises(SourceError, match="cannot open"):
        post.ensure_file()


def test_registered_with_the_others(tmp_path):
    cfg = Config.load(tmp_path / "c.json")
    assert "ehentai" in build_sources(FakeHttp(), cfg)
