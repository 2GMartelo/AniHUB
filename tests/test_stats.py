import time
from datetime import datetime
from types import SimpleNamespace

from anihub.core.db import Database
from anihub.services import stats


def ts(year, month, day=15):
    return datetime(year, month, day, 12).timestamp()


def make(tmp_path):
    db = Database(tmp_path / "t.db")
    add = lambda name, tags=(), **kw: db.add_item(kind=kw.pop("kind", "art"), path=f"arts/{name}.png", tags=list(tags), **kw)  # noqa: E731
    add("a", [("cat", "general"), ("miku", "artist")], size=1000, source_site="danbooru", added_at=ts(2026, 9), favorite=1, stars=4)
    add("b", [("cat", "general"), ("dog", "general"), ("miku", "artist")], size=2000, source_site="danbooru", added_at=ts(2026, 7), rating="explicit")
    add("c", [("cat", "general")], size=500, source_site="rule34", added_at=ts(2026, 9), rating="sensitive")
    trashed = add("d", [("cat", "general")], size=9999, source_site="danbooru", added_at=ts(2026, 9))
    db.update_fields(trashed, trashed_at=time.time())
    add("gen", kind="sd", size=300, added_at=ts(2025, 12))
    db.create_collection("C")
    db.create_category("K")
    db.novel_add(title="B1", path="n/1.txt", ext="txt", sha256="1", chapters=1, finished=1)
    db.novel_add(title="B2", path="n/2.txt", ext="txt", sha256="2", chapters=1)
    db.anime_upsert(media_id=1, title="X", status="CURRENT", progress=5)
    db.anime_upsert(media_id=2, title="Y", status="COMPLETED", progress=12)
    db.add_subscription("s", "danbooru", "cat")
    db.add_history([{"path": "sd/generated/1.png", "seed": 1, "model": "modelA", "prompt": "p", "negative": "", "params": {}, "backend": "main"},
                    {"path": "sd/generated/2.png", "seed": 2, "model": "modelA", "prompt": "p", "negative": "", "params": {}, "backend": "main"},
                    {"path": "sd/generated/3.png", "seed": 3, "model": "modelB", "prompt": "p", "negative": "", "params": {}, "backend": "main"}])
    return db


def test_month_keys_cross_year_boundaries():
    assert stats.month_keys(ts(2026, 2), 4) == ["2025-11", "2025-12", "2026-01", "2026-02"]
    assert stats.month_keys(ts(2026, 9), 1) == ["2026-09"]


def test_human_size():
    assert stats.human_size(0) == "0 B" and stats.human_size(1536) == "1.5 KB" and stats.human_size(5 * 1024**3) == "5.0 GB"


def test_collect_counts_everything_and_ignores_the_trash(tmp_path):
    s = stats.collect(make(tmp_path), months=6, now=ts(2026, 9, 20))
    assert (s.items, s.total_bytes, s.favorites, s.rated, s.trashed) == (4, 3800, 1, 1, 1)
    assert s.by_kind == {"art": 3, "sd": 1} and s.by_rating == {"general": 2, "explicit": 1, "sensitive": 1}
    assert s.by_source[0] == ("danbooru", 2) and ("rule34", 1) in s.by_source and ("?", 1) in s.by_source
    assert s.top_tags[0] == ("cat", 3) and ("dog", 1) in s.top_tags and all(name != "miku" for name, _ in s.top_tags)
    assert s.top_artists == [("miku", 2)]
    assert s.tags_total == 3 and (s.collections, s.categories, s.subscriptions) == (1, 1, 1)
    assert (s.novels, s.novels_finished) == (2, 1)
    assert s.anime_by_status == {"CURRENT": 1, "COMPLETED": 1} and s.episodes_watched == 17
    assert [k for k, _ in s.per_month] == ["2026-04", "2026-05", "2026-06", "2026-07", "2026-08", "2026-09"]
    assert dict(s.per_month)["2026-09"] == 2 and dict(s.per_month)["2026-07"] == 1 and dict(s.per_month)["2026-08"] == 0
    assert "2025-12" not in dict(s.per_month)                                        # older than the window
    assert s.generations == 3 and s.generations_by_model[0] == ("modelA", 2) and ("modelB", 1) in s.generations_by_model


def test_empty_library_gives_zeros(tmp_path):
    s = stats.collect(Database(tmp_path / "e.db"))
    assert s.items == 0 and s.total_bytes == 0 and s.top_tags == [] and len(s.per_month) == 12 and not any(v for _, v in s.per_month)
    assert s.generations == 0 and s.generations_by_model == []


def test_dashboard_renders_charts_and_cards(qapp, tmp_path):
    from PySide6.QtGui import QImage

    from anihub.ui import theme
    from anihub.ui.stats_dialog import BarChart, StatsDialog

    theme.apply_theme(qapp, "dark")
    db = make(tmp_path)
    ctx = SimpleNamespace(db=db)
    dlg = StatsDialog(ctx)
    end = time.time() + 5
    while time.time() < end and dlg.body.count() < 5:
        qapp.processEvents()
        time.sleep(0.01)
    assert dlg.body.count() >= 5
    charts = dlg.findChildren(BarChart)
    assert len(charts) == 6
    for chart in charts:
        chart.resize(500, chart.minimumHeight())
        image = QImage(chart.size(), QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(0)
        chart.render(image)
        assert any(image.pixelColor(x, y).alpha() for x in range(0, image.width(), 7) for y in range(0, image.height(), 5)) or not chart.data
    empty = BarChart([])
    empty.resize(300, 100)
    empty.grab()                                                                      # an empty chart must paint too
    dlg.close()
