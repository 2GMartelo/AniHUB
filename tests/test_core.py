from pathlib import Path

from anihub.core.config import Config
from anihub.core.db import Database
from anihub.core.paths import LibraryPaths
from anihub.library.service import LibraryService
from anihub.library.media import MediaCache
from anihub.sources import danbooru
from anihub.sources.moebooru_sites import Yandere
from anihub.sources.rule34 import Rule34
from anihub.sources.zerochan import Zerochan
from anihub.sources.base import Post
from anihub.ui.library_view import split_query
from anihub.ui.tagquery import apply_tag


def test_config_roundtrip_and_defaults(tmp_path):
    path = tmp_path / "config.json"
    cfg = Config.load(path)
    assert cfg.get("ratings.allowed") == ["general"]
    cfg.set("network.proxy", "http://x:1")
    again = Config.load(path)
    assert again.get("network.proxy") == "http://x:1"
    assert again.get("network.max_parallel") == 6  # default preserved after merge


def test_config_broken_file_is_kept(tmp_path):
    path = tmp_path / "config.json"
    path.write_text("{not json")
    cfg = Config.load(path)
    assert cfg.get("language") == "ru"
    assert (tmp_path / "config.broken.json").exists()


def test_danbooru_parse():
    raw = {"id": 5, "file_url": "https://x/a.png", "preview_file_url": "https://x/p.jpg", "rating": "e",
           "tag_string_artist": "some_artist", "tag_string_general": "1girl solo", "file_ext": "png",
           "image_width": 10, "image_height": 20, "score": 3}
    post = danbooru.parse_post(raw)
    assert post.rating == "explicit" and post.author == "some_artist"
    assert ("1girl", "general") in post.tags and ("some_artist", "artist") in post.tags
    assert danbooru.parse_post({"id": 6}) is None  # no file_url (gold-only)


def test_rule34_parse():
    raw = {"id": 7, "file_url": "https://x/a.webm", "preview_url": "https://x/p.jpg", "tags": "a b",
           "rating": "questionable", "width": 1, "height": 2, "score": 0}
    post = Rule34.parse(raw)
    assert post.rating == "questionable" and post.badge == "▶" and post.tag_names == ["a", "b"]


def test_split_query():
    assert split_query("Cat  -dog blue") == (["cat", "blue"], ["dog"])


class FakeHttp:
    def download(self, url: str, dest: Path) -> None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(url.encode())  # content depends on the url -> different hashes


def make_service(tmp_path):
    paths = LibraryPaths(tmp_path / "lib")
    paths.ensure()
    return LibraryService(Database(paths.db_file), paths, FakeHttp()), paths


def make_post(pid: str, url: str | None = None, rating="general", tags=(("cat", "general"),)) -> Post:
    return Post("danbooru", pid, url or f"https://x/{pid}.png", "https://x/t.jpg", rating=rating,
                tags=list(tags), author="me", ext="png")


def test_save_and_dedup(tmp_path):
    svc, paths = make_service(tmp_path)
    assert svc.save_post(make_post("1")).status == "saved"
    assert (paths.arts / "danbooru" / "danbooru_1.png").exists()
    assert svc.save_post(make_post("1")).status == "duplicate"  # same source id
    assert svc.save_post(make_post("2", url="https://x/1.png")).status == "duplicate"  # same content hash
    assert not (paths.arts / "danbooru" / "danbooru_2.png").exists()
    assert svc.db.count_items() == 1


def test_search_include_exclude_and_rating(tmp_path):
    svc, _ = make_service(tmp_path)
    svc.save_post(make_post("1", tags=[("cat", "general"), ("blue", "general")]))
    svc.save_post(make_post("2", tags=[("cat", "general")]))
    svc.save_post(make_post("3", rating="explicit", tags=[("cat", "general")]))
    db = svc.db
    assert len(db.search_items(["cat"], [], ["general"])) == 2
    assert [r["source_post_id"] for r in db.search_items(["cat"], ["blue"], ["general"])] == ["2"]
    assert len(db.search_items(["cat"], [], ["general", "explicit"])) == 3
    assert db.search_items(["cat"], [], []) == []
    assert db.item_tags(1) == ["blue", "cat"]


def test_moebooru_parse():
    raw = {"id": 9, "file_url": "https://y/a.jpg", "preview_url": "https://y/p.jpg", "sample_url": "https://y/s.jpg",
           "tags": "x y", "rating": "s", "width": 5, "height": 6, "score": 2, "file_ext": "jpg"}
    post = Yandere.parse(raw)
    assert post.rating == "general" and post.page_url == "https://yande.re/post/show/9"
    assert post.display_url() == "https://y/s.jpg"


def test_display_url_rules():
    gif = Post("s", "1", "https://x/a.gif", "p", sample_url="https://x/s.jpg", ext="gif")
    assert gif.display_url() == "https://x/a.gif" and gif.badge == "GIF"
    ugoira = Post("s", "2", "https://x/a.zip", "p", sample_url="https://x/s.webm", ext="zip")
    assert ugoira.display_url() == "https://x/s.webm"
    still = Post("s", "3", "https://x/a.png", "p", ext="png")
    assert still.display_url() == "https://x/a.png" and still.badge == ""


class FakeZerochanHttp:
    def get_json(self, url, params=None, auth=None, headers=None, interval_ms=None):
        self.last = (url, params, headers)
        if url.endswith("/555"):
            return {"full": "https://static.zerochan.net/A.B.full.555.png", "width": 100, "height": 200}
        return {"items": [
            {"id": 555, "width": 1, "height": 2, "thumbnail": "https://s3.zerochan.net/240/1/2/555.avif",
             "source": "", "tags": ["Hatsune Miku", "Solo"]},
            {"id": 556, "width": 1, "height": 2, "thumbnail": "https://s3.zerochan.net/240/1/2/556.avif",
             "source": "", "tags": ["Hatsune Miku", "Male"]}]}


def test_zerochan_lazy_file_and_client_side_exclusion(tmp_path):
    cfg = Config.load(tmp_path / "c.json")
    src = Zerochan(FakeZerochanHttp(), cfg)
    posts = src.search(["hatsune_miku", "-male"], 1, 40)
    assert [p.id for p in posts] == ["555"]  # 556 has the excluded tag
    assert src.http.last[0].endswith("/hatsune%20miku") and src.http.last[2]["User-Agent"].startswith("AniHUB")
    post = posts[0]
    assert post.preview_url.endswith(".jpg") and post.file_url == ""
    post.ensure_file()
    assert post.file_url.endswith(".png") and post.ext == "png" and post.width == 100


def test_media_cache(tmp_path):
    class Http:
        calls = 0

        def download(self, url, dest):
            Http.calls += 1
            dest.write_bytes(b"x" * 10)

    cache = MediaCache(Http(), tmp_path / "m")
    a = cache.get("https://x/some%20file.webm")
    assert a.suffix == ".webm" and cache.get("https://x/some%20file.webm") == a and Http.calls == 1
    cache.prune(limit=0)
    assert not a.exists()


def test_apply_tag():
    assert apply_tag("cat dog", "bird", "search") == "bird"
    assert apply_tag("cat", "dog", "add") == "cat dog"
    assert apply_tag("cat -dog", "dog", "add") == "cat dog"
    assert apply_tag("cat dog", "dog", "exclude") == "cat -dog"


def test_save_lazy_post(tmp_path):
    svc, paths = make_service(tmp_path)
    post = Post("zerochan", "9", "", "https://x/t.jpg", ext="", tags=[("a", "general")])

    def resolver(p):
        p.file_url, p.ext = "https://x/9.png", "png"

    post.resolver = resolver
    assert svc.save_post(post).status == "saved"
    assert (paths.arts / "zerochan" / "zerochan_9.png").exists()
