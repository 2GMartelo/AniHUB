import time
from types import SimpleNamespace

from anihub.core.db import Database
from anihub.sources.danbooru import Danbooru
from anihub.sources.engines import GelbooruEngine, MoebooruEngine
from anihub.ui.tag_widgets import NAME_ROLE, tag_line_edit


def names(edit):
    model = edit.tag_completer._model
    return [model.item(i).data(NAME_ROLE) for i in range(model.rowCount())]


def wait(qapp, cond, limit=5):
    end = time.time() + limit
    while time.time() < end and not cond():
        qapp.processEvents()
        time.sleep(0.01)


def test_the_site_search_box_suggests_library_tags_at_once_and_the_sites_tags_a_moment_later(qapp, tmp_path):
    db = Database(tmp_path / "l.db")
    asked = []

    def remote(token):
        asked.append(token)
        return [("blue_hair", 1200), ("light_blue_hair", 90)]

    edit = tag_line_edit(db, "search", remote=remote)
    edit.show()
    edit.setFocus()
    edit.setText("cat -blue_h")
    edit.textEdited.emit("cat -blue_h")
    assert names(edit) == []                                                    # nothing in the library, nothing to show yet
    wait(qapp, lambda: names(edit) == ["blue_hair", "light_blue_hair"])
    assert names(edit) == ["blue_hair", "light_blue_hair"] and asked == ["blue_h"]      # the token is the last word without its "-"
    completer = edit.tag_completer
    assert completer.pathFromIndex(completer._model.index(0, 0)) == "cat -blue_hair "  # the "-" and the words before it are kept
    edit.setText("a")
    edit.textEdited.emit("a")
    time.sleep(0.4)
    qapp.processEvents()
    assert asked == ["blue_h"]                                                  # a single letter is answered by the library only
    db.close()


def test_sources_ask_their_own_tag_lists():
    class Http:
        def __init__(self, data):
            self.data, self.calls = data, []

        def get_json(self, url, params=None, **kw):
            self.calls.append((url, params))
            return self.data

    danbooru = Danbooru(Http([{"value": "blue_hair", "post_count": 5}, {"value": "blue_hat", "post_count": 2}, "junk"]), SimpleNamespace(get=lambda *a: None))
    assert danbooru.suggest_tags("blue_ha") == [("blue_hair", 5), ("blue_hat", 2)]
    assert danbooru.http.calls[0][1]["search[query]"] == "blue_ha"

    class Moe(MoebooruEngine):
        name, title, base_url = "moe", "Moe", "https://moe.example"

    moe = Moe(Http([{"name": "blue_hair", "count": 21314}, {"name": "x"}]), SimpleNamespace(get=lambda *a: None))
    assert moe.suggest_tags("blue") == [("blue_hair", 21314), ("x", 0)] and moe.http.calls[0][0] == "https://moe.example/tag.json"

    class Gel(GelbooruEngine):
        name, title, api_url, page_url_tpl = "gel", "Gel", "https://gel.example/index.php", "x{id}"

    keyed = SimpleNamespace(get=lambda key, default=None: {"sources.gel.user_id": "1", "sources.gel.api_key": "k"}.get(key, default))
    gel = Gel(Http({"tag": [{"name": "blue_hair", "count": 7}]}), keyed)
    assert gel.suggest_tags("blue") == [("blue_hair", 7)] and gel.http.calls[0][1]["name_pattern"] == "%blue%"
    assert Gel(Http([]), SimpleNamespace(get=lambda key, default=None: default)).suggest_tags("blue") == []     # no API key: no request at all
    assert Danbooru(Http({"error": 1}), SimpleNamespace(get=lambda *a: None)).suggest_tags("x") == []
