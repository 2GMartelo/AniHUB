import re
import time

import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication, QListWidget, QPlainTextEdit

from anihub.core.config import Config
from anihub.ui import smoothscroll, theme
from anihub.ui.theme import build_custom, contrast, mix


def pump(app, seconds=0.0, cond=None, limit=3.0):
    end = time.time() + (limit if cond else seconds)
    while time.time() < end:
        app.processEvents()
        if cond and cond():
            return True
        time.sleep(0.01)
    return True if cond is None else bool(cond())


def over(fg: str, bg: str) -> str:
    r, g, b, a = (float(x) for x in re.match(r"rgba\((\d+),\s*(\d+),\s*(\d+),\s*([\d.]+)\)", fg).groups())
    base = [int(bg[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(c * a + o * (1 - a)):02x}" for c, o in zip((r, g, b), base))


# --- the light theme is pink now -----------------------------------------------------------------------------------------

def test_light_theme_has_no_violet_left():
    t = theme.LIGHT
    for name in ("accent", "accent_hover", "accent_press", "accent_text", "accent_end", "bg", "surface2", "border"):
        r, g, b = (int(getattr(t, name)[i:i + 2], 16) for i in (1, 3, 5))
        assert r >= g and r >= b, (name, getattr(t, name))                       # red-dominant (pink), never blue-dominant (violet)
    assert "199, 61, 123" not in t.soft and t.soft.startswith("rgba(201, 61, 123")
    sheet_colours = " ".join([t.window, *[c for _p, c in t.window_glass], t.dialog])
    for hexed in re.findall(r"#([0-9a-f]{6})", sheet_colours):
        r, g, b = (int(hexed[i:i + 2], 16) for i in (0, 2, 4))
        assert r >= b, hexed                                                                    # the gradients are pink as well
    for r, g, b, _a in re.findall(r"rgba\((\d+), (\d+), (\d+), ([\d.]+)\)", sheet_colours):
        assert int(r) >= int(b)


def test_pink_accent_keeps_the_button_text_readable():
    t = theme.LIGHT
    assert contrast(t.on_accent, t.accent) >= 4.5 and contrast(t.on_accent, t.accent_end) >= 4.5


# --- the custom theme --------------------------------------------------------------------------------------------------

PRESETS = [
    {},                                                                                         # defaults
    {"bg": "#101010", "panel": "#1c1c1c", "text": "#ffffff", "accent": "#ff0055"},
    {"bg": "#fffdf5", "panel": "#f4ecd8", "text": "#3b2f22", "accent": "#8a4b12"},
    {"bg": "#ffffff", "panel": "#ffffff", "text": "#ffffff", "accent": "#ffffff"},             # everything white: must be repaired
    {"bg": "#000000", "panel": "#000000", "text": "#000000", "accent": "#000000"},             # everything black
    {"bg": "#808080", "panel": "#909090", "text": "#858585", "accent": "#7f7f7f"},             # mid grey, no contrast at all
    {"bg": "#1a1a40", "panel": "#22225a", "text": "#9999ff", "accent": "#ffee00"},
    {"bg": "#e8f5e9", "panel": "#c8e6c9", "text": "#1b5e20", "accent": "#00c853"},
    {"bg": "not a colour", "panel": "#12", "text": None, "accent": ""},                          # garbage falls back to the defaults
]


@pytest.mark.parametrize("colors", PRESETS, ids=range(len(PRESETS)))
def test_custom_theme_is_always_readable(colors):
    t = build_custom(colors)
    assert t.name == "custom" and t.dark == (theme._luminance(t.bg) < 0.18)
    floor = 4.0 if colors == PRESETS[5] else 4.5                                                  # mid grey cannot do better
    for surface in (t.bg, t.surface, t.surface2, t.surface3):
        assert contrast(t.text, surface) >= floor, (colors, surface, "text")
        assert contrast(t.dim, surface) >= 4.5 or surface == t.surface3 and contrast(t.dim, surface) >= 4.2, (colors, surface, "dim")
    assert contrast(t.on_accent, t.accent) >= 4.5 and contrast(t.on_accent, t.accent_end) >= 4.5, (colors, "button text")
    for surface in (t.bg, t.surface):
        assert contrast(t.accent_text, surface) >= 4.5, (colors, "accent text")
    for name in ("surface", "surface2", "surface3"):                                              # translucent panels, alone and in a card
        once = over(t.qss[name], t.bg)
        in_card = over(t.qss[name], over(t.qss["surface"], t.bg))
        for surface in (once, in_card):
            assert contrast(t.text, surface) >= floor, (colors, name)
    assert re.fullmatch(r"#[0-9a-f]{6}", t.accent) and "qlineargradient" in t.window


def test_custom_theme_follows_the_chosen_colours():
    a, b = build_custom({"accent": "#2fb8a6"}), build_custom({"accent": "#d81b60"})
    assert a.accent != b.accent and a.window != b.window
    light = build_custom({"bg": "#fdf6e3", "panel": "#eee8d5", "text": "#073642", "accent": "#268bd2"})
    assert not light.dark and build_custom({"bg": "#111111"}).dark
    assert build_custom({"bg": "#111111"}) == build_custom({"bg": "#111111"})                 # deterministic
    assert mix("#000000", "#ffffff", 0.5) == "#808080"


def test_custom_theme_applies_to_the_application_and_survives_switching(qapp):
    theme.set_custom_colors({"bg": "#101820", "panel": "#1b2a36", "text": "#eaf2f8", "accent": "#ff8a00"})
    theme.apply_theme(qapp, "custom")
    sheet = qapp.styleSheet()
    assert theme.current().name == "custom" and "ff8a00" in sheet.lower()
    assert not re.search(r"\$[a-z_]+", sheet) and len(sheet) > 5000
    assert theme.logo_colors()[1] == theme.current().accent
    theme.apply_theme(qapp, "light")
    assert theme.current().name == "light" and theme.logo_colors()[1] == "#c93d7b"
    theme.apply_theme(qapp, "dark")
    assert theme.logo_colors() == ("#b07bff", "#7a38d8")
    theme.set_custom_colors(None)
    assert theme.custom_colors() == theme.DEFAULT_CUSTOM


def test_settings_offer_the_custom_theme_and_store_the_colours(qapp, tmp_path):
    from anihub.context import AppContext
    from anihub.ui.settings import SettingsPage

    cfg = Config.load(tmp_path / "c.json")
    cfg.set("library_path", str(tmp_path / "lib"), save=False)
    page = SettingsPage(AppContext.build(cfg))
    keys = [page.theme.itemData(i) for i in range(page.theme.count())]
    assert keys == ["system", "light", "dark", "custom"]
    page.show()
    assert page.custom_row.isHidden() or not page.custom_row.isVisible()
    page.theme.setCurrentIndex(page.theme.findData("custom"))
    assert not page.custom_row.isHidden()
    page.custom_buttons["accent"].set_color("#ff5500")
    page._custom_changed()                                                                     # what a pick does
    assert theme.current().name == "custom" and theme.current().accent == "#ff5500"      # applied at once
    page._save()
    assert cfg.get("theme") == "custom" and cfg.get("theme_custom")["accent"] == "#ff5500"
    page._custom_reset()
    assert page.custom_buttons["accent"].color == theme.DEFAULT_CUSTOM["accent"]
    page.theme.setCurrentIndex(page.theme.findData("dark"))
    page._save()
    theme.set_custom_colors(None)
    theme.apply_theme(qapp, "dark")
    assert page.custom_row.isHidden()


# --- smooth scrolling ------------------------------------------------------------------------------------------------------

@pytest.fixture
def smooth(qapp):
    filt = smoothscroll.install(qapp, True)
    yield filt
    smoothscroll.set_enabled(False)


def send_wheel(widget, delta, mods=Qt.KeyboardModifier.NoModifier, pixel=0):
    ev = QWheelEvent(QPointF(20, 20), QPointF(20, 20), QPoint(0, pixel), QPoint(0, delta), Qt.MouseButton.NoButton, mods,
                     Qt.ScrollPhase.NoScrollPhase, False)
    QApplication.sendEvent(widget, ev)
    return ev


def make_list(qapp, rows=200):
    lw = QListWidget()
    lw.addItems([f"row {i}" for i in range(rows)])
    lw.resize(300, 300)
    lw.show()
    pump(qapp, 0.05)
    return lw


def test_a_wheel_notch_animates_the_scroll_bar_instead_of_jumping(qapp, smooth):
    lw = make_list(qapp)
    bar = lw.verticalScrollBar()
    seen = []
    bar.valueChanged.connect(seen.append)
    ev = send_wheel(lw.viewport(), -120)                                        # one notch down
    assert ev.isAccepted()
    assert bar.value() < smoothscroll.PIXELS_PER_NOTCH                          # not there yet
    assert lw.verticalScrollMode() == lw.ScrollMode.ScrollPerPixel              # rows scroll by pixels now
    assert pump(qapp, cond=lambda: bar.value() >= smoothscroll.PIXELS_PER_NOTCH - 1, limit=2.0)
    assert len(seen) > 4 and seen == sorted(seen)
    send_wheel(lw.viewport(), -120)
    send_wheel(lw.viewport(), -120)                                             # several turns add up
    assert pump(qapp, cond=lambda: bar.value() >= 3 * smoothscroll.PIXELS_PER_NOTCH - 3, limit=2.0)
    send_wheel(lw.viewport(), 120)                                              # and back up
    assert pump(qapp, cond=lambda: bar.value() <= 2 * smoothscroll.PIXELS_PER_NOTCH + 3, limit=2.0)
    lw.close()


def test_the_wheel_is_left_alone_when_it_should_be(qapp, smooth):
    lw = make_list(qapp)
    bar = lw.verticalScrollBar()
    send_wheel(lw.viewport(), -120, Qt.KeyboardModifier.ControlModifier)
    running = [a for a in smooth._anims.values() if a.state() == a.State.Running]
    assert not running                                                          # Ctrl + wheel is never animated by us
    send_wheel(lw.viewport(), -120, pixel=-30)                                  # a touchpad's pixel delta: handled by Qt itself
    pump(qapp, 0.4)
    assert bar.value() <= 40
    top = make_list(qapp, rows=3)                                               # nothing to scroll: the event goes on
    assert not send_wheel(top.viewport(), -120).isAccepted()
    assert top.verticalScrollBar().maximum() == 0
    smooth.enabled = False
    before = bar.value()
    send_wheel(lw.viewport(), -120)
    assert not smoothscroll.SmoothScroll.area_of(lw.viewport()) is None
    pump(qapp, 0.3)
    assert bar.value() >= before                                                # with the switch off Qt scrolls as usual
    smooth.enabled = True
    lw.close()
    top.close()


def test_the_webtoon_strip_and_scroll_areas_can_opt_out(qapp, smooth):
    from anihub.ui.manga_reader import WebtoonView

    web = WebtoonView()
    assert smoothscroll.SmoothScroll.opted_out(web)                             # it has its own animation
    edit = QPlainTextEdit("\n".join(str(i) for i in range(300)))
    edit.resize(200, 200)
    edit.show()
    pump(qapp, 0.05)
    assert not smoothscroll.SmoothScroll.opted_out(edit)                        # text views scroll smoothly as well
    edit.setProperty("smoothScroll", False)
    assert smoothscroll.SmoothScroll.opted_out(edit)
    edit.close()


def test_settings_switch_toggles_smooth_scrolling(qapp, tmp_path, smooth):
    from anihub.context import AppContext
    from anihub.ui.settings import SettingsPage

    cfg = Config.load(tmp_path / "c.json")
    cfg.set("library_path", str(tmp_path / "lib"), save=False)
    page = SettingsPage(AppContext.build(cfg))
    assert page.smooth.isChecked() and smooth.enabled
    page.smooth.setChecked(False)
    assert not smooth.enabled
    page._save()
    assert cfg.get("ui.smooth_scroll") is False
    page.smooth.setChecked(True)
    assert smooth.enabled
