import time
from types import SimpleNamespace

import pytest

from anihub.core.config import Config
from anihub.core.db import Database
from anihub.services.subscriptions import SubscriptionService, post_number
from anihub.sources.base import Post, SourceError


def post(i, rating="general", site="fake"):
    return Post(site, str(i), f"https://x/{i}.png", "https://x/t.png", rating=rating)


class FakeSource:
    title = "Fake"

    def __init__(self, ids_by_page):
        self.pages, self.calls, self.error = ids_by_page, [], None

    def search(self, tags, page, limit):
        self.calls.append((tuple(tags), page))
        if self.error:
            raise self.error
        return list(self.pages.get(page, []))


class FakeDownloads:
    def __init__(self):
        self.submitted = []

    def submit(self, posts):
        self.submitted.append([p.id for p in posts])
        return 1


@pytest.fixture
def env(tmp_path):
    cfg = Config.load(tmp_path / "c.json")
    db = Database(tmp_path / "d.db")
    src = FakeSource({1: [post(50), post(49), post(48)]})
    dl = FakeDownloads()
    svc = SubscriptionService(db, {"fake": src}, dl, cfg)
    return svc, db, src, dl, cfg


def test_subscribing_starts_from_now(env):
    svc, db, src, dl, _ = env
    sid = svc.subscribe("fake", "cat -dog", "Cats")
    row = db.subscription(sid)
    assert (row["name"], row["query"], row["last_seen_id"], row["new_count"]) == ("Cats", "cat -dog", 50, 0)
    assert src.calls[0] == (("cat", "-dog"), 1)
    assert db.subscription(svc.subscribe("fake", "x"))["name"] == "Fake: x"          # default name
    assert svc.check(sid).new == []                                                  # nothing is new yet


def test_check_counts_new_posts_and_respects_ratings(env):
    svc, db, src, dl, cfg = env
    sid = svc.subscribe("fake", "cat")
    src.pages = {1: [post(53, "explicit"), post(52), post(51), post(50), post(49)]}
    result = svc.check(sid)
    assert [p.id for p in result.new] == ["52", "51"]                                # 53 is hidden by the rating filter
    assert db.subscription(sid)["new_count"] == 2 and db.subscription(sid)["last_check"] and not db.subscription(sid)["last_error"]
    cfg.set("ratings.allowed", ["general", "explicit"], save=False)
    assert [p.id for p in svc.check(sid).new] == ["53", "52", "51"]
    assert svc.total_new() == 3


def test_check_reads_older_pages_until_it_meets_a_seen_post(env):
    svc, db, src, dl, _ = env
    sid = svc.subscribe("fake", "cat")
    src.pages = {1: [post(i) for i in range(90, 70, -1)], 2: [post(i) for i in range(70, 50, -1)], 3: [post(50), post(49)]}
    result = svc.check(sid)
    assert len(result.new) == 40 and [c[1] for c in src.calls[1:]] == [1, 2, 3]      # went to page 3 to find 50
    src.calls.clear()
    svc.mark_seen(sid, result.new)
    assert db.subscription(sid)["last_seen_id"] == 90 and db.subscription(sid)["new_count"] == 0
    assert svc.check(sid).new == [] and src.calls == [(("cat",), 1)]                 # one page is enough now


def test_auto_save_hands_new_posts_to_the_download_manager(env):
    svc, db, src, dl, _ = env
    sid = svc.subscribe("fake", "cat", auto_save=True)
    src.pages = {1: [post(52), post(51), post(50)]}
    result = svc.check(sid)
    assert dl.submitted == [["52", "51"]] and result.saved == 2
    assert db.subscription(sid)["last_seen_id"] == 52 and db.subscription(sid)["new_count"] == 0
    assert svc.check(sid).new == [] and len(dl.submitted) == 1                       # not downloaded twice


def test_mark_seen_without_posts_uses_the_current_new_ones(env):
    svc, db, src, dl, _ = env
    sid = svc.subscribe("fake", "cat")
    src.pages = {1: [post(60), post(55), post(50)]}
    svc.check(sid)
    svc.mark_seen(sid)
    assert db.subscription(sid)["last_seen_id"] == 60 and db.subscription(sid)["new_count"] == 0


def test_a_failing_site_records_the_error_and_keeps_the_count(env):
    svc, db, src, dl, _ = env
    a = svc.subscribe("fake", "cat")
    b = svc.subscribe("fake", "dog")
    src.pages = {1: [post(55), post(50)]}
    svc.check(a)
    src.error = SourceError("site is down")
    result = svc.check(a)
    assert result.error == "site is down" and result.new == []
    row = db.subscription(a)
    assert row["last_error"] == "site is down" and row["new_count"] == 1             # the earlier count is kept
    results = svc.check_all()                                                          # others still run
    assert len(results) == 2 and all(r.error for r in results)
    ghost = db.add_subscription("Gone", "no_such_source", "x")
    assert svc.check(ghost).error                                                      # an unknown source is an error, not a crash
    assert svc.check(999).new == []                                                    # unknown subscription: nothing


def test_disabled_subscriptions_are_skipped_and_polling_is_paced(env):
    svc, db, src, dl, cfg = env
    a = svc.subscribe("fake", "cat")
    b = svc.subscribe("fake", "dog")
    db.update_subscription(b, enabled=0)
    src.calls.clear()
    assert [r.sub_id for r in svc.check_all()] == [a] and len(src.calls) == 1
    assert len(svc.check_all(only_enabled=False)) == 2
    assert svc.is_due(now=1_000_000)
    cfg.set("subscriptions.last_poll", 1_000_000, save=False)
    assert not svc.is_due(now=1_000_000 + 59 * 60) and svc.is_due(now=1_000_000 + 61 * 60)
    db.update_subscription(a, new_count=4)
    db.update_subscription(b, new_count=9)
    assert svc.total_new() == 4                                                        # disabled ones do not count


def test_post_number_and_update_validation(env):
    _, db, _, _, _ = env
    assert post_number(post(7)) == 7 and post_number(Post("s", "abc", "u", "p")) == 0
    sid = db.add_subscription("n", "fake", "q")
    with pytest.raises(ValueError):
        db.update_subscription(sid, source="other")
    db.delete_subscription(sid)
    assert db.subscription(sid) is None


# --- UI -------------------------------------------------------------------------------------------------------

def wait_for(cond, limit=5.0):
    from PySide6.QtWidgets import QApplication

    end = time.time() + limit
    while time.time() < end and not cond():
        QApplication.processEvents()
        time.sleep(0.01)
    return cond()


def sub_ctx(tmp_path):
    from PySide6.QtCore import QBuffer, QIODevice
    from PySide6.QtGui import QColor, QImage

    cfg = Config.load(tmp_path / "c.json")
    db = Database(tmp_path / "d.db")
    src = FakeSource({1: [post(50), post(49)]})
    dl = FakeDownloads()
    img = QImage(20, 20, QImage.Format.Format_RGB32)
    img.fill(QColor("red"))
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    http = SimpleNamespace(get_bytes=lambda url: bytes(buf.data()))
    svc = SubscriptionService(db, {"fake": src}, dl, cfg)
    ctx = SimpleNamespace(cfg=cfg, db=db, sources={"fake": src}, subscriptions=svc, downloads=dl, http=http, media=None)
    return ctx, svc, src, dl, db


def test_view_lists_subscriptions_shows_new_posts_and_saves_them(qapp, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    from anihub.ui.subscriptions_view import SubscriptionsView

    ctx, svc, src, dl, db = sub_ctx(tmp_path)
    view = SubscriptionsView(ctx)
    assert not view.empty.isHidden() and view.details.isHidden()
    sid = svc.subscribe("fake", "cat", "Cats")
    src.pages = {1: [post(53), post(52), post(51), post(50)]}
    changes = []
    view.changed.connect(lambda: changes.append(1))
    view.reload()
    assert view.list.count() == 1 and not view.details.isHidden() and view.empty.isHidden()
    assert wait_for(lambda: view.grid.count() == 3)
    assert wait_for(lambda: db.subscription(sid)["new_count"] == 3) and changes
    view.reload()
    assert "●3" in view.list.item(0).text()
    assert wait_for(lambda: view.grid.count() == 3)                                    # reloading fetches the new posts again
    view.save_btn.click()
    assert dl.submitted == [["53", "52", "51"]]                                       # nothing selected: all the new ones
    assert db.subscription(sid)["last_seen_id"] == 53 and db.subscription(sid)["new_count"] == 0
    assert wait_for(lambda: view.grid.count() == 0)
    view.auto.setChecked(True)
    view.enabled.setChecked(False)
    row = db.subscription(sid)
    assert (row["auto_save"], row["enabled"]) == (1, 0)
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes))
    view.delete_btn.click()
    assert db.subscriptions() == [] and not view.empty.isHidden()


def test_view_checks_and_marks_seen_and_reports_errors(qapp, tmp_path):
    from anihub.ui.subscriptions_view import SubscriptionsView

    ctx, svc, src, dl, db = sub_ctx(tmp_path)
    sid = svc.subscribe("fake", "cat")
    view = SubscriptionsView(ctx)
    src.pages = {1: [post(60), post(50)]}
    view.check_btn.click()
    assert wait_for(lambda: db.subscription(sid)["new_count"] == 1 and view.check_btn.isEnabled())
    assert wait_for(lambda: view.grid.count() == 1)
    view.seen_btn.click()
    assert db.subscription(sid)["last_seen_id"] == 60 and db.subscription(sid)["new_count"] == 0
    src.error = SourceError("down")
    view.check_all_btn.click()
    assert wait_for(lambda: db.subscription(sid)["last_error"] == "down" and view.check_all_btn.isEnabled())
    view.reload()
    assert "down" in view.info.text()
    ctx.cfg.set("network.offline", True, save=False)
    view.load_new()
    assert view.grid.count() == 0 and view.status.text()
