import pytest

from anihub.core.config import Config
from anihub.net.http import HttpError
from anihub.sources import build_sources
from anihub.sources.base import SourceError
from anihub.sources.nhentai import NHentai, parse_tags, search_token

LISTING = {"result": [
    {"id": 11, "media_id": "9", "english_title": "First", "japanese_title": "", "thumbnail": "galleries/9/thumb.webp", "num_favorites": 40,
     "blacklisted": False},
    {"id": 12, "media_id": "8", "english_title": "", "japanese_title": "Nihongo", "thumbnail": "galleries/8/thumb.webp", "num_favorites": 3,
     "blacklisted": True}], "num_pages": 1, "per_page": 25, "total": 2}
DETAIL = {"id": 11, "title": {"english": "First (full)"}, "pages": [{"number": 1, "path": "galleries/9/1.webp", "width": 1280, "height": 876}],
          "tags": [{"type": "artist", "name": "foo bar"}, {"type": "tag", "name": "big breasts"}, {"type": "parody", "name": "some show"},
                   {"type": "language", "name": "english"}, {"type": "tag", "name": "big breasts"}]}


class FakeHttp:
    def __init__(self, listing=LISTING, detail=DETAIL):
        self.calls, self.listing, self.detail = [], listing, detail

    def get_json(self, url, params=None, auth=None, headers=None, interval_ms=None):
        self.calls.append((url, params))
        if isinstance(self.listing, Exception):
            raise self.listing
        return self.detail if url.rsplit("/", 1)[-1].isdigit() else self.listing


def make(tmp_path, ratings=("explicit",), **kw):
    cfg = Config.load(tmp_path / "c.json")
    cfg.set("ratings.allowed", list(ratings), save=False)
    return NHentai(FakeHttp(**kw), cfg)


def test_search_tokens():
    assert search_token("big_breasts") == 'tag:"big breasts"' and search_token("-yaoi") == '-tag:"yaoi"'
    assert search_token("artist:foo_bar") == 'artist:"foo bar"' and search_token("language:english") == 'language:"english"'
    assert search_token("unknown:x") == 'tag:"unknown:x"' and search_token("-") == ""


def test_tag_parsing():
    tags, artists = parse_tags(DETAIL["tags"])
    assert tags == [("foo_bar", "artist"), ("big_breasts", "general"), ("some_show", "copyright"), ("english", "meta")]
    assert artists == "foo_bar"


def test_search_lists_galleries_and_skips_blacklisted(tmp_path):
    src = make(tmp_path)
    posts = src.search(["big_breasts", "-yaoi"], 2, 40)
    assert src.http.calls[0] == ("https://nhentai.net/api/v2/search", {"query": 'tag:"big breasts" -tag:"yaoi"', "page": 2})
    assert [p.id for p in posts] == ["11"]
    post = posts[0]
    assert (post.title, post.rating, post.score) == ("First", "explicit", 40)
    assert post.preview_url == "https://t1.nhentai.net/galleries/9/thumb.webp" and post.page_url == "https://nhentai.net/g/11/"
    src.search([], 1, 40)
    assert src.http.calls[1] == ("https://nhentai.net/api/v2/galleries", {"page": 1})           # no query: newest galleries


def test_first_page_and_tags_arrive_lazily(tmp_path):
    src = make(tmp_path)
    post = src.search([], 1, 40)[0]
    assert post.file_url == "" and post.tags == []
    post.ensure_file()
    assert post.file_url == "https://i1.nhentai.net/galleries/9/1.webp" and post.ext == "webp" and (post.width, post.height) == (1280, 876)
    assert ("big_breasts", "general") in post.tags and post.author == "foo_bar" and post.title == "First (full)"


def test_needs_explicit_and_reports_errors(tmp_path):
    with pytest.raises(SourceError, match="explicit"):
        make(tmp_path, ratings=("general", "sensitive")).search([], 1, 40)
    with pytest.raises(SourceError, match="403"):
        make(tmp_path, listing=HttpError(403, "no")).search([], 1, 40)
    with pytest.raises(SourceError, match="unexpected"):
        make(tmp_path, listing={"nope": 1}).search([], 1, 40)
    src = make(tmp_path, detail={"pages": []})
    post = src.search([], 1, 40)[0]
    with pytest.raises(SourceError, match="no pages"):
        post.ensure_file()


def test_registered(tmp_path):
    assert "nhentai" in build_sources(FakeHttp(), Config.load(tmp_path / "c.json"))
