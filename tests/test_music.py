from pathlib import Path
from types import SimpleNamespace

from PySide6.QtCore import Qt

from anihub.core.config import Config
from anihub.core.db import Database
from anihub.core.paths import LibraryPaths
from anihub.services import music
from anihub.services.music import Album, Track, match_title, track_of


def touch(root: Path, *names: str) -> None:
    for n in names:
        f = root / n
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(b"x")


def test_track_names_are_split_into_number_and_title():
    assert (track_of(Path("03 - Main Theme.mp3")).number, track_of(Path("03 - Main Theme.mp3")).title) == (3, "Main Theme")
    assert track_of(Path("12. Ending.flac")).title == "Ending" and track_of(Path("Disc 1 - 07 Battle.ogg")).number == 7
    plain = track_of(Path("Opening.mp3"))
    assert plain.number is None and plain.title == "Opening"
    assert track_of(Path("07.mp3")).title == "07"                                     # nothing after the number: keep the name


def test_scan_groups_by_folder_and_orders_naturally(tmp_path):
    root = tmp_path / "music"
    touch(root, "Frieren/10 - Late.mp3", "Frieren/2 - Early.mp3", "Frieren/cover.jpg", "Bleach/CD1/01 - A.flac", "Bleach/CD2/01 - B.flac",
          "Empty/readme.txt", "loose.mp3")
    albums = music.scan(root)
    assert [a.name for a in albums] == ["Bleach", "Frieren", ""]                       # Empty has no audio; loose files last
    assert [t.title for t in albums[1].tracks] == ["Early", "Late"]                    # 2 before 10
    assert [t.title for t in albums[0].tracks] == ["A", "B"] and len(albums[0]) == 2
    assert music.scan(tmp_path / "nothing") == []


def test_albums_are_matched_to_watch_list_titles():
    album = lambda n: Album(n, Path(n), [])                                          # noqa: E731
    titles = ["Sousou no Frieren", "Bleach: Thousand-Year Blood War"]
    assert match_title(album("frieren"), titles) == "Sousou no Frieren"
    assert match_title(album("Bleach"), titles) == "Bleach: Thousand-Year Blood War"
    assert match_title(album("Naruto"), titles) is None and match_title(album("ab"), titles) is None and match_title(album(""), titles) is None


def make_ctx(tmp_path):
    paths = LibraryPaths(tmp_path / "lib")
    paths.ensure()
    cfg = Config.load(tmp_path / "c.json")
    db = Database(paths.db_file)
    return SimpleNamespace(cfg=cfg, db=db, paths=paths)


def test_tab_lists_albums_filters_and_marks_watch_list_titles(qapp, tmp_path):
    from anihub.ui.music_tab import MusicTab

    ctx = make_ctx(tmp_path)
    tab = MusicTab(ctx)
    assert not tab.empty.isHidden() and tab.tree.isHidden()
    touch(ctx.paths.root / "music", "Frieren OST/01 - Journey.mp3", "Frieren OST/02 - Magic.mp3", "Other/01 - Song.mp3")
    ctx.db.anime_upsert(media_id=1, title="Sousou no Frieren OST Show", status="CURRENT")
    tab.rescan()
    assert tab.tree.topLevelItemCount() == 2 and tab.empty.isHidden()
    head = tab.tree.topLevelItem(1) if "Frieren" in tab.tree.topLevelItem(1).text(0) else tab.tree.topLevelItem(0)
    assert "Sousou no Frieren OST Show" in head.text(0) and head.childCount() == 2
    tab.filter.setText("magic")
    assert tab.tree.topLevelItemCount() == 1 and tab.tree.topLevelItem(0).child(0).text(1) == "Magic"


def test_queue_navigation_shuffle_and_repeat(qapp, tmp_path):
    from anihub.ui.music_tab import MusicTab

    tab = MusicTab(make_ctx(tmp_path))
    tracks = [Track(Path(f"{i}.mp3"), f"t{i}", i) for i in range(3)]
    tab.queue, tab.index = tracks, 0
    assert tab.next_index(1) == 1 and tab.next_index(-1) == 2                         # stepping back from the first wraps (button press)
    tab.index = 2
    assert tab.next_index(1) == 0                                                     # manual next wraps too
    assert tab.next_index(1, ended=True) is None                                      # a finished last track stops without repeat
    tab.repeat = True
    assert tab.next_index(1, ended=True) == 0
    tab.shuffle = True
    picks = {tab.next_index(1) for _ in range(40)}
    assert picks <= {0, 1} and len(picks) == 2                                        # never the current track
    tab.queue = []
    assert tab.next_index(1) is None
    tab.volume.setValue(30)
    assert tab.ctx.cfg.get("music.volume") == 0.3


def test_double_click_builds_the_queue_from_the_album(qapp, tmp_path):
    from anihub.ui.music_tab import MusicTab

    ctx = make_ctx(tmp_path)
    touch(ctx.paths.root / "music", "A/01 - One.mp3", "A/02 - Two.mp3")
    tab = MusicTab(ctx)
    tab.tree.topLevelItem(0).setExpanded(True)
    played = []
    tab._play_current = lambda: played.append((tab.index, tab.queue[tab.index].title))       # no audio device needed
    tab._activated(tab.tree.topLevelItem(0).child(1))
    assert played == [(1, "Two")] and len(tab.queue) == 2
    tab._activated(tab.tree.topLevelItem(0))                                          # the album row plays from the start
    assert played[-1] == (0, "One")
    tab.stop()
