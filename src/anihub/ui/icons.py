"""Vector icon set (24x24 stroke icons, Lucide style) rendered in the current theme's colours."""
from __future__ import annotations

from functools import lru_cache

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QIconEngine, QImage, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

_P = {
    "image": '<rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="9" cy="9" r="2"/><path d="m21 15-3.09-3.09a2 2 0 0 0-2.82 0L6 21"/>',
    "book": '<path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z"/><path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z"/>',
    "sparkles": '<path d="M9.937 15.5A2 2 0 0 0 8.5 14.063l-6.135-1.582a.5.5 0 0 1 0-.962L8.5 9.936A2 2 0 0 0 9.937 8.5l1.582-6.135a.5.5 0 0 1 .963 0L14.063 8.5A2 2 0 0 0 15.5 9.937l6.135 1.581a.5.5 0 0 1 0 .964L15.5 14.063a2 2 0 0 0-1.437 1.437l-1.582 6.135a.5.5 0 0 1-.963 0z"/><path d="M20 3v4"/><path d="M22 5h-4"/><path d="M4 17v2"/><path d="M5 18H3"/>',
    "tv": '<rect x="2" y="7" width="20" height="15" rx="2"/><polyline points="17 2 12 7 7 2"/>',
    "sliders": '<line x1="21" x2="14" y1="4" y2="4"/><line x1="10" x2="3" y1="4" y2="4"/><line x1="21" x2="12" y1="12" y2="12"/><line x1="8" x2="3" y1="12" y2="12"/><line x1="21" x2="16" y1="20" y2="20"/><line x1="12" x2="3" y1="20" y2="20"/><line x1="14" x2="14" y1="2" y2="6"/><line x1="8" x2="8" y1="10" y2="14"/><line x1="16" x2="16" y1="18" y2="22"/>',
    "search": '<circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>',
    "download": '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" x2="12" y1="15" y2="3"/>',
    "upload": '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" x2="12" y1="3" y2="15"/>',
    "plus": '<path d="M5 12h14"/><path d="M12 5v14"/>',
    "x": '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>',
    "refresh": '<path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/><path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16"/><path d="M8 16H3v5"/>',
    "heart": '<path d="M19 14c1.49-1.46 3-3.21 3-5.5A5.5 5.5 0 0 0 16.5 3c-1.76 0-3 .5-4.5 2-1.5-1.5-2.74-2-4.5-2A5.5 5.5 0 0 0 2 8.5c0 2.3 1.5 4.05 3 5.5l7 7Z"/>',
    "star": '<polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/>',
    "trash": '<path d="M3 6h18"/><path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6"/><path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2"/>',
    "folder": '<path d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z"/>',
    "play": '<polygon points="6 3 20 12 6 21 6 3"/>',
    "stop": '<rect x="6" y="6" width="12" height="12" rx="1.5"/>',
    "pause": '<rect x="14" y="4" width="4" height="16" rx="1"/><rect x="6" y="4" width="4" height="16" rx="1"/>',
    "list": '<line x1="8" x2="21" y1="6" y2="6"/><line x1="8" x2="21" y1="12" y2="12"/><line x1="8" x2="21" y1="18" y2="18"/><line x1="3" x2="3.01" y1="6" y2="6"/><line x1="3" x2="3.01" y1="12" y2="12"/><line x1="3" x2="3.01" y1="18" y2="18"/>',
    "clock": '<circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>',
    "tag": '<path d="M12.586 2.586A2 2 0 0 0 11.172 2H4a2 2 0 0 0-2 2v7.172a2 2 0 0 0 .586 1.414l8.704 8.704a2.426 2.426 0 0 0 3.42 0l6.58-6.58a2.426 2.426 0 0 0 0-3.42z"/><circle cx="7.5" cy="7.5" r=".5"/>',
    "layers": '<path d="m12.83 2.18a2 2 0 0 0-1.66 0L2.6 6.08a1 1 0 0 0 0 1.83l8.58 3.91a2 2 0 0 0 1.66 0l8.58-3.9a1 1 0 0 0 0-1.83Z"/><path d="m22 17.65-9.17 4.16a2 2 0 0 1-1.66 0L2 17.65"/><path d="m22 12.65-9.17 4.16a2 2 0 0 1-1.66 0L2 12.65"/>',
    "wrench": '<path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/>',
    "more": '<circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/><circle cx="5" cy="12" r="1"/>',
    "zap": '<polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/>',
    "external": '<path d="M15 3h6v6"/><path d="M10 14 21 3"/><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/>',
    "chevron-down": '<path d="m6 9 6 6 6-6"/>',
    "chevron-up": '<path d="m18 15-6-6-6 6"/>',
    "arrow-up": '<path d="m5 12 7-7 7 7"/><path d="M12 19V5"/>',
    "arrow-down": '<path d="M12 5v14"/><path d="m19 12-7 7-7-7"/>',
    "save": '<path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/><polyline points="17 21 17 13 7 13 7 21"/><polyline points="7 3 7 8 15 8"/>',
    "grid": '<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/>',
    "check": '<path d="M20 6 9 17l-5-5"/>',
    "copy": '<rect x="8" y="8" width="14" height="14" rx="2"/><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/>',
    "cloud": '<path d="M17.5 19H9a7 7 0 1 1 6.71-9h1.79a4.5 4.5 0 1 1 0 9Z"/>',
    "chevron-left": '<path d="m15 18-6-6 6-6"/>',
    "chevron-right": '<path d="m9 18 6-6-6-6"/>',
    "chevrons-left": '<path d="m11 17-5-5 5-5"/><path d="m18 17-5-5 5-5"/>',
    "chevrons-right": '<path d="m6 17 5-5-5-5"/><path d="m13 17 5-5-5-5"/>',
    "skip-back": '<polygon points="19 20 9 12 19 4 19 20"/><line x1="5" x2="5" y1="19" y2="5"/>',
    "skip-forward": '<polygon points="5 4 15 12 5 20 5 4"/><line x1="19" x2="19" y1="5" y2="19"/>',
    "maximize": '<path d="M8 3H5a2 2 0 0 0-2 2v3"/><path d="M21 8V5a2 2 0 0 0-2-2h-3"/><path d="M3 16v3a2 2 0 0 0 2 2h3"/><path d="M16 21h3a2 2 0 0 0 2-2v-3"/>',
    "minimize": '<path d="M8 3v3a2 2 0 0 1-2 2H3"/><path d="M21 8h-3a2 2 0 0 1-2-2V3"/><path d="M3 16h3a2 2 0 0 1 2 2v3"/><path d="M16 21v-3a2 2 0 0 1 2-2h3"/>',
    "volume": '<path d="M11 4.702a.705.705 0 0 0-1.203-.498L6.413 7.587A1.4 1.4 0 0 1 5.416 8H3a1 1 0 0 0-1 1v6a1 1 0 0 0 1 1h2.416a1.4 1.4 0 0 1 .997.413l3.383 3.384A.705.705 0 0 0 11 19.298z"/><path d="M16 9a5 5 0 0 1 0 6"/><path d="M19.364 18.364a9 9 0 0 0 0-12.728"/>',
    "volume-x": '<path d="M11 4.702a.705.705 0 0 0-1.203-.498L6.413 7.587A1.4 1.4 0 0 1 5.416 8H3a1 1 0 0 0-1 1v6a1 1 0 0 0 1 1h2.416a1.4 1.4 0 0 1 .997.413l3.383 3.384A.705.705 0 0 0 11 19.298z"/><line x1="22" x2="16" y1="9" y2="15"/><line x1="16" x2="22" y1="9" y2="15"/>',
    "user": '<path d="M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/>',
    "filter": '<polygon points="22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3"/>',
    "columns": '<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M12 3v18"/>',
    "rotate": '<path d="M21 12a9 9 0 1 1-9-9c2.52 0 4.93 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/>',
    "heart-filled": '<path d="M19 14c1.49-1.46 3-3.21 3-5.5A5.5 5.5 0 0 0 16.5 3c-1.76 0-3 .5-4.5 2-1.5-1.5-2.74-2-4.5-2A5.5 5.5 0 0 0 2 8.5c0 2.3 1.5 4.05 3 5.5l7 7Z"/>',
    "star-filled": '<polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/>',
}


def _svg(name: str, color: str, stroke: float) -> bytes:
    body = _P[name]
    fill = "currentColor" if name == "stop" or name.endswith("-filled") else "none"
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="{fill}" '
            f'stroke="{color}" stroke-width="{stroke}" stroke-linecap="round" stroke-linejoin="round" color="{color}">'
            f'{body}</svg>').encode()


_renderers: dict[tuple[str, str, float], QSvgRenderer] = {}


def _renderer(name: str, color: str, stroke: float) -> QSvgRenderer:
    key = (name, color, stroke)
    r = _renderers.get(key)
    if r is None:
        r = _renderers[key] = QSvgRenderer(QByteArray(_svg(name, color, stroke)))
    return r


def _paint_svg(painter: QPainter, rect: QRectF, name: str, color: str, stroke: float) -> None:
    painter.save()
    painter.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform
                           | QPainter.RenderHint.TextAntialiasing)
    _renderer(name, color, stroke).render(painter, rect)
    painter.restore()


@lru_cache(maxsize=512)
def pixmap(name: str, color: str, size: int = 20, stroke: float = 2.0, dpr: float = 2.0) -> QPixmap:
    """The icon as an anti-aliased pixmap of size*dpr device pixels."""
    px = max(1, int(round(size * dpr)))
    image = QImage(px, px, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    _paint_svg(painter, QRectF(0, 0, px, px), name, color, stroke)
    painter.end()
    pm = QPixmap.fromImage(image)
    pm.setDevicePixelRatio(dpr)
    return pm


Look = tuple[str, float]                                   # (colour, stroke width)


class VectorIconEngine(QIconEngine):
    """Paints the SVG straight at the requested size, so the icon is anti-aliased at any DPI (no pixmap rescaling)."""

    def __init__(self, name: str, looks: dict[tuple[QIcon.Mode, QIcon.State], Look], default: Look):
        super().__init__()
        self.name = name
        self.looks = looks
        self.default = default

    def _look(self, mode: QIcon.Mode, state: QIcon.State) -> Look:
        return (self.looks.get((mode, state)) or self.looks.get((mode, QIcon.State.Off))
                or self.looks.get((QIcon.Mode.Normal, state)) or self.default)

    def paint(self, painter: QPainter, rect, mode, state) -> None:  # noqa: D102
        color, stroke = self._look(mode, state)
        _paint_svg(painter, QRectF(rect), self.name, color, stroke)

    def pixmap(self, size, mode, state) -> QPixmap:  # noqa: D102
        image = QImage(size, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        self.paint(painter, image.rect(), mode, state)
        painter.end()
        return QPixmap.fromImage(image)

    def actualSize(self, size, mode, state):  # noqa: D102, N802
        return size

    def clone(self) -> "VectorIconEngine":  # noqa: D102
        return VectorIconEngine(self.name, dict(self.looks), self.default)


def icon(name: str, color: str | None = None, size: int = 20, stroke: float = 2.0) -> QIcon:
    """QIcon with states: normal = the theme's dim text colour (or `color`), disabled = muted, active/selected = accent."""
    from anihub.ui import theme  # late import: theme uses icons for its own assets

    t = theme.current()
    M, S = QIcon.Mode, QIcon.State
    looks = {(M.Normal, S.Off): (color or t.dim, stroke), (M.Disabled, S.Off): (t.muted, stroke),
             (M.Active, S.Off): (color or t.text, stroke), (M.Selected, S.Off): (color or t.accent, stroke)}
    return QIcon(VectorIconEngine(name, looks, looks[(M.Normal, S.Off)]))


def nav_icon(name: str) -> QIcon:
    """Navigation rail icon: dim when idle, bright on hover, accent when its section is selected."""
    from anihub.ui import theme

    t = theme.current()
    M, S = QIcon.Mode, QIcon.State
    looks = {(M.Normal, S.Off): (t.dim, 1.8), (M.Normal, S.On): (t.accent_text, 2.0),
             (M.Active, S.Off): (t.text, 1.8), (M.Active, S.On): (t.accent_text, 2.0)}
    return QIcon(VectorIconEngine(name, looks, looks[(M.Normal, S.Off)]))


def white_icon(name: str, size: int = 18, stroke: float = 2.2) -> QIcon:
    """For buttons on the accent colour."""
    M, S = QIcon.Mode, QIcon.State
    looks = {(M.Normal, S.Off): ("#ffffff", stroke), (M.Active, S.Off): ("#ffffff", stroke),
             (M.Selected, S.Off): ("#ffffff", stroke), (M.Disabled, S.Off): ("#c4b8ff", stroke)}
    return QIcon(VectorIconEngine(name, looks, looks[(M.Normal, S.Off)]))


def clear_cache() -> None:
    """Call after a theme switch."""
    pixmap.cache_clear()
    _renderers.clear()


def color_of(value: str) -> QColor:
    return QColor(value)
