import json

import httpx
import pytest

from anihub.core import agemode
from anihub.core.config import Config
from anihub.net.http import HttpClient, HttpError
from anihub.sources.base import SourceError
from anihub.sources.pinterest import Pinterest, original_of, route_of, words_of
from anihub.sources.pixiv import Pixiv, rating_of, sample_of

THUMB = "https://i.pximg.net/c/250x250_80_a2/img-master/img/2026/09/21/16/22/12/149928297_p0_square1200.jpg"


def cfg_in(tmp_path, **sets) -> Config:
    cfg = Config.load(tmp_path / "c.json")
    for key, value in sets.items():
        cfg.set(key.replace("__", "."), value, save=False)
    return cfg


class FakeHttp:
    def __init__(self, responses=None):
        self.responses, self.calls, self.hosts = responses or {}, [], {}

    def add_host_headers(self, suffix, headers):
        self.hosts[suffix] = headers

    def _answer(self, url, params=None):
        self.calls.append((url, params))
        for key, value in self.responses.items():
            if key in url:
                if isinstance(value, Exception):
                    raise value
                return value
        raise AssertionError(url)

    def get_json(self, url, params=None, headers=None, interval_ms=None):
        return self._answer(url, params)

    def get_text(self, url, params=None, headers=None, interval_ms=None):
        return self._answer(url, params)


def raw(pid="1", restrict=0, sl=2, tags=("miku", "初音ミク"), **kw):
    return {"id": pid, "title": "T", "illustType": 0, "xRestrict": restrict, "sl": sl, "url": THUMB, "tags": list(tags),
            "userName": "artist", "width": 10, "height": 20, **kw}


# --- Pixiv -------------------------------------------------------------------------------------------------------

def test_pixiv_ratings_and_sample_url():
    assert rating_of(0) == "general" and rating_of(0, 4) == "questionable" and rating_of(1) == "explicit" and rating_of(2) == "explicit"
    assert sample_of(THUMB) == "https://i.pximg.net/img-master/img/2026/09/21/16/22/12/149928297_p0_master1200.jpg"
    assert sample_of("https://x/y.jpg") == ""


def test_pixiv_search_parses_and_filters(tmp_path):
    items = [raw("1"), raw("2", restrict=1), raw("3", tags=("spam",)), raw("4", illustType=2), raw("5", isMasked=True), {"id": "6"}]
    http = FakeHttp({"/ajax/search/": {"error": False, "body": {"illustManga": {"data": items}}}})
    src = Pixiv(http, cfg_in(tmp_path))
    posts = src.search(["hatsune_miku", "-spam"], 2, 60)
    assert [p.id for p in posts] == ["1", "2"]                                   # ugoira, masked, broken and excluded are gone
    assert posts[0].rating == "general" and posts[1].rating == "explicit" and ("nsfw", "meta") in posts[1].tags
    assert posts[0].author == "artist" and posts[0].page_url.endswith("/artworks/1")
    url, params = http.calls[0]
    assert params["word"] == "hatsune miku" and params["p"] == 2 and params["mode"] == "safe"


def test_pixiv_asks_for_r18_only_with_cookie_and_adult_mode(tmp_path):
    http = FakeHttp({"/ajax/search/": {"error": False, "body": {"illustManga": {"data": []}}}})
    cfg = cfg_in(tmp_path)
    src = Pixiv(http, cfg)
    agemode.apply_mode(cfg, "18", save=False)
    src.search(["x"], 1, 10)
    assert http.calls[-1][1]["mode"] == "safe"                                     # 18+ but no cookie
    cfg.set("sources.pixiv.cookie", "abc_123", save=False)
    src.search(["x"], 1, 10)
    assert http.calls[-1][1]["mode"] == "all"
    agemode.apply_mode(cfg, "16", save=False)
    src.search(["x"], 1, 10)
    assert http.calls[-1][1]["mode"] == "safe"                                     # the cookie alone changes nothing


def test_pixiv_registers_referer_and_cookie_headers(tmp_path):
    http = FakeHttp()
    cfg = cfg_in(tmp_path)
    Pixiv(http, cfg)
    assert http.hosts["pximg.net"]()["Referer"] == "https://www.pixiv.net/"
    assert "Cookie" not in http.hosts["pixiv.net"]()
    cfg.set("sources.pixiv.cookie", "12345_abcdef", save=False)                     # applied at once, without a restart
    assert http.hosts["pixiv.net"]()["Cookie"] == "PHPSESSID=12345_abcdef"
    cfg.set("sources.pixiv.cookie", "PHPSESSID=1_x; other=2", save=False)
    assert http.hosts["pixiv.net"]()["Cookie"] == "PHPSESSID=1_x; other=2"


def test_pixiv_ranking_for_an_empty_query_and_lazy_original(tmp_path):
    ranking = {"contents": [{"illust_id": 7, "url": "https://i.pximg.net/c/480x960/img-master/img/2026/09/19/00/00/18/7_p0_master1200.jpg",
                             "tags": ["a"], "title": "R", "user_name": "u", "width": 5, "height": 6, "illust_type": "0",
                             "illust_content_type": {"sexual": 0}}]}
    pages = {"body": [{"urls": {"original": "https://i.pximg.net/img-original/img/2026/09/19/00/00/18/7_p0.png"}, "width": 50, "height": 60}]}
    http = FakeHttp({"ranking.php": ranking, "/ajax/illust/7/pages": pages})
    posts = Pixiv(http, cfg_in(tmp_path)).search([], 1, 10)
    assert len(posts) == 1 and posts[0].file_url == ""
    posts[0].ensure_file()
    assert posts[0].file_url.endswith("7_p0.png") and posts[0].ext == "png" and posts[0].width == 50


def test_pixiv_errors_are_readable(tmp_path):
    src = Pixiv(FakeHttp({"/ajax/search/": HttpError(403, "no")}), cfg_in(tmp_path, sources__pixiv__cookie="abc"))
    with pytest.raises(SourceError, match="PHPSESSID"):
        src.search(["x"], 1, 10)
    src = Pixiv(FakeHttp({"/ajax/search/": {"error": True, "message": "nope"}}), cfg_in(tmp_path))
    with pytest.raises(SourceError, match="nope"):
        src.search(["x"], 1, 10)


# --- Pinterest ---------------------------------------------------------------------------------------------------

RSS = """<?xml version="1.0"?><rss version="2.0"><channel>
<item><title>Blue sky &amp; sea</title><link>https://www.pinterest.com/pin/111/</link>
<description>&lt;a href="https://www.pinterest.com/pin/111/"&gt;&lt;img src="https://i.pinimg.com/236x/aa/bb/cc/aabbcc.jpg"&gt;&lt;/a&gt;Blue sky and a quiet sea</description></item>
<item><title>No image</title><link>https://www.pinterest.com/pin/112/</link><description>text only</description></item>
</channel></rss>"""


def search_reply(ids, bookmark):
    pins = [{"type": "pin", "id": i, "title": f"Pin {i}", "description": "hatsune miku", "pinner": {"username": "who"},
             "images": {"236x": {"url": f"https://i.pinimg.com/236x/aa/{i}.jpg"},
                        "orig": {"url": f"https://i.pinimg.com/originals/aa/{i}.png", "width": 9, "height": 8}}} for i in ids]
    pins.append({"type": "pin", "id": "ad", "is_promoted": True, "images": {}})
    pins.append({"type": "story", "id": "s"})
    return {"resource_response": {"data": {"results": pins}, "bookmark": bookmark}}


def test_pinterest_helpers():
    assert original_of("https://i.pinimg.com/474x/aa/bb.jpg") == "https://i.pinimg.com/originals/aa/bb.jpg"
    assert original_of("https://i.pinimg.com/originals/aa/bb.jpg") == "https://i.pinimg.com/originals/aa/bb.jpg"
    assert route_of("user:Someone") == ("rss", "https://www.pinterest.com/Someone/feed.rss")
    assert route_of("board:a/b-c")[1] == "https://www.pinterest.com/a/b-c.rss"
    assert route_of("https://www.pinterest.com/a/b/")[1] == "https://www.pinterest.com/a/b.rss"
    assert route_of("https://www.pinterest.com/a/")[1] == "https://www.pinterest.com/a/feed.rss"
    assert route_of("https://www.pinterest.com/pin/123/") is None and route_of("cat") is None
    assert words_of("𝐻𝑎𝑡𝑠𝑢𝑛𝑒 Miku, the 3D art") == ["hatsune", "miku", "art"]


def test_pinterest_rss_route(tmp_path):
    http = FakeHttp({".rss": RSS})
    src = Pinterest(http, cfg_in(tmp_path))
    posts = src.search(["user:someone"], 1, 10)
    assert [p.id for p in posts] == ["111"] and posts[0].file_url == "https://i.pinimg.com/originals/aa/bb/cc/aabbcc.jpg"
    assert posts[0].title.startswith("Blue sky") and ("quiet", "general") in posts[0].tags
    assert http.calls[0][0] == "https://www.pinterest.com/someone/feed.rss"
    assert src.search(["user:someone"], 2, 10) == []                                # RSS has one page
    assert src.search(["user:someone", "-quiet"], 1, 10) == []                      # excluded word


def test_pinterest_search_pages_by_bookmark_and_skips_ads(tmp_path):
    replies = [search_reply(["1", "2"], "BM1"), search_reply(["3"], "BM2"), search_reply(["4"], "-end-")]
    seen = []

    class Http(FakeHttp):
        def get_json(self, url, params=None, headers=None, interval_ms=None):
            options = json.loads(params["data"])["options"]
            seen.append((options["query"], options["bookmarks"]))
            return replies.pop(0)

    src = Pinterest(Http(), cfg_in(tmp_path))
    first = src.search(["hatsune_miku"], 1, 25)
    assert [p.id for p in first] == ["1", "2"] and first[0].ext == "png" and first[0].rating == "general"
    assert [p.id for p in src.search(["hatsune_miku"], 2, 25)] == ["3"]
    assert [p.id for p in src.search(["hatsune_miku"], 3, 25)] == ["4"]
    assert seen == [("hatsune miku", []), ("hatsune miku", ["BM1"]), ("hatsune miku", ["BM2"])]
    assert src.search(["hatsune_miku"], 4, 25) == []                                # the end marker stops paging


def test_pinterest_needs_a_query_and_reports_failures(tmp_path):
    with pytest.raises(SourceError):
        Pinterest(FakeHttp(), cfg_in(tmp_path)).search([], 1, 10)
    with pytest.raises(SourceError, match="404"):
        Pinterest(FakeHttp({".rss": HttpError(404, "Board not found")}), cfg_in(tmp_path)).search(["user:nobody"], 1, 10)
    with pytest.raises(SourceError, match="unexpected"):
        Pinterest(FakeHttp({".rss": "<html>"}), cfg_in(tmp_path)).search(["user:x"], 1, 10)


def test_pinterest_words_are_visible_to_the_tag_filter(tmp_path):
    src = Pinterest(FakeHttp({".rss": RSS.replace("quiet", "naked")}), cfg_in(tmp_path))
    post = src.search(["user:x"], 1, 10)[0]
    assert agemode.blocker_for(cfg_in(tmp_path)).blocked_in(post.tag_names)         # 12+ hides it


# --- per-host headers in the real client ---------------------------------------------------------------------------

def test_http_client_adds_host_headers(tmp_path):
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.url.host, dict(request.headers)))
        return httpx.Response(200, content=b"x")

    http = HttpClient(cfg_in(tmp_path))
    http._client = httpx.Client(transport=httpx.MockTransport(handler), headers={"User-Agent": "base"})
    http.add_host_headers("pximg.net", lambda: {"Referer": "https://www.pixiv.net/"})
    http.get_bytes("https://i.pximg.net/a.jpg")
    http.get_bytes("https://example.com/a.jpg")
    http.get_bytes("https://notpximg.net/a.jpg")
    http.download("https://i.pximg.net/b.jpg", tmp_path / "d.jpg")
    assert seen[0][1]["referer"] == "https://www.pixiv.net/" and seen[3][1]["referer"] == "https://www.pixiv.net/"
    assert "referer" not in seen[1][1] and "referer" not in seen[2][1]              # only that host and its subdomains
