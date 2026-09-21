"""Source filters (genres, tags, status, sort...) as a side panel, and the source settings / login dialog."""
from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QSize, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QFrame, QHBoxLayout, QLabel, QLayout, QLayoutItem,
    QLineEdit, QPushButton, QScrollArea, QSizePolicy, QToolButton, QVBoxLayout, QWidget,
)

from anihub.core.i18n import tr
from anihub.ui import style
from anihub.ui.workers import run_async

TRI_NEXT = {"IGNORE": "INCLUDE", "INCLUDE": "EXCLUDE", "EXCLUDE": "IGNORE"}


class FlowLayout(QLayout):
    """Left-to-right layout that wraps to the next row (for chips)."""

    def __init__(self, parent=None, spacing: int = 6):
        super().__init__(parent)
        self._items: list[QLayoutItem] = []
        self.setContentsMargins(0, 0, 0, 0)
        self._spacing = spacing

    def addItem(self, item: QLayoutItem) -> None:  # noqa: N802
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int) -> QLayoutItem | None:  # noqa: N802
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index: int) -> QLayoutItem | None:  # noqa: N802
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self) -> Qt.Orientation:  # noqa: N802
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:  # noqa: N802
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802
        return self._layout(QRect(0, 0, width, 0), apply=False)

    def setGeometry(self, rect: QRect) -> None:  # noqa: N802
        super().setGeometry(rect)
        self._layout(rect, apply=True)

    def sizeHint(self) -> QSize:  # noqa: N802
        return self.minimumSize()

    def minimumSize(self) -> QSize:  # noqa: N802
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        m = self.contentsMargins()
        return size + QSize(m.left() + m.right(), m.top() + m.bottom())

    def _layout(self, rect: QRect, apply: bool) -> int:
        m = self.contentsMargins()
        area = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        x, y, row_h = area.x(), area.y(), 0
        for item in self._items:
            if item.widget() is not None and item.widget().isHidden():
                continue
            hint = item.sizeHint()
            if x + hint.width() > area.right() + 1 and row_h > 0:
                x, y, row_h = area.x(), y + row_h + self._spacing, 0
            if apply:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x += hint.width() + self._spacing
            row_h = max(row_h, hint.height())
        return y + row_h - rect.y() + m.bottom()


class Chip(QPushButton):
    """A toggle for one genre/tag. Two-state, or three-state (include -> exclude -> off) for tri-state filters."""

    changed = Signal()

    def __init__(self, node: dict, path: tuple[int, ...]):
        super().__init__(node["name"])
        self.node, self.path = node, path
        self.tri = node["kind"] == "tristate"
        self.value = node["default"]
        self.setProperty("chip", True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.clicked.connect(self._click)
        self._paint()

    def _click(self) -> None:
        self.value = TRI_NEXT.get(self.value, "INCLUDE") if self.tri else not self.value
        self._paint()
        self.changed.emit()

    def set_value(self, value) -> None:
        self.value = value
        self._paint()

    def _paint(self) -> None:
        state = "off"
        if self.tri:
            state = {"INCLUDE": "include", "EXCLUDE": "exclude"}.get(self.value, "off")
        elif self.value:
            state = "include"
        mark = {"include": "✓  ", "exclude": "✕  "}.get(state, "")
        self.setText(mark + self.node["name"])
        self.setProperty("chipState", state)
        self.setToolTip(tr("filters.chip_hint") if self.tri else "")
        style.repolish(self)


class Section(QWidget):
    """Collapsible group of chips."""

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.title = title
        self.head = QToolButton()
        self.head.setProperty("section", True)
        self.head.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.head.setCursor(Qt.CursorShape.PointingHandCursor)
        self.head.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.body = QWidget()
        self.flow = FlowLayout(self.body)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addWidget(self.head)
        layout.addWidget(self.body)
        self.head.clicked.connect(lambda: self.set_open(not self.body.isVisible()))
        self.chips: list[Chip] = []
        self.set_open(True)

    def set_open(self, value: bool) -> None:
        self.body.setVisible(value)
        style.bind_icon(self.head, "chevron-down" if value else "chevron-right", "normal", 14)

    def refresh_title(self) -> None:
        active = sum(1 for c in self.chips if (c.value not in ("IGNORE", False, None, "")))
        self.head.setText(f"{self.title}  ·  {active}" if active else self.title)


class FilterPanel(QFrame):
    """Renders a source's filters. state() feeds suwayomi.filter_changes()."""

    changed = Signal()
    apply_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        self.setFixedWidth(330)
        self.nodes: list[dict] = []
        self._values: dict[tuple[int, ...], object] = {}
        self._chips: list[Chip] = []
        self._sections: list[Section] = []
        self.search = QLineEdit(placeholderText=tr("filters.search"))
        self.search.setClearButtonEnabled(True)
        self.reset_btn = style.ghost(QPushButton(tr("filters.reset")), "refresh")
        self.apply_btn = style.primary(QPushButton(tr("filters.apply")), "check")
        self.empty = QLabel(tr("filters.none"))
        self.empty.setWordWrap(True)
        style.role(self.empty, "dim")
        self.content = QWidget()
        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(0, 0, 6, 0)
        self.content_layout.setSpacing(10)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setWidget(self.content)
        top = QHBoxLayout()
        top.addWidget(self.search, 1)
        top.addWidget(self.reset_btn)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        layout.addLayout(top)
        layout.addWidget(self.scroll, 1)
        layout.addWidget(self.apply_btn)
        self.search.textChanged.connect(self._search)
        self.reset_btn.clicked.connect(self.reset)
        self.apply_btn.clicked.connect(self.apply_requested)

    # --- building ---------------------------------------------------------------------------------------

    def set_filters(self, nodes: list[dict]) -> None:
        self.nodes = nodes
        self._values.clear()
        self._chips.clear()
        self._sections.clear()
        self.search.clear()
        while self.content_layout.count():
            item = self.content_layout.takeAt(0)
            widget = item.widget()
            if widget is self.empty:
                widget.hide()               # kept for reuse: it must not be deleted with the other widgets
                widget.setParent(None)
            elif widget is not None:
                widget.hide()               # deleteLater() alone leaves it painted (and overlapping) until the next event loop turn
                widget.setParent(None)
                widget.deleteLater()
        for node in nodes:
            self._add_node(node, (node["pos"],), self.content_layout)
        if not nodes:
            self.content_layout.addWidget(self.empty)
            self.empty.show()
        self.content_layout.addStretch(1)
        self.changed.emit()

    def _add_node(self, node: dict, path: tuple[int, ...], layout: QVBoxLayout) -> None:
        kind = node["kind"]
        self._values[path] = node["default"]
        if kind == "header":
            label = QLabel(node["name"])
            label.setStyleSheet("font-weight: 600;")
            layout.addWidget(label)
        elif kind == "separator":
            layout.addWidget(style.hline())
        elif kind == "group":
            section = Section(node["name"])
            layout.addWidget(section)
            self._sections.append(section)
            for child in node["children"]:
                self._values.pop(path + (child["pos"],), None)
                if child["kind"] in ("tristate", "checkbox"):
                    chip = Chip(child, path + (child["pos"],))
                    chip.changed.connect(lambda c=chip, s=section: self._chip_changed(c, s))
                    section.flow.addWidget(chip)
                    section.chips.append(chip)
                    self._chips.append(chip)
                    self._values[chip.path] = chip.value
                else:  # selects/texts inside groups are rare: render them below the chips
                    holder = QWidget()
                    inner = QVBoxLayout(holder)
                    inner.setContentsMargins(0, 0, 0, 0)
                    self._add_node(child, path + (child["pos"],), inner)
                    section.layout().addWidget(holder)
            section.refresh_title()
        elif kind == "checkbox":
            box = QCheckBox(node["name"], checked=bool(node["default"]))
            box.toggled.connect(lambda v, p=path: self._set(p, v))
            layout.addWidget(box)
        elif kind == "select":
            layout.addWidget(QLabel(node["name"]))
            combo = QComboBox()
            combo.addItems([str(v) for v in node["values"]])
            combo.setCurrentIndex(int(node["default"] or 0))
            combo.currentIndexChanged.connect(lambda i, p=path: self._set(p, i))
            layout.addWidget(combo)
        elif kind == "text":
            layout.addWidget(QLabel(node["name"]))
            edit = QLineEdit(str(node["default"] or ""))
            edit.textChanged.connect(lambda t, p=path: self._set(p, t))
            edit.returnPressed.connect(self.apply_requested)
            layout.addWidget(edit)
        elif kind == "sort":
            layout.addWidget(QLabel(node["name"]))
            default = node["default"] or {"ascending": False, "index": 0}
            row = QHBoxLayout()
            combo = QComboBox()
            combo.addItems([str(v) for v in node["values"]])
            combo.setCurrentIndex(int(default["index"]))
            asc = QCheckBox(tr("filters.ascending"), checked=bool(default["ascending"]))

            def push(_=None, p=path, c=combo, a=asc) -> None:
                self._set(p, {"ascending": a.isChecked(), "index": c.currentIndex()})

            combo.currentIndexChanged.connect(push)
            asc.toggled.connect(push)
            row.addWidget(combo, 1)
            row.addWidget(asc)
            layout.addLayout(row)

    # --- state ------------------------------------------------------------------------------------------

    def _set(self, path: tuple[int, ...], value) -> None:
        self._values[path] = value
        self.changed.emit()

    def _chip_changed(self, chip: Chip, section: Section) -> None:
        self._values[chip.path] = chip.value
        section.refresh_title()
        self.changed.emit()

    def state(self) -> dict[tuple[int, ...], object]:
        return dict(self._values)

    def active_count(self) -> int:
        from anihub.services.suwayomi import filter_changes

        return len(filter_changes(self.nodes, self._values))

    def reset(self) -> None:
        self.set_filters(self.nodes)

    def _search(self, text: str) -> None:
        needle = text.strip().lower()
        for chip in self._chips:
            chip.setVisible(not needle or needle in chip.node["name"].lower())
        for section in self._sections:
            visible = any(not c.isHidden() for c in section.chips)
            section.setVisible(visible or not section.chips)
            if needle and visible:
                section.set_open(True)
            section.flow.invalidate()


class SourceSettingsDialog(QDialog):
    """The source's own settings: this is where login / password, quality and mirror options of an extension live."""

    def __init__(self, api, source: dict, parent=None):
        super().__init__(parent)
        self.api, self.source = api, source
        self.changed = False
        self.setWindowTitle(tr("srcset.title", name=source["displayName"]))
        self.setMinimumWidth(520)
        self.hint = QLabel(tr("srcset.hint"))
        self.hint.setWordWrap(True)
        style.role(self.hint, "dim")
        self.status = QLabel(tr("status.loading"))
        self.status.setWordWrap(True)
        self.form = QFormLayout()
        self.form.setLabelAlignment(Qt.AlignmentFlag.AlignTop)
        self.form.setVerticalSpacing(10)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.accept)
        layout = QVBoxLayout(self)
        layout.addWidget(self.hint)
        layout.addLayout(self.form)
        layout.addWidget(self.status)
        layout.addWidget(buttons)
        run_async(api.source_preferences, source["id"], on_done=self._loaded,
                  on_error=lambda exc: self.status.setText(tr("status.error", msg=str(exc))))

    def _loaded(self, prefs: list[dict]) -> None:
        self.status.setText("" if prefs else tr("srcset.none"))
        for pref in prefs:
            widget = self._widget_for(pref)
            label = QLabel(pref["title"])
            label.setWordWrap(True)
            cell = QWidget()
            box = QVBoxLayout(cell)
            box.setContentsMargins(0, 0, 0, 0)
            box.setSpacing(2)
            box.addWidget(widget)
            if pref["summary"] and pref["kind"] not in ("switch", "check"):
                sub = QLabel(pref["summary"])
                sub.setWordWrap(True)
                style.role(sub, "muted")
                box.addWidget(sub)
            self.form.addRow("" if pref["kind"] in ("switch", "check") else label, cell)

    def _save(self, pref: dict, value) -> None:
        def done(_r) -> None:
            self.changed = True
            self.status.setText(tr("srcset.saved"))

        run_async(self.api.set_source_preference, self.source["id"], pref, value, on_done=done,
                  on_error=lambda exc: self.status.setText(tr("status.error", msg=str(exc))))

    def _widget_for(self, pref: dict) -> QWidget:
        kind, value = pref["kind"], pref["value"]
        if kind in ("switch", "check"):
            box = QCheckBox(pref["title"], checked=bool(value))
            if pref["summary"]:
                box.setToolTip(pref["summary"])
            box.toggled.connect(lambda v, p=pref: self._save(p, v))
            return box
        if kind == "text":
            edit = QLineEdit(str(value or ""))
            secret = any(word in f"{pref['key']} {pref['title']}".lower() for word in ("pass", "пароль", "token", "secret"))
            if secret:
                edit.setEchoMode(QLineEdit.EchoMode.Password)
            edit.editingFinished.connect(lambda p=pref, e=edit: self._save_text(p, e))
            edit._last = edit.text()  # type: ignore[attr-defined]
            return edit
        if kind == "list":
            combo = QComboBox()
            for entry, entry_value in zip(pref["entries"], pref["entry_values"]):
                combo.addItem(entry, entry_value)
            index = combo.findData(value)
            combo.setCurrentIndex(index if index >= 0 else -1)
            combo.activated.connect(lambda _i, p=pref, c=combo: self._save(p, c.currentData()))
            return combo
        holder = QWidget()  # multi-select
        col = QVBoxLayout(holder)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(4)
        chosen = set(value or [])
        boxes: list[tuple[QCheckBox, str]] = []
        for entry, entry_value in zip(pref["entries"], pref["entry_values"]):
            box = QCheckBox(entry, checked=entry_value in chosen)
            boxes.append((box, entry_value))
            col.addWidget(box)
        for box, _v in boxes:
            box.toggled.connect(lambda _c, p=pref, b=boxes: self._save(p, [v for cb, v in b if cb.isChecked()]))
        return holder

    def _save_text(self, pref: dict, edit: QLineEdit) -> None:
        if edit.text() != getattr(edit, "_last", None):
            edit._last = edit.text()  # type: ignore[attr-defined]
            self._save(pref, edit.text())
