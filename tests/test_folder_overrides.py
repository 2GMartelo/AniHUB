"""Standard save folders (apps, generations, VTube output, music) auto-created under the library root, each
independently overridable via config -- core/paths.py's LibraryPaths.apps/generations/vtube_out/music, and the
Settings "Folders" box on top of it."""
from types import SimpleNamespace

from anihub.core.config import Config
from anihub.core.paths import LibraryPaths


def test_without_a_cfg_the_defaults_are_plain_subfolders(tmp_path):
    paths = LibraryPaths(tmp_path / "lib")
    assert paths.apps == paths.root / "apps"
    assert paths.generations == paths.sd / "generated"
    assert paths.vtube_out == paths.root / "vtube"
    assert paths.music == paths.root / "music"


def test_an_empty_override_still_falls_back_to_the_default(tmp_path):
    cfg = Config.load(tmp_path / "c.json")
    paths = LibraryPaths(tmp_path / "lib", cfg)
    assert paths.generations == paths.sd / "generated"


def test_a_configured_override_redirects_the_folder(tmp_path):
    cfg = Config.load(tmp_path / "c.json")
    elsewhere = tmp_path / "elsewhere"
    cfg.set("paths.generations", str(elsewhere), save=False)
    paths = LibraryPaths(tmp_path / "lib", cfg)
    assert paths.generations == elsewhere
    assert paths.vtube_out == paths.root / "vtube"                 # the other two are untouched


def test_ensure_creates_all_three_standard_folders_including_overridden_ones(tmp_path):
    cfg = Config.load(tmp_path / "c.json")
    elsewhere = tmp_path / "elsewhere_music"
    cfg.set("paths.music", str(elsewhere), save=False)
    paths = LibraryPaths(tmp_path / "lib", cfg)
    paths.ensure()
    assert paths.apps.is_dir()
    assert paths.generations.is_dir()
    assert paths.vtube_out.is_dir()
    assert elsewhere.is_dir()                                      # the override itself, not the default music/ subfolder
    assert not (paths.root / "music").exists()


# --- Settings UI wiring --------------------------------------------------------------------------------------

def make_ctx(tmp_path):
    from anihub.context import AppContext

    cfg = Config.load(tmp_path / "c.json")
    cfg.set("library_path", str(tmp_path / "lib"), save=False)
    return AppContext.build(cfg)


def test_settings_page_saves_a_folder_override(qapp, tmp_path):
    from anihub.ui.settings import SettingsPage

    ctx = make_ctx(tmp_path)
    page = SettingsPage(ctx)
    elsewhere = tmp_path / "custom_generations"
    page.folder_fields["generations"].setText(str(elsewhere))
    page._save()
    assert ctx.cfg.get("paths.generations") == str(elsewhere)
    assert ctx.paths.generations == elsewhere
    page.close()


def test_settings_page_clearing_the_field_restores_the_default(qapp, tmp_path):
    from anihub.ui.settings import SettingsPage

    ctx = make_ctx(tmp_path)
    ctx.cfg.set("paths.generations", str(tmp_path / "old"), save=False)
    page = SettingsPage(ctx)
    assert page.folder_fields["generations"].text() == str(tmp_path / "old")
    page.folder_fields["generations"].clear()
    page._save()
    assert ctx.cfg.get("paths.generations") == ""
    assert ctx.paths.generations == ctx.paths.sd / "generated"
    page.close()


def test_pick_folder_fills_the_field(qapp, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog, QLineEdit

    from anihub.ui.settings import SettingsPage

    ctx = make_ctx(tmp_path)
    page = SettingsPage(ctx)
    chosen = tmp_path / "chosen_folder"
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", staticmethod(lambda *a, **k: str(chosen)))
    page._pick_folder(page.folder_fields["vtube"])
    assert page.folder_fields["vtube"].text() == str(chosen)
    page.close()
