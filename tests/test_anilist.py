from datetime import date

import pytest

from anihub.core.config import Config
from anihub.core.db import Database
from anihub.net.http import HttpError
from anihub.services.anilist import (
    AniList, AniListError, clamp_progress, current_season, next_status, normalize_media, shift_season,
)

RAW = {"id": 7, "title": {"romaji": "Sousou no Frieren", "english": "Frieren", "native": "葬送のフリーレン"},
       "coverImage": {"large": "https://img/7.jpg"}, "format": "TV", "episodes": 28, "status": "RELEASING",
       "season": "FALL", "seasonYear": 2023, "averageScore": 91, "genres": ["Fantasy"], "description": "A<br>B <i>x</i>",
       "siteUrl": "https://anilist.co/anime/7", "isAdult": False,
       "nextAiringEpisode": {"episode": 5, "airingAt": 1700000000}, "studios": {"nodes": [{"name": "Madhouse"}]}}


class FakeHttp:
    """post_json returns queued replies and remembers what was sent."""

    def __init__(self, *replies):
        self.replies, self.sent = list(replies), []

    def post_json(self, url, payload, headers=None, interval_ms=None):
        self.sent.append((payload, headers))
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


@pytest.fixture
def make(tmp_path):
    def build(*replies, token="tok"):
        cfg = Config.load(tmp_path / "c.json")
        if token:
            cfg.set("tracker.anilist.token", token, save=False)
            cfg.set("tracker.anilist.user_id", 42, save=False)
        db = Database(tmp_path / "t.db")
        http = FakeHttp(*replies)
        return AniList(http, cfg, db), http, db
    return build


def test_seasons_wrap_around_years():
    assert current_season(date(2026, 2, 1)) == ("WINTER", 2026) and current_season(date(2026, 9, 20)) == ("FALL", 2026)
    assert current_season(date(2026, 12, 5)) == ("WINTER", 2027) and current_season(date(2026, 3, 1)) == ("SPRING", 2026)
    assert current_season(date(2026, 8, 31)) == ("SUMMER", 2026) and current_season(date(2026, 11, 30)) == ("FALL", 2026)
    assert shift_season("FALL", 2026, 1) == ("WINTER", 2027) and shift_season("WINTER", 2026, -1) == ("FALL", 2025)
    assert shift_season("SPRING", 2026, -6) == ("FALL", 2024)


def test_normalize_media_flattens_and_cleans():
    m = normalize_media(RAW)
    assert m["title"] == "Frieren" and m["native"] == "葬送のフリーレン" and m["studio"] == "Madhouse"
    assert m["description"] == "A\nB x" and m["next_episode"] == 5 and m["cover"] == "https://img/7.jpg"
    bare = normalize_media({"id": 1, "title": {"romaji": "R"}})
    assert bare["title"] == "R" and bare["genres"] == [] and bare["next_episode"] is None


def test_progress_rules():
    assert clamp_progress(30, 28) == 28 and clamp_progress(-3, 28) == 0 and clamp_progress(99, None) == 99
    assert next_status("CURRENT", 28, 28) == "COMPLETED" and next_status("PLANNING", 1, 12) == "CURRENT"
    assert next_status("CURRENT", 3, 12) == "CURRENT" and next_status("PLANNING", 0, 12) == "PLANNING"


def test_season_query_hides_adult_unless_allowed(make):
    reply = {"data": {"Page": {"pageInfo": {"hasNextPage": True}, "media": [RAW]}}}
    api, http, _ = make(reply, reply, token="")
    shows, more = api.season("FALL", 2026)
    assert shows[0]["id"] == 7 and more
    assert http.sent[0][0]["variables"] == {"page": 1, "season": "FALL", "year": 2026, "adult": False}
    assert http.sent[0][1].get("Authorization") is None                       # public query: no token needed
    api.season("FALL", 2026, allow_adult=True)
    assert "adult" not in http.sent[1][0]["variables"]                         # no filter at all


def test_graphql_errors_become_anilist_errors(make):
    api, _, _ = make({"errors": [{"message": "Too many"}]}, HttpError(500, "boom"), token="")
    with pytest.raises(AniListError, match="Too many"):
        api.season("FALL", 2026)
    with pytest.raises(AniListError):
        api.search("x")


def test_track_stores_locally_and_marks_unsynced(make):
    api, http, db = make(token="")
    media = normalize_media(RAW)
    api.track(media, "PLANNING")
    row = db.anime_get(7)
    assert (row["status"], row["progress"], row["episodes"], row["synced"]) == ("PLANNING", 0, 28, 0)
    api.set_progress(7, 1)
    assert db.anime_get(7)["status"] == "CURRENT" and db.anime_get(7)["progress"] == 1
    api.set_progress(7, 99)
    row = db.anime_get(7)
    assert (row["progress"], row["status"]) == (28, "COMPLETED")
    api.set_score(7, 250)
    assert db.anime_get(7)["score"] == 100
    assert http.sent == []                                                     # nothing went out: not signed in
    api.track(media, "COMPLETED")
    assert db.anime_get(7)["progress"] == 28
    api.remove(7)
    assert db.anime_get(7) is None


def test_push_sends_unsynced_entries_and_remembers_entry_ids(make):
    api, http, db = make({"data": {"SaveMediaListEntry": {"id": 555, "status": "CURRENT", "progress": 3, "score": 80}}})
    api.track(normalize_media(RAW), "CURRENT", progress=3, score=80)
    assert api.push() == 1
    variables = http.sent[0][0]["variables"]
    assert variables == {"mediaId": 7, "status": "CURRENT", "progress": 3, "score": 80}
    assert http.sent[0][1]["Authorization"] == "Bearer tok"
    row = db.anime_get(7)
    assert row["entry_id"] == 555 and row["synced"] == 1
    assert api.push() == 0                                                     # nothing left to send


def test_pull_merges_but_keeps_unsent_local_changes(make):
    def entry(media_id, status, progress, updated):
        raw = {**RAW, "id": media_id, "title": {"romaji": f"Show {media_id}"}}
        return {"id": 900 + media_id, "mediaId": media_id, "status": status, "progress": progress, "score": 70,
                "updatedAt": updated, "media": raw}

    reply = {"data": {"MediaListCollection": {"lists": [{"entries": [entry(1, "COMPLETED", 12, 1000), entry(2, "CURRENT", 5, 1000)]}]}}}
    api, _, db = make(reply)
    api.track({**normalize_media(RAW), "id": 2, "title": "Local two"}, "DROPPED", progress=1)      # local, not sent
    assert api.pull() == 1                                                     # only entry 1 is new to us
    assert db.anime_get(1)["status"] == "COMPLETED" and db.anime_get(1)["synced"] == 1 and db.anime_get(1)["score"] == 70
    assert db.anime_get(2)["status"] == "DROPPED" and db.anime_get(2)["synced"] == 0


def test_sign_in_verifies_the_token_and_keeps_the_old_one_on_failure(make):
    api, http, _ = make({"data": {"Viewer": {"id": 9, "name": "Ann"}}}, {"errors": [{"message": "Invalid token"}]}, token="")
    assert api.authorize_url(" 123 ").endswith("client_id=123&response_type=token")
    assert api.sign_in(" abc ") == {"id": 9, "name": "Ann"}
    assert api.token == "abc" and api.cfg.get("tracker.anilist.user") == "Ann"
    with pytest.raises(AniListError):
        api.sign_in("bad")
    assert api.token == "abc"                                                  # the good token survived
    api.sign_out()
    assert not api.logged_in
    with pytest.raises(AniListError):
        api.sign_in("  ")


def test_airing_text_and_score_label(qapp):
    from anihub.core.i18n import set_language
    from anihub.services.anilist import format_airing
    from anihub.ui.anime_page import airing_text, score_label

    set_language("en")
    assert format_airing(None, 1, 0) is None and format_airing(3, None, 0) is None
    assert format_airing(3, 1000, 400) == (3, 600.0)
    assert airing_text(None, None) == ""
    assert airing_text(5, 1000 + 2 * 86400 + 3 * 3600, 1000) == "Episode 5 in 2 d 3 h"
    assert airing_text(5, 1000 + 90 * 60, 1000) == "Episode 5 in 1 h 30 min"
    assert airing_text(5, 1000 + 20 * 60, 1000) == "Episode 5 in 20 min"
    assert airing_text(5, 900, 1000) == "Episode 5 is airing now"
    assert score_label(0) == "—" and score_label(85) == "8.5" and score_label(80) == "8" and score_label(100) == "10"
    set_language("ru")


def anime_ctx(make, tmp_path, *replies, token=""):
    from types import SimpleNamespace

    api, http, db = make(*replies, token=token)
    media = SimpleNamespace(get=lambda url: (_ for _ in ()).throw(RuntimeError("no network in tests")))
    ctx = SimpleNamespace(cfg=api.cfg, db=db, anilist=api, media=media, allowed_ratings=lambda: ["general"])
    return ctx, api, http, db


def test_my_list_tab_counts_bumps_and_removes(qapp, make, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    from anihub.ui.anime_page import MyListTab

    ctx, api, http, db = anime_ctx(make, tmp_path)
    api.track(normalize_media(RAW), "PLANNING")
    api.track({**normalize_media(RAW), "id": 8, "title": "Other", "episodes": 2}, "CURRENT", progress=1)
    tab = MyListTab(ctx)
    assert tab.tree.topLevelItemCount() == 2 and tab.filter.count() == 3            # All + two statuses present
    tab.tree.topLevelItem(0).setSelected(True)
    first = tab.tree.topLevelItem(0).data(0, 0x100)
    tab.plus_btn.click()
    assert db.anime_get(first)["progress"] >= 1
    other = 8
    tab.tree.clearSelection()
    for i in range(tab.tree.topLevelItemCount()):
        if tab.tree.topLevelItem(i).data(0, 0x100) == other:
            tab.tree.topLevelItem(i).setSelected(True)
    tab.plus_btn.click()
    assert db.anime_get(other)["status"] == "COMPLETED" and db.anime_get(other)["progress"] == 2   # last episode completes it
    tab._set_score(90)
    assert db.anime_get(other)["score"] == 90
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    tab.remove_btn.click()
    assert db.anime_get(other) is None
    assert not tab.plus_btn.isEnabled() or tab.tree.selectedItems()


def test_sync_button_needs_sign_in_then_pushes_and_pulls(qapp, make, tmp_path):
    import time as _t

    from anihub.ui.anime_page import MyListTab

    save = {"data": {"SaveMediaListEntry": {"id": 5, "status": "PLANNING", "progress": 0, "score": 0}}}
    pull = {"data": {"MediaListCollection": {"lists": []}}}
    ctx, api, http, db = anime_ctx(make, tmp_path, save, pull, token="tok")
    api.track(normalize_media(RAW), "PLANNING")
    tab = MyListTab(ctx)
    tab.sync()
    end = _t.time() + 5
    while _t.time() < end and db.anime_get(7)["synced"] == 0:
        qapp.processEvents()
        _t.sleep(0.01)
    assert db.anime_get(7)["synced"] == 1 and db.anime_get(7)["entry_id"] == 5
    ctx2, api2, _, _ = anime_ctx(make, tmp_path, token="")
    tab2 = MyListTab(ctx2)
    tab2.sync()
    assert "AniList" in tab2.message.text()


def test_season_tab_navigation_and_quick_add(qapp, make, tmp_path):
    from anihub.ui.anime_page import SeasonTab

    ctx, api, http, db = anime_ctx(make, tmp_path)
    tab = SeasonTab(ctx)
    season, year = tab.season, tab.year
    tab._move(1)
    assert (tab.season, tab.year) != (season, year)
    tab._move(-1)
    assert (tab.season, tab.year) == (season, year)
    media = normalize_media(RAW)
    tab._quick_add(media, "PLANNING")
    assert db.anime_get(7)["status"] == "PLANNING" and "Frieren" in tab.status.text()
    assert tab._mark(media).startswith("✓")


def test_detail_dialog_adds_and_edits_the_entry(qapp, make, tmp_path):
    from anihub.core.i18n import tr
    from anihub.ui.anime_page import AnimeDetail

    ctx, api, http, db = anime_ctx(make, tmp_path)
    media = normalize_media(RAW)
    dlg = AnimeDetail(ctx, media)
    assert dlg.status.currentData() == "PLANNING" and dlg.save_btn.text() == tr("anime.add")
    dlg.status.setCurrentIndex(dlg.status.findData("CURRENT"))
    dlg.progress.setValue(4)
    dlg.score.setCurrentIndex(dlg.score.findData(80))
    dlg._save()
    row = db.anime_get(7)
    assert (row["status"], row["progress"], row["score"]) == ("CURRENT", 4, 80)
    dlg._remove()
    assert db.anime_get(7) is None
    dlg.close()
