from pathlib import Path
from types import SimpleNamespace

import pytest

from anihub.core.config import Config
from anihub.core.db import Database
from anihub.services.anilist import AniList, normalize_media
from anihub.services.anime_watch import WatchService, is_watched
from anihub.sources.anime import build_anime_sources, load_plugins
from anihub.sources.anime.base import AnimeEntry, AnimeSourceError, Episode
from anihub.sources.anime.local import LocalAnime, episode_number

MEDIA = normalize_media({"id": 7, "title": {"romaji": "Frieren"}, "episodes": 12, "coverImage": {"large": "u"}, "format": "TV"})


def test_episode_numbers_ignore_quality_tags():
    assert episode_number("Show - 05 [1080p]") == 5 and episode_number("[Group] Show - 12 (BD 1080p HEVC) [ABCD1234]") == 12
    assert episode_number("Show S02E07 720p") == 7 and episode_number("Show ep3") == 3 and episode_number("Show 8.5") == 8.5
    assert episode_number("Show - Серия 4") == 4 and episode_number("Movie 1080p x264") is None
    assert episode_number("Show 2024 - 03") == 3 or episode_number("Show 2024 - 03") == 2024        # last bare number wins


def make_local(tmp_path, files):
    root = tmp_path / "anime"
    for rel in files:
        f = root / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(b"x")
    return LocalAnime(None, None, root), root


def test_local_source_lists_titles_and_orders_episodes(tmp_path):
    src, _ = make_local(tmp_path, ["Frieren/Frieren - 10.mkv", "Frieren/Frieren - 02.mkv", "Frieren/notes.txt", "Bleach/Bleach 01.mp4"])
    entries, more = src.search("")
    assert [e.title for e in entries] == ["Bleach", "Frieren"] and not more
    assert [e.title for e in src.search("frie")[0]] == ["Frieren"] and src.search("", page=2) == ([], False)
    eps = src.episodes(AnimeEntry("Frieren", "Frieren"))
    assert [e.number for e in eps] == [2, 10] and eps[0].id == "Frieren - 02.mkv"
    stream = src.streams(AnimeEntry("Frieren", "Frieren"), eps[1])[0]
    assert Path(stream.url).name == "Frieren - 10.mkv" and stream.label == "MKV" and not stream.headers


def test_local_source_falls_back_to_order_and_reports_problems(tmp_path):
    src, _ = make_local(tmp_path, ["Odd/alpha.mkv", "Odd/beta.mkv", "Dup/Show 01 a.mkv", "Dup/Show 01 b.mkv"])
    assert [e.number for e in src.episodes(AnimeEntry("Odd", "Odd"))] == [1, 2]            # no numbers: file order
    assert [e.number for e in src.episodes(AnimeEntry("Dup", "Dup"))] == [1, 2]            # repeated numbers: file order
    with pytest.raises(AnimeSourceError):
        src.episodes(AnimeEntry("Missing", "Missing"))
    with pytest.raises(AnimeSourceError):
        src.streams(AnimeEntry("Odd", "Odd"), Episode("gone.mkv", 1))
    assert LocalAnime(None, None, tmp_path / "nothing").search("")[0] == []


PLUGIN = '''
from anihub.sources.anime.base import AnimeSource, AnimeEntry, Episode, Stream

class Demo(AnimeSource):
    name = "demo"
    title = "Demo site"
    def search(self, query, page=1):
        return [AnimeEntry("1", "Demo " + query)], False
    def episodes(self, entry):
        return [Episode("a", 1)]
    def streams(self, entry, episode):
        return [Stream("https://x/y.m3u8", "auto")]
'''


def test_plugins_are_loaded_and_broken_ones_are_skipped(tmp_path):
    folder = tmp_path / "plugins"
    folder.mkdir()
    (folder / "demo.py").write_text(PLUGIN, encoding="utf-8")
    (folder / "broken.py").write_text("this is not python (", encoding="utf-8")
    (folder / "noclass.py").write_text("X = 1", encoding="utf-8")
    assert [c.name for c in load_plugins(folder)] == ["demo"]
    sources = build_anime_sources(None, None, tmp_path / "anime", folder)
    assert list(sources) == ["local", "demo"] and sources["demo"].search("x")[0][0].title == "Demo x"
    (folder / "clash.py").write_text(PLUGIN.replace("Demo", "Demo2"), encoding="utf-8")          # same name "demo": ignored
    assert list(build_anime_sources(None, None, tmp_path / "anime", folder)) == ["local", "demo"]
    assert load_plugins(tmp_path / "missing") == []


def test_watched_rule():
    assert is_watched(1300_000, 1400_000) and is_watched(1_300_000, 1_380_000) and not is_watched(600_000, 1_400_000)
    assert not is_watched(10, 0)


class FakeHttp:
    def post_json(self, *a, **k):
        raise AssertionError("must stay offline")


@pytest.fixture
def watch(tmp_path):
    cfg = Config.load(tmp_path / "c.json")
    db = Database(tmp_path / "d.db")
    api = AniList(FakeHttp(), cfg, db)
    return WatchService(db, api), db


def eps(n):
    return [Episode(f"e{i}", float(i)) for i in range(1, n + 1)]


def test_positions_resume_and_watched_flow(watch):
    svc, db = watch
    e1, e2 = eps(2)
    assert svc.resume_ms("s", "t", e1) == 0
    assert svc.record("s", "t", e1, 5_000, 1_400_000) is False and svc.resume_ms("s", "t", e1) == 0     # too early to resume
    svc.record("s", "t", e1, 600_000, 1_400_000)
    assert svc.resume_ms("s", "t", e1) == 600_000
    assert svc.record("s", "t", e1, 1_350_000, 1_400_000) is True                                    # completed just now
    assert svc.record("s", "t", e1, 1_360_000, 1_400_000) is False                                   # ...only once
    assert svc.resume_ms("s", "t", e1) == 0 and svc.positions("s", "t")["e1"]["watched"]
    assert svc.next_episode("s", "t", [e1, e2]) == e2
    svc.mark("s", "t", e2, True)
    assert svc.next_episode("s", "t", [e1, e2]) == e2                                                # all watched: the last one
    svc.mark("s", "t", e2, False)
    assert svc.next_episode("s", "t", [e1, e2]) == e2 and not svc.positions("s", "t")["e2"]["watched"]


def test_watching_a_linked_title_feeds_the_watch_list(watch):
    svc, db = watch
    e1, e2, e3 = eps(3)
    svc.record("s", "t", e1, 1_400_000, 1_400_000)
    assert db.anime_get(7) is None                                            # not linked: the list is untouched
    svc.link("s", "t", MEDIA)
    assert svc.linked_media("s", "t")["id"] == 7
    svc.record("s", "t", e2, 1_390_000, 1_400_000)
    row = db.anime_get(7)
    assert (row["status"], row["progress"]) == ("CURRENT", 2)                  # first watched episode adds the show
    svc.mark("s", "t", e1, True)                                               # an older episode never lowers the progress
    assert db.anime_get(7)["progress"] == 2
    svc.mark("s", "t", Episode("e12", 12.0), True)
    assert (db.anime_get(7)["progress"], db.anime_get(7)["status"]) == (12, "COMPLETED")
    svc.link("s", "t", None)
    assert svc.linked_media("s", "t") is None


def test_positions_are_per_title(watch):
    svc, _ = watch
    e1 = eps(1)[0]
    svc.record("local", "A", e1, 1_400_000, 1_400_000)
    assert svc.positions("local", "B") == {} and svc.positions("other", "A") == {}


# --- UI -------------------------------------------------------------------------------------------------------

def wait(qapp, cond, limit=5):
    import time

    end = time.time() + limit
    while time.time() < end and not cond():
        qapp.processEvents()
        time.sleep(0.01)


def watch_ctx(tmp_path, files=(), plugin_sources=()):
    from anihub.core.paths import LibraryPaths

    paths = LibraryPaths(tmp_path / "lib")
    paths.ensure()
    for rel in files:
        f = paths.anime / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(b"not really a video")
    cfg = Config.load(tmp_path / "c.json")
    db = Database(paths.db_file)
    api = AniList(FakeHttp(), cfg, db)
    sources = {"local": LocalAnime(None, cfg, paths.anime)}
    for s in plugin_sources:
        sources[s.name] = s
    ctx = SimpleNamespace(cfg=cfg, db=db, paths=paths, anilist=api, watch=WatchService(db, api), anime_sources=sources,
                          media=SimpleNamespace(get=lambda url: Path(url)), allowed_ratings=lambda: ["general"])
    return ctx


def test_player_helpers():
    from anihub.sources.anime.base import Stream
    from anihub.ui.anime_player import external_command, fmt, stream_url

    assert fmt(65_000) == "1:05" and fmt(3_725_000) == "1:02:05" and fmt(-5) == "0:00"
    assert stream_url(Stream(r"C:\a\b.mkv")).isLocalFile() and stream_url(Stream("https://x/y.m3u8")).scheme() == "https"
    s = Stream("https://x/y.m3u8", headers={"Referer": "https://site/"})
    assert external_command("C:/mpv/mpv.exe", s) == ["C:/mpv/mpv.exe", "--http-header-fields=Referer: https://site/", "https://x/y.m3u8"]
    assert external_command("vlc.exe", s)[1] == "--http-referrer=https://site/" and external_command("x.exe", Stream("u")) == ["x.exe", "u"]


def test_watch_tab_lists_local_shows_and_episodes(qapp, tmp_path):
    from PySide6.QtCore import Qt

    from anihub.ui.anime_watch import WatchTab

    ctx = watch_ctx(tmp_path, ["Frieren/Frieren - 01.mkv", "Frieren/Frieren - 02.mkv", "Bleach/Bleach 1.mkv"])
    tab = WatchTab(ctx)
    tab.ensure_loaded()
    wait(qapp, lambda: tab.grid.count() == 2)
    assert tab.grid.count() == 2 and not tab.folder_btn.isHidden()
    entry = tab.grid.item(1).data(Qt.ItemDataRole.UserRole)
    assert entry.title == "Frieren"
    tab.select_entry(entry)
    wait(qapp, lambda: tab.tree.topLevelItemCount() == 2)
    assert [tab.tree.topLevelItem(i).text(0) for i in range(2)] == ["1", "2"] and not tab.details.isHidden()
    tab.tree.topLevelItem(1).setSelected(True)
    tab._mark(True)
    assert tab.tree.topLevelItem(1).text(2).startswith("✓")
    assert ctx.watch.positions("local", "Frieren")["Frieren - 02.mkv"]["watched"]
    tab.tree.clearSelection()
    tab._mark(False)                                                             # nothing selected: nothing changes
    tab.query.setText("bleach")
    tab.search()
    wait(qapp, lambda: tab.grid.count() == 1)
    assert tab.grid.count() == 1


def test_watch_tab_reports_an_empty_local_folder_and_links(qapp, tmp_path, monkeypatch):
    from PySide6.QtCore import Qt

    from anihub.ui import anime_watch
    from anihub.ui.anime_watch import WatchTab

    ctx = watch_ctx(tmp_path)
    tab = WatchTab(ctx)
    tab.ensure_loaded()
    wait(qapp, lambda: "anime" in tab.status.text().lower() or "папк" in tab.status.text())
    assert tab.grid.count() == 0 and "папк" in tab.status.text()
    ctx = watch_ctx(tmp_path / "b", ["Show/Show 01.mkv"])
    tab = WatchTab(ctx)
    tab.search()
    wait(qapp, lambda: tab.grid.count() == 1)
    tab.select_entry(tab.grid.item(0).data(Qt.ItemDataRole.UserRole))

    class Dlg:
        chosen = MEDIA

        def __init__(self, *a):
            pass

        def exec(self):
            return True

    monkeypatch.setattr(anime_watch, "LinkDialog", Dlg)
    tab._link()
    assert ctx.watch.linked_media("local", "Show")["id"] == 7 and not tab.unlink_btn.isHidden()
    tab._unlink()
    assert ctx.watch.linked_media("local", "Show") is None


def test_player_opens_the_episode_and_records_progress(qapp, tmp_path):
    from anihub.sources.anime.base import AnimeEntry
    from anihub.ui.anime_player import AnimePlayer

    ctx = watch_ctx(tmp_path, ["Show/Show 01.mkv", "Show/Show 02.mkv"])
    source = ctx.anime_sources["local"]
    entry = AnimeEntry("Show", "Show")
    episodes = source.episodes(entry)
    ctx.watch.link("local", "Show", MEDIA)
    player = AnimePlayer(ctx, source, entry, episodes, 0)
    wait(qapp, lambda: player.quality.count() == 1)
    assert player.quality.count() == 1 and player.prev_btn.isEnabled() is False and player.next_btn.isEnabled()
    saved = []
    player.progress_changed.connect(lambda: saved.append(1))
    player._record(1_390_000, 1_400_000)                                        # the episode is (almost) over
    assert saved and ctx.watch.positions("local", "Show")["Show 01.mkv"]["watched"]
    assert ctx.db.anime_get(7)["progress"] == 1                                # the linked show moved forward
    player.open_episode(1)
    assert player.index == 1 and not player.next_btn.isEnabled() and "2" in player.title.text()
    player.open_episode(5)                                                     # out of range: ignored
    assert player.index == 1
    player.close()
