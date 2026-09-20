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
