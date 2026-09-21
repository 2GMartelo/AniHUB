"""Mouse controls, manga filters, source settings and the vector icon engine."""
from pathlib import Path

import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QColor, QImage, QWheelEvent
from PySide6.QtWidgets import QApplication

from anihub.services.suwayomi import filter_changes, normalize_preference, _normalize_filter
from anihub.ui import icons, theme
from anihub.ui.manga_filters import FilterPanel
from anihub.ui.manga_views import library_match
from anihub.ui.navrail import NavButton
from anihub.ui.viewer import ViewItem, Viewer


def raw_filters():
    return [
        {"__typename": "CheckBoxFilter", "name": "Has chapters", "boolDef": False},
        {"__typename": "GroupFilter", "name": "Genre", "filters": [
            {"__typename": "TriStateFilter", "name": "Action", "triDef": "IGNORE"},
            {"__typename": "TriStateFilter", "name": "Comedy", "triDef": "IGNORE"}]},
        {"__typename": "SortFilter", "name": "Sort", "values": ["A", "B"], "sortDef": {"ascending": False, "index": 1}},
        {"__typename": "SelectFilter", "name": "Age", "values": ["any", "18+"], "selDef": 0},
        {"__typename": "TextFilter", "name": "Author", "txtDef": ""},
    ]


@pytest.fixture
def nodes():
    return [_normalize_filter(f, i) for i, f in enumerate(raw_filters())]


def test_untouched_filters_produce_no_changes(nodes):
    assert filter_changes(nodes, {}) == []
    assert filter_changes(nodes, {(1, 1): "IGNORE", (0,): False}) == []


def test_changes_use_group_and_top_level_shapes(nodes):
    state = {(0,): True, (1, 1): "INCLUDE", (1, 0): "EXCLUDE", (2,): {"ascending": True, "index": 0},
             (3,): 1, (4,): "abe"}
    changes = filter_changes(nodes, state)
    assert {"position": 0, "checkBoxState": True} in changes
    assert {"position": 1, "groupChange": {"position": 1, "triState": "INCLUDE"}} in changes
    assert {"position": 1, "groupChange": {"position": 0, "triState": "EXCLUDE"}} in changes
    assert {"position": 2, "sortState": {"ascending": True, "index": 0}} in changes
    assert {"position": 3, "selectState": 1} in changes
    assert {"position": 4, "textState": "abe"} in changes
    assert len(changes) == 6


def test_preference_normalization():
    sw = normalize_preference({"__typename": "SwitchPreference", "key": "k", "title": "T", "switchValue": True}, 3)
    assert sw["kind"] == "switch" and sw["value"] is True and sw["pos"] == 3 and sw["field"] == "switchState"
    txt = normalize_preference({"__typename": "EditTextPreference", "key": "pw", "title": "Password", "textValue": "x"}, 0)
    assert txt["field"] == "editTextState" and txt["value"] == "x"
    lst = normalize_preference({"__typename": "ListPreference", "key": "q", "entries": ["a"], "entryValues": ["1"],
                                "listValue": "1"}, 1)
    assert lst["field"] == "listState" and lst["entry_values"] == ["1"]
    assert normalize_preference({"__typename": "SomethingNew"}, 0) is None


def test_library_match_combines_all_filters():
    m = {"title": "Ten Koi", "genre": ["Comedy", "Romance"], "status": "ONGOING", "unreadCount": 2}
    assert library_match(m)
    assert library_match(m, "koi", "Comedy", "ONGOING", True)
    assert not library_match(m, "koi", "Horror")
    assert not library_match(m, status="COMPLETED")
    assert not library_match({**m, "unreadCount": 0}, unread_only=True)
    assert not library_match(m, "zzz")


def test_filter_panel_chips_cycle_and_feed_changes(qapp, nodes):
    panel = FilterPanel()
    panel.set_filters(nodes)
    chip = next(c for c in panel._chips if c.node["name"] == "Comedy")
    for expected in ("INCLUDE", "EXCLUDE", "IGNORE"):
        chip.click()
        assert panel.state()[(1, 1)] == expected
    chip.click()
    assert panel.active_count() == 1 and filter_changes(panel.nodes, panel.state())[0]["groupChange"]["triState"] == "INCLUDE"
    panel.reset()
    assert panel.active_count() == 0


def test_filter_panel_search_hides_other_chips(qapp, nodes):
    panel = FilterPanel()
    panel.set_filters(nodes)
    panel.search.setText("com")
    assert {c.node["name"]: c.isHidden() for c in panel._chips} == {"Action": True, "Comedy": False}
    panel.search.setText("")
    assert not any(c.isHidden() for c in panel._chips)


def test_icons_are_antialiased_and_sized_exactly(qapp):
    theme.apply_theme(qapp, "dark")
    pm = icons.icon("x", "#ffffff").pixmap(24, 24)
    assert pm.width() >= 24
    image = pm.toImage()
    alphas = {image.pixelColor(x, y).alpha() for x in range(image.width()) for y in range(image.height())}
    assert any(0 < a < 255 for a in alphas), "diagonal strokes must have smooth edges"
    big = icons.icon("x", "#ffffff").pixmap(64, 64)
    assert big.width() >= 64


def test_nav_button_paints_icon_centred(qapp):
    theme.apply_theme(qapp, "dark")
    button = NavButton("A", "image")
    button.resize(68, 62)
    button.setChecked(True)
    image = QImage(68, 62, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor("black"))
    button.render(image)
    bright = [x for x in range(68) for y in range(8, 36) if image.pixelColor(x, y).lightness() > 120]
    assert bright, "icon was not painted"
    centre = (min(bright) + max(bright)) / 2
    assert abs(centre - 34) <= 2


def make_items(tmp_path: Path, n: int = 3) -> list[ViewItem]:
    items = []
    for i in range(n):
        path = tmp_path / f"{i}.png"
        image = QImage(40, 30, QImage.Format.Format_RGB32)
        image.fill(QColor("red"))
        image.save(str(path))
        items.append(ViewItem(f"t{i}", "info", (lambda p=path: p)))
    return items


def test_viewer_buttons_navigate_and_report_actions(qapp, tmp_path):
    seen = {}
    viewer = Viewer(make_items(tmp_path), 0, on_save=lambda it: seen.setdefault("saved", it.title),
                    on_favorite=lambda it, v: seen.update(fav=(it.title, v)),
                    on_stars=lambda it, v: seen.update(stars=(it.title, v)))
    viewer.next_btn.click()
    assert viewer.index == 1
    viewer.prev_btn.click()
    viewer.prev_btn.click()
    assert viewer.index == 2 and viewer.counter.text() == "3 / 3"       # wraps around
    viewer.fav_btn.click()
    assert seen["fav"] == ("t2", True) and viewer.items[2].favorite
    viewer.fav_btn.click()
    assert seen["fav"] == ("t2", False)
    viewer._set_stars(4)
    assert seen["stars"] == ("t2", 4) and viewer.items[2].stars == 4
    viewer.save_btn.click()
    assert seen["saved"] == "t2"
    viewer.slide_btn.click()
    assert viewer.timer.isActive() and viewer.slide_btn.isChecked()
    viewer.slide_btn.click()
    assert not viewer.timer.isActive()
    viewer.tags_btn.click()
    assert viewer.tags.isHidden()
    viewer.close()


def test_viewer_hides_actions_without_callbacks(qapp, tmp_path):
    viewer = Viewer(make_items(tmp_path, 1), 0)
    assert viewer.fav_btn.isHidden() and viewer.stars_btn.isHidden() and viewer.save_btn.isHidden()
    assert not viewer.next_btn.isEnabled()                              # a single item: nothing to flip to
    viewer.close()


def test_viewer_wheel_flips_items(qapp, tmp_path):
    viewer = Viewer(make_items(tmp_path), 0)
    down = QWheelEvent(QPointF(5, 5), QPointF(5, 5), QPoint(0, 0), QPoint(0, -120), Qt.MouseButton.NoButton,
                       Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
    QApplication.sendEvent(viewer, down)
    assert viewer.index == 1
    viewer.close()


class _Cfg(dict):
    def get(self, key, default=None):
        return dict.get(self, key, default)

    def set(self, key, value, save=True):
        self[key] = value

    def save(self):
        pass


def make_reader(qapp, rtl=True):
    from types import SimpleNamespace

    from anihub.ui.manga_reader import Reader

    api = SimpleNamespace(chapter_pages=lambda cid: [], fetch_bytes=lambda url: b"", update_chapters=lambda *a, **k: None)
    ctx = SimpleNamespace(cfg=_Cfg({"manga.reader.rtl": rtl}), suwayomi=SimpleNamespace(api=api))
    chapters = [{"id": i, "name": f"ch{i}", "isRead": False, "lastPageRead": 0} for i in range(3)]
    reader = Reader(ctx, {"title": "M"}, chapters, 1)
    reader._token += 1                      # ignore the (empty) page list the worker returns
    reader.pages = ["a", "b", "c", "d"]
    reader.images = {i: QImage(10, 20, QImage.Format.Format_RGB32) for i in range(4)}
    reader._goto(1)
    return reader


def test_reader_arrows_follow_reading_direction(qapp):
    reader = make_reader(qapp, rtl=True)
    reader.left_btn.click()                 # right-to-left: the left arrow goes forward
    assert reader.page == 2
    reader.right_btn.click()
    assert reader.page == 1
    reader.rtl_box.setChecked(False)
    reader.right_btn.click()
    assert reader.page == 2
    reader.close()


def test_reader_slider_and_labels_track_the_page(qapp):
    reader = make_reader(qapp)
    assert reader.page_slider.maximum() == 3 and reader.page_slider.value() == 1
    assert reader.page_label.text() == "2 / 4"
    reader.page_slider.setValue(3)
    assert reader.page == 3
    assert reader.page_slider.invertedAppearance()      # RTL: the slider runs right to left
    reader.close()


def test_reader_chapter_buttons_enabled_by_position(qapp):
    reader = make_reader(qapp)
    assert reader.prev_btn.isEnabled() and reader.next_btn.isEnabled()
    reader.index = 0
    reader._update_title()
    assert not reader.prev_btn.isEnabled()
    reader.close()


def test_source_settings_dialog_saves_changes(qapp):
    import time
    from types import SimpleNamespace

    from PySide6.QtWidgets import QCheckBox, QLineEdit

    from anihub.ui.manga_filters import SourceSettingsDialog

    prefs = [normalize_preference({"__typename": "EditTextPreference", "key": "password", "title": "Password",
                                   "textValue": ""}, 0),
             normalize_preference({"__typename": "SwitchPreference", "key": "hq", "title": "HQ", "switchValue": False}, 1)]
    saved = []
    api = SimpleNamespace(source_preferences=lambda sid: prefs,
                          set_source_preference=lambda sid, pref, value: saved.append((pref["pos"], pref["field"], value)))
    dialog = SourceSettingsDialog(api, {"id": "1", "displayName": "Src"})

    def pump(cond):
        end = time.time() + 5
        while time.time() < end and not cond():
            qapp.processEvents()
            time.sleep(0.01)

    pump(lambda: dialog.form.rowCount() == 2)
    assert dialog.form.rowCount() == 2
    edit = dialog.findChild(QLineEdit)
    assert edit.echoMode() == QLineEdit.EchoMode.Password           # passwords are masked
    edit.setText("secret")
    edit.editingFinished.emit()
    box = dialog.findChild(QCheckBox)
    box.setChecked(True)
    pump(lambda: len(saved) == 2)
    assert (0, "editTextState", "secret") in saved and (1, "switchState", True) in saved
    pump(lambda: dialog.changed)
    assert dialog.changed


def test_tag_rows_have_plus_and_minus_buttons(qapp, tmp_path):
    from anihub.ui.viewer import TagRow

    viewer = Viewer([ViewItem("t", "i", lambda: tmp_path / "x.png", tags=[("cat", "general"), ("miku", "artist")])], 0)
    seen = []
    viewer.tag_action.connect(lambda tag, mode: seen.append((tag, mode)))
    rows = [viewer.tags.itemWidget(viewer.tags.item(i)) for i in range(viewer.tags.count())]
    rows = [r for r in rows if isinstance(r, TagRow)]
    assert [r.name for r in rows] == ["miku", "cat"] or sorted(r.name for r in rows) == ["cat", "miku"]
    cat = next(r for r in rows if r.name == "cat")
    cat.plus.click()
    cat.minus.click()
    cat.label.mousePressEvent(None)
    assert seen == [("cat", "add"), ("cat", "exclude"), ("cat", "search")]
    viewer.close()


def test_add_from_viewer_keeps_it_open_and_extends_the_query():
    from anihub.ui.tagquery import apply_tag

    assert apply_tag("cat", "dog", "add") == "cat dog" and apply_tag("cat dog", "dog", "exclude") == "cat -dog"
