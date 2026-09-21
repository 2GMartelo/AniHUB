"""Language filter for lists of sources: a button with a menu of check boxes (none checked = every language)."""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QMenu, QToolButton

from anihub.core.i18n import tr

LANG_NAMES = {
    "ru": "Русский", "en": "English", "ja": "日本語", "es": "Español", "pt": "Português", "fr": "Français", "de": "Deutsch",
    "it": "Italiano", "id": "Indonesia", "ar": "العربية", "zh": "中文", "ko": "한국어", "tr": "Türkçe", "uk": "Українська",
    "pl": "Polski", "vi": "Tiếng Việt", "th": "ไทย", "multi": "Multi",
}


def lang_name(code: str) -> str:
    return LANG_NAMES.get(code, code)


class LangFilter(QToolButton):
    changed = Signal()

    def __init__(self, cfg, key: str, parent=None):
        super().__init__(parent)
        self.cfg, self.key = cfg, key
        self.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.setProperty("chipbtn", True)
        self._menu = QMenu(self)
        self.setMenu(self._menu)
        self._codes: list[str] = []
        self._update_text()

    def selected(self) -> set[str]:
        """The chosen languages; empty = no filtering."""
        return {str(c) for c in (self.cfg.get(self.key) or [])}

    def set_languages(self, codes) -> None:
        self._codes = sorted(set(codes), key=lambda c: (c == "multi", lang_name(c).lower()))
        self._menu.clear()
        chosen = self.selected()
        for code in self._codes:
            action = self._menu.addAction(lang_name(code))
            action.setCheckable(True)
            action.setChecked(code in chosen)
            action.toggled.connect(lambda _on, c=code: self._toggle())
        self._menu.addSeparator()
        self._menu.addAction(tr("lang.all"), self._clear)
        self._update_text()

    def _toggle(self) -> None:
        chosen = [c for c, a in zip(self._codes, [a for a in self._menu.actions() if a.isCheckable()]) if a.isChecked()]
        self.cfg.set(self.key, chosen)
        self._update_text()
        self.changed.emit()

    def _clear(self) -> None:
        for action in self._menu.actions():
            if action.isCheckable():
                action.blockSignals(True)
                action.setChecked(False)
                action.blockSignals(False)
        self._toggle()

    def _update_text(self) -> None:
        chosen = self.selected() & set(self._codes or self.selected())
        self.setText(tr("lang.filter") if not chosen else ", ".join(lang_name(c) for c in sorted(chosen))[:24])

    def accepts(self, code: str) -> bool:
        chosen = self.selected() & set(self._codes)
        return not chosen or code in chosen or code == "multi"
