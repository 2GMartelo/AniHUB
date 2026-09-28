"""The "send this picture to VTube" bridge from Generate/History/Library (ui/sd_page.py's GenerateView, sd_history.py's
HistoryView, library_view.py's LibraryView) into the VTube tab (ui/vtube_view.py). None of these three views had any
direct construction test before this file -- GenerateView needs the most scaffolding (it kicks off a few background
Forge-data fetches at construction time; FakeApi below is just enough surface that those fail quietly instead of
raising anything that would abort the test)."""
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QColor, QImage

from anihub.context import AppContext
from anihub.core.config import Config
from anihub.core.db import Database
from anihub.services.procservice import ServiceState
from anihub.ui.library_view import LibraryView
from anihub.ui.sd_history import HistoryView
from anihub.ui.sd_page import GenerateView
from anihub.ui.sd_queue import QueueController


def make_ctx(tmp_path, **cfg_values):
    cfg = Config.load(tmp_path / "c.json")
    cfg.set("library_path", str(tmp_path / "lib"), save=False)
    cfg.set("forge.path", str(tmp_path / "forge"), save=False)
    for k, v in cfg_values.items():
        cfg.set(k, v, save=False)
    return AppContext.build(cfg)


def make_png(path: Path, color: str = "red") -> Path:
    img = QImage(8, 8, QImage.Format.Format_RGBA8888)
    img.fill(QColor(color))
    path.parent.mkdir(parents=True, exist_ok=True)
    assert img.save(str(path), "PNG")
    return path


class FakeApi:
    """Just enough surface that GenerateView's own background start-up fetches fail quietly (caught by run_async)
    instead of raising something that reaches the test."""
    def interrupt(self):
        pass


class FakeForgeController(QObject):
    state_changed = Signal(str)
    error = Signal(str)

    def __init__(self):
        super().__init__()
        self.state = ServiceState.RUNNING
        self.manager = SimpleNamespace(api=FakeApi())

    def set_busy(self, busy):
        pass


# --- GenerateView: the results-grid "Send to VTube" button ------------------------------------------------------

@pytest.fixture
def generate(tmp_path, qapp):
    ctx = make_ctx(tmp_path, **{"comfyui.path": str(tmp_path / "comfy")})
    ctrl = FakeForgeController()
    qc = QueueController(ctx, {"main": ctrl})
    view = GenerateView(ctx, ctrl, qc)
    yield SimpleNamespace(view=view, ctx=ctx)


def test_vtube_button_hidden_when_not_configured(tmp_path, qapp):
    ctx = make_ctx(tmp_path)                                       # no comfyui.path
    ctrl = FakeForgeController()
    view = GenerateView(ctx, ctrl, QueueController(ctx, {"main": ctrl}))
    assert view.vtube_btn.isHidden()


def test_vtube_button_visible_and_gated_by_selection(generate):
    view = generate.view
    assert not view.vtube_btn.isHidden()
    assert not view.vtube_btn.isEnabled()                          # nothing generated/selected yet


def test_vtube_button_emits_the_selected_results_path(generate, tmp_path):
    from anihub.services.generation import GenResult

    view = generate.view
    png = make_png(tmp_path / "r.png")
    view.add_results([GenResult(png, 1, {"prompt": "x"})])
    view.grid.item(0).setSelected(True)
    view._update_buttons()
    assert view.vtube_btn.isEnabled()

    seen = []
    view.send_to_vtube.connect(seen.append)
    view.vtube_btn.click()

    assert seen == [png]


def test_vtube_button_disabled_with_more_than_one_selected(generate, tmp_path):
    from anihub.services.generation import GenResult

    view = generate.view
    a, b = make_png(tmp_path / "a.png"), make_png(tmp_path / "b.png", "blue")
    view.add_results([GenResult(a, 1, {}), GenResult(b, 2, {})])
    view.grid.item(0).setSelected(True)
    view.grid.item(1).setSelected(True)
    view._update_buttons()
    assert not view.vtube_btn.isEnabled()


# --- HistoryView: the context-menu action -----------------------------------------------------------------------

def test_history_to_vtube_emits_the_rows_own_file(tmp_path, qapp):
    import time

    ctx = make_ctx(tmp_path, **{"comfyui.path": str(tmp_path / "comfy")})
    view = HistoryView(ctx)
    png = make_png(ctx.paths.root / "sd" / "generated" / "a.png")
    ctx.db.add_history([{"path": "sd/generated/a.png", "seed": 1, "model": "m", "prompt": "p", "negative": "",
                        "params": {}, "backend": "main"}])
    view.reload()
    for _ in range(200):                    # the grid fills asynchronously; give the one background load a moment
        qapp.processEvents()
        if view.grid.count():
            break
        time.sleep(0.005)
    assert view.grid.count() == 1
    view.grid.setCurrentItem(view.grid.item(0))

    seen = []
    view.send_to_vtube.connect(seen.append)
    view._to_vtube()

    assert seen == [png]


# HistoryView's own _menu() calls QMenu.exec(pos), a blocking popup -- not something an automated test can safely
# call. Its "if self.ctx.vtube_enabled:" gate is the same shape as LibraryView's own (tested below through
# _fill_menu, which only builds the menu and never shows it), so it is not re-verified separately here.


# --- LibraryView: the context-menu action -------------------------------------------------------------------------

def load_one_item(view, ctx, tmp_path, name: str) -> None:
    make_png(ctx.paths.root / "arts" / "local" / f"{name}.png")
    ctx.db.add_item(kind="art", path=f"arts/local/{name}.png", sha256=name * 8, ext="png",
                    source_site="local", source_post_id=name)
    view.reload()
    import time

    from PySide6.QtWidgets import QApplication
    for _ in range(200):
        QApplication.processEvents()
        if view.grid.count():
            return
        time.sleep(0.005)
    raise AssertionError("item never loaded into the grid")


def test_library_menu_offers_vtube_only_when_enabled(tmp_path, qapp):
    from PySide6.QtWidgets import QMenu

    ctx = make_ctx(tmp_path / "off")
    view = LibraryView(ctx)
    load_one_item(view, ctx, tmp_path, "a")
    view.grid.item(0).setSelected(True)
    menu = QMenu()
    view._fill_menu(menu)
    assert not any(a.text() == "Отправить в VTube" for a in menu.actions())

    ctx2 = make_ctx(tmp_path / "on", **{"comfyui.path": str(tmp_path / "comfy")})
    view2 = LibraryView(ctx2)
    load_one_item(view2, ctx2, tmp_path, "b")
    view2.grid.item(0).setSelected(True)
    menu2 = QMenu()
    view2._fill_menu(menu2)
    vtube_actions = [a for a in menu2.actions() if a.text() == "Отправить в VTube"]
    assert len(vtube_actions) == 1

    seen = []
    view2.send_to_vtube.connect(seen.append)
    vtube_actions[0].trigger()
    assert seen == [ctx2.paths.root / "arts" / "local" / "b.png"]
