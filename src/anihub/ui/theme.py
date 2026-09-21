"""Design system: colour tokens for the dark and light themes, one application-wide stylesheet, fonts, title bar."""
from __future__ import annotations

import ctypes
import re
import sys
from dataclasses import dataclass, field, replace
from pathlib import Path
from string import Template

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QLinearGradient, QPainter, QPalette, QPixmap
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

    @property
    def dark(self) -> bool:
        return self.name == "dark"


DARK = Tokens(
    "dark", bg="#13121c", rail="#100f18", surface="#1b1a26", surface2="#232230", surface3="#2f2e3d", card="#1d1c29",
    border="#2a2938", border_hover="#413f55", text="#eceaf4", dim="#aeabc0", muted="#726f86",
    accent="#7658f7", accent_hover="#6d50ec", accent_press="#6046dc", accent_text="#b3a3ff",
    soft="rgba(124, 92, 255, 0.22)", on_accent="#ffffff", success="#34d399", warning="#fbbf24", danger="#f87171",
    danger_soft="rgba(248, 113, 113, 0.14)", scroll="#3a3950",
    window="qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #1d1736, stop:0.5 #13121c, stop:1 #0e0e15)",
    window_glass=((0.0, "rgba(86, 60, 196, 0.30)"), (0.5, "rgba(22, 18, 40, 0.42)"), (1.0, "rgba(10, 10, 18, 0.58)")),
    dialog="qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #1b1633, stop:1 #12111a)",
    popup="#1c1a2a",
    qss=dict(rail="rgba(255, 255, 255, 0.025)", surface="rgba(255, 255, 255, 0.045)", surface2="rgba(255, 255, 255, 0.07)",
             surface3="rgba(255, 255, 255, 0.115)", border="rgba(255, 255, 255, 0.075)", border_hover="rgba(255, 255, 255, 0.2)",
             scroll="rgba(255, 255, 255, 0.2)"))

LIGHT = Tokens(
    "light", bg="#f4f2fb", rail="#f6f4fd", surface="#fbfaff", surface2="#efedf9", surface3="#e4e1f3", card="#ffffff",
    border="#e0dcef", border_hover="#c2bddc", text="#1c1a2e", dim="#544f6b", muted="#8a869e",
    accent="#6a4cf5", accent_hover="#5b3de6", accent_press="#4f32d4", accent_text="#5b3de6",
    soft="rgba(106, 76, 245, 0.13)", on_accent="#ffffff", success="#15a26b", warning="#d99100", danger="#dc4a4a",
    danger_soft="rgba(220, 74, 74, 0.10)", scroll="#c9c5de", accent_end="#5230d6",
    window="qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #e9e4fb, stop:0.5 #f4f2fb, stop:1 #f8f7fd)",
    window_glass=((0.0, "rgba(222, 213, 250, 0.84)"), (0.5, "rgba(244, 242, 251, 0.88)"), (1.0, "rgba(250, 249, 255, 0.92)")),   # mostly opaque: the backdrop follows the system theme, not ours
    dialog="qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #e8e3fa, stop:1 #f6f5fc)",
    popup="#ffffff",
    qss=dict(rail="rgba(255, 255, 255, 0.35)", surface="rgba(255, 255, 255, 0.62)", surface2="rgba(90, 70, 190, 0.07)",
             surface3="rgba(90, 70, 190, 0.13)", border="rgba(70, 55, 150, 0.12)", border_hover="rgba(70, 55, 150, 0.3)",
             scroll="rgba(70, 55, 150, 0.25)"))

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
QRadioButton::indicator { width: 18px; height: 18px; border-radius: 10px; border: 1px solid $border_hover; background: $surface2; }
QRadioButton::indicator:checked { border: 5px solid $accent; background: #ffffff; }
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
    font.setFamilies(["Segoe UI Variable Text", "Segoe UI", "Inter", "Arial"])
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


def paint_glass(widget: QWidget) -> None:
    """The translucent violet gradient over the Windows backdrop (call from the main window's paintEvent)."""
    t = _current
    gradient = QLinearGradient(0, 0, widget.width(), widget.height())
    for position, color in t.window_glass:
        gradient.setColorAt(position, css_color(color))
    painter = QPainter(widget)
    painter.fillRect(widget.rect(), gradient)
    painter.end()


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


def make_app_icon() -> QIcon:
    icon = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256):
        pm = QPixmap(size, size)
        pm.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pm)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        gradient = QLinearGradient(0, 0, size, size)
        gradient.setColorAt(0, QColor("#9b7bff"))
        gradient.setColorAt(1, QColor("#5a3ee8"))
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
