"""Statistics dashboard: numbers as cards, the rest as simple bar charts painted by hand."""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import QDialog, QFrame, QGridLayout, QLabel, QScrollArea, QVBoxLayout, QWidget

from anihub.context import AppContext
from anihub.core.i18n import tr
from anihub.services import stats as stats_service
from anihub.services.stats import Stats, human_size
from anihub.ui import style, theme
from anihub.ui.workers import run_async


class BarChart(QWidget):
    """Horizontal bars (labels left, value right) or, with vertical=True, columns (a month per column)."""

    def __init__(self, data: list[tuple[str, int]], vertical: bool = False, parent=None):
        super().__init__(parent)
        self.data, self.vertical = data, vertical
        rows = len(data)
        self.setMinimumHeight(150 if vertical else max(28 * rows, 40))
        self.setMinimumWidth(320)

    def paintEvent(self, _e) -> None:  # noqa: N802
        t = theme.current()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        font = QFont(self.font())
        font.setPixelSize(12)
        p.setFont(font)
        if not self.data:
            p.setPen(QColor(t.muted))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "—")
            return
        top = max(v for _, v in self.data) or 1
        if self.vertical:
            n = len(self.data)
            gap = 6
            w = (self.width() - gap * (n + 1)) / n
            base = self.height() - 22
            for i, (label, value) in enumerate(self.data):
                h = (base - 18) * value / top
                x = gap + i * (w + gap)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(t.accent))
                p.drawRoundedRect(QRectF(x, base - h, w, max(h, 1)), 4, 4)
                p.setPen(QColor(t.dim))
                p.drawText(QRectF(x - 4, base + 3, w + 8, 16), Qt.AlignmentFlag.AlignCenter, label[-2:])
                if value:
                    p.setPen(QColor(t.text))
                    p.drawText(QRectF(x - 6, base - h - 16, w + 12, 14), Qt.AlignmentFlag.AlignCenter, str(value))
            return
        label_w = min(170, int(self.width() * 0.4))
        row_h = 26
        for i, (label, value) in enumerate(self.data):
            y = i * 28
            p.setPen(QColor(t.text))
            p.drawText(QRectF(0, y, label_w - 8, row_h), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                       p.fontMetrics().elidedText(label, Qt.TextElideMode.ElideRight, label_w - 8))
            bar_w = max((self.width() - label_w - 56) * value / top, 2)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(t.accent))
            p.drawRoundedRect(QRectF(label_w, y + 5, bar_w, row_h - 10), 4, 4)
            p.setPen(QColor(t.dim))
            p.drawText(QRectF(label_w + bar_w + 6, y, 50, row_h), Qt.AlignmentFlag.AlignVCenter, str(value))


class StatsDialog(QDialog):
    def __init__(self, ctx: AppContext, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.setWindowTitle(tr("stats.title"))
        self.resize(900, 720)
        self.body = QVBoxLayout()
        self.body.setSpacing(14)
        holder = QWidget()
        holder.setLayout(self.body)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(holder)
        layout = QVBoxLayout(self)
        layout.addWidget(scroll)
        self.body.addWidget(QLabel(tr("status.loading")))
        run_async(lambda: stats_service.collect(ctx.db), on_done=self.show_stats,
                  on_error=lambda exc: self._error(str(exc)))

    def _error(self, msg: str) -> None:
        self._clear()
        self.body.addWidget(QLabel(tr("status.error", msg=msg)))

    def _clear(self) -> None:
        while self.body.count():
            item = self.body.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()

    @staticmethod
    def _card(value: str, caption: str) -> QFrame:
        frame = QFrame()
        frame.setObjectName("card")
        box = QVBoxLayout(frame)
        big = QLabel(value)
        big.setStyleSheet("font-size: 24px; font-weight: 700;")
        small = style.role(QLabel(caption), "dim")
        box.addWidget(big)
        box.addWidget(small)
        return frame

    def show_stats(self, s: Stats) -> None:
        self._clear()
        cards = QGridLayout()
        entries = [(f"{s.items:,}".replace(",", " "), tr("stats.items")), (human_size(s.total_bytes), tr("stats.size")),
                   (str(s.favorites), tr("stats.favorites")), (str(s.rated), tr("stats.rated")),
                   (f"{s.tags_total:,}".replace(",", " "), tr("stats.tags")), (str(s.collections), tr("stats.collections")),
                   (f"{s.novels_finished}/{s.novels}", tr("stats.novels")), (str(s.episodes_watched), tr("stats.episodes")),
                   (str(s.subscriptions), tr("stats.subscriptions")), (str(s.trashed), tr("stats.trash")),
                   (str(s.generations), tr("stats.generations"))]
        for i, (value, caption) in enumerate(entries):
            cards.addWidget(self._card(value, caption), i // 5, i % 5)
        holder = QWidget()
        holder.setLayout(cards)
        self.body.addWidget(holder)
        sections = [(tr("stats.per_month"), BarChart(s.per_month, vertical=True)),
                    (tr("stats.by_source"), BarChart(s.by_source)),
                    (tr("stats.by_rating"), BarChart([(tr(f"rating.{k}") if k in ("general", "sensitive", "questionable", "explicit") else k, v)
                                                      for k, v in sorted(s.by_rating.items(), key=lambda kv: -kv[1])])),
                    (tr("stats.top_tags"), BarChart(s.top_tags)), (tr("stats.top_artists"), BarChart(s.top_artists)),
                    (tr("stats.by_model"), BarChart(s.generations_by_model))]
        for title, chart in sections:
            self.body.addWidget(style.role(QLabel(title), "h2"))
            self.body.addWidget(chart)
        self.body.addStretch(1)
