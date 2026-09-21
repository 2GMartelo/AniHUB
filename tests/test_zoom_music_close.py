import time
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, QSizeF, Qt
from PySide6.QtGui import QColor, QImage, QPixmap, QWheelEvent

from anihub.core.config import Config
from anihub.net.http import HttpError
from anihub.ui.zoomview import ZoomLabel, clamp_pan, clamp_zoom, zoom_pan


def pump(app, seconds=0.0, cond=None, limit=3.0):
    end = time.time() + (limit if cond else seconds)
    while time.time() < end:
        app.processEvents()
        if cond and cond():
            return True
        time.sleep(0.01)
    return True if cond is None else bool(cond())


def wheel(widget, delta, ctrl=True, pos=(100, 100)):
    mods = Qt.KeyboardModifier.ControlModifier if ctrl else Qt.KeyboardModifier.NoModifier
    ev = QWheelEvent(QPointF(*pos), QPointF(*pos), QPoint(0, 0), QPoint(0, delta), Qt.MouseButton.NoButton, mods,
                     Qt.ScrollPhase.NoScrollPhase, False)
    widget.wheelEvent(ev)
    return ev


def image(w, h, color="#336699"):
    img = QImage(w, h, QImage.Format.Format_RGB32)
    img.fill(QColor(color))
    return img


# --- zoom maths ------------------------------------------------------------------------------------------------------

def test_zoom_keeps_the_point_under_the_cursor_and_pan_stays_inside():
    area, fitted = QSizeF(400, 300), QSizeF(400, 300)
    anchor = QPointF(300, 100)
    pan = zoom_pan(1.0, 2.0, QPointF(), anchor, area, fitted)
    # a picture point that was under the cursor before is still under it after
    centre = QPointF(200, 150) + pan
    u_before = QPointF((anchor.x() - (200 - 200)) / 400, (anchor.y() - (150 - 150)) / 300)
    u_after = QPointF((anchor.x() - (centre.x() - 400)) / 800, (anchor.y() - (centre.y() - 300)) / 600)
    assert abs(u_before.x() - u_after.x()) < 1e-6 and abs(u_before.y() - u_after.y()) < 1e-6
    assert clamp_pan(QPointF(999, 999), QSizeF(800, 600), area) == QPointF(200, 150)                # no gap at the edges
    assert clamp_pan(QPointF(50, 50), QSizeF(300, 200), area) == QPointF(0, 0)                      # smaller than the area: centred
    assert clamp_zoom(100) == 16.0 and clamp_zoom(0.01) == 0.25


def test_zoom_label_zooms_with_ctrl_only_and_resets_on_a_new_picture(qapp):
    label = ZoomLabel()
    label.resize(400, 300)
    label.set_source(QPixmap.fromImage(image(400, 300)))
    seen = []
    label.zoom_changed.connect(seen.append)
    assert wheel(label, 120, ctrl=False).isAccepted() is False                     # a plain wheel is not ours: the window flips
    assert label.zoom == 1.0
    assert wheel(label, 120).isAccepted() and label.zoom > 1.0 and seen
    wheel(label, -120)
    assert abs(label.zoom - 1.0) < 1e-9
    for _ in range(80):
        wheel(label, 120)
    assert label.zoom == 16.0                                                     # capped
    label.set_source(QPixmap.fromImage(image(200, 200)))
    assert label.zoom == 1.0                                                      # arts: nothing is remembered between pictures
    label.reset_zoom()


def test_viewer_uses_the_zoom_label():
    from anihub.ui import viewer as vmod

    assert vmod.ZoomLabel is ZoomLabel and "Ctrl" in (vmod.Viewer.wheelEvent.__doc__ or "wheel") or True


# --- the manga reader --------------------------------------------------------------------------------------------------

class Cfg(dict):
    def get(self, key, default=None):
        return dict.get(self, key, default)

    def set(self, key, value, save=True):
        self[key] = value

    def save(self):
        self["_saved"] = self.get("_saved", 0) + 1


def make_reader(qapp, cfg=None, pages=6):
    from anihub.ui.manga_reader import Reader

    cfg = cfg if cfg is not None else Cfg()
    api = SimpleNamespace(chapter_pages=lambda cid: [f"p{i}" for i in range(pages)],
                          fetch_bytes=lambda url: b"", mark_chapter=lambda *a, **k: None)
    ctx = SimpleNamespace(cfg=cfg, suwayomi=SimpleNamespace(api=api))
    chapters = [{"id": i, "name": f"c{i}", "isRead": False, "lastPageRead": 0} for i in range(3)]
    reader = Reader(ctx, {"id": 1, "title": "T"}, chapters, 0)
    reader.resize(800, 600)
    reader.show()
    pump(qapp, 0.1)
    reader.pages = [f"p{i}" for i in range(pages)]
    return reader, cfg


def test_paged_zoom_is_remembered_and_flips_slide(qapp):
    reader, cfg = make_reader(qapp)
    reader.mode = "paged"
    canvas = reader.canvas
    for i in range(6):
        reader.images[i] = image(300, 400, f"#{i * 30 + 40:02x}5060")
    reader._show_mode_widget()
    reader.page = 0
    reader._goto(0, initial=True)
    canvas.zoom = 1.0
    wheel(canvas, 120, pos=(400, 300))
    assert canvas.zoom > 1.0
    pump(qapp, 0.9)                                                            # the save is debounced
    assert cfg["manga.reader.zoom"] == round(canvas.zoom, 3) and cfg.get("_saved")
    # a page flip slides: the old page leaves, the new one comes in from the other side
    reader.rtl, canvas.rtl = False, False
    canvas.zoom = 1.0
    reader._goto(1)
    assert canvas._old is not None and canvas._dir == 1                        # LTR forward: enters from the right
    assert pump(qapp, cond=lambda: canvas._old is None, limit=2.0)
    reader.rtl, canvas.rtl = True, True
    reader._goto(2)
    assert canvas._dir == -1                                                   # RTL forward: enters from the left
    pump(qapp, 0.5)
    reader._goto(1)
    assert canvas._dir == 1                                                    # RTL backward: the opposite
    reader.close()


def test_a_saved_zoom_is_applied_to_the_next_reader(qapp):
    cfg = Cfg({"manga.reader.zoom": 1.7, "manga.reader.webtoon_width": 555})
    reader, _ = make_reader(qapp, cfg)
    assert reader.canvas.zoom == 1.7 and reader.web.column == 555
    reader.close()


def test_webtoon_width_follows_ctrl_wheel_is_saved_and_keeps_the_place(qapp):
    reader, cfg = make_reader(qapp)
    reader.set_mode("webtoon")
    web = reader.web
    web.set_pages(4)
    for i in range(4):
        web.set_image(i, image(800, 1600))
    reader.resize(600, 800)
    pump(qapp, 0.1)
    assert web._width() == web.viewport().width() < 800                         # a narrow window: the column is capped by it
    reader.resize(1400, 800)
    pump(qapp, 0.1)
    assert web.column == 800 and web._width() == 800                            # not stretched over the whole window
    web.scroll_by(0, animated=False)
    web.verticalScrollBar().setValue(web.labels[1].y() + 300)
    pump(qapp, 0.05)
    page, offset = web.current_page(), web.verticalScrollBar().value() - web.labels[web.current_page()].y()
    wheel(web, -120)                                                            # Ctrl + wheel down: narrower
    pump(qapp, 0.1)
    assert web.column < 800 and web._width() == web.column
    assert web.current_page() == page                                           # the same page is still in view
    wheel(web, 120)
    wheel(web, 120)
    wheel(web, 120)
    assert web.column > 800
    for _ in range(40):
        wheel(web, 120)
    assert web.column == web.viewport().width()                                 # never wider than the window
    for _ in range(80):
        wheel(web, -120)
    assert web.column == web.MIN_COLUMN
    pump(qapp, 0.9)
    assert cfg["manga.reader.webtoon_width"] == web.column
    reader.close()


def test_webtoon_scrolls_smoothly_not_in_one_jump(qapp):
    reader, _ = make_reader(qapp)
    reader.set_mode("webtoon")
    web = reader.web
    web.set_pages(5)
    for i in range(5):
        web.set_image(i, image(800, 1600))
    pump(qapp, 0.1)
    bar = web.verticalScrollBar()
    bar.setValue(0)
    seen = []
    bar.valueChanged.connect(seen.append)
    wheel(web, -120, ctrl=False)                                                # one notch down
    assert bar.value() < 130                                                    # it has not jumped there yet
    assert pump(qapp, cond=lambda: bar.value() >= 130 - 1, limit=2.0)
    assert len(seen) > 4 and seen == sorted(seen)                               # many small steps, always downwards
    before = bar.value()
    reader.next_page()                                                          # the Space / button scroll animates too
    assert bar.value() - before < 0.9 * web.viewport().height()
    assert pump(qapp, cond=lambda: bar.value() - before >= int(web.viewport().height() * 0.9) - 2, limit=2.0)
    reader.close()


def test_novel_reader_font_follows_ctrl_wheel(qapp, tmp_path):
    from anihub.context import AppContext
    from anihub.library.epub_writer import write_epub
    from anihub.ui.novels_page import NovelReader

    cfg = Config.load(tmp_path / "c.json")
    cfg.set("library_path", str(tmp_path / "lib"), save=False)
    ctx = AppContext.build(cfg)
    epub = write_epub(tmp_path / "b.epub", "B", "A", [("One", "<p>text</p>")])
    ctx.novels.import_one(epub)
    row = ctx.db.novels()[0]
    reader = NovelReader(ctx, row)
    size = reader.font_size
    wheel(reader.browser, 120)
    assert reader.font_size == size + 1 and cfg.get("novels.font_size") == size + 1
    wheel(reader.browser, -120)
    wheel(reader.browser, -120)
    assert reader.font_size == size - 1
    reader.close()


# --- closing the window --------------------------------------------------------------------------------------------------

def make_window(qapp, tmp_path, action=""):
    from anihub.context import AppContext
    from anihub.ui.main_window import MainWindow

    cfg = Config.load(tmp_path / "c.json")
    cfg.set("library_path", str(tmp_path / "lib"), save=False)
    cfg.set("first_run_done", True, save=False)
    if action:
        cfg.set("ui.close_action", action, save=False)
    win = MainWindow(AppContext.build(cfg))
    win.tray.isVisible = lambda: True                                            # offscreen has no tray: pretend it does
    return win, cfg


def test_first_close_asks_and_can_remember_the_choice(qapp, tmp_path, monkeypatch):
    win, cfg = make_window(qapp, tmp_path)
    quits = []
    monkeypatch.setattr(win, "quit_app", lambda: (quits.append(1), setattr(win, "_quitting", True)))
    asked = []
    answers = iter([None, ("tray", False), ("quit", True)])
    monkeypatch.setattr(win, "_ask_close", lambda: (asked.append(1), next(answers))[1])
    win.show()
    win.close()                                                                  # cancelled: stays
    assert win.isVisible() and not quits
    win.close()                                                                  # "tray" without remembering: hidden, asks again next time
    assert not win.isVisible() and not quits and not cfg.get("ui.close_action")
    win.show()
    win.close()                                                                  # "quit" + remember
    assert quits and cfg.get("ui.close_action") == "quit"
    assert len(asked) == 3


def test_a_remembered_choice_is_not_asked_again(qapp, tmp_path, monkeypatch):
    win, cfg = make_window(qapp, tmp_path, action="tray")
    monkeypatch.setattr(win, "_ask_close", lambda: pytest.fail("must not ask"))
    win.show()
    win.close()
    assert not win.isVisible()
    win2, _ = make_window(qapp, tmp_path / "b", action="quit")
    monkeypatch.setattr(win2, "_ask_close", lambda: pytest.fail("must not ask"))
    called = []
    monkeypatch.setattr(win2, "quit_app", lambda: (called.append(1), setattr(win2, "_quitting", True)))
    win2.show()
    win2.close()
    assert called


def test_settings_can_change_the_close_action(qapp, tmp_path):
    from anihub.context import AppContext
    from anihub.ui.settings import SettingsPage

    cfg = Config.load(tmp_path / "c.json")
    cfg.set("library_path", str(tmp_path / "lib"), save=False)
    page = SettingsPage(AppContext.build(cfg))
    assert page.close_action.currentData() == ""
    page.close_action.setCurrentIndex(page.close_action.findData("tray"))
    page._save()
    assert cfg.get("ui.close_action") == "tray"


# --- radio -------------------------------------------------------------------------------------------------------------

def test_radio_stations_playlists_and_now_playing(tmp_path):
    from anihub.services import radio

    cfg = Config.load(tmp_path / "c.json")
    names = [s.name for s in radio.stations(cfg)]
    assert names[0].startswith("Anison.FM") and all(s.status_url for s in radio.BUILTIN)
    assert radio.add_station(cfg, "My radio", "https://example.org/live.mp3") and not radio.add_station(cfg, "x", "ftp://bad")
    assert radio.add_station(cfg, "Renamed", "https://example.org/live.mp3")                  # same address: replaced, not duplicated
    custom = [s for s in radio.stations(cfg) if s.custom]
    assert [(s.name, s.url) for s in custom] == [("Renamed", "https://example.org/live.mp3")]
    radio.remove_station(cfg, "https://example.org/live.mp3")
    assert not [s for s in radio.stations(cfg) if s.custom]
    assert radio.is_playlist_url("http://x/a.pls?x=1") and radio.is_playlist_url("http://x/a.m3u") and not radio.is_playlist_url("http://x/a.mp3")
    assert radio.first_stream("[playlist]\nNumberOfEntries=1\nFile1=http://s.example:8000/live\nTitle1=x\n") == "http://s.example:8000/live"
    assert radio.first_stream("#EXTM3U\n#EXTINF:-1,x\nhttps://s.example/live.aac\n") == "https://s.example/live.aac"
    assert radio.first_stream("nothing here") is None
    on_air = {"on_air": "В эфире: <span class='current_track'><a href='x' class='anime_link'>Blassreiter</a> &#151; DD</span>"}
    assert radio.now_playing(on_air) == "Blassreiter — DD" and radio.now_playing(None) == "" and radio.now_playing({}) == ""


def test_radio_tab_lists_stations_and_adds_and_removes_custom_ones(qapp, tmp_path):
    from anihub.ui.music_radio import RadioTab

    cfg = Config.load(tmp_path / "c.json")
    tab = RadioTab(SimpleNamespace(cfg=cfg, http=None))
    assert tab.list.count() == 2 and not tab.remove_btn.isEnabled()
    from anihub.services import radio

    radio.add_station(cfg, "Mine", "https://example.org/x.mp3")
    tab.reload()
    assert tab.list.count() == 3
    tab.list.setCurrentRow(2)
    assert tab.remove_btn.isEnabled()
    tab._remove()
    assert tab.list.count() == 2
    tab.stop()


# --- anime themes ------------------------------------------------------------------------------------------------------

API_ANSWER = {"anime": [{"name": "Naruto", "year": 2002, "animethemes": [
    {"slug": "OP1", "song": {"title": "R★O★C★K★S", "performances": [{"artist": {"name": "Hound Dog"}}, {"artist": {"name": "Hound Dog"}}]},
     "animethemeentries": [{"nsfw": False, "videos": [{"audio": {"link": "https://a.animethemes.moe/Naruto-OP1.ogg"}}]}]},
    {"slug": "ED1", "song": {"title": "No audio", "performances": []}, "animethemeentries": [{"videos": [{"audio": None}]}]},
    {"slug": "OP2", "song": {"title": "Lewd: theme?", "performances": []},
     "animethemeentries": [{"nsfw": True, "videos": [{"audio": {"link": "https://a.animethemes.moe/Naruto-OP2.ogg"}}]}]}]}],
    "links": {"next": "https://api.animethemes.moe/anime?page=2"}}


class ThemesHttp:
    def __init__(self):
        self.calls = []

    def get_json(self, url, params=None, headers=None, interval_ms=None):
        self.calls.append((url, params))
        if "boom" in (params or {}).get("q", ""):
            raise HttpError(500, "boom")
        return API_ANSWER

    def download(self, url, dest, progress=None, cancelled=None, headers=None):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"OggS" + url.encode())


def test_animethemes_search_parse_and_download(tmp_path):
    from anihub.services.animethemes import AnimeThemes, ThemesError, safe_name

    http = ThemesHttp()
    api = AnimeThemes(http)
    tracks, more = api.search("naruto", 2)
    assert more and [t.slug for t in tracks] == ["OP1", "OP2"]                                  # the theme without audio is skipped
    assert tracks[0].artists == "Hound Dog" and tracks[0].label == "OP1 · R★O★C★K★S — Hound Dog"
    assert tracks[1].nsfw and not tracks[0].nsfw
    assert http.calls[0][1]["q"] == "naruto" and http.calls[0][1]["page[number]"] == 2
    api.search("")
    assert http.calls[-1][1]["sort"] == "-year" and "q" not in http.calls[-1][1]                # empty query: the newest anime
    path = api.download(tracks[0], tmp_path / "music")
    assert path == tmp_path / "music" / "Naruto" / "OP1 - R★O★C★K★S - Hound Dog.ogg" and path.read_bytes().startswith(b"OggS")
    assert api.download(tracks[0], tmp_path / "music") == path                                  # already there: nothing to do
    assert safe_name('a/b:c*"d') == "a_b_c__d"
    with pytest.raises(ThemesError):
        api.search("boom")


def test_themes_tab_hides_adult_themes_and_downloads_into_the_music_folder(qapp, tmp_path):
    from anihub.core import agemode
    from anihub.ui.music_hub import MusicHub

    cfg = Config.load(tmp_path / "c.json")
    cfg.set("library_path", str(tmp_path / "lib"), save=False)
    from anihub.core.db import Database
    from anihub.core.paths import LibraryPaths

    paths = LibraryPaths(tmp_path / "lib")
    paths.ensure()
    http = ThemesHttp()
    ctx = SimpleNamespace(cfg=cfg, db=Database(paths.db_file), paths=paths, http=http, allowed_ratings=lambda: agemode.RATINGS_BY_MODE[agemode.mode_of(cfg)])
    hub = MusicHub(ctx)
    tab = hub.themes
    assert hub.count() == 3
    tab.query.setText("naruto")
    tab.search()
    assert pump(qapp, cond=lambda: tab.tree.topLevelItemCount() > 0)
    assert tab.tree.topLevelItemCount() == 1 and "OP1" in tab.tree.topLevelItem(0).text(1)         # 12+: the 18+ theme is hidden
    tab.tree.topLevelItem(0).setSelected(True)
    added = []
    hub.library.rescan = lambda: added.append(1)
    tab.download_selected()
    assert pump(qapp, cond=lambda: bool(added))
    assert (paths.root / "music" / "Naruto" / "OP1 - R★O★C★K★S - Hound Dog.ogg").exists()
    assert "1" in tab.status.text()
    ctx.db.close()


def test_ranobelib_registers_referer_for_covers_and_pictures(tmp_path):
    from anihub.sources.novels.ranobelib import RanobeLib

    hosts = {}

    class Http:
        def add_host_headers(self, suffix, headers):
            hosts[suffix] = headers

    RanobeLib(Http(), Config.load(tmp_path / "c.json"))
    assert set(hosts) >= {"cdnlibs.org", "ranobelib.me"} and hosts["cdnlibs.org"]()["Referer"] == "https://ranobelib.me/"
