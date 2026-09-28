"""ui/vtube_view.py (Stage 3 UI) and the Settings/AppContext wiring it needs: comfyui.path/port/idle_minutes,
AppContext.comfy/vtube_enabled. FakeController stands in for a real ComfyUI process (mirrors test_sd_queue.py's own
FakeController), so nothing here spawns a process or makes a real network call."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QColor, QImage

from anihub.context import AppContext
from anihub.core.config import Config
from anihub.services import seethrough as st
from anihub.services.procservice import ServiceState
from anihub.ui.vtube_view import VTubeView


def make_png(path: Path, color: str = "red", size=(20, 16)) -> Path:
    img = QImage(*size, QImage.Format.Format_RGBA8888)
    img.fill(QColor(color))
    path.parent.mkdir(parents=True, exist_ok=True)
    assert img.save(str(path), "PNG")
    return path


def make_ctx(tmp_path, **cfg_values):
    cfg = Config.load(tmp_path / "c.json")
    cfg.set("library_path", str(tmp_path / "lib"), save=False)
    cfg.set("forge.path", str(tmp_path / "forge"), save=False)  # sd_enabled needs this
    for k, v in cfg_values.items():
        cfg.set(k, v, save=False)
    return AppContext.build(cfg)


class FakeApi:
    def __init__(self, installed=True):
        self.installed = installed
        self.uploaded = []
        self.unloaded = 0
        self.interrupted = []

    def object_info(self):
        return {n: {} for n in st.REQUIRED_NODES} if self.installed else {}

    def upload_image(self, path):
        self.uploaded.append(path)
        return path.name

    def unload_checkpoint(self):
        self.unloaded += 1

    def interrupt(self, prompt_id=None):
        self.interrupted.append(prompt_id)


class FakeComfyController(QObject):
    """Stands in for ui.forge_controller.ServiceController wrapping a services.comfyui.ComfyManager."""
    state_changed = Signal(str)

    def __init__(self, comfy_dir: Path, ready=True, installed=True):
        super().__init__()
        self.state = ServiceState.RUNNING if ready else ServiceState.STOPPED
        self.manager = SimpleNamespace(api=FakeApi(installed=installed), comfy_dir=comfy_dir, gpu=None,
                                       log_tail=lambda lines=200: "")
        self.started = self.stopped = self.polled = 0

    def start(self):
        self.started += 1
        self.state = ServiceState.RUNNING
        self.state_changed.emit("running")

    def stop(self):
        self.stopped += 1
        self.state = ServiceState.STOPPED
        self.state_changed.emit("stopped")

    def poll(self):
        self.polled += 1


class FakeForgeController(QObject):
    def __init__(self, ready=True):
        super().__init__()
        self.state = ServiceState.RUNNING if ready else ServiceState.STOPPED
        self.manager = SimpleNamespace(api=FakeApi())


@pytest.fixture
def env(tmp_path, qapp):
    ctx = make_ctx(tmp_path, **{"comfyui.path": str(tmp_path / "comfy")})
    comfy_dir = tmp_path / "comfy"
    (comfy_dir / "output").mkdir(parents=True)
    comfy = FakeComfyController(comfy_dir)
    forge = {"main": FakeForgeController()}
    view = VTubeView(ctx, comfy, forge)
    view.show()
    yield SimpleNamespace(view=view, ctx=ctx, comfy=comfy, forge=forge, comfy_dir=comfy_dir, tmp_path=tmp_path)
    view.close()


def write_output(comfy_dir: Path, prefix: str, tags: list[str], size=(20, 16)) -> None:
    entries = []
    for i, tag in enumerate(tags):
        png = comfy_dir / "output" / f"{prefix}_ts_uid_{tag}.png"
        make_png(png, "blue", size=size)
        entries.append({"name": tag, "filename": png.name, "left": i, "top": i,
                        "right": i + size[0], "bottom": i + size[1], "depth_median": 1.0 - i * 0.1})
    (comfy_dir / "output" / f"{prefix}_ts_uid_layers.json").write_text(
        json.dumps({"prefix": prefix, "layers": entries, "width": 100, "height": 100}), encoding="utf-8")


# --- AppContext / config wiring --------------------------------------------------------------------------------

def test_vtube_enabled_needs_both_sd_and_a_comfyui_path(tmp_path, qapp):
    assert make_ctx(tmp_path).vtube_enabled is False
    assert make_ctx(tmp_path, **{"comfyui.path": str(tmp_path)}).vtube_enabled is True
    cfg = Config.load(tmp_path / "c2.json")
    cfg.set("library_path", str(tmp_path / "lib2"), save=False)
    cfg.set("comfyui.path", str(tmp_path), save=False)          # no forge.path: sd_enabled is False
    assert AppContext.build(cfg).vtube_enabled is False


def test_context_always_builds_a_comfy_manager(tmp_path, qapp):
    ctx = make_ctx(tmp_path)
    assert ctx.comfy.check_install() is not None                # not configured, but present and asks cleanly


# --- service status chip / buttons -----------------------------------------------------------------------------

def test_polls_an_already_running_comfyui_on_construction(env):
    assert env.comfy.polled == 1


def test_start_stop_buttons_drive_the_controller(tmp_path, qapp):
    ctx = make_ctx(tmp_path)
    comfy = FakeComfyController(tmp_path / "c", ready=False)
    view = VTubeView(ctx, comfy, {})
    view.stop_btn.click()                                          # disabled while stopped: no-op
    assert comfy.stopped == 0
    view.start_btn.click()
    assert comfy.started == 1
    view._on_state("running")
    view.stop_btn.click()
    assert comfy.stopped == 1


def test_button_enablement_follows_state(tmp_path, qapp):
    ctx = make_ctx(tmp_path)
    comfy = FakeComfyController(tmp_path / "c", ready=False)
    view = VTubeView(ctx, comfy, {})
    assert view.start_btn.isEnabled() and not view.stop_btn.isEnabled()
    comfy.start()
    view._on_state("running")
    assert not view.start_btn.isEnabled() and view.stop_btn.isEnabled()


# --- picking a picture -------------------------------------------------------------------------------------------

def test_load_path_shows_a_preview_and_enables_generate_once_ready(env, tmp_path):
    assert not env.view.generate_btn.isEnabled()                 # no picture yet
    png = make_png(tmp_path / "a.png")
    env.view.load_path(png)
    assert env.view.path == png
    assert not env.view.preview.pixmap().isNull()
    assert env.view.generate_btn.isEnabled()


def test_load_path_of_a_broken_file_falls_back_to_the_filename(env, tmp_path):
    bad = tmp_path / "bad.png"
    bad.write_bytes(b"not a png")
    env.view.load_path(bad)
    assert env.view.path == bad
    assert env.view.preview.text() == "bad.png"


def test_drop_event_loads_the_dropped_file(env, tmp_path):
    from PySide6.QtCore import QMimeData, QPointF, QUrl
    from PySide6.QtGui import QDropEvent
    from PySide6.QtCore import Qt

    png = make_png(tmp_path / "dropped.png")
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(png))])
    event = QDropEvent(QPointF(5, 5), Qt.DropAction.CopyAction, mime, Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier)
    env.view.dropEvent(event)
    assert env.view.path == png


# --- generation: end to end with a fake run_workflow --------------------------------------------------------------

def test_generate_runs_the_pipeline_and_shows_results(env, tmp_path, monkeypatch, qapp):
    png = make_png(tmp_path / "art.png")
    env.view.load_path(png)
    save_to = tmp_path / "out.psd"
    monkeypatch.setattr("anihub.ui.vtube_view.QFileDialog.getSaveFileName", lambda *a, **k: (str(save_to), ""))

    def fake_run_workflow(api, workflow, on_progress=None, should_stop=None, poll_interval=0.7):
        prefix = workflow["7"]["inputs"]["filename_prefix"]
        write_output(env.comfy_dir, prefix, ["face", "hair"])
        return {}

    monkeypatch.setattr(st, "run_workflow", fake_run_workflow)
    from anihub.ui import vtube_view as vv
    monkeypatch.setattr(vv, "run_async", lambda fn, on_done=None, on_error=None: on_done(fn()))

    env.view._generate()

    assert save_to.exists()
    assert env.view.result is not None and env.view.layer_list.count() == 2
    # write_output gave "face" the larger depth_median (farther) -- collect_output reverses back-to-front into
    # top-to-bottom, so "hair" (closer) ends up first
    assert [env.view.layer_list.item(i).text() for i in range(2)] == ["hair", "face"]
    assert not env.view.result_preview.pixmap().isNull()
    assert env.view.save_btn.isEnabled() and env.view.reveal_btn.isEnabled()
    assert env.forge["main"].manager.api.unloaded == 1               # free_others actually unloaded Forge's checkpoint
    assert env.comfy.manager.api.uploaded == [png]


def test_generate_does_nothing_without_a_picture(env):
    env.view._generate()
    assert env.view.status.text()                                    # "open a picture first"-style message


def test_generate_refuses_when_see_through_is_not_installed(env, tmp_path):
    env.comfy.manager.api.installed = False
    env.view.load_path(make_png(tmp_path / "a.png"))
    env.view._generate()
    assert "See-through" in env.view.status.text() or "не установлен" in env.view.status.text()


def fake_run_async(fn, on_done=None, on_error=None):
    """A synchronous stand-in for ui.workers.run_async: calls `fn` right here (still off any real thread pool),
    and routes an exception to `on_error` the same way the real worker's try/except does."""
    try:
        result = fn()
    except Exception as exc:  # noqa: BLE001
        if on_error is not None:
            on_error(exc)
    else:
        if on_done is not None:
            on_done(result)


def test_generate_cancelled_reports_cancelled(env, tmp_path, monkeypatch, qapp):
    from anihub.services.comfyui import ComfyError
    from anihub.ui import vtube_view as vv

    png = make_png(tmp_path / "art.png")
    env.view.load_path(png)
    monkeypatch.setattr(vv.QFileDialog, "getSaveFileName", lambda *a, **k: (str(tmp_path / "o.psd"), ""))

    def fake_run_workflow(api, workflow, on_progress=None, should_stop=None, poll_interval=0.7):
        env.view._interrupting = True                  # simulate a Cancel click that happened mid-run
        assert should_stop() is True
        raise ComfyError("cancelled")

    monkeypatch.setattr(st, "run_workflow", fake_run_workflow)
    monkeypatch.setattr(vv, "run_async", fake_run_async)

    env.view._generate()

    assert "Отмен" in env.view.status.text() or "cancel" in env.view.status.text().lower()
    assert not env.view._running


def test_save_as_writes_a_new_copy_from_the_in_memory_result(env, tmp_path, monkeypatch):
    from anihub.services.psd_writer import PsdLayer
    import numpy as np
    from anihub.ui import vtube_view as vv

    env.view.result = st.SeeThroughResult(
        layers=[PsdLayer("x", np.zeros((4, 4, 4), dtype=np.uint8), 0, 0)], width=10, height=10, tags=["x"])
    dest = tmp_path / "copy.psd"
    monkeypatch.setattr(vv.QFileDialog, "getSaveFileName", lambda *a, **k: (str(dest), ""))

    env.view._save_as()

    assert dest.exists()
    assert dest.name in env.view.status.text()
