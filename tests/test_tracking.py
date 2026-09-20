import time
from types import SimpleNamespace

from anihub.core.i18n import tr
from anihub.services.suwayomi import SuwayomiApi, oauth_callback

ANILIST = {"id": 2, "name": "AniList", "isLoggedIn": True, "isTokenExpired": False, "authUrl": "https://anilist.co/x", "icon": "",
           "scores": ["0", "5", "10"], "statuses": [{"name": "Reading", "value": 1}, {"name": "Completed", "value": 2}],
           "supportsTrackDeletion": True}
MAL = {**ANILIST, "id": 1, "name": "MyAnimeList", "isLoggedIn": False}
KITSU = {**ANILIST, "id": 3, "name": "Kitsu", "isLoggedIn": False, "authUrl": None}
RECORD = {"id": 10, "trackerId": 2, "remoteId": "55", "title": "Berserk", "status": 1, "lastChapterRead": 3.0, "totalChapters": 100,
          "score": 5.0, "displayScore": "5", "remoteUrl": "https://anilist.co/manga/55"}


def wait(qapp, cond, limit=5):
    end = time.time() + limit
    while time.time() < end and not cond():
        qapp.processEvents()
        time.sleep(0.01)


class FakeApi:
    """Stands in for SuwayomiApi: records the calls the dialogs make."""

    def __init__(self, trackers, records=()):
        self._trackers, self._records, self.calls = trackers, list(records), []

    def trackers(self):
        return self._trackers

    def track_records(self, manga_id):
        return self._records

    def track_search(self, tracker_id, query):
        self.calls.append(("search", tracker_id, query))
        return [{"remoteId": "77", "title": "Berserk (found)", "coverUrl": "", "summary": "", "publishingStatus": "Ongoing",
                 "publishingType": "Manga", "totalChapters": 364, "trackingUrl": ""}]

    def track_bind(self, manga_id, tracker_id, remote_id):
        self.calls.append(("bind", manga_id, tracker_id, remote_id))
        self._records = [{**RECORD, "remoteId": remote_id}]
        return self._records[0]

    def track_update(self, record_id, **kw):
        self.calls.append(("update", record_id, kw))

    def track_unbind(self, record_id, delete_remote=False):
        self.calls.append(("unbind", record_id, delete_remote))
        self._records = []

    def tracker_login_oauth(self, tracker_id, callback):
        self.calls.append(("oauth", tracker_id, callback))
        return True

    def tracker_login_credentials(self, tracker_id, username, password):
        self.calls.append(("creds", tracker_id, username, password))
        return True

    def tracker_logout(self, tracker_id):
        self.calls.append(("logout", tracker_id))


def test_oauth_callback_wraps_bare_tokens_only():
    assert oauth_callback("AniList", " mihon://anilist-auth#access_token=abc&x=1 ") == "mihon://anilist-auth#access_token=abc&x=1"
    assert oauth_callback("AniList", "abc123").endswith("#access_token=abc123")
    assert oauth_callback("MyAnimeList", "codeXYZ").endswith("?code=codeXYZ")
    assert oauth_callback("MyAnimeList", "") == ""


def api_with(gql_reply, **cfg):
    api = SuwayomiApi.__new__(SuwayomiApi)
    api.cfg = SimpleNamespace(get=lambda key, default=None: cfg.get(key.replace(".", "_"), default))
    api.sent = []

    def gql(query, variables=None, timeout=None):
        api.sent.append((query, variables))
        if isinstance(gql_reply, Exception):
            raise gql_reply
        return gql_reply

    api.gql = gql
    return api


def test_tracker_api_builds_the_expected_calls():
    api = api_with({"bindTrack": {"trackRecord": RECORD}})
    assert api.track_bind(4, 2, 55) == RECORD
    assert api.sent[-1][1] == {"i": {"mangaId": 4, "trackerId": 2, "remoteId": "55"}}
    api = api_with({"updateTrack": {"trackRecord": RECORD}})
    api.track_update(10, status=2, last_chapter_read=5.5)
    assert api.sent[-1][1] == {"i": {"recordId": 10, "status": 2, "lastChapterRead": 5.5}}     # unset fields stay out
    api = api_with({"loginTrackerOAuth": {"isLoggedIn": True}})
    assert api.tracker_login_oauth(2, "cb") is True and api.sent[-1][1] == {"t": 2, "c": "cb"}
    api = api_with({"unbindTrack": {"clientMutationId": None}})
    api.track_unbind(10, True)
    assert api.sent[-1][1] == {"i": {"recordId": 10, "deleteRemoteTrack": True}}


def test_automatic_sync_never_raises_and_can_be_switched_off():
    api = api_with(RuntimeError("no tracker"))
    api.sync_tracking(4)                                        # swallowed
    assert api.sent, "the mutation was attempted"
    off = api_with({}, manga_track_auto=False)
    off.sync_tracking(4)
    assert off.sent == []


def test_account_dialog_logs_in_with_the_pasted_address_and_credentials(qapp):
    from anihub.ui.manga_tracking import TrackerAccountsDialog

    api = FakeApi([MAL, ANILIST, KITSU])
    dlg = TrackerAccountsDialog(api)
    wait(qapp, lambda: dlg.list.count() == 3)
    assert dlg.list.item(0).text().startswith("○") and dlg.list.item(1).text().startswith("●")
    dlg.list.setCurrentRow(0)
    assert not dlg.pages.isHidden() and dlg.pages.currentIndex() == 0 and dlg.logout_btn.isHidden()
    dlg.paste.setText("mihon://mal-auth?code=abc")
    dlg._login_oauth()
    wait(qapp, lambda: api.calls)
    assert api.calls[0] == ("oauth", 1, "mihon://mal-auth?code=abc")
    wait(qapp, lambda: dlg.list.count() == 3)
    dlg.list.setCurrentRow(2)                                    # Kitsu has no OAuth page: credentials
    assert dlg.pages.currentIndex() == 1
    dlg.user.setText("ann")
    dlg.password.setText("pw")
    dlg._login_credentials()
    wait(qapp, lambda: len(api.calls) == 2)
    assert api.calls[1] == ("creds", 3, "ann", "pw")
    wait(qapp, lambda: dlg.list.count() == 3)
    dlg.list.setCurrentRow(1)
    assert not dlg.logout_btn.isHidden() and dlg.pages.isHidden()
    dlg._logout()
    wait(qapp, lambda: len(api.calls) == 3)
    assert api.calls[2] == ("logout", 2)
    dlg.close()


def cards_of(dlg):
    return [dlg.body.itemAt(i).widget() for i in range(dlg.body.count()) if dlg.body.itemAt(i).widget() is not None]


def test_track_dialog_binds_edits_and_unbinds(qapp, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    from anihub.ui.manga_tracking import TrackDialog

    api = FakeApi([MAL, ANILIST])
    dlg = TrackDialog(api, {"id": 4, "title": "Berserk"})
    wait(qapp, lambda: cards_of(dlg))
    cards = cards_of(dlg)
    assert len(cards) == 1 and cards[0].title() == "AniList"                  # only trackers you are signed in to
    card = cards[0]
    assert card.query.text() == "Berserk"
    card._search()
    wait(qapp, lambda: card.results.count() == 1)
    card.results.setCurrentRow(0)
    card._bind()
    wait(qapp, lambda: ("bind", 4, 2, "77") in api.calls)
    wait(qapp, lambda: cards_of(dlg) and hasattr(cards_of(dlg)[0], "status") and cards_of(dlg)[0] is not card)
    card = cards_of(dlg)[0]
    card.status.setCurrentIndex(card.status.findData(2))
    card.chapters.setValue(12)
    card.score.setCurrentIndex(card.score.findData("10"))
    card._save()
    wait(qapp, lambda: any(c[0] == "update" for c in api.calls))
    update = next(c for c in api.calls if c[0] == "update")
    assert update[1] == 10 and update[2] == {"status": 2, "last_chapter_read": 12.0, "score": "10"}
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.No)
    card._unbind()
    wait(qapp, lambda: any(c[0] == "unbind" for c in api.calls))
    assert ("unbind", 10, False) in api.calls                                 # "No" = keep the remote entry
    dlg.close()


def test_track_dialog_explains_when_nothing_is_signed_in(qapp):
    from anihub.ui.manga_tracking import TrackDialog

    dlg = TrackDialog(FakeApi([MAL, KITSU]), {"id": 4, "title": "X"})
    wait(qapp, lambda: dlg.message.text() == tr("track.none_signed"))
    assert dlg.message.text() == tr("track.none_signed") and not cards_of(dlg)
    dlg.close()
