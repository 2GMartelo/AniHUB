"""LibraryView's "Folders" sidebar section: browsing the library's own arts/sd folders by their real on-disk
structure (core/db.py's folder_tree()/search_items(folder=...), covered on their own in test_library_db.py)."""
import time
from pathlib import Path

from PySide6.QtGui import QColor, QImage

from anihub.context import AppContext
from anihub.core.config import Config
from anihub.ui.library_view import ROLE, LibraryView


def make_ctx(tmp_path):
    cfg = Config.load(tmp_path / "c.json")
    cfg.set("library_path", str(tmp_path / "lib"), save=False)
    return AppContext.build(cfg)


def make_png(path: Path) -> Path:
    img = QImage(4, 4, QImage.Format.Format_RGBA8888)
    img.fill(QColor("red"))
    path.parent.mkdir(parents=True, exist_ok=True)
    assert img.save(str(path), "PNG")
    return path


def add_item(ctx, rel_path: str, post_id: str) -> None:
    make_png(ctx.paths.root / rel_path)
    ctx.db.add_item(kind="art", path=rel_path, sha256=post_id * 8, ext="png", source_site="danbooru", source_post_id=post_id)


def wait_for(qapp, condition, tries: int = 200) -> None:
    for _ in range(tries):
        qapp.processEvents()
        if condition():
            return
        time.sleep(0.005)
    raise AssertionError("condition never became true")


def thumbs_loaded(grid, n: int) -> bool:
    """count() alone only confirms the items were added; waiting for a non-null icon too confirms the
    background thumb_pool() decode finished, so a test's tmp_path is never torn down mid-read."""
    return grid.count() == n and all(not grid.item(i).icon().isNull() for i in range(n))


def find_folder_item(view, full_path: str):
    stack = [view.side.topLevelItem(i) for i in range(view.side.topLevelItemCount())]
    while stack:
        item = stack.pop()
        if item.data(0, ROLE) == ("folder", full_path):
            return item
        stack += [item.child(i) for i in range(item.childCount())]
    return None


def test_no_folders_header_when_the_library_is_empty(qapp, tmp_path):
    ctx = make_ctx(tmp_path)
    view = LibraryView(ctx)
    assert find_folder_item(view, "arts/danbooru") is None
    assert not any(view.side.topLevelItem(i).data(0, ROLE) == ("header", "folder") for i in range(view.side.topLevelItemCount()))


def test_folders_section_mirrors_the_real_subfolders(qapp, tmp_path):
    ctx = make_ctx(tmp_path)
    add_item(ctx, "arts/danbooru/danbooru_1.png", "1")
    add_item(ctx, "arts/local/2026-09/local_1.png", "2")
    view = LibraryView(ctx)
    view.refresh_sidebar()
    assert find_folder_item(view, "arts/danbooru") is not None
    assert find_folder_item(view, "arts/local") is not None
    assert find_folder_item(view, "arts/local/2026-09") is not None


def test_selecting_a_folder_filters_the_grid_to_that_folder_recursively(qapp, tmp_path):
    ctx = make_ctx(tmp_path)
    add_item(ctx, "arts/danbooru/danbooru_1.png", "1")
    add_item(ctx, "arts/local/2026-09/local_1.png", "2")
    add_item(ctx, "arts/local/2026-08/local_2.png", "3")
    view = LibraryView(ctx)
    view.refresh_sidebar()

    item = find_folder_item(view, "arts/local")
    assert item is not None
    view.side.setCurrentItem(item)
    assert view.mode == ("folder", "arts/local")
    wait_for(qapp, lambda: thumbs_loaded(view.grid, 2))
    paths = {row["path"] for row in view.grid.payloads()}
    assert paths == {"arts/local/2026-09/local_1.png", "arts/local/2026-08/local_2.png"}


def test_folder_context_menu_offers_show_in_folder(qapp, tmp_path, monkeypatch):
    import anihub.ui.library_view as lv_module
    from PySide6.QtWidgets import QMenu

    opened = []

    class RecordingMenu(QMenu):
        def exec(self, pos):
            opened.append([a.text() for a in self.actions()])

    monkeypatch.setattr(lv_module, "QMenu", RecordingMenu)
    ctx = make_ctx(tmp_path)
    add_item(ctx, "arts/danbooru/danbooru_1.png", "1")
    view = LibraryView(ctx)
    view.refresh_sidebar()
    item = find_folder_item(view, "arts/danbooru")
    view.side.setCurrentItem(item)
    rect = view.side.visualItemRect(item)

    view._sidebar_menu(rect.center())
    assert opened and opened[0] == ["Показать в папке"]
