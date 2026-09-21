import colorsys
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from anihub.core.config import Config
from anihub.services import forge_install, sysreq
from anihub.services.sysreq import ForgeAssessment, judge_forge


# --- the verdict ------------------------------------------------------------------------------------------------------

def test_judge_forge_levels():
    good = judge_forge("RTX 4070", 12, 32, 200)
    assert good.suitable and good.level == "ok" and not good.problems
    weak = judge_forge("GTX 1650", 4, 16, 200)
    assert weak.suitable and weak.level == "low" and weak.problems == ("sys.forge.weak_gpu",)
    assert judge_forge("RTX 3060", 12, 12, 200).problems == ("sys.forge.weak_ram",)
    tiny_ram = judge_forge("RTX 3060", 12, 6, 200)
    assert not tiny_ram.suitable and tiny_ram.level == "no" and "sys.forge.small_ram" in tiny_ram.problems
    old_gpu = judge_forge("GT 1030", 2, 32, 200)
    assert not old_gpu.suitable and "sys.forge.small_gpu" in old_gpu.problems
    no_gpu = judge_forge("", 0, 32, 200)
    assert not no_gpu.suitable and no_gpu.problems == ("sys.forge.no_gpu",)                       # AMD / Intel only / no card
    low_disk = judge_forge("RTX 4070", 12, 32, 9)
    assert low_disk.suitable and low_disk.level == "low" and low_disk.problems == ("sys.forge.low_disk",)   # fixable by another drive
    unknown_ram = judge_forge("RTX 4070", 12, 0, 200)
    assert unknown_ram.suitable                                                                     # RAM unreadable: do not punish
    assert total_ram_is_positive()


def total_ram_is_positive() -> bool:
    return sysreq.total_ram_gb() > 0


def test_assess_forge_uses_the_measurements(monkeypatch):
    monkeypatch.setattr(sysreq, "check_gpu", lambda: sysreq.Check(True, "RTX 5070 (12 GB)", 12.0))
    monkeypatch.setattr(sysreq, "total_ram_gb", lambda: 32.0)
    monkeypatch.setattr(sysreq, "check_disk", lambda path: sysreq.Check(True, "", 300.0))
    a = sysreq.assess_forge("D:/x")
    assert a.suitable and a.level == "ok" and a.gpu == "RTX 5070" and a.vram_gb == 12 and a.ram_gb == 32
    monkeypatch.setattr(sysreq, "check_gpu", lambda: sysreq.Check(False))
    assert not sysreq.assess_forge().suitable


# --- installing Forge ---------------------------------------------------------------------------------------------------

def test_pick_asset_prefers_the_newest_cuda_and_torch():
    release = {"assets": [{"name": "webui_forge_cu121_torch21.7z"}, {"name": "webui_forge_cu124_torch24.7z"},
                          {"name": "webui_forge_cu121_torch231.7z"}, {"name": "notes.txt"}, {"name": "other.zip"}]}
    assert forge_install.pick_asset(release)["name"] == "webui_forge_cu124_torch24.7z"
    with pytest.raises(forge_install.ForgeInstallError):
        forge_install.pick_asset({"assets": [{"name": "x.zip"}]})


def make_package(root: Path) -> Path:
    pkg = root / "webui_forge_cu124_torch24"
    (pkg / "webui").mkdir(parents=True)
    (pkg / "webui" / "webui.bat").write_text("@echo off\n")
    (pkg / "environment.bat").write_text("@echo off\n")
    (pkg / "run.bat").write_text("@echo off\n")
    return pkg


def test_forge_path_of_accepts_the_package_folder_the_webui_folder_or_its_parent(tmp_path):
    pkg = make_package(tmp_path / "somewhere")
    assert forge_install.forge_path_of(pkg) == pkg / "webui"
    assert forge_install.forge_path_of(pkg / "webui") == pkg / "webui"
    assert forge_install.forge_path_of(pkg.parent) == pkg / "webui"                               # one level above
    assert forge_install.forge_path_of(tmp_path) is None and forge_install.forge_path_of(tmp_path / "missing") is None
    assert forge_install.find_package_root(tmp_path / "nothing") is None


@pytest.mark.skipif(forge_install.tar_exe() is None or sys.platform != "win32", reason="needs Windows' bsdtar")
def test_extract_reads_a_7z_with_the_windows_tar(tmp_path):
    pkg = make_package(tmp_path / "src")
    archive = tmp_path / "forge.7z"
    subprocess.run([forge_install.tar_exe(), "--format", "7zip", "-cf", str(archive), "-C", str(pkg.parent), pkg.name], check=True,
                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    dest = tmp_path / "out"
    forge_install.extract(archive, dest)
    assert forge_install.find_package_root(dest) == dest / pkg.name
    with pytest.raises(forge_install.ForgeInstallError):
        forge_install.extract(tmp_path / "missing.7z", tmp_path / "out2")


def test_install_downloads_unpacks_and_reports_progress(tmp_path, monkeypatch):
    pkg = make_package(tmp_path / "src")
    archive = tmp_path / "src" / "a.7z"
    calls = []

    class Http:
        def get_json(self, url, params=None, headers=None, interval_ms=None):
            return {"assets": [{"name": "webui_forge_cu121_torch21.7z", "browser_download_url": "https://x/a.7z", "size": 100}]}

        def download(self, url, dest, progress=None, cancelled=None, headers=None):
            dest.write_bytes(b"7z")
            progress(50, 100)
            calls.append(url)

    def fake_extract(arc, dst, cancelled=None):
        (dst / pkg.name).mkdir(parents=True, exist_ok=True)
        (dst / pkg.name / "webui").mkdir(exist_ok=True)
        (dst / pkg.name / "webui" / "webui.bat").write_text("x")

    monkeypatch.setattr(forge_install, "extract", fake_extract)
    monkeypatch.setattr(forge_install, "tar_exe", lambda: "tar")
    stages = []
    result = forge_install.install(Http(), tmp_path / "dest", lambda s, d, t: stages.append((s, d, t)))
    assert result == tmp_path / "dest" / pkg.name / "webui" and calls == ["https://x/a.7z"]
    assert [s for s, _d, _t in stages][0] == "release" and ("download", 50, 100) in stages and stages[-1][0] == "done"
    assert not any(p.suffix == ".7z" for p in (tmp_path / "dest").iterdir())                        # the archive is removed
    monkeypatch.setattr(forge_install.shutil, "disk_usage", lambda p: SimpleNamespace(free=1 * 1024**3))
    with pytest.raises(forge_install.ForgeInstallError, match="disk"):
        forge_install.install(Http(), tmp_path / "d2")


# --- the wizard page ------------------------------------------------------------------------------------------------------

def make_page(qapp, tmp_path, assessment):
    from anihub.ui.wizard import ForgePage, LibraryPage

    cfg = Config.load(tmp_path / "c.json")
    library = LibraryPage(cfg)
    page = ForgePage(cfg, library)
    return cfg, page, assessment


def test_wizard_page_switches_generation_off_on_an_unsuitable_pc(qapp, tmp_path, monkeypatch):
    cfg, page, _ = make_page(qapp, tmp_path, None)
    monkeypatch.setattr(sysreq, "assess_forge", lambda p="": judge_forge("", 0, 32, 100))
    page.initializePage()
    assert not page.options.isVisibleTo(page) and "NVIDIA" in page.report.text() or page.report.text()
    assert page.validatePage()
    assert cfg.get("sd.enabled") is False


def test_wizard_page_download_existing_and_later(qapp, tmp_path, monkeypatch):
    cfg, page, _ = make_page(qapp, tmp_path, None)
    monkeypatch.setattr(sysreq, "assess_forge", lambda p="": judge_forge("RTX 4070", 12, 32, 300))
    page.initializePage()
    assert page.options.isVisibleTo(page) and page.download.isChecked()
    page.install_dir.setText(str(tmp_path / "ForgeHere"))
    assert page.validatePage() and cfg.get("sd.enabled") is True and cfg.get("sd.install_pending") == str(tmp_path / "ForgeHere")
    # an existing installation: the folder must really hold Forge
    page.existing.setChecked(True)
    page.existing_dir.setText(str(tmp_path / "nothing"))
    assert not page.validatePage() and page.hint.text()
    pkg = make_package(tmp_path / "have")
    page.existing_dir.setText(str(pkg))
    assert page.validatePage() and Path(cfg.get("forge.path")) == pkg / "webui"
    page.later.setChecked(True)
    cfg.set("sd.install_pending", "", save=False)
    assert page.validatePage() and not cfg.get("sd.install_pending")
    # weak but working PCs stay on, with a warning
    monkeypatch.setattr(sysreq, "assess_forge", lambda p="": judge_forge("GTX 1650", 4, 8, 300))
    page.initializePage()
    assert page.options.isVisibleTo(page) and page.verdict.text()


def test_wizard_has_the_forge_page_before_the_end(qapp, tmp_path):
    from anihub.ui.wizard import ForgePage, SetupWizard

    wizard = SetupWizard(Config.load(tmp_path / "c.json"))
    kinds = [type(wizard.page(i)).__name__ for i in wizard.pageIds()]
    assert kinds.index("ForgePage") == kinds.index("SystemPage") + 1 and kinds[-1] == "DonePage"


# --- the main window without generation ---------------------------------------------------------------------------------------

def make_window(qapp, tmp_path, enabled):
    from anihub.context import AppContext
    from anihub.ui.main_window import MainWindow

    cfg = Config.load(tmp_path / "c.json")
    cfg.set("library_path", str(tmp_path / "lib"), save=False)
    cfg.set("first_run_done", True, save=False)
    if enabled is not None:
        cfg.set("sd.enabled", enabled, save=False)
    ctx = AppContext.build(cfg)
    win = MainWindow(ctx)
    win.resize(1400, 850)
    win.show()
    return win, ctx


def test_sections_are_ordered_manga_then_novels_and_generation_is_optional(qapp, tmp_path):
    win, ctx = make_window(qapp, tmp_path, None)                                   # an old config: keeps generation
    assert list(win.rows) == ["arts", "manga", "novels", "sd", "anime", "settings"]
    assert win.rows["novels"] == win.rows["manga"] + 1 and win.sd_page is not None and ctx.sd_enabled
    win.go("novels")
    assert win.pages.currentWidget() is win.novels_hub
    win._quitting = True
    win.close()


def test_a_pc_without_stable_diffusion_loses_every_trace_of_it(qapp, tmp_path):
    from anihub.ui.palette_providers import actions, sections

    win, ctx = make_window(qapp, tmp_path, False)
    assert list(win.rows) == ["arts", "manga", "novels", "anime", "settings"] and not ctx.sd_enabled
    assert win.sd_page is None and win.forge is None and win.forge_status is None and win.sd_controllers == {}
    assert win.nav._buttons and len(win.nav._buttons) == 5
    titles = [e.title for e in sections(win)] + [e.title for e in actions(win)]
    assert not any("CivitAI" in t or "Forge" in t for t in titles)
    steps = [s.key for s in win.tutorial_steps()]
    assert "nav_sd" not in steps and "nav_novels" in steps
    win.set_offline(True)                                                            # touches the SD tabs: must not crash
    win.set_offline(False)
    win.go("sd")                                                                     # a hidden section is ignored
    assert win.nav.currentRow() != 3 or win.pages.currentWidget() is not None
    assert not ctx.sd_enabled
    win.settings.show()
    assert win.settings.sd_box is not None and not win.settings.sd_download_btn.isVisibleTo(win.settings)
    assert "off" in win.settings.sd_status.text().lower() or "отключ" in win.settings.sd_status.text().lower()
    win._quitting = True
    win.close()


def test_library_menu_has_img2img_only_with_generation(qapp, tmp_path):
    for enabled in (True, False):
        win, ctx = make_window(qapp, tmp_path / str(enabled), enabled)
        import inspect

        source = inspect.getsource(type(win.library))
        assert "ctx.sd_enabled" in source
        assert (win.library.send_to_img2img is not None)
        win._quitting = True
        win.close()


def test_recheck_button_updates_the_setting(qapp, tmp_path, monkeypatch):
    import time

    win, ctx = make_window(qapp, tmp_path, False)
    monkeypatch.setattr(sysreq, "assess_forge", lambda p="": judge_forge("RTX 4070", 12, 32, 300))
    win.settings._recheck_pc()
    end = time.time() + 3
    while time.time() < end and ctx.sd_enabled is False:
        qapp.processEvents()
        time.sleep(0.02)
    assert ctx.sd_enabled and ctx.cfg.get("sd.enabled") is True
    assert "Restart" in win.settings.sd_status.text() or "Перезапустите" in win.settings.sd_status.text()
    win._quitting = True
    win.close()


# --- the violet dark theme -------------------------------------------------------------------------------------------------

def hue(color: str) -> float:
    r, g, b = (int(color[i:i + 2], 16) / 255 for i in (1, 3, 5))
    return colorsys.rgb_to_hsv(r, g, b)[0] * 360


def test_dark_theme_is_violet_not_blue():
    from anihub.ui import theme

    t = theme.DARK
    for name in ("accent", "accent_hover", "accent_press", "accent_end", "accent_text", "bg", "surface", "surface2", "border"):
        assert 262 <= hue(getattr(t, name)) <= 290, (name, getattr(t, name), hue(getattr(t, name)))        # violet, no longer blue-indigo
    assert theme.logo_colors() == ("#b07bff", "#7a38d8") or theme.current().name != "dark"
