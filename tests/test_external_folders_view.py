"""ui/external_folders_view.py: browsing a folder on disk directly, without importing it, plus an explicit
"Add to library" action that goes through the real import path when asked."""
import time
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QFileDialog, QInputDialog

from anihub.context import AppContext
from anihub.core.config import Config
from anihub.ui.external_folders_view import ROLE, ExternalFoldersView, has_subfolder, list_media


def make_ctx(tmp_path):
    cfg = Config.load(tmp_path / "c.json")
    cfg.set("library_path", str(tmp_path / "lib"), save=False)
    return AppContext.build(cfg)


def make_image(path: Path, color: str = "red") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    img = QImage(4, 4, QImage.Format.Format_RGBA8888)
    img.fill(QColor(color))
    assert img.save(str(path), "PNG")
    return path


def pump_until(qapp, condition, tries: int = 600) -> None:
    """A longer budget than the usual 200-try/1s convention elsewhere in this suite: thumbs_loaded() below waits
    for a second async leg (the thumbnail decode on ui/grid.py's thumb_pool(), not just the item being added),
    which can lag noticeably when the shared global thread pool is also busy with unrelated background work from
    other tests still finishing up."""
    for _ in range(tries):
        qapp.processEvents()
        if condition():
            return
        time.sleep(0.005)
    raise AssertionError("condition never became true")


def thumbs_loaded(view, n: int) -> bool:
    """True only once every item AND its thumbnail icon (decoded on a background pool, ui/grid.py's thumb_pool())
    has actually arrived -- waiting on item count alone lets the test (and its tmp_path) tear down while a decode
    is still in flight, which can crash the interpreter if the file disappears mid-read."""
    grid = view.grid
    return grid.count() == n and all(not grid.item(i).icon().isNull() for i in range(n))


# --- pure helpers ----------------------------------------------------------------------------------------------

def test_list_media_only_returns_recognised_files_directly_inside(tmp_path):
    make_image(tmp_path / "a.png")
    (tmp_path / "notes.txt").write_text("x")
    sub = tmp_path / "sub"
    make_image(sub / "b.png")
    names = {p.name for p in list_media(tmp_path)}
    assert names == {"a.png"}                                        # "notes.txt" excluded, "sub/b.png" not recursed into


def test_list_media_on_a_missing_folder_is_empty_not_an_error(tmp_path):
    assert list_media(tmp_path / "does_not_exist") == []


def test_has_subfolder(tmp_path):
    make_image(tmp_path / "a.png")
    assert not has_subfolder(tmp_path)
    (tmp_path / "sub").mkdir()
    assert has_subfolder(tmp_path)


# --- the view --------------------------------------------------------------------------------------------------

@pytest.fixture
def env(qapp, tmp_path):
    ctx = make_ctx(tmp_path)
    view = ExternalFoldersView(ctx)
    view.show()
    yield view, ctx
    view.close()


def find_item(view, path: Path):
    stack = [view.tree.topLevelItem(i) for i in range(view.tree.topLevelItemCount())]
    while stack:
        item = stack.pop()
        data = item.data(0, ROLE)
        if data[0] != "placeholder" and data[1] == path:
            return item
        stack += [item.child(i) for i in range(item.childCount())]
    return None


def test_no_roots_yet(env):
    view, ctx = env
    assert view.tree.topLevelItemCount() == 0
    assert view.grid.count() == 0


def test_add_root_shows_up_in_the_tree_and_in_config(env, monkeypatch, tmp_path):
    view, ctx = env
    folder = tmp_path / "photos"
    folder.mkdir()
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", staticmethod(lambda *a, **k: str(folder)))
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("My photos", True)))
    view._add_root()
    assert ctx.cfg.get("library.external_folders") == [{"path": str(folder), "label": "My photos"}]
    item = find_item(view, folder)
    assert item is not None and item.text(0) == "My photos"


def test_selecting_a_root_loads_its_pictures_into_the_grid(qapp, tmp_path):
    ctx = make_ctx(tmp_path)
    folder = tmp_path / "photos"
    make_image(folder / "a.png")
    make_image(folder / "b.png", "blue")
    ctx.cfg.set("library.external_folders", [{"path": str(folder), "label": "Photos"}], save=False)
    view = ExternalFoldersView(ctx)
    item = find_item(view, folder)
    assert item is not None
    view.tree.setCurrentItem(item)
    assert view.current == folder
    pump_until(qapp, lambda: thumbs_loaded(view, 2))
    names = {p.name for p in view.grid.payloads()}
    assert names == {"a.png", "b.png"}
    view.close()


def test_a_subfolder_gets_a_lazy_placeholder_that_expands_into_real_children(qapp, tmp_path):
    ctx = make_ctx(tmp_path)
    root = tmp_path / "root"
    (root / "sub").mkdir(parents=True)
    make_image(root / "sub" / "a.png")
    ctx.cfg.set("library.external_folders", [{"path": str(root), "label": "Root"}], save=False)
    view = ExternalFoldersView(ctx)
    root_item = find_item(view, root)
    assert root_item.childCount() == 1
    assert root_item.child(0).data(0, ROLE)[0] == "placeholder"

    view.tree.expandItem(root_item)
    view._populate_children(root_item)
    assert root_item.childCount() == 1
    child = root_item.child(0)
    assert child.data(0, ROLE) == ("folder", root / "sub")
    view.close()


def test_removing_a_root_clears_it_from_config_and_the_tree(env, tmp_path):
    view, ctx = env
    folder = tmp_path / "photos"
    folder.mkdir()
    ctx.cfg.set("library.external_folders", [{"path": str(folder), "label": "Photos"}], save=False)
    view.reload_roots()
    assert find_item(view, folder) is not None
    view._remove_root(folder)
    assert ctx.cfg.get("library.external_folders") == []
    assert find_item(view, folder) is None


def test_add_to_library_button_enabled_state_follows_selection(qapp, tmp_path):
    ctx = make_ctx(tmp_path)
    folder = tmp_path / "photos"
    make_image(folder / "a.png")
    ctx.cfg.set("library.external_folders", [{"path": str(folder), "label": "Photos"}], save=False)
    view = ExternalFoldersView(ctx)
    view.tree.setCurrentItem(find_item(view, folder))
    pump_until(qapp, lambda: thumbs_loaded(view, 1))
    assert not view.add_to_library_btn.isEnabled()
    view.grid.item(0).setSelected(True)
    assert view.add_to_library_btn.isEnabled()
    view.close()


def test_add_to_library_copies_the_file_in_without_deleting_the_original(qapp, tmp_path):
    ctx = make_ctx(tmp_path)
    folder = tmp_path / "photos"
    original = make_image(folder / "a.png")
    ctx.cfg.set("library.external_folders", [{"path": str(folder), "label": "Photos"}], save=False)
    view = ExternalFoldersView(ctx)
    view.tree.setCurrentItem(find_item(view, folder))
    pump_until(qapp, lambda: thumbs_loaded(view, 1))
    view.grid.item(0).setSelected(True)

    view._add_selected_to_library()
    pump_until(qapp, lambda: "Добавлено" in view.path_label.text() or "Added" in view.path_label.text())
    assert original.exists()                                          # the external file itself is untouched
    assert ctx.db.count_items("art") == 1
    view.close()


def test_grid_context_menu_offers_the_shared_image_menu(qapp, tmp_path, monkeypatch):
    import anihub.ui.external_folders_view as efv_module

    ctx = make_ctx(tmp_path)
    folder = tmp_path / "photos"
    make_image(folder / "a.png")
    ctx.cfg.set("library.external_folders", [{"path": str(folder), "label": "Photos"}], save=False)
    view = ExternalFoldersView(ctx)
    view.tree.setCurrentItem(find_item(view, folder))
    pump_until(qapp, lambda: thumbs_loaded(view, 1))

    seen = {}
    monkeypatch.setattr(efv_module, "show_image_menu", lambda parent, pos, **kw: seen.update(kw))
    rect = view.grid.visualItemRect(view.grid.item(0))
    global_pos = view.grid.viewport().mapToGlobal(rect.center())
    view._grid_menu(global_pos)
    assert seen["path"] == folder / "a.png"
    view.close()
