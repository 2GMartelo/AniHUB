from types import SimpleNamespace

from anihub.sources.engines import GelbooruEngine, MoebooruEngine
from anihub.sources.rule34 import Rule34


class QueuedHttp:
    """Returns each queued response in order, one per get_json() call; records every call made."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls: list[tuple[str, dict]] = []

    def get_json(self, url, params=None, **kw):
        self.calls.append((url, params or {}))
        return self.responses.pop(0)


def keyed_cfg(**values):
    return SimpleNamespace(get=lambda key, default=None: values.get(key, default))


GEL_POST_PAGE = [{"id": 1, "file_url": "https://x/1.jpg", "tags": "1girl blue_hair some_artist"}]
GEL_TAG_LOOKUP = {"tag": [{"name": "blue_hair", "type": 0}, {"name": "some_artist", "type": 1}]}


def test_gelbooru_categorises_tags_after_search_when_credentials_are_set():
    class Gel(GelbooruEngine):
        name, title, api_url, page_url_tpl = "gel", "Gel", "https://gel.example/index.php", "x{id}"

    http = QueuedHttp(GEL_POST_PAGE, GEL_TAG_LOOKUP)
    gel = Gel(http, keyed_cfg(**{"sources.gel.user_id": "1", "sources.gel.api_key": "k"}))
    posts = gel.search(["1girl"], page=1, limit=10)

    assert len(http.calls) == 2                              # the post search, then one batched tag lookup
    assert http.calls[1][1]["names"] == "1girl blue_hair some_artist"     # every unique tag on the page, one request
    tags = dict(posts[0].tags)
    assert tags["blue_hair"] == "general" and tags["some_artist"] == "artist"
    assert tags["1girl"] == "general"                        # not found in the lookup response: left as the default


def test_gelbooru_skips_categorising_without_credentials():
    class Gel(GelbooruEngine):
        name, title, api_url, page_url_tpl = "gel", "Gel", "https://gel.example/index.php", "x{id}"

    http = QueuedHttp(GEL_POST_PAGE)
    gel = Gel(http, keyed_cfg())                              # no user_id/api_key
    posts = gel.search(["1girl"], page=1, limit=10)

    assert len(http.calls) == 1                               # no second (tag-lookup) call at all
    assert all(cat == "general" for _name, cat in posts[0].tags)


def test_gelbooru_categorising_fails_quietly_and_keeps_the_posts(monkeypatch):
    class Gel(GelbooruEngine):
        name, title, api_url, page_url_tpl = "gel", "Gel", "https://gel.example/index.php", "x{id}"

    class BrokenSecondCall(QueuedHttp):
        def get_json(self, url, params=None, **kw):
            self.calls.append((url, params or {}))
            if len(self.calls) == 1:
                return GEL_POST_PAGE
            raise RuntimeError("network down")

    http = BrokenSecondCall()
    gel = Gel(http, keyed_cfg(**{"sources.gel.user_id": "1", "sources.gel.api_key": "k"}))
    try:
        posts = gel.search(["1girl"], page=1, limit=10)
    except RuntimeError:
        raise AssertionError("a failed category lookup must not break the whole search")
    assert len(posts) == 1 and all(cat == "general" for _name, cat in posts[0].tags)


def test_rule34_uses_its_own_type_numbering_not_the_gelbooru_default():
    http = QueuedHttp(
        [{"id": 1, "file_url": "https://x/1.jpg", "tags": "a_character a_series"}],
        {"tag": [{"name": "a_character", "type": 2}, {"name": "a_series", "type": 3}]},
    )
    r34 = Rule34(http, keyed_cfg(**{"sources.rule34.user_id": "1", "sources.rule34.api_key": "k"}))
    posts = r34.search(["x"], page=1, limit=10)
    tags = dict(posts[0].tags)
    assert tags["a_character"] == "character" and tags["a_series"] == "copyright"
    # the stock GelbooruEngine mapping would have read type 2 as neither of those -- confirms the override is live
    assert GelbooruEngine.TAG_TYPE_MAP.get(2) != "character"


def test_moebooru_resolves_the_most_common_tags_one_lookup_each():
    class Moe(MoebooruEngine):
        name, title, base_url = "moe", "Moe", "https://moe.example"

    posts_page = [
        {"id": 1, "file_url": "https://x/1.jpg", "tags": "1girl a_character"},
        {"id": 2, "file_url": "https://x/2.jpg", "tags": "1girl another_tag"},
    ]
    http = QueuedHttp(posts_page, [{"name": "1girl", "type": 0}], [{"name": "a_character", "type": 4}],
                      [{"name": "another_tag", "type": 0}])
    moe = Moe(http, keyed_cfg())
    posts = moe.search(["1girl"], page=1, limit=10)

    assert dict(posts[0].tags)["a_character"] == "character"
    assert dict(posts[0].tags)["1girl"] == "general"
    # "1girl" appears on both posts (looked up first), the other two once each: 1 (search) + 3 (one per unique tag)
    assert len(http.calls) == 4


def test_moebooru_caps_how_many_tags_it_will_look_up_per_page():
    class Moe(MoebooruEngine):
        name, title, base_url = "moe", "Moe", "https://moe.example"
        MAX_TAG_LOOKUPS = 2

    posts_page = [{"id": 1, "file_url": "https://x/1.jpg", "tags": "tag_a tag_b tag_c tag_d"}]
    http = QueuedHttp(posts_page, [{"name": "tag_a", "type": 0}], [{"name": "tag_b", "type": 0}])
    moe = Moe(http, keyed_cfg())
    moe.search(["x"], page=1, limit=10)
    assert len(http.calls) == 3           # 1 search + only MAX_TAG_LOOKUPS(=2) tag lookups, not 4
