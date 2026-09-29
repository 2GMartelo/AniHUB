"""Settings additions from the "9-item" user request: changing the library folder without moving files, a
cookie-import that actually refreshes the credential fields afterwards (they used to stay stale until restart),
a disk-scanned default-checkpoint picker, a visible autotagger model path, a configurable Suwayomi install
location reachable from Settings (not just the Manga tab), a labelled ComfyUI/VTube connection, and a single
"download everything missing" button."""
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QFileDialog, QMessageBox

from anihub.context import AppContext
from anihub.core.config import Config
from anihub.core.i18n import tr
from anihub.ui.settings import SettingsPage


def make_ctx(tmp_path, **cfg_extra):
    cfg = Config.load(tmp_path / "c.json")
    cfg.set("library_path", str(tmp_path / "lib"), save=False)
    cfg.set("first_run_done", True, save=False)
    for key, value in cfg_extra.items():
        cfg.set(key, value, save=False)
    return AppContext.build(cfg)


@pytest.fixture
def page(qapp, tmp_path):
    ctx = make_ctx(tmp_path)
    p = SettingsPage(ctx)
    yield p, ctx
    p.close()


# --- changing the library folder --------------------------------------------------------------------------------

def test_change_library_repoints_cfg_and_warns_about_a_restart(page, monkeypatch, tmp_path):
    settings_page, ctx = page
    new_folder = tmp_path / "elsewhere"
    new_folder.mkdir()
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", staticmethod(lambda *a, **k: str(new_folder)))
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes))
    seen = {}
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **k: seen.setdefault("info", a[2])))
    settings_page._change_library()
    assert ctx.cfg.get("library_path") == str(new_folder)
    assert settings_page.library.text() == str(new_folder)
    assert tr("settings.change_library.restart") in seen["info"]


def test_change_library_does_nothing_when_the_same_folder_is_picked_again(page, monkeypatch):
    settings_page, ctx = page
    current = ctx.cfg.get("library_path")
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", staticmethod(lambda *a, **k: current))
    settings_page._change_library()
    assert ctx.cfg.get("library_path") == current


# --- cookie import refreshing the credential fields (the actual bug report) ------------------------------------

def test_reload_credentials_picks_up_a_cfg_change_made_outside_the_page(page):
    settings_page, ctx = page
    key = next(iter(settings_page.cred_fields))
    assert settings_page.cred_fields[key].text() == ""
    ctx.cfg.set(key, "imported-value", save=False)
    settings_page.reload_credentials()
    assert settings_page.cred_fields[key].text() == "imported-value"


def test_import_cookies_button_refreshes_the_fields(page, monkeypatch):
    settings_page, ctx = page
    key = next(iter(settings_page.cred_fields))

    def fake_pick_and_import(ctx_arg, parent):
        ctx_arg.cfg.set(key, "from-a-dropped-file", save=False)

    monkeypatch.setattr("anihub.ui.settings.cookie_import.pick_and_import", fake_pick_and_import)
    settings_page._import_cookies()
    assert settings_page.cred_fields[key].text() == "from-a-dropped-file"


# --- autotagger model path is now shown -------------------------------------------------------------------------

def test_autotag_path_caption_shows_the_real_model_folder(page):
    settings_page, ctx = page
    assert str(ctx.autotagger.model_dir) in settings_page.tag_path.text()


# --- default checkpoint picker, scanned straight off disk ---------------------------------------------------------

def test_forge_model_combo_lists_checkpoints_found_on_disk(qapp, tmp_path):
    forge_dir = tmp_path / "forge"
    models_dir = forge_dir / "models" / "Stable-diffusion"
    models_dir.mkdir(parents=True)
    (models_dir / "anything-v5.safetensors").write_bytes(b"")
    (models_dir / "old-model.ckpt").write_bytes(b"")
    (models_dir / "not-a-model.txt").write_bytes(b"")
    ctx = make_ctx(tmp_path, **{"forge.path": str(forge_dir)})
    assert ctx.sd_enabled
    settings_page = SettingsPage(ctx)
    names = {settings_page.forge_model.itemText(i) for i in range(settings_page.forge_model.count())}
    assert {"anything-v5", "old-model"} <= names
    assert "not-a-model" not in names
    assert settings_page.forge_model.itemText(0) == tr("settings.forge_model.auto")
    settings_page.close()


def test_forge_model_combo_rescans_when_the_forge_path_field_changes(qapp, tmp_path):
    ctx = make_ctx(tmp_path, **{"forge.path": str(tmp_path / "forge")})
    settings_page = SettingsPage(ctx)
    assert settings_page.forge_model.count() == 1                       # nothing on disk yet, just "auto"
    models_dir = tmp_path / "forge2" / "models" / "Stable-diffusion"
    models_dir.mkdir(parents=True)
    (models_dir / "new-model.safetensors").write_bytes(b"")
    settings_page.forge_path.setText(str(tmp_path / "forge2"))
    names = {settings_page.forge_model.itemText(i) for i in range(settings_page.forge_model.count())}
    assert "new-model" in names
    settings_page.close()


def test_save_persists_the_chosen_default_model(qapp, tmp_path):
    forge_dir = tmp_path / "forge"
    models_dir = forge_dir / "models" / "Stable-diffusion"
    models_dir.mkdir(parents=True)
    (models_dir / "pick-me.safetensors").write_bytes(b"")
    ctx = make_ctx(tmp_path, **{"forge.path": str(forge_dir)})
    settings_page = SettingsPage(ctx)
    idx = settings_page.forge_model.findData("pick-me.safetensors")
    assert idx >= 0
    settings_page.forge_model.setCurrentIndex(idx)
    settings_page._save()
    assert ctx.cfg.get("forge.default_model") == "pick-me.safetensors"
    settings_page.close()


# --- Suwayomi is now reachable from Settings, not just the Manga tab ---------------------------------------------

def test_suwayomi_settings_field_defaults_from_cfg_and_status_shows_the_folder(qapp, tmp_path):
    ctx = make_ctx(tmp_path, **{"manga.suwayomi_path": str(tmp_path / "apps" / "Suwayomi")})
    settings_page = SettingsPage(ctx)
    assert settings_page.suwayomi_path.text() == str(tmp_path / "apps" / "Suwayomi")
    assert str(ctx.suwayomi.install_dir) in settings_page.suwayomi_status.text()
    assert tr("settings.suwayomi_missing") in settings_page.suwayomi_status.text()
    settings_page.close()


def test_download_suwayomi_button_starts_at_the_apps_folder(page, monkeypatch):
    settings_page, ctx = page
    seen = {}
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", staticmethod(lambda *a, **k: seen.setdefault("start", a[2]) and ""))
    settings_page._download_suwayomi()
    assert seen["start"] == str(ctx.paths.apps)


# --- ComfyUI box is now explicitly tied to the VTube feature ------------------------------------------------------

def test_comfyui_box_explains_the_vtube_connection(page):
    settings_page, ctx = page
    assert settings_page.comfyui_box.title() == tr("settings.comfyui_group")
    assert "VTube" in tr("settings.comfyui_hint")


# --- one button for everything still missing -----------------------------------------------------------------

def test_missing_deps_lists_suwayomi_and_wd14_even_when_generation_is_off(page, monkeypatch):
    """ctx.suwayomi/ctx.autotagger resolve their install paths under the real %APPDATA%\\AniHUB (services/
    autotag.py, context.py) regardless of the test's own tmp_path config -- a real dev machine that already has
    them installed would otherwise make this test's result depend on machine state. Monkeypatched deterministic
    here instead."""
    settings_page, ctx = page
    assert not ctx.sd_enabled
    monkeypatch.setattr(ctx.suwayomi, "installed", lambda: None)
    monkeypatch.setattr(type(ctx.autotagger), "available", property(lambda self: False))
    missing = settings_page._missing_deps()
    assert "Forge" not in missing and "ComfyUI" not in missing and "sd-scripts" not in missing
    assert "Suwayomi" in missing and "WD14" in missing


def test_missing_deps_includes_forge_family_once_generation_is_on(qapp, tmp_path):
    ctx = make_ctx(tmp_path, **{"forge.path": str(tmp_path / "forge")})
    settings_page = SettingsPage(ctx)
    missing = settings_page._missing_deps()
    assert "ComfyUI" in missing and "sd-scripts" in missing
    assert "Forge" not in missing                                        # forge.path is already set
    settings_page.close()


def test_download_everything_does_nothing_destructive_when_declined(page, monkeypatch):
    settings_page, ctx = page
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.No))
    settings_page._download_everything()
    assert settings_page.deps_status.text() != tr("settings.download_all.done")


def test_download_everything_reports_when_nothing_is_missing(page, monkeypatch):
    settings_page, ctx = page
    monkeypatch.setattr(settings_page, "_missing_deps", lambda: [])
    settings_page._download_everything()
    assert settings_page.deps_status.text() == tr("settings.download_all.none")
