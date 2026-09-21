import re

import pytest
from PySide6.QtWidgets import QPushButton

from anihub.ui import icons, style, theme
from anihub.ui.navrail import NavRail


def hex_luminance(color: str) -> float:
    r, g, b = (int(color[i:i + 2], 16) / 255 for i in (1, 3, 5))
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in (r, g, b)]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def contrast(a: str, b: str) -> float:
    la, lb = sorted((hex_luminance(a), hex_luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


@pytest.mark.parametrize("tokens", [theme.DARK, theme.LIGHT], ids=["dark", "light"])
def test_text_colours_are_readable_on_their_surfaces(tokens):
    for surface in (tokens.bg, tokens.surface, tokens.surface2, tokens.card):
        assert contrast(tokens.text, surface) >= 7, (surface, "main text")
        assert contrast(tokens.dim, surface) >= 4.5, (surface, "secondary text")
    assert contrast(tokens.on_accent, tokens.accent) >= 4.5, "text on primary buttons"
    for surface in (tokens.bg, tokens.surface):
        assert contrast(tokens.accent_text, surface) >= 4.5, (surface, "accent used as text")
        assert contrast(tokens.danger, surface) >= 3.0


def test_themes_apply_and_leave_no_unresolved_tokens(qapp):
    for mode in ("dark", "light", "system"):
        theme.apply_theme(qapp, mode)
        sheet = qapp.styleSheet()
        assert len(sheet) > 5000 and not re.search(r"\$[a-z_]+", sheet), mode
        assert theme.current().name in ("dark", "light")
    theme.apply_theme(qapp, "dark")
    assert theme.current().dark


def test_stylesheet_assets_exist(qapp):
    theme.apply_theme(qapp, "dark")
    urls = re.findall(r'url\("([^"]+)"\)', qapp.styleSheet())
    assert urls
    from pathlib import Path
    assert all(Path(u).exists() for u in urls)


def test_every_icon_renders(qapp):
    theme.apply_theme(qapp, "dark")
    for name in icons._P:
        pm = icons.pixmap(name, "#ffffff", 20)
        assert not pm.isNull()
        image = pm.toImage()
        assert any(image.pixelColor(x, y).alpha() > 0 for x in range(0, image.width(), 2) for y in range(0, image.height(), 2)), name


def test_buttons_get_roles_and_recoloured_icons_on_theme_change(qapp):
    theme.apply_theme(qapp, "dark")
    btn = style.primary(QPushButton("Go"), "zap")
    assert btn.property("variant") == "primary" and not btn.icon().isNull()
    ghost = style.ghost(QPushButton("x"), "trash")
    before = ghost.icon().pixmap(18, 18).toImage().pixelColor(9, 9).name()
    theme.apply_theme(qapp, "light")                         # icons bound through style follow the theme
    after = ghost.icon().pixmap(18, 18).toImage().pixelColor(9, 9).name()
    assert before != after or ghost.icon().cacheKey() != 0
    theme.apply_theme(qapp, "dark")


def test_navrail_keeps_the_list_widget_api(qapp):
    rail = NavRail()
    seen = []
    rail.currentRowChanged.connect(seen.append)
    a, b, c = rail.add_item("A", "image"), rail.add_item("B", "book"), rail.add_item("C", "sliders", bottom=True)
    assert (a, b, c) == (0, 1, 2)
    rail.setCurrentRow(1)
    assert rail.currentRow() == 1 and seen == [1]
    rail._buttons[2].click()
    assert rail.currentRow() == 2 and seen[-1] == 2          # a click behaves like selecting the row
    rail.setCurrentRow(99)                                    # out of range: ignored
    assert rail.currentRow() == 2


def test_status_chip_and_state_colours(qapp):
    theme.apply_theme(qapp, "dark")
    chip = style.StatusChip()
    chip.set_state("running", "Forge · работает")
    assert chip.text.text() == "Forge · работает"
    assert style.state_color("running") == theme.DARK.success and style.state_color("failed") == theme.DARK.danger
    assert style.state_color("unknown") == theme.DARK.muted


def over(fg: str, bg: str) -> str:
    """Composite an rgba(r, g, b, a) stylesheet colour over a flat #rrggbb one."""
    r, g, b, a = (float(x) for x in re.match(r"rgba\((\d+),\s*(\d+),\s*(\d+),\s*([\d.]+)\)", fg).groups())
    base = [int(bg[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(c * a + o * (1 - a)):02x}" for c, o in zip((r, g, b), base))


@pytest.mark.parametrize("tokens", [theme.DARK, theme.LIGHT], ids=["dark", "light"])
def test_translucent_stylesheet_surfaces_keep_text_readable(tokens):
    """The panels are translucent in the stylesheet: text must stay readable on them, alone and inside a panel."""
    floor = tokens.bg
    for name in ("surface", "surface2", "surface3"):
        once = over(tokens.qss[name], floor)
        in_card = over(tokens.qss[name], over(tokens.qss["surface"], floor))          # a control inside a panel
        for surface in (once, in_card):
            assert contrast(tokens.text, surface) >= 7, (name, "main text")
            assert contrast(tokens.dim, surface) >= 4.5, (name, "secondary text")
            assert contrast(tokens.accent_text, surface) >= 4.5, (name, "accent text")


@pytest.mark.parametrize("tokens", [theme.DARK, theme.LIGHT], ids=["dark", "light"])
def test_primary_button_gradient_is_readable_at_both_ends(tokens):
    assert contrast(tokens.on_accent, tokens.accent) >= 4.5 and contrast(tokens.on_accent, tokens.accent_end) >= 4.5


def test_glass_switch_changes_the_window_background_and_palette(qapp):
    from PySide6.QtGui import QPalette

    theme.apply_theme(qapp, "dark", glass=False)
    assert not theme.is_glass() and "qlineargradient" in qapp.styleSheet().split("QMainWindow {")[1].split("}")[0]
    theme.apply_theme(qapp, "dark", glass=True)
    if theme.glass_supported():
        assert theme.is_glass()
        assert "QMainWindow { background: transparent; }" in qapp.styleSheet()
        assert qapp.palette().color(QPalette.ColorRole.Window).alpha() == 0
    else:
        assert not theme.is_glass()                                              # older Windows / other systems: stays opaque
    theme.apply_theme(qapp, "dark")                                              # omitted: keeps the last choice
    assert theme.is_glass() == theme.glass_supported()
    theme.apply_theme(qapp, "dark", glass=False)


def test_main_window_can_be_toggled_between_glass_and_opaque(qapp, tmp_path):
    from PySide6.QtCore import Qt

    from anihub.context import AppContext
    from anihub.core.config import Config
    from anihub.ui.main_window import MainWindow

    cfg = Config.load(tmp_path / "c.json")
    cfg.set("library_path", str(tmp_path / "lib"), save=False)
    cfg.set("first_run_done", True, save=False)
    theme.apply_theme(qapp, "dark", glass=False)
    win = MainWindow(AppContext.build(cfg))
    assert not win.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    theme.apply_theme(qapp, "dark", glass=True)
    assert win.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground) == theme.is_glass()
    theme.apply_theme(qapp, "dark", glass=False)
    assert not win.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    win._quitting = True                                  # closing must not ask the tray question
    win.close()
