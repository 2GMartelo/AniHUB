import hashlib
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from anihub.core.config import Config
from anihub.net.http import HttpClient, HttpError
from anihub.net.streamproxy import proxy_for, rewrite_playlist
from anihub.services.extensions import ExtensionError, ExtensionManager, build_index, parse_index, version_key
from anihub.sources.anime.anilibria import AniLibria
from anihub.sources.novels.base import NovelChapter, NovelEntry, NovelSource
from anihub.sources.novels.ranobelib import RanobeLib, age_of, prosemirror_html


def cfg_in(tmp_path, **sets) -> Config:
    cfg = Config.load(tmp_path / "c.json")
    for key, value in sets.items():
        cfg.set(key.replace("__", "."), value, save=False)
    return cfg


class FakeHttp:
    def __init__(self, responses):
        self.responses, self.calls = responses, []

    def add_host_headers(self, *_a):
        pass

    def get_json(self, url, params=None, headers=None, interval_ms=None):
        self.calls.append((url, params, headers))
        for key, value in self.responses.items():
            if key in url:
                if isinstance(value, Exception):
                    raise value
                return value(params) if callable(value) else value
        raise AssertionError(url)

    def get_bytes(self, url):
        self.calls.append((url, None, None))
        value = self.responses.get(url)
        if isinstance(value, Exception):
            raise value
        if value is None:
            raise HttpError(404, "no")
        return value


# --- the stream proxy ----------------------------------------------------------------------------------------------

class Upstream(BaseHTTPRequestHandler):
    seen: list = []

    def log_message(self, *a):
        pass

    def do_GET(self):                                                        # noqa: N802
        Upstream.seen.append((self.path, self.headers.get("Referer"), self.headers.get("Range")))
        if self.headers.get("Referer") != "https://site.example/":
            self.send_error(403)
            return
        if self.path.endswith(".m3u8"):
            body = b"#EXTM3U\n#EXT-X-KEY:METHOD=AES-128,URI=\"key.bin\"\n#EXTINF:10,\nseg0.ts\n#EXTINF:10,\nseg1.ts\n"
            self.send_response(200)
            self.send_header("Content-Type", "application/vnd.apple.mpegurl")
        else:
            data = b"0123456789" * 100
            start = 0
            rng = self.headers.get("Range")
            if rng:
                start = int(rng.split("=")[1].split("-")[0])
                body = data[start:]
                self.send_response(206)
                self.send_header("Content-Range", f"bytes {start}-{len(data) - 1}/{len(data)}")
            else:
                body = data
                self.send_response(200)
            self.send_header("Content-Type", "video/mp4")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture
def upstream():
    server = ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    Upstream.seen = []
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


def test_proxy_adds_headers_forwards_ranges_and_rewrites_playlists(tmp_path, upstream):
    import httpx

    http = HttpClient(cfg_in(tmp_path))
    proxy = proxy_for(http)
    assert proxy_for(http) is proxy
    headers = {"Referer": "https://site.example/"}
    try:
        url = proxy.url_for(f"{upstream}/v/a.mp4", headers)
        assert url.startswith("http://127.0.0.1:") and url.endswith(".mp4")
        assert httpx.get(url).content == b"0123456789" * 100                       # the header made the upstream answer
        partial = httpx.get(url, headers={"Range": "bytes=990-"})
        assert partial.status_code == 206 and partial.content == b"0123456789"     # seeking works
        assert httpx.get(url.replace("/s/", "/s/x")).status_code == 404             # unknown token
        playlist = httpx.get(proxy.url_for(f"{upstream}/v/index.m3u8", headers)).text
        lines = [ln for ln in playlist.splitlines() if ln and not ln.startswith("#")]
        assert len(lines) == 2 and all("127.0.0.1" in ln and "/s/" in ln for ln in lines), playlist
        assert 'URI="http://127.0.0.1:' in playlist                                 # the key goes through the proxy too
        segment_url = next(ln for ln in lines if ln.endswith(".ts"))
        assert httpx.get(segment_url).status_code == 200                            # ...and so do the segments
        assert httpx.get(f"{upstream}/v/a.mp4").status_code == 403                  # sanity: without the proxy it is refused
    finally:
        proxy.stop()


def test_rewrite_playlist_resolves_relative_and_absolute_uris():
    text = "#EXTM3U\n#EXT-X-MAP:URI=\"init.mp4\"\n#EXTINF:5,\nhttps://cdn.x/a/seg1.ts\n#EXTINF:5,\n../seg2.ts\n"
    out = rewrite_playlist(text, "https://site.x/v/1/index.m3u8", lambda u: f"<{u}>")
    assert '<https://site.x/v/1/init.mp4>' in out and "<https://cdn.x/a/seg1.ts>" in out and "<https://site.x/v/seg2.ts>" in out


def test_player_sends_streams_with_headers_through_the_proxy(tmp_path):
    from anihub.sources.anime.base import Stream
    from anihub.ui.anime_player import stream_url

    http = HttpClient(cfg_in(tmp_path))
    try:
        assert stream_url(Stream("https://x/y.m3u8"), http).host() == "x"                     # no headers: direct
        proxied = stream_url(Stream("https://x/y.m3u8", headers={"Referer": "https://x/"}), http)
        assert proxied.host() == "127.0.0.1" and proxied.path().endswith(".m3u8")
    finally:
        proxy_for(http).stop()


# --- AniLibria -----------------------------------------------------------------------------------------------------

def test_anilibria_catalogue_search_episodes_and_streams(tmp_path):
    raw = {"id": 7, "name": {"main": "Наруто", "english": "Naruto"}, "alias": "naruto", "description": "About",
           "poster": {"src": "/storage/p.jpg", "optimized": {"preview": "/storage/p.webp"}}}
    release = {**raw, "episodes": [
        {"id": "e2", "ordinal": 2, "name": "Two", "hls_480": "https://c/2/480.m3u8", "hls_720": "https://c/2/720.m3u8", "hls_1080": None},
        {"id": "e1", "ordinal": 1, "name": None, "hls_480": "https://c/1/480.m3u8", "hls_720": None, "hls_1080": None}]}
    http = FakeHttp({"/anime/catalog/releases": {"data": [raw], "meta": {"pagination": {"current_page": 1, "total_pages": 3}}},
                     "/app/search/releases": [raw], "/anime/releases/7": release})
    src = AniLibria(http, cfg_in(tmp_path))
    entries, more = src.search("", 1)
    assert more and entries[0].title == "Наруто" and entries[0].cover == "https://anilibria.top/storage/p.webp"
    entries, more = src.search("нар")
    assert not more and entries[0].id == "7"
    episodes = src.episodes(entries[0])
    assert [e.number for e in episodes] == [1.0, 2.0]                                       # oldest first
    streams = src.streams(entries[0], episodes[1])
    assert [s.label for s in streams] == ["720p", "480p"] and not streams[0].headers
    assert src.lang == "ru" and not src.nsfw


# --- RanobeLib -----------------------------------------------------------------------------------------------------

def test_ranobelib_search_details_chapters_and_text(tmp_path):
    item = {"id": 1, "slug_url": "1--solo", "rus_name": "Соло", "eng_name": "Solo", "ageRestriction": {"label": "16+"},
            "cover": {"default": "https://c/1.jpg"}}
    detail = {"data": {"summary": "Story", "genres": [{"name": "Боевик"}], "tags": [{"name": "Игра"}],
                       "authors": [{"name": "A"}, {"name": "B"}], "ageRestriction": {"label": "18+"}}}
    chapters = {"data": [{"volume": "1", "number": "0", "name": "Пролог", "branches": [{"branch_id": 9}]},
                         {"volume": "1", "number": "1", "name": "", "branches": []}]}
    text = {"data": {"content": '<p>Hi</p><img src="/uploads/a.jpg"/>', "name": "x"}}
    http = FakeHttp({"/manga/1--solo/chapters": chapters, "/manga/1--solo/chapter": text, "/manga/1--solo": detail,
                     "/api/manga": {"data": [item], "meta": {"has_next_page": True}}})
    src = RanobeLib(http, cfg_in(tmp_path))
    entries, more = src.search("solo", 2)
    assert more and entries[0].title == "Соло" and entries[0].age == 16
    _, params, headers = http.calls[0]
    assert ("site_id[]", 3) in params and ("q", "solo") in params and ("page", 2) in params and headers["Site-Id"] == "3"
    entry = src.details(entries[0])
    assert entry.author == "A, B" and entry.tags == ["Боевик", "Игра"] and entry.age == 18 and entry.description == "Story"
    chs = src.chapters(entry)
    assert [c.title for c in chs] == ["Том 1. Глава 0. Пролог", "Том 1. Глава 1"] and chs[0].id == "1/0/9" and chs[1].id == "1/1/"
    html = src.chapter_html(entry, chs[0])
    assert "<p>Hi</p>" in html and 'src="https://ranobelib.me/uploads/a.jpg"' in html
    params = http.calls[-1][1]
    assert ("volume", "1") in params and ("number", "0") in params and ("branch_id", "9") in params
    with pytest.raises(Exception, match="RanobeLib"):
        RanobeLib(FakeHttp({"/api/manga": HttpError(500, "boom")}), cfg_in(tmp_path)).search("x")


def test_ranobelib_age_and_prosemirror():
    assert age_of({"ageRestriction": {"label": "16+"}}) == 16 and age_of({"ageRestriction": {"label": "Нет"}}) == 0 and age_of({}) == 0
    doc = {"type": "doc", "content": [
        {"type": "paragraph", "content": [{"type": "text", "text": "a < b", "marks": [{"type": "bold"}]}]},
        {"type": "heading", "attrs": {"level": 2}, "content": [{"type": "text", "text": "H"}]},
        {"type": "image", "attrs": {"images": [{"image": "pic"}]}}]}
    html = prosemirror_html(doc, {"pic": "/uploads/pic.png"})
    assert "<p><b>a &lt; b</b></p>" in html and "<h2>H</h2>" in html and 'src="https://ranobelib.me/uploads/pic.png"' in html


# --- extension repositories ------------------------------------------------------------------------------------------

PLUGIN = '''
EXTENSION = {"id": "demo_src", "kind": "anime", "name": "Demo", "lang": "en", "version": "1.2", "description": "d"}
from anihub.sources.anime.base import AnimeSource, AnimeEntry, Episode, Stream
class DemoSrc(AnimeSource):
    name = "demo_src"
    title = "Demo"
    lang = "en"
    def search(self, query, page=1):
        return [AnimeEntry("1", "Demo " + query)], False
    def episodes(self, entry):
        return [Episode("a", 1)]
    def streams(self, entry, episode):
        return [Stream("https://x/y.m3u8", "auto")]
'''


class RepoHttp:
    def __init__(self, files):
        self.files = files

    def get_json(self, url, params=None, headers=None, interval_ms=None):
        if url not in self.files:
            raise HttpError(404, "no")
        return json.loads(self.files[url])

    def get_bytes(self, url):
        if url not in self.files:
            raise HttpError(404, "no")
        return self.files[url] if isinstance(self.files[url], bytes) else self.files[url].encode()


def make_repo(tmp_path, code=PLUGIN):
    data = code.encode()
    index = {"name": "R", "extensions": [
        {"id": "demo_src", "kind": "anime", "name": "Demo", "lang": "en", "version": "1.2", "file": "demo_src.py",
         "sha256": hashlib.sha256(data).hexdigest(), "description": "d"},
        {"id": "Bad Id", "kind": "anime", "file": "x.py", "sha256": "0" * 64},                # invalid id: skipped
        {"id": "nosum", "kind": "anime", "file": "x.py"},                                     # no checksum: skipped
        {"id": "weird", "kind": "music", "file": "x.py", "sha256": "0" * 64}]}                # unknown kind: skipped
    url = "https://repo.example/index.json"
    http = RepoHttp({url: json.dumps(index), "https://repo.example/demo_src.py": data})
    cfg = cfg_in(tmp_path, extensions__repos=[url])
    return ExtensionManager(http, cfg, tmp_path / "plugins"), http, url


def test_index_parsing_validates_entries():
    infos = parse_index({"extensions": [{"id": "ok_one", "kind": "novel", "file": "a.py", "sha256": "a" * 64, "lang": "ru"},
                                        {"id": "bad", "kind": "novel"}]}, "https://h/r/index.json")
    assert [(i.id, i.url, i.lang) for i in infos] == [("ok_one", "https://h/r/a.py", "ru")]
    with pytest.raises(ExtensionError):
        parse_index({"nothing": 1}, "https://h/i.json")
    assert version_key("1.10") > version_key("1.9") and version_key("2") > version_key("1.99")


def test_install_verifies_the_checksum_and_the_loader_picks_the_plugin_up(tmp_path):
    from anihub.sources.anime import build_anime_sources

    manager, http, url = make_repo(tmp_path)
    infos, errors = manager.available()
    assert not errors and [i.id for i in infos] == ["demo_src"]
    info = infos[0]
    assert manager.status(info) == "new"
    path = manager.install(info)
    assert path == tmp_path / "plugins" / "anime" / "demo_src.py" and manager.status(info) == "installed"
    assert manager.installed() == {("anime", "demo_src"): "1.2"}
    sources = build_anime_sources(http, cfg_in(tmp_path), tmp_path / "lib", tmp_path / "plugins" / "anime")
    assert sources["demo_src"].search("x")[0][0].title == "Demo x" and sources["demo_src"].lang == "en"
    manager.uninstall("anime", "demo_src")
    assert not path.exists() and manager.status(info) == "new"


def test_tampered_or_broken_files_are_refused(tmp_path):
    manager, http, url = make_repo(tmp_path)
    info = manager.available()[0][0]
    http.files["https://repo.example/demo_src.py"] = PLUGIN + "\nimport os  # tampered\n"
    with pytest.raises(ExtensionError, match="checksum"):
        manager.install(info)
    assert not manager.file_of("anime", "demo_src").exists()
    broken = "def (:\n"
    manager2, http2, _ = make_repo(tmp_path, code=broken)
    with pytest.raises(ExtensionError, match="Python"):
        manager2.install(manager2.available()[0][0])
    manager3 = ExtensionManager(RepoHttp({}), cfg_in(tmp_path, extensions__repos=["https://gone/index.json"]), tmp_path / "p3")
    infos, errors = manager3.available()
    assert infos == [] and "gone" in errors[0]                                              # a dead repository is reported, not fatal


def test_update_is_offered_when_the_repository_has_a_newer_version(tmp_path):
    manager, http, url = make_repo(tmp_path)
    manager.install(manager.available()[0][0])
    newer = PLUGIN.replace('"1.2"', '"1.3"')
    index = json.loads(http.files[url])
    index["extensions"][0].update(version="1.3", sha256=hashlib.sha256(newer.encode()).hexdigest())
    http.files[url] = json.dumps(index)
    http.files["https://repo.example/demo_src.py"] = newer
    info = manager.available()[0][0]
    assert manager.status(info) == "update"
    manager.install(info)
    assert manager.status(info) == "installed" and manager.installed()[("anime", "demo_src")] == "1.3"


def test_build_index_reads_extension_dicts_without_running_the_files(tmp_path):
    folder = tmp_path / "ext"
    folder.mkdir()
    (folder / "demo_src.py").write_text(PLUGIN.replace("EXTENSION =", "raise SystemExit('must not run')\nEXTENSION ="), encoding="utf-8")
    index = build_index(folder)
    item = index["extensions"][0]
    assert item["id"] == "demo_src" and item["file"] == "demo_src.py" and len(item["sha256"]) == 64
    assert parse_index(index, "https://h/index.json")[0].lang == "en"
