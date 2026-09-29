"""Downloading Forge/ComfyUI/sd-scripts from Settings defaults its folder picker to the library's own "apps"
folder (core/paths.py's LibraryPaths.apps) instead of the user's home directory -- ui/comfyui_install_dialog.py
(new) mirrors the existing ForgeInstallDialog/LoraTrainInstallDialog shape."""
import time

import pytest
from PySide6.QtWidgets import QFileDialog

from anihub.context import AppContext
from anihub.core.config import Config


def make_ctx(tmp_path):
    cfg = Config.load(tmp_path / "c.json")
    cfg.set("library_path", str(tmp_path / "lib"), save=False)
    cfg.set("first_run_done", True, save=False)
    return AppContext.build(cfg)


def pump_until(qapp, condition, tries: int = 400) -> None:
    for _ in range(tries):
        qapp.processEvents()
        if condition():
            return
        time.sleep(0.005)
    raise AssertionError("condition never became true")


# --- the ComfyUI install dialog -----------------------------------------------------------------------------------

def test_comfyui_install_dialog_writes_comfyui_path_on_success(qapp, tmp_path, monkeypatch):
    from anihub.services import comfyui_install
    from anihub.ui.comfyui_install_dialog import ComfyuiInstallDialog

    installed_to = tmp_path / "dest" / "ComfyUI"
    monkeypatch.setattr(comfyui_install, "install", lambda *a, **k: installed_to)
    ctx = make_ctx(tmp_path)
    dlg = ComfyuiInstallDialog(ctx, tmp_path / "dest")
    pump_until(qapp, lambda: dlg.installed is not None)
    assert dlg.installed == installed_to
    assert ctx.cfg.get("comfyui.path") == str(installed_to)
    assert not dlg.close_btn.isHidden() and dlg.cancel_btn.isHidden()
    dlg.close()


def test_comfyui_install_dialog_reports_failure(qapp, tmp_path, monkeypatch):
    from anihub.services import comfyui_install
    from anihub.ui.comfyui_install_dialog import ComfyuiInstallDialog

    def boom(*a, **k):
        raise comfyui_install.ComfyInstallError("no space")

    monkeypatch.setattr(comfyui_install, "install", boom)
    ctx = make_ctx(tmp_path)
    dlg = ComfyuiInstallDialog(ctx, tmp_path / "dest")
    pump_until(qapp, lambda: not dlg.close_btn.isHidden())
    assert "no space" in dlg.state.text()
    assert not ctx.cfg.get("comfyui.path")
    dlg.close()


def test_comfyui_install_dialog_paused_before_extracting_keeps_installed_none(qapp, tmp_path, monkeypatch):
    from anihub.services import comfyui_install
    from anihub.ui.comfyui_install_dialog import ComfyuiInstallDialog

    monkeypatch.setattr(comfyui_install, "install", lambda *a, **k: None)
    ctx = make_ctx(tmp_path)
    dlg = ComfyuiInstallDialog(ctx, tmp_path / "dest")
    pump_until(qapp, lambda: not dlg.close_btn.isHidden())
    assert dlg.installed is None
    assert not ctx.cfg.get("comfyui.path")
    dlg.close()


# --- the VSeeFace install dialog ----------------------------------------------------------------------------------

def test_vseeface_install_dialog_writes_vseeface_path_on_success(qapp, tmp_path, monkeypatch):
    from anihub.services import vseeface_install
    from anihub.ui.vseeface_install_dialog import VSeeFaceInstallDialog

    installed_to = tmp_path / "dest" / "VSeeFace"
    monkeypatch.setattr(vseeface_install, "install", lambda *a, **k: installed_to)
    ctx = make_ctx(tmp_path)
    dlg = VSeeFaceInstallDialog(ctx, tmp_path / "dest")
    pump_until(qapp, lambda: dlg.installed is not None)
    assert dlg.installed == installed_to
    assert ctx.cfg.get("vtuber.vseeface_path") == str(installed_to)
    assert not dlg.close_btn.isHidden() and dlg.cancel_btn.isHidden()
    dlg.close()


def test_vseeface_install_dialog_reports_failure(qapp, tmp_path, monkeypatch):
    from anihub.services import vseeface_install
    from anihub.ui.vseeface_install_dialog import VSeeFaceInstallDialog

    def boom(*a, **k):
        raise vseeface_install.VSeeFaceInstallError("no space")

    monkeypatch.setattr(vseeface_install, "install", boom)
    ctx = make_ctx(tmp_path)
    dlg = VSeeFaceInstallDialog(ctx, tmp_path / "dest")
    pump_until(qapp, lambda: not dlg.close_btn.isHidden())
    assert "no space" in dlg.state.text()
    assert not ctx.cfg.get("vtuber.vseeface_path")
    dlg.close()


# --- Settings: the download buttons default to ctx.paths.apps -----------------------------------------------------

@pytest.fixture
def page(qapp, tmp_path):
    from anihub.ui.settings import SettingsPage

    ctx = make_ctx(tmp_path)
    p = SettingsPage(ctx)
    yield p, ctx
    p.close()


def _capture_start_dir(monkeypatch, seen: dict) -> None:
    def fake_get_existing_directory(parent, caption, start_dir):
        seen["start"] = start_dir
        return ""  # as if the user cancelled: the caller returns early, nothing else happens

    monkeypatch.setattr(QFileDialog, "getExistingDirectory", staticmethod(fake_get_existing_directory))


def test_download_forge_button_starts_at_the_apps_folder(page, monkeypatch):
    settings_page, ctx = page
    seen: dict = {}
    _capture_start_dir(monkeypatch, seen)
    settings_page._download_forge()
    assert seen["start"] == str(ctx.paths.apps)


def test_download_comfyui_button_starts_at_the_apps_folder(page, monkeypatch):
    settings_page, ctx = page
    seen: dict = {}
    _capture_start_dir(monkeypatch, seen)
    settings_page._download_comfyui()
    assert seen["start"] == str(ctx.paths.apps)


def test_download_train_scripts_button_starts_at_the_apps_folder(page, monkeypatch):
    settings_page, ctx = page
    seen: dict = {}
    _capture_start_dir(monkeypatch, seen)
    settings_page._download_train_scripts()
    assert seen["start"] == str(ctx.paths.apps)


def test_download_vseeface_button_starts_at_the_apps_folder(page, monkeypatch):
    settings_page, ctx = page
    seen: dict = {}
    _capture_start_dir(monkeypatch, seen)
    settings_page._download_vseeface()
    assert seen["start"] == str(ctx.paths.apps)


def test_vtuber_and_koikatsu_boxes_are_visible_even_before_generation_is_enabled(page):
    """Rigging/tracking/Koikatsu don't need Forge at all -- unlike forge_box/comfyui_box/train_box, these must not
    be hidden (or garbage-collected) just because the PC can't run Stable Diffusion."""
    settings_page, ctx = page
    assert not ctx.sd_enabled
    assert settings_page.vtuber_box.parent() is not None
    assert settings_page.koikatsu_box.parent() is not None
    assert settings_page.vseeface_path.text() == ""
    assert settings_page.koikatsu_path.text() == ""


def test_save_persists_vseeface_and_koikatsu_paths(page):
    settings_page, ctx = page
    settings_page.vseeface_path.setText(r"C:\apps\VSeeFace")
    settings_page.koikatsu_path.setText(r"C:\games\Koikatsu")
    settings_page._save()
    assert ctx.cfg.get("vtuber.vseeface_path") == r"C:\apps\VSeeFace"
    assert ctx.cfg.get("koikatsu.path") == r"C:\games\Koikatsu"


# --- VTube Studio via Steam, Stretchy Studio / Cubism as plain links -----------------------------------------------

def test_vtubestudio_button_launches_steam_when_steam_is_present(page, monkeypatch):
    settings_page, ctx = page
    from anihub.services import steam_launch

    monkeypatch.setattr(steam_launch, "steam_installed", lambda: True)
    seen = {}
    monkeypatch.setattr(steam_launch, "open_steam_install", lambda app_id: seen.setdefault("app_id", app_id))
    settings_page._open_vtubestudio()
    assert seen["app_id"] == 1325860


def test_vtubestudio_button_falls_back_to_the_store_page_without_steam(page, monkeypatch):
    settings_page, ctx = page
    from anihub.services import steam_launch

    monkeypatch.setattr(steam_launch, "steam_installed", lambda: False)
    seen = {}
    monkeypatch.setattr(settings_page, "_open_url", lambda url: seen.setdefault("url", url))
    settings_page._open_vtubestudio()
    assert "store.steampowered.com/app/1325860" in seen["url"]


def test_stretchy_and_cubism_buttons_just_open_their_urls(page, monkeypatch):
    settings_page, ctx = page
    seen = []
    monkeypatch.setattr(settings_page, "_open_url", lambda url: seen.append(url))
    settings_page.stretchy_btn.click()
    settings_page.cubism_btn.click()
    assert seen == ["https://editor.stretchy.studio/", "https://www.live2d.com/en/cubism/download/editor/"]


def test_koikatsu_download_button_opens_the_vk_page(page, monkeypatch):
    settings_page, ctx = page
    seen = []
    monkeypatch.setattr(settings_page, "_open_url", lambda url: seen.append(url))
    settings_page.koikatsu_download_btn.click()
    assert seen == ["https://vk.ru/@1koikatsu-vse-nuzhnye-ssylki-dlya-ustanovki-kk"]


def test_forge_download_button_is_not_hidden_before_generation_is_enabled(page):
    """The button used to only setVisible(True) once ctx.sd_enabled was already True -- backwards for a button
    whose whole job is enabling it in the first place. A never-shown widget always reports isVisible()==False
    regardless, so isHidden() is the real check here."""
    settings_page, ctx = page
    assert not ctx.sd_enabled
    assert not settings_page.sd_download_btn.isHidden()
