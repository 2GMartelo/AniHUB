"""Central keyboard-shortcut registry (a "Keyboard shortcuts" settings page and rebindable hotkeys are standard in
most desktop apps; before this the whole program had exactly one QShortcut, Ctrl+K, and nothing else was
rebindable). This only covers *global*, app-level actions -- per-widget navigation keys (arrows in the viewer,
Delete in a grid, ...) stay where they are, they are not meaningfully "rebindable" the way a menu command is."""
from __future__ import annotations

from dataclasses import dataclass

from anihub.core.config import Config


@dataclass(frozen=True)
class Action:
    id: str
    label_key: str   # i18n key for its human-readable name, shown in the hotkeys settings box
    default: str      # default QKeySequence text, e.g. "Ctrl+K"


ACTIONS: list[Action] = [
    Action("palette", "hotkey.palette", "Ctrl+K"),
    Action("notifications", "hotkey.notifications", "Ctrl+Shift+N"),
    Action("undo", "hotkey.undo", "Ctrl+Z"),
    Action("redo", "hotkey.redo", "Ctrl+Y"),
    Action("go_arts", "hotkey.go_arts", "Ctrl+1"),
    Action("go_manga", "hotkey.go_manga", "Ctrl+2"),
    Action("go_novels", "hotkey.go_novels", "Ctrl+3"),
    Action("go_sd", "hotkey.go_sd", "Ctrl+4"),
    Action("go_anime", "hotkey.go_anime", "Ctrl+5"),
    Action("go_settings", "hotkey.go_settings", "Ctrl+,"),
]
BY_ID = {a.id: a for a in ACTIONS}


def key_for(cfg: Config, action_id: str) -> str:
    """The user's remapped shortcut text for `action_id`, or its default."""
    custom = cfg.get(f"hotkeys.{action_id}")
    return str(custom) if custom else BY_ID[action_id].default
