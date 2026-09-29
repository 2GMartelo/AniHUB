"""LibraryView._trash()/_restore() push onto ctx.undo (core/undo.py) -- the one library action actually worth an
"oops, undo that" safety net for. Reuses test_vtube_bridge.py's ctx/item-loading helpers."""
import time
from pathlib import Path

from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication

from anihub.context import AppContext
from anihub.core.config import Config
from anihub.ui.library_view import LibraryView


def make_ctx(tmp_path, **cfg_values):
    cfg = Config.load(tmp_path / "c.json")
    cfg.set("library_path", str(tmp_path / "lib"), save=False)
    for k, v in cfg_values.items():
        cfg.set(k, v, save=False)
    return AppContext.build(cfg)


def make_png(path: Path, color: str = "red") -> Path:
    img = QImage(8, 8, QImage.Format.Format_RGBA8888)
    img.fill(QColor(color))
    path.parent.mkdir(parents=True, exist_ok=True)
    assert img.save(str(path), "PNG")
    return path


def load_one_item(view, ctx, tmp_path, name: str) -> None:
    make_png(ctx.paths.root / "arts" / "local" / f"{name}.png")
    ctx.db.add_item(kind="art", path=f"arts/local/{name}.png", sha256=name * 8, ext="png",
                    source_site="local", source_post_id=name)
    view.reload()
    for _ in range(200):
        QApplication.processEvents()
        if view.grid.count():
            return
        time.sleep(0.005)
    raise AssertionError("item never loaded into the grid")


def pump_until(qapp, condition, tries: int = 200) -> None:
    for _ in range(tries):
        qapp.processEvents()
        if condition():
            return
        time.sleep(0.005)
    raise AssertionError("condition never became true")


def test_trashing_pushes_an_undo_entry_and_undo_restores_the_item(qapp, tmp_path):
    ctx = make_ctx(tmp_path)
    view = LibraryView(ctx)
    load_one_item(view, ctx, tmp_path, "a")
    row = ctx.db.search_items(kind="art", limit=10)[0]
    ctx.cfg.set("ui.confirm_trash", False, save=False)  # skip the confirmation dialog

    view._trash([row["id"]])
    pump_until(qapp, ctx.undo.can_undo)
    assert ctx.db.search_items(kind="art", trashed=True, limit=10)[0]["id"] == row["id"]

    label = ctx.undo.undo()
    assert label
    pump_until(qapp, lambda: not ctx.db.search_items(kind="art", trashed=True, limit=10))
    assert ctx.db.search_items(kind="art", limit=10)[0]["id"] == row["id"]
    assert ctx.undo.can_redo()

    ctx.undo.redo()
    pump_until(qapp, lambda: bool(ctx.db.search_items(kind="art", trashed=True, limit=10)))


def test_purge_does_not_push_an_undo_entry(qapp, tmp_path):
    """Permanent deletion: nothing to undo. Never loaded into the grid, so no thumbnail cache file is generated --
    on Windows a thumbnail can stay briefly locked by whatever last painted it, which would make purge()'s own
    unrelated unlink() flaky here for reasons that have nothing to do with the undo stack this test is about."""
    ctx = make_ctx(tmp_path)
    view = LibraryView(ctx)
    make_png(ctx.paths.root / "arts" / "local" / "a.png")
    ctx.db.add_item(kind="art", path="arts/local/a.png", sha256="a" * 8, ext="png", source_site="local", source_post_id="a")
    row = ctx.db.search_items(kind="art", limit=10)[0]

    view._file_op(lambda: ctx.library.purge([row["id"]]))
    pump_until(qapp, lambda: not ctx.db.search_items(kind="art", limit=10) and not ctx.db.search_items(kind="art", trashed=True, limit=10))
    assert not ctx.undo.can_undo()
