"""Design system: colour tokens for the dark and light themes, one application-wide stylesheet, fonts, title bar."""
from __future__ import annotations

import ctypes
import re
import sys
from dataclasses import dataclass, field, replace
from pathlib import Path
from string import Template

from PySide6.QtCore import QEvent, QObject, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QImage, QLinearGradient, QPainter, QPainterPath, QPalette, QPen, QPixmap, QRadialGradient
from PySide6.QtWidgets import QApplication, QMainWindow, QWidget

from anihub.core.config import config_dir


@dataclass(frozen=True)
class Tokens:
    name: str
    bg: str          # window background
    rail: str        # navigation rail / status bar
    surface: str     # cards, panels, lists
    surface2: str    # inputs, buttons
    surface3: str    # hover
    card: str        # gallery cards (must stand out from the window background)
    border: str
    border_hover: str
    text: str
    dim: str         # secondary text
    muted: str       # hints, disabled
    accent: str
    accent_hover: str
    accent_press: str
    accent_text: str  # accent used as text on a normal background
    soft: str        # translucent accent (selection, checked)
    on_accent: str
    success: str
    warning: str
    danger: str
    danger_soft: str
    scroll: str
    accent_end: str = "#5d41dc"   # the other end of the accent gradient (primary buttons, progress)
    # Stylesheet-only colours: translucent, so the window gradient / Windows backdrop shows through the panels. The flat
    # tokens above stay opaque because widgets that paint by hand (grid cards, viewers) and the contrast tests use them.
    window: str = ""              # gradient behind everything (opaque)
    window_glass: tuple = ()      # (position, colour) stops of the same gradient, translucent: painted by hand (paint_glass)
                                  # over the Windows Mica backdrop, because Qt's stylesheet background ignores alpha there
    dialog: str = ""              # dialogs are separate windows, always opaque
    popup: str = ""               # menus, drop-downs, tooltips: opaque too
    qss: dict = field(default_factory=dict, compare=False, hash=False, repr=False)
    mode_dark: bool | None = None  # custom themes say themselves whether they are dark (built-in ones go by name)

    @property
    def dark(self) -> bool:
        return self.name == "dark" if self.mode_dark is None else self.mode_dark


DARK = Tokens(
    "dark", bg="#16101f", rail="#120d1a", surface="#1e1629", surface2="#271e34", surface3="#322940", card="#201829",
    border="#2c2439", border_hover="#453a58", text="#efe9f7", dim="#b4aac6", muted="#7a6f8c",
    accent="#8f48e0", accent_hover="#8340d3", accent_press="#7538c2", accent_text="#cfa9ff",
    soft="rgba(143, 72, 224, 0.24)", on_accent="#ffffff", success="#34d399", warning="#fbbf24", danger="#f87171",
    danger_soft="rgba(248, 113, 113, 0.14)", scroll="#3d3450", accent_end="#6a30b5",
    window="qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #2a1745, stop:0.5 #16101f, stop:1 #100b17)",
    window_glass=((0.0, "rgba(112, 50, 190, 0.30)"), (0.5, "rgba(26, 16, 42, 0.42)"), (1.0, "rgba(12, 8, 20, 0.58)")),
    dialog="qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #261340, stop:1 #130f1b)",
    popup="#201a2d",
    qss=dict(rail="rgba(222, 200, 255, 0.03)", surface="rgba(222, 200, 255, 0.05)", surface2="rgba(222, 200, 255, 0.08)",
             surface3="rgba(222, 200, 255, 0.125)", border="rgba(222, 200, 255, 0.085)", border_hover="rgba(222, 200, 255, 0.22)",
             scroll="rgba(222, 200, 255, 0.22)"))

LIGHT = Tokens(
    "light", bg="#fdf2f7", rail="#fceaf2", surface="#fff7fa", surface2="#f8e4ee", surface3="#f0d6e4", card="#ffffff",
    border="#f0d3e2", border_hover="#dcaac4", text="#2a1822", dim="#6b4a5a", muted="#9a7888",
    accent="#c93d7b", accent_hover="#bb3472", accent_press="#a02c66", accent_text="#a8285f",
    soft="rgba(201, 61, 123, 0.13)", on_accent="#ffffff", success="#15a26b", warning="#d99100", danger="#dc4a4a",
    danger_soft="rgba(220, 74, 74, 0.10)", scroll="#e2bcd1", accent_end="#a92f68",
    window="qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #fbdcea, stop:0.5 #fdf2f7, stop:1 #fff8fb)",
    window_glass=((0.0, "rgba(250, 214, 230, 0.84)"), (0.5, "rgba(253, 242, 247, 0.88)"), (1.0, "rgba(255, 248, 251, 0.92)")),   # mostly opaque: the backdrop follows the system theme, not ours
    dialog="qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #fcdfeb, stop:1 #fff5f9)",
    popup="#ffffff",
    qss=dict(rail="rgba(255, 255, 255, 0.4)", surface="rgba(255, 255, 255, 0.68)", surface2="rgba(201, 61, 123, 0.07)",
             surface3="rgba(201, 61, 123, 0.13)", border="rgba(160, 50, 100, 0.14)", border_hover="rgba(160, 50, 100, 0.32)",
             scroll="rgba(160, 50, 100, 0.28)"))

# --- the custom theme: four colours chosen by the user, everything else derived and kept readable ---------------------------

DEFAULT_CUSTOM = {"bg": "#0f1a1f", "panel": "#182830", "text": "#e6f1f4", "accent": "#2fb8a6"}


def _norm_hex(value, fallback: str) -> str:
    text = str(value or "").strip()
    return text.lower() if re.fullmatch(r"#[0-9a-fA-F]{6}", text) else fallback


def _rgb(hex_color: str) -> tuple[int, int, int]:
    return int(hex_color[1:3], 16), int(hex_color[3:5], 16), int(hex_color[5:7], 16)


def _hex(rgb) -> str:
    return "#" + "".join(f"{max(0, min(255, round(c))):02x}" for c in rgb)


def mix(a: str, b: str, t: float) -> str:
    """t = 0 gives a, t = 1 gives b."""
    return _hex(tuple(x * (1 - t) + y * t for x, y in zip(_rgb(a), _rgb(b))))


def _luminance(hex_color: str) -> float:
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in (v / 255 for v in _rgb(hex_color))]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def contrast(a: str, b: str) -> float:
    hi, lo = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def _rgba(hex_color: str, alpha: float) -> str:
    r, g, b = _rgb(hex_color)
    return f"rgba({r}, {g}, {b}, {alpha})"


def readable(color: str, backgrounds: list[str], minimum: float) -> str:
    """`color`, moved towards white (on dark backgrounds) or black (on light ones) until it reads on all of `backgrounds`."""
    dark_bg = sum(_luminance(b) for b in backgrounds) / len(backgrounds) < 0.18
    target = "#ffffff" if dark_bg else "#000000"
    for step in range(0, 21):
        candidate = mix(color, target, step / 20)
        if all(contrast(candidate, b) >= minimum for b in backgrounds):
            return candidate
    return target


def build_custom(colors: dict | None) -> Tokens:
    """Tokens from four colours (bg, panel, text, accent). Text, secondary text, accent text and the text on buttons are corrected
    so that they stay readable whatever the user picks."""
    c = {k: _norm_hex((colors or {}).get(k), v) for k, v in DEFAULT_CUSTOM.items()}
    bg, panel, accent = c["bg"], c["panel"], c["accent"]
    dark = _luminance(bg) < 0.18
    surface = mix(bg, panel, 0.85)
    surface2, surface3 = mix(surface, c["text"], 0.07), mix(surface, c["text"], 0.12)
    floor = [bg, surface, surface3]
    text = readable(c["text"], floor, 7.2)
    dim = readable(mix(text, bg, 0.35), floor, 4.7)
    muted = mix(text, bg, 0.55)
    on_accent = "#ffffff" if contrast("#ffffff", accent) >= contrast("#000000", accent) else "#000000"
    for _ in range(20):                                            # a pale accent under white text (or the opposite): shift it
        if contrast(on_accent, accent) >= 4.6:
            break
        accent = mix(accent, "#000000" if on_accent == "#ffffff" else "#ffffff", 0.06)
    sign = -1 if on_accent == "#ffffff" else 1                     # towards the side that keeps the text on it readable
    shade = lambda t: mix(accent, "#000000" if sign < 0 else "#ffffff", abs(t))
    accent_text = readable(accent, [bg, surface], 4.6)
    if dark:
        window = f"qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {mix(bg, accent, 0.2)}, stop:0.5 {bg}, stop:1 {mix(bg, '#000000', 0.25)})"
        glass = ((0.0, _rgba(mix(bg, accent, 0.35), 0.4)), (0.5, _rgba(bg, 0.45)), (1.0, _rgba(mix(bg, "#000000", 0.3), 0.6)))
        popup = mix(bg, text, 0.08)
    else:
        window = f"qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {mix(bg, accent, 0.14)}, stop:0.5 {bg}, stop:1 {mix(bg, '#ffffff', 0.5)})"
        glass = ((0.0, _rgba(mix(bg, accent, 0.14), 0.84)), (0.5, _rgba(bg, 0.88)), (1.0, _rgba(mix(bg, "#ffffff", 0.5), 0.92)))
        popup = mix(bg, "#ffffff", 0.7)
    return Tokens(
        "custom", bg=bg, rail=mix(bg, panel, 0.5), surface=surface, surface2=surface2, surface3=surface3, card=panel,
        border=mix(bg, text, 0.13), border_hover=mix(bg, text, 0.3), text=text, dim=dim, muted=muted,
        accent=accent, accent_hover=shade(0.08), accent_press=shade(0.16), accent_text=accent_text,
        soft=_rgba(accent, 0.22 if dark else 0.14), on_accent=on_accent, success="#34d399" if dark else "#15a26b",
        warning="#fbbf24" if dark else "#d99100", danger=readable("#f87171" if dark else "#dc4a4a", [bg], 3.2),
        danger_soft="rgba(248, 113, 113, 0.14)" if dark else "rgba(220, 74, 74, 0.10)", scroll=mix(bg, text, 0.22),
        accent_end=shade(0.2), window=window, window_glass=glass,
        dialog=f"qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {mix(bg, accent, 0.12)}, stop:1 {bg})", popup=popup,
        qss=dict(rail=_rgba(panel, 0.45), surface=_rgba(panel, 0.85), surface2=_rgba(text, 0.07), surface3=_rgba(text, 0.12),
                 border=_rgba(text, 0.1), border_hover=_rgba(text, 0.26), scroll=_rgba(text, 0.22)),
        mode_dark=dark)


_custom_colors: dict = dict(DEFAULT_CUSTOM)


def set_custom_colors(colors: dict | None) -> None:
    _custom_colors.clear()
    _custom_colors.update({k: _norm_hex((colors or {}).get(k), v) for k, v in DEFAULT_CUSTOM.items()})


def custom_colors() -> dict:
    return dict(_custom_colors)


def logo_colors() -> tuple[str, str]:
    """The two ends of the logo's gradient in the current theme."""
    t = _current
    if t.name == "light":
        return "#f59bc0", "#c93d7b"
    if t.name == "custom":
        return mix(t.accent, "#ffffff", 0.25), t.accent
    return "#b07bff", "#7a38d8"


_current: Tokens = DARK
_glass: bool = False


def css_color(value: str) -> QColor:
    """Tokens hold CSS colours; QColor does not understand rgba(r, g, b, a)."""
    m = re.match(r"rgba\((\d+),\s*(\d+),\s*(\d+),\s*([\d.]+)\)", value)
    if m:
        return QColor(int(m[1]), int(m[2]), int(m[3]), round(float(m[4]) * 255))
    return QColor(value)
_title_filter: "TitleBarFilter | None" = None


def current() -> Tokens:
    return _current


# --- assets referenced from the stylesheet (Qt needs files for `image: url()`) -----------------------------------

def _write_assets(t: Tokens) -> dict[str, str]:
    from anihub.ui.icons import _svg

    folder = config_dir() / "theme_cache" / t.name
    folder.mkdir(parents=True, exist_ok=True)
    specs = {"chevron_down": ("chevron-down", t.dim, 2.4), "chevron_up": ("chevron-up", t.dim, 2.4),
             "chevron_right": ("chevron-down", t.dim, 2.4), "check": ("check", "#ffffff", 3.2)}
    assets = {}
    for key, (name, color, stroke) in specs.items():
        path = folder / f"{key}.svg"
        svg = _svg(name, color, stroke)
        if key == "chevron_right":  # rotate the down chevron by 90 degrees for collapsed tree branches
            svg = svg.replace(b'viewBox="0 0 24 24"', b'viewBox="0 0 24 24"').replace(
                b">", b'><g transform="rotate(-90 12 12)">', 1).replace(b"</svg>", b"</g></svg>")
        path.write_bytes(svg)
        assets[key] = path.as_posix()
    return assets


QSS = Template(r"""
* { outline: 0; }
QWidget { color: $text; }
QMainWindow { background: $window; }
QDialog, QWizard, QMessageBox { background: $dialog; }
QWidget#navRail { background: $rail; border: 0; }
QStatusBar { background: transparent; color: $dim; border: 0; }
QStatusBar::item { border: 0; }
QStatusBar QLabel { padding: 0 12px; color: $dim; }
QToolTip { background: $popup; color: $text; border: 1px solid $border_hover; border-radius: 8px; padding: 6px 10px; }
QLabel { background: transparent; }
QLabel#thumbHolder { background: $surface2; border: 0; border-radius: 12px; color: $muted; }
QFrame#card { background: $surface; border: 1px solid $border; border-radius: 16px; }
QFrame#chip { background: $surface2; border: 0; border-radius: 15px; }
QFrame#chip QLabel { background: transparent; }
QLabel[role="muted"] { color: $muted; }
QLabel[role="dim"] { color: $dim; }
QLabel[role="title"] { font-size: 22px; font-weight: 700; }
QLabel[role="h2"] { font-size: 15px; font-weight: 600; }
QLabel[role="h3"] { font-size: 14px; font-weight: 600; }
QLabel[role="error"] { color: $danger; }
QLabel[role="chip"] { background: $surface3; color: $dim; border-radius: 9px; padding: 2px 10px; }

QPushButton { background: $surface2; border: 1px solid transparent; border-radius: 10px; padding: 7px 16px; min-height: 18px; }
QPushButton:hover { background: $surface3; border-color: $border_hover; }
QPushButton:pressed { background: $border_hover; }
QPushButton:disabled { color: $muted; background: transparent; border-color: $border; }
QPushButton:checked { background: $soft; border-color: $accent; color: $accent_text; }
QPushButton::menu-indicator { image: none; width: 0; }
QPushButton[variant="primary"], QPushButton:default { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 $accent, stop:1 $accent_end);
    border: 1px solid transparent; color: $on_accent; font-weight: 600; }
QPushButton[variant="primary"]:hover, QPushButton:default:hover { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 $accent_hover, stop:1 $accent_end); }
QPushButton[variant="primary"]:pressed, QPushButton:default:pressed { background: $accent_press; }
QPushButton[variant="primary"]:disabled, QPushButton:default:disabled { background: $soft; border-color: transparent; color: $muted; }
QPushButton[variant="ghost"] { background: transparent; border-color: transparent; color: $dim; }
QPushButton[variant="ghost"]:hover { background: $surface3; color: $text; }
QPushButton[variant="ghost"]:disabled { color: $muted; }
QPushButton[variant="danger"] { background: transparent; border-color: $danger; color: $danger; }
QPushButton[variant="danger"]:hover { background: $danger_soft; }
QPushButton[variant="danger"]:disabled { border-color: $border; color: $muted; }
QToolButton { background: transparent; border: 0; border-radius: 10px; padding: 6px; }
QToolButton:hover { background: $surface3; }
QToolButton[viewer="true"] { background: $surface2; border: 0; border-radius: 14px; padding: 0; }
QToolButton[viewer="true"]:hover { background: $surface3; }
QToolButton[viewer="true"]:checked { background: $soft; border-color: $accent; }
QToolButton[viewer="true"]:disabled { background: transparent; border-color: transparent; }
QFrame#coach { background: $popup; border: 1px solid $border_hover; border-radius: 18px; }
QDialog#palette { background: $popup; border: 1px solid $border_hover; border-radius: 16px; }
QLabel#offlineBanner { background: $soft; border: 1px solid $warning; border-radius: 8px; padding: 8px 12px; color: $text; }
QToolButton#updateNotice { border-radius: 10px; padding: 3px 10px; color: $accent_text; font-weight: 600; }
QToolButton#offlineToggle { border-radius: 10px; padding: 3px 10px; color: $dim; }
QToolButton#offlineToggle:checked { background: $soft; color: $text; }
QToolButton[tagbtn="true"] { background: $surface2; border: 0; border-radius: 7px; padding: 0; color: $dim; font-weight: 700; }
QToolButton[tagbtn="true"]:hover { background: $soft; border-color: $accent; color: $accent_text; }
QToolButton[chipbtn="true"] { background: $surface2; border: 1px solid transparent; border-radius: 10px; padding: 7px 26px 7px 14px; color: $text; }
QToolButton[chipbtn="true"]:hover { background: $surface3; }
QToolButton[chipbtn="true"]::menu-indicator { image: url("$chevron_down"); subcontrol-position: right center; subcontrol-origin: padding; right: 8px; width: 12px; height: 12px; }
QToolButton[section="true"] { background: transparent; border: 0; padding: 4px 2px; font-weight: 600; color: $text; text-align: left; }
QToolButton[section="true"]:hover { color: $accent_text; }
QPushButton[chip="true"] { border-radius: 14px; padding: 4px 12px; min-height: 0; background: $surface2; border: 1px solid transparent; color: $dim; }
QPushButton[chip="true"]:hover { border-color: $border_hover; color: $text; }
QPushButton[chip="true"][chipState="include"] { background: $soft; border-color: $accent; color: $accent_text; }
QPushButton[chip="true"][chipState="exclude"] { background: $danger_soft; border-color: $danger; color: $danger; }

QLineEdit, QPlainTextEdit, QTextEdit, QTextBrowser, QSpinBox, QDoubleSpinBox, QTimeEdit, QDateEdit, QComboBox {
    background: $surface2; border: 1px solid transparent; border-radius: 10px; padding: 7px 12px;
    selection-background-color: $accent; selection-color: #ffffff; }
QPlainTextEdit, QTextEdit, QTextBrowser { padding: 8px; }
QLineEdit:hover, QPlainTextEdit:hover, QTextEdit:hover, QSpinBox:hover, QDoubleSpinBox:hover, QTimeEdit:hover, QComboBox:hover { border-color: $border; }
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QTimeEdit:focus, QComboBox:focus, QComboBox:on { border-color: $accent; }
QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled, QComboBox:disabled, QTimeEdit:disabled { color: $muted; background: $surface; }
QComboBox { padding-right: 28px; }
QComboBox::drop-down { border: 0; width: 26px; subcontrol-origin: padding; subcontrol-position: right center; }
QComboBox::down-arrow { image: url("$chevron_down"); width: 14px; height: 14px; }
QComboBox QAbstractItemView { background: $popup; border: 1px solid $border_hover; border-radius: 10px; padding: 4px;
    selection-background-color: $soft; selection-color: $text; outline: 0; }
QSpinBox, QDoubleSpinBox, QTimeEdit { padding-right: 22px; }
QSpinBox::up-button, QDoubleSpinBox::up-button, QTimeEdit::up-button { subcontrol-origin: border; subcontrol-position: top right; width: 20px; border: 0; background: transparent; }
QSpinBox::down-button, QDoubleSpinBox::down-button, QTimeEdit::down-button { subcontrol-origin: border; subcontrol-position: bottom right; width: 20px; border: 0; background: transparent; }
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow, QTimeEdit::up-arrow { image: url("$chevron_up"); width: 10px; height: 10px; }
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow, QTimeEdit::down-arrow { image: url("$chevron_down"); width: 10px; height: 10px; }

QCheckBox, QRadioButton { spacing: 9px; background: transparent; }
QCheckBox::indicator { width: 18px; height: 18px; border-radius: 5px; border: 1px solid $border_hover; background: $surface2; }
QCheckBox::indicator:hover { border-color: $accent; }
QCheckBox::indicator:checked { background: $accent; border-color: $accent; image: url("$check"); }
QCheckBox::indicator:indeterminate { background: $soft; border-color: $accent; }
QCheckBox::indicator:disabled { background: $surface; border-color: $border; }
QRadioButton::indicator { width: 16px; height: 16px; border-radius: 9px; border: 1px solid $border_hover; background: $surface2; }
QRadioButton::indicator:hover { border-color: $accent; }
QRadioButton::indicator:checked { width: 8px; height: 8px; border: 5px solid $accent; background: #ffffff; }
QGroupBox::indicator { width: 18px; height: 18px; border-radius: 5px; border: 1px solid $border_hover; background: $surface2; }
QGroupBox::indicator:checked { background: $accent; border-color: $accent; image: url("$check"); }

QGroupBox { background: $surface; border: 0; border-radius: 16px; margin-top: 6px; padding: 34px 14px 14px 14px; }
QGroupBox::title { subcontrol-origin: padding; subcontrol-position: top left; left: 16px; top: 10px; color: $accent_text; font-weight: 600; }

QTabWidget::pane { border: 0; top: -1px; }
QTabBar { background: transparent; }
QTabBar::tab { background: transparent; color: $dim; padding: 9px 16px; margin-right: 4px; border: 0; border-bottom: 2px solid transparent; }
QTabBar::tab:hover { color: $text; }
QTabBar::tab:selected { color: $text; border-bottom: 2px solid $accent; }
QTabBar::tab:disabled { color: $muted; }

QScrollArea, QScrollArea > QWidget > QWidget { border: 0; background: transparent; }
QScrollBar:vertical { background: transparent; width: 12px; margin: 2px; }
QScrollBar::handle:vertical { background: $scroll; border-radius: 4px; min-height: 36px; margin: 0 2px; }
QScrollBar::handle:vertical:hover { background: $muted; }
QScrollBar:horizontal { background: transparent; height: 12px; margin: 2px; }
QScrollBar::handle:horizontal { background: $scroll; border-radius: 4px; min-width: 36px; margin: 2px 0; }
QScrollBar::handle:horizontal:hover { background: $muted; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; background: none; }
QScrollBar::add-page, QScrollBar::sub-page { background: none; }

QListView, QListWidget, QTreeView, QTreeWidget, QTableView, QTableWidget {
    background: $surface; border: 0; border-radius: 14px; alternate-background-color: transparent; padding: 4px;
    selection-background-color: transparent; selection-color: $text; }
QListView::item, QTreeView::item { padding: 6px 8px; border-radius: 7px; margin: 1px 2px; }
QListView::item:hover, QTreeView::item:hover { background: $surface3; }
QListView::item:selected, QTreeView::item:selected { background: $soft; color: $text; }
QTreeView::branch, QTreeView::branch:selected, QTreeView::branch:hover { background: transparent; }
QTreeView::branch:has-children:!has-siblings:closed, QTreeView::branch:closed:has-children:has-siblings { image: url("$chevron_right"); }
QTreeView::branch:open:has-children:!has-siblings, QTreeView::branch:open:has-children:has-siblings { image: url("$chevron_down"); }
QListWidget#thumbGrid { background: transparent; border: 0; padding: 0; }
QListWidget#tagList::item { padding: 0 6px; margin: 0 2px; }
QListWidget#tagList::item:hover { background: transparent; }
QListWidget#thumbGrid::item, QListWidget#thumbGrid::item:hover, QListWidget#thumbGrid::item:selected { background: transparent; }
QTreeWidget#sideTree { background: $surface; border: 0; }
QHeaderView::section { background: transparent; color: $dim; border: 0; border-bottom: 1px solid $border; padding: 8px 10px; }
QTableView { gridline-color: $border; }
QTableCornerButton::section { background: transparent; border: 0; }

QMenu { background: $popup; border: 1px solid $border_hover; border-radius: 12px; padding: 6px; }
QMenu::item { padding: 7px 28px 7px 12px; border-radius: 8px; margin: 1px 2px; }
QMenu::item:selected { background: $soft; color: $text; }
QMenu::item:disabled { color: $muted; }
QMenu::separator { height: 1px; background: $border; margin: 6px 8px; }
QMenu::icon { padding-left: 8px; }

QProgressBar { background: $surface3; border: 0; border-radius: 4px; max-height: 8px; min-height: 8px; qproperty-textVisible: false; }
QProgressBar::chunk { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 $accent, stop:1 $accent_text); border-radius: 4px; }
QSlider::groove:horizontal { height: 4px; background: $surface3; border-radius: 2px; }
QSlider::sub-page:horizontal { background: $accent; border-radius: 2px; }
QSlider::handle:horizontal { background: $accent; width: 14px; height: 14px; margin: -5px 0; border-radius: 7px; }
QSplitter::handle { background: transparent; }
QSplitter::handle:horizontal { width: 8px; }
QFrame[frameShape="4"], QFrame[frameShape="5"] { color: $border; }
QDialogButtonBox QPushButton { min-width: 84px; }
QWizard QLabel#qt_wizard_title { font-size: 18px; font-weight: 700; }
QCalendarWidget QWidget { background: $popup; }
""")


def _palette(t: Tokens) -> QPalette:
    p = QPalette()
    roles = {
        QPalette.ColorRole.Window: t.bg, QPalette.ColorRole.WindowText: t.text, QPalette.ColorRole.Base: t.surface2,
        QPalette.ColorRole.AlternateBase: t.surface, QPalette.ColorRole.Text: t.text, QPalette.ColorRole.Button: t.surface2,
        QPalette.ColorRole.ButtonText: t.text, QPalette.ColorRole.ToolTipBase: t.surface3,
        QPalette.ColorRole.ToolTipText: t.text, QPalette.ColorRole.Highlight: t.accent,
        QPalette.ColorRole.HighlightedText: "#ffffff", QPalette.ColorRole.PlaceholderText: t.muted,
        QPalette.ColorRole.Link: t.accent_text, QPalette.ColorRole.BrightText: "#ffffff",
    }
    for role, color in roles.items():
        p.setColor(role, QColor(color))
    if _glass:                                # the window's own colour must not paint over the Windows backdrop
        p.setColor(QPalette.ColorRole.Window, QColor(0, 0, 0, 0))
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText, QPalette.ColorRole.WindowText):
        p.setColor(QPalette.ColorGroup.Disabled, role, QColor(t.muted))
    return p


def resolve(mode: str, app: QApplication) -> Tokens:
    if mode == "system":
        mode = "dark" if app.styleHints().colorScheme() == Qt.ColorScheme.Dark else "light"
    if mode == "custom":
        return build_custom(_custom_colors)
    return DARK if mode == "dark" else LIGHT


def glass_supported() -> bool:
    """Mica / Acrylic need Windows 11 22H2 (build 22621) or newer."""
    if sys.platform != "win32":
        return False
    try:
        return sys.getwindowsversion().build >= 22621
    except AttributeError:
        return False


def is_glass() -> bool:
    return _glass


def apply_theme(app: QApplication, mode: str, glass: bool | None = None) -> None:
    """Colours and stylesheet. `glass` (Windows backdrop under a translucent main window) keeps its last value when omitted."""
    global _current, _title_filter, _glass
    if glass is not None:
        _glass = bool(glass) and glass_supported()
    t = resolve(mode, app)
    _current = t
    from anihub.ui import icons

    icons.clear_cache()
    app.setStyle("Fusion")
    app.setPalette(_palette(t))
    font = app.font()
    font.setFamilies(["Segoe UI Variable Text", "Segoe UI", "Inter", "Yu Gothic UI", "Microsoft YaHei UI", "Malgun Gothic", "Arial"])
    font.setPointSizeF(10.0)
    font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    app.setFont(font)
    values = {f: getattr(t, f) for f in t.__dataclass_fields__ if f not in ("name", "qss")}
    values.update(t.qss)                      # stylesheet surfaces are the translucent ones
    values["window"] = "transparent" if _glass else t.window
    app.setStyleSheet(QSS.substitute(**values, **_write_assets(t)))
    if _title_filter is None:
        _title_filter = TitleBarFilter()
        app.installEventFilter(_title_filter)
    _title_filter.tokens = t
    for widget in app.topLevelWidgets():
        if widget.isVisible():
            set_title_bar(widget, t)
        if isinstance(widget, QMainWindow):
            apply_backdrop(widget)
    from anihub.ui import navrail, style  # recolour icons that were created under the previous theme

    style.refresh_icons()
    navrail.refresh_rails()


# --- Windows title bar in the theme's colours -----------------------------------------------------------------------

def set_title_bar(widget: QWidget, t: Tokens) -> None:
    if sys.platform != "win32":
        return
    try:
        hwnd = int(widget.winId())
        dwm = ctypes.windll.dwmapi

        def attr(index: int, value: int) -> None:
            v = ctypes.c_int(value)
            dwm.DwmSetWindowAttribute(hwnd, index, ctypes.byref(v), ctypes.sizeof(v))

        def colorref(hex_color: str) -> int:
            c = QColor(hex_color)
            return c.red() | (c.green() << 8) | (c.blue() << 16)

        attr(20, 1 if t.dark else 0)          # DWMWA_USE_IMMERSIVE_DARK_MODE
        if not _glass:
            attr(35, colorref(t.rail))        # DWMWA_CAPTION_COLOR (Windows 11)
        attr(36, colorref(t.text))            # DWMWA_TEXT_COLOR
        attr(34, colorref(t.border))          # DWMWA_BORDER_COLOR
    except (OSError, AttributeError, ValueError):
        pass


DWMWA_SYSTEMBACKDROP_TYPE = 38
BACKDROP_NONE, BACKDROP_MICA, BACKDROP_ACRYLIC = 1, 2, 3


class _Margins(ctypes.Structure):
    _fields_ = [("left", ctypes.c_int), ("right", ctypes.c_int), ("top", ctypes.c_int), ("bottom", ctypes.c_int)]


_STOP = re.compile(r"stop:\s*([\d.]+)\s+(#[0-9a-fA-F]{6})")
_backdrop_cache: dict[tuple, QPixmap] = {}
_noise_tile: QPixmap | None = None
SPARKLES = ((0.94, 0.30, 7), (0.975, 0.38, 4), (0.905, 0.42, 3), (0.975, 0.78, 5), (0.925, 0.93, 4), (0.70, 0.955, 3))
# a loose scatter of small dots near the top-right corner (fractional x, y, radius in px): fixed, not random each frame
DOTS = ((0.80, 0.08, 2.2), (0.84, 0.14, 1.6), (0.90, 0.06, 1.8), (0.87, 0.20, 1.3), (0.93, 0.15, 2.0),
        (0.96, 0.24, 1.4), (0.78, 0.18, 1.5), (0.91, 0.28, 1.7), (0.965, 0.10, 1.2), (0.83, 0.05, 1.1))


def _smooth_stops(stops: list[tuple[float, QColor]], steps: int = 28) -> list[tuple[float, QColor]]:
    """The gradient's few stops resampled with an ease in between: two- and three-stop gradients show visible bands (and a hard edge at
    every stop), an eased one with many stops does not."""
    stops = sorted(stops, key=lambda s: s[0])
    out = []
    for i in range(steps + 1):
        pos = i / steps
        lo = max((s for s in stops if s[0] <= pos), key=lambda s: s[0], default=stops[0])
        hi = min((s for s in stops if s[0] >= pos), key=lambda s: s[0], default=stops[-1])
        span = hi[0] - lo[0]
        f = 0.0 if span <= 0 else (pos - lo[0]) / span
        f = f * f * (3 - 2 * f)                                       # smoothstep
        mix_ = lambda a, b: round(a + (b - a) * f)                    # noqa: E731
        out.append((pos, QColor(mix_(lo[1].red(), hi[1].red()), mix_(lo[1].green(), hi[1].green()), mix_(lo[1].blue(), hi[1].blue()),
                                mix_(lo[1].alpha(), hi[1].alpha()))))
    return out


def _noise() -> QPixmap:
    """A tile of almost invisible noise: laid over the gradient it breaks up the 8-bit steps (dithering)."""
    global _noise_tile
    if _noise_tile is None:
        import random

        rnd = random.Random(7)
        img = QImage(128, 128, QImage.Format.Format_ARGB32)
        for y in range(128):
            for x in range(128):
                v = 255 if rnd.random() < 0.5 else 0
                img.setPixelColor(x, y, QColor(v, v, v, rnd.randint(0, 5)))
        _noise_tile = QPixmap.fromImage(img)
    return _noise_tile


def _pattern(painter: QPainter, t: Tokens, w: float, h: float) -> None:
    """A faint decorative wash in the corners the sparkles don't already cover: one thin meandering line low-left,
    a scatter of tiny dots top-right -- the same idea as the sparkles, just with more variety so the empty space
    reads as designed rather than flat."""
    base = QColor(t.accent_text if t.dark else t.accent)

    line = QColor(base)
    line.setAlphaF(0.11 if t.dark else 0.08)
    pen = QPen(line)
    pen.setWidthF(max(1.0, min(w, h) * 0.0012))
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    path = QPainterPath()
    path.moveTo(-w * 0.05, h * 0.62)
    path.cubicTo(w * 0.10, h * 0.55, w * 0.16, h * 0.74, w * 0.28, h * 0.68)
    path.cubicTo(w * 0.38, h * 0.63, w * 0.40, h * 0.80, w * 0.50, h * 0.76)
    painter.drawPath(path)

    painter.setPen(Qt.PenStyle.NoPen)
    dot = QColor(base)
    for x, y, r in DOTS:
        dot.setAlphaF((0.15 if t.dark else 0.11) * min(1.0, r / 2.2))
        painter.setBrush(dot)
        painter.drawEllipse(QPointF(w * x, h * y), r, r)


def _backdrop(t: Tokens, w: int, h: int, glass: bool, dpr: float) -> QPixmap:
    pm = QPixmap(int(w * dpr), int(h * dpr))
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.GlobalColor.transparent)
    stops = [(p, css_color(c)) for p, c in t.window_glass] if glass else [(float(p), QColor(c)) for p, c in _STOP.findall(t.window)] or \
        [(0.0, QColor(t.bg)), (1.0, QColor(t.bg))]
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    gradient = QLinearGradient(0, 0, w, h)
    for pos, color in _smooth_stops(stops):
        gradient.setColorAt(pos, color)
    painter.fillRect(QRectF(0, 0, w, h), gradient)
    # two soft glows of the accent colour: the light comes from the corners, the middle stays calm
    accent, end = QColor(t.accent), QColor(t.accent_end)
    for (cx, cy), radius, color, alpha in (((0.06, 0.0), 0.75, accent, 0.20 if t.dark else 0.10), ((1.0, 1.0), 0.6, end, 0.13 if t.dark else 0.07)):
        glow = QRadialGradient(w * cx, h * cy, max(w, h) * radius)
        for k in range(9):
            f = k / 8
            c = QColor(color)
            c.setAlphaF(alpha * (1 - f) ** 2.2)                       # a long, gentle fall-off
            glow.setColorAt(f, c)
        painter.fillRect(QRectF(0, 0, w, h), glow)
    # a few tiny sparkles near the corners: the small detail that makes the empty space feel finished
    spark = QColor(t.accent_text if t.dark else t.accent)
    painter.setPen(Qt.PenStyle.NoPen)
    for x, y, size in SPARKLES:
        c = QColor(spark)
        c.setAlphaF(0.20 if t.dark else 0.16)
        painter.setBrush(c)
        cx, cy, r = w * x, h * y, size
        star = QPainterPath()
        star.moveTo(cx, cy - r)
        for dx, dy in ((r * 0.16, -r * 0.16), (r, 0), (r * 0.16, r * 0.16), (0, r), (-r * 0.16, r * 0.16), (-r, 0), (-r * 0.16, -r * 0.16)):
            star.lineTo(cx + dx, cy + dy)
        star.closeSubpath()
        painter.drawPath(star)
    _pattern(painter, t, w, h)
    painter.setOpacity(0.55)
    painter.drawTiledPixmap(QRectF(0, 0, w, h).toRect(), _noise())
    painter.end()
    return pm


def paint_backdrop(widget: QWidget) -> None:
    """The window background: the theme's gradient (eased and dithered, so it is smooth), soft glows of the accent colour and a few
    sparkles. Opaque, or translucent over the Windows backdrop in glass mode. Rendered once per size and theme, then just copied."""
    t, glass = _current, _glass
    w, h = widget.width(), widget.height()
    dpr = widget.devicePixelRatioF()
    key = (t.name, t.bg, t.accent, t.accent_end, t.window, t.window_glass, glass, w, h, dpr)
    pm = _backdrop_cache.get(key)
    if pm is None:
        if len(_backdrop_cache) > 6:
            _backdrop_cache.clear()
        pm = _backdrop_cache[key] = _backdrop(t, w, h, glass, dpr)
    painter = QPainter(widget)
    if not glass:
        painter.fillRect(widget.rect(), QColor(t.bg))                  # the glass mode's alpha must not pile up on an old frame
    painter.drawPixmap(0, 0, pm)
    painter.end()


def paint_glass(widget: QWidget) -> None:
    """Kept for the callers that used the glass painting by name."""
    paint_backdrop(widget)


def apply_backdrop(window: QWidget, kind: int | None = None) -> bool:
    """Puts (or removes) the Windows 11 Mica / Acrylic material behind a top-level window. Returns whether DWM accepted it.
    A window is translucent only while the effect is on, so the opaque look stays exactly as before when it is off."""
    on = _glass
    if kind is None:
        kind = BACKDROP_MICA if on else BACKDROP_NONE
    was = window.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    if not on and not was:
        return False                          # nothing to undo
    if was != on:
        visible = window.isVisible()
        if visible:
            window.hide()                     # the native window must be recreated to change its alpha
        window.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, on)
        if visible:
            window.show()
    if sys.platform != "win32":
        return False
    try:
        hwnd = int(window.winId())
        dwm = ctypes.windll.dwmapi
        value = ctypes.c_int(kind)
        hr = dwm.DwmSetWindowAttribute(hwnd, DWMWA_SYSTEMBACKDROP_TYPE, ctypes.byref(value), ctypes.sizeof(value))
        margins = _Margins(-1, -1, -1, -1) if on else _Margins(0, 0, 0, 0)
        dwm.DwmExtendFrameIntoClientArea(hwnd, ctypes.byref(margins))
        caption = ctypes.c_uint(0xFFFFFFFE if on else 0xFFFFFFFF)          # DWMWA_COLOR_NONE (see-through) / DEFAULT
        dwm.DwmSetWindowAttribute(hwnd, 35, ctypes.byref(caption), ctypes.sizeof(caption))
        set_title_bar(window, current())
        return hr == 0
    except (OSError, AttributeError, ValueError):
        return False


class TitleBarFilter(QObject):
    tokens: Tokens = DARK

    def eventFilter(self, obj, event) -> bool:
        if event.type() == QEvent.Type.Show and isinstance(obj, QWidget) and obj.isWindow():
            set_title_bar(obj, self.tokens)
        return False


def make_app_icon(colors: tuple[str, str] | None = None) -> QIcon:
    icon = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256):
        pm = QPixmap(size, size)
        pm.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pm)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        gradient = QLinearGradient(0, 0, size, size)
        gradient.setColorAt(0, QColor((colors or ("#b07bff", "#7a38d8"))[0]))
        gradient.setColorAt(1, QColor((colors or ("#b07bff", "#7a38d8"))[1]))
        painter.setBrush(gradient)
        painter.setPen(Qt.PenStyle.NoPen)
        radius = size * 0.24
        painter.drawRoundedRect(0, 0, size, size, radius, radius)
        painter.setPen(QColor("white"))
        font = QFont("Segoe UI", 1)
        font.setBold(True)
        font.setPixelSize(int(size * 0.58))
        painter.setFont(font)
        painter.drawText(pm.rect(), Qt.AlignmentFlag.AlignCenter, "A")
        painter.end()
        icon.addPixmap(pm)
    return icon
