"""core/keymap.py: the hotkey registry, and MainWindow._apply_hotkeys()/settings.py wiring on top of it."""
from anihub.context import AppContext
from anihub.core import keymap
from anihub.core.config import Config


def make_window(qapp, tmp_path, **cfg_values):
    from anihub.ui.main_window import MainWindow

    cfg = Config.load(tmp_path / "c.json")
    cfg.set("library_path", str(tmp_path / "lib"), save=False)
    cfg.set("first_run_done", True, save=False)
    for k, v in cfg_values.items():
        cfg.set(k, v, save=False)
    ctx = AppContext.build(cfg)
    win = MainWindow(ctx)
    return win, ctx


def test_key_for_falls_back_to_the_default(tmp_path):
    cfg = Config.load(tmp_path / "c.json")
    assert keymap.key_for(cfg, "palette") == "Ctrl+K"


def test_key_for_returns_the_users_override(tmp_path):
    cfg = Config.load(tmp_path / "c.json")
    cfg.set("hotkeys.palette", "Ctrl+P", save=False)
    assert keymap.key_for(cfg, "palette") == "Ctrl+P"


def test_main_window_registers_a_shortcut_per_known_action(qapp, tmp_path):
    win, ctx = make_window(qapp, tmp_path)
    assert set(win._hotkey_shortcuts) >= {"palette", "notifications", "undo", "redo", "go_arts", "go_settings"}
    from PySide6.QtGui import QKeySequence

    assert win._hotkey_shortcuts["palette"].key() == QKeySequence("Ctrl+K")
    win._quitting = True
    win.close()


def test_main_window_skips_shortcuts_for_sections_that_do_not_exist(qapp, tmp_path):
    """No SD backend configured -> no "sd" row in self.rows -> no go_sd shortcut registered."""
    win, ctx = make_window(qapp, tmp_path, **{"sd.enabled": False})
    assert "sd" not in win.rows
    assert "go_sd" not in win._hotkey_shortcuts
    win._quitting = True
    win.close()


def test_rebinding_a_hotkey_in_config_and_reapplying_changes_the_shortcut(qapp, tmp_path):
    from PySide6.QtGui import QKeySequence

    win, ctx = make_window(qapp, tmp_path)
    ctx.cfg.set("hotkeys.palette", "Ctrl+Shift+P", save=False)
    win._apply_hotkeys()
    assert win._hotkey_shortcuts["palette"].key() == QKeySequence("Ctrl+Shift+P")
    win._quitting = True
    win.close()


def test_settings_page_saves_a_rebound_hotkey(qapp, tmp_path):
    from PySide6.QtGui import QKeySequence

    win, ctx = make_window(qapp, tmp_path)
    win.settings.hotkey_edits["undo"].setKeySequence(QKeySequence("Ctrl+Alt+Z"))
    win.settings._save()
    assert ctx.cfg.get("hotkeys.undo") == "Ctrl+Alt+Z"
    assert win._hotkey_shortcuts["undo"].key() == QKeySequence("Ctrl+Alt+Z")
    win._quitting = True
    win.close()


def test_settings_page_clears_a_hotkey_reset_back_to_default(qapp, tmp_path):
    from PySide6.QtGui import QKeySequence

    win, ctx = make_window(qapp, tmp_path, **{"hotkeys.undo": "Ctrl+Alt+Z"})
    win.settings.hotkey_edits["undo"].setKeySequence(QKeySequence(keymap.BY_ID["undo"].default))
    win.settings._save()
    assert ctx.cfg.get("hotkeys.undo") == ""            # stored empty: key_for() falls back to the default
    win._quitting = True
    win.close()
