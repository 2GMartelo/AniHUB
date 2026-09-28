"""ComfyUI client + process manager (services/comfyui.py) and the shared VRAM slot (services/gpu_scheduler.py) --
infrastructure for ТЗ_rasshirenie_prilozheniya.md, before any real ComfyUI install or model weights exist."""
import json
import subprocess
import threading
import time

import httpx
import pytest

from anihub.core.config import Config
from anihub.services.comfyui import ComfyApi, ComfyError, ComfyManager, find_python, run_workflow
from anihub.services.gpu_scheduler import GpuScheduler
from anihub.services.procservice import ServiceState

WORKFLOW = {"3": {"class_type": "KSampler", "inputs": {}}}


def make_api(tmp_path, handler) -> ComfyApi:
    api = ComfyApi(Config({}, tmp_path / "c.json"))
    api._client = httpx.Client(transport=httpx.MockTransport(handler))
    return api


# --- ComfyApi: real endpoints ------------------------------------------------------------------------------------

def test_ping_uses_system_stats(tmp_path):
    seen = []

    def handler(request):
        seen.append(str(request.url))
        return httpx.Response(200, json={"devices": [{"vram_free": 1024 * 1024 * 1024, "vram_total": 0}]})

    api = make_api(tmp_path, handler)
    assert api.ping() is True
    assert seen[0].endswith("/system_stats")


def test_ping_false_on_connection_error(tmp_path):
    def handler(request):
        raise httpx.ConnectError("refused", request=request)

    assert make_api(tmp_path, handler).ping() is False


def test_vram_free_mb_reads_the_primary_device(tmp_path):
    def handler(request):
        return httpx.Response(200, json={"devices": [{"vram_free": 6 * 1024 * 1024 * 1024}]})

    assert make_api(tmp_path, handler).vram_free_mb() == 6144


def test_vram_free_mb_none_without_a_device(tmp_path):
    assert make_api(tmp_path, lambda r: httpx.Response(200, json={"devices": []})).vram_free_mb() is None


def test_has_node_checks_object_info(tmp_path):
    def handler(request):
        assert request.url.path == "/object_info"
        return httpx.Response(200, json={"WanVideoSampler": {}, "KSampler": {}})

    api = make_api(tmp_path, handler)
    assert api.has_node("WanVideoSampler") and not api.has_node("Nonexistent")


def test_has_node_false_when_comfyui_is_down(tmp_path):
    def handler(request):
        raise httpx.ConnectError("refused", request=request)

    assert make_api(tmp_path, handler).has_node("Anything") is False


def test_queue_prompt_sends_client_id_and_returns_prompt_id(tmp_path):
    sent = {}

    def handler(request):
        sent.update(json.loads(request.content))
        return httpx.Response(200, json={"prompt_id": "abc-123", "number": 1, "node_errors": {}})

    api = make_api(tmp_path, handler)
    pid = api.queue_prompt(WORKFLOW)
    assert pid == "abc-123"
    assert sent["prompt"] == WORKFLOW and sent["client_id"] == api.client_id and "prompt_id" not in sent


def test_queue_prompt_with_explicit_id_sends_it(tmp_path):
    sent = {}

    def handler(request):
        sent.update(json.loads(request.content))
        return httpx.Response(200, json={"prompt_id": "mine", "number": 1, "node_errors": {}})

    api = make_api(tmp_path, handler)
    assert api.queue_prompt(WORKFLOW, prompt_id="mine") == "mine"
    assert sent["prompt_id"] == "mine"


def test_queue_prompt_raises_on_validation_error(tmp_path):
    def handler(request):
        return httpx.Response(200, json={"error": {"message": "bad node"}, "node_errors": {"3": "oops"}})

    with pytest.raises(ComfyError, match="bad node"):
        make_api(tmp_path, handler).queue_prompt(WORKFLOW)


def test_queue_prompt_raises_on_http_error(tmp_path):
    def handler(request):
        return httpx.Response(400, json={"error": "invalid_prompt_id"})

    with pytest.raises(ComfyError, match="400"):
        make_api(tmp_path, handler).queue_prompt(WORKFLOW)


def test_history_none_while_unfinished_then_the_finished_entry(tmp_path):
    def handler(request):
        return httpx.Response(200, json={})  # not present yet: still running

    assert make_api(tmp_path, handler).history("abc") is None

    def handler2(request):
        assert request.url.path == "/history/abc"
        return httpx.Response(200, json={"abc": {"outputs": {"9": {"images": [{"filename": "x.png"}]}},
                                                  "status": {"status_str": "success", "completed": True}}})

    entry = make_api(tmp_path, handler2).history("abc")
    assert entry["outputs"]["9"]["images"][0]["filename"] == "x.png"


def test_view_bytes_sends_the_right_query(tmp_path):
    seen = {}

    def handler(request):
        seen.update(dict(request.url.params))
        return httpx.Response(200, content=b"\x89PNG fake")

    data = make_api(tmp_path, handler).view_bytes("a.png", subfolder="sub", kind="temp")
    assert data == b"\x89PNG fake"
    assert seen == {"filename": "a.png", "subfolder": "sub", "type": "temp"}


def test_view_bytes_raises_on_missing_file(tmp_path):
    with pytest.raises(ComfyError):
        make_api(tmp_path, lambda r: httpx.Response(404)).view_bytes("nope.png")


def test_upload_image_returns_the_stored_name(tmp_path):
    src = tmp_path / "art.png"
    src.write_bytes(b"\x89PNG data")

    def handler(request):
        assert b'name="image"; filename="art.png"' in request.content
        return httpx.Response(200, json={"name": "art (1).png", "subfolder": "", "type": "input"})

    assert make_api(tmp_path, handler).upload_image(src) == "art (1).png"


def test_interrupt_and_free_send_expected_bodies(tmp_path):
    calls = []

    def handler(request):
        calls.append((request.url.path, json.loads(request.content) if request.content else {}))
        return httpx.Response(200)

    api = make_api(tmp_path, handler)
    api.interrupt()
    api.interrupt("pid-1")
    api.free()
    api.free(unload_models=False, free_memory=True)
    assert calls == [
        ("/interrupt", {}), ("/interrupt", {"prompt_id": "pid-1"}),
        ("/free", {"unload_models": True, "free_memory": True}),
        ("/free", {"unload_models": False, "free_memory": True}),
    ]


def test_queue_status_and_clear(tmp_path):
    calls = []

    def handler(request):
        calls.append(request.method)
        if request.method == "GET":
            return httpx.Response(200, json={"queue_running": [1], "queue_pending": []})
        assert json.loads(request.content) == {"clear": True}
        return httpx.Response(200)

    api = make_api(tmp_path, handler)
    assert api.queue_status() == {"queue_running": [1], "queue_pending": []}
    api.clear_queue()
    assert calls == ["GET", "POST"]


def test_call_wraps_transport_errors(tmp_path):
    def handler(request):
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(ComfyError, match="not responding"):
        make_api(tmp_path, handler).system_stats()


# --- run_workflow: submit then poll /history --------------------------------------------------------------------

def test_run_workflow_polls_until_the_history_entry_appears(tmp_path):
    responses = [None, None, {"outputs": {"9": {"images": [{"filename": "out.png"}]}},
                              "status": {"status_str": "success", "completed": True}}]
    calls = {"prompt": 0, "history": 0, "queue": 0}

    def handler(request):
        if request.url.path == "/prompt":
            calls["prompt"] += 1
            return httpx.Response(200, json={"prompt_id": "p1", "number": 1, "node_errors": {}})
        if request.url.path == "/history/p1":
            calls["history"] += 1
            entry = responses.pop(0)
            return httpx.Response(200, json={"p1": entry} if entry else {})
        calls["queue"] += 1
        return httpx.Response(200, json={"queue_running": [["p1"]], "queue_pending": []})

    api = make_api(tmp_path, handler)
    seen_progress = []
    outputs = run_workflow(api, WORKFLOW, on_progress=seen_progress.append, poll_interval=0)
    assert outputs == {"9": {"images": [{"filename": "out.png"}]}}
    assert calls["prompt"] == 1 and calls["history"] == 3 and len(seen_progress) == 2


def test_run_workflow_raises_on_a_failed_job(tmp_path):
    def handler(request):
        if request.url.path == "/prompt":
            return httpx.Response(200, json={"prompt_id": "p1", "number": 1, "node_errors": {}})
        return httpx.Response(200, json={"p1": {"outputs": {},
                                                 "status": {"status_str": "error", "completed": False,
                                                           "messages": ["OOM"]}}})

    with pytest.raises(ComfyError, match="OOM"):
        run_workflow(make_api(tmp_path, handler), WORKFLOW, poll_interval=0)


def test_run_workflow_stops_and_interrupts_when_asked(tmp_path):
    interrupted = []

    def handler(request):
        if request.url.path == "/prompt":
            return httpx.Response(200, json={"prompt_id": "p1", "number": 1, "node_errors": {}})
        if request.url.path == "/history/p1":
            return httpx.Response(200, json={})  # never finishes on its own
        interrupted.append(json.loads(request.content))
        return httpx.Response(200)

    with pytest.raises(ComfyError, match="cancelled"):
        run_workflow(make_api(tmp_path, handler), WORKFLOW, should_stop=lambda: True, poll_interval=0)
    assert interrupted == [{"prompt_id": "p1"}]


# --- ComfyManager: process lifecycle (no real ComfyUI involved) --------------------------------------------------

def test_find_python_prefers_the_portable_layout(tmp_path):
    root = tmp_path / "ComfyUI_windows_portable"
    comfy = root / "ComfyUI"
    comfy.mkdir(parents=True)
    (root / "python_embeded").mkdir()
    (root / "python_embeded" / "python.exe").write_bytes(b"")
    assert find_python(comfy) == root / "python_embeded" / "python.exe"


def test_find_python_falls_back_to_a_venv(tmp_path):
    comfy = tmp_path / "ComfyUI"
    (comfy / "venv" / "Scripts").mkdir(parents=True)
    (comfy / "venv" / "Scripts" / "python.exe").write_bytes(b"")
    assert find_python(comfy) == comfy / "venv" / "Scripts" / "python.exe"


def test_find_python_none_when_neither_exists(tmp_path):
    comfy = tmp_path / "ComfyUI"
    comfy.mkdir()
    assert find_python(comfy) is None


def test_check_install_messages(tmp_path):
    cfg = Config({}, tmp_path / "c.json")
    mgr = ComfyManager(cfg, tmp_path / "work")
    assert "not set" in mgr.check_install()

    comfy = tmp_path / "ComfyUI"
    comfy.mkdir()
    cfg.set("comfyui.path", str(comfy))
    assert "main.py" in mgr.check_install()

    (comfy / "main.py").write_text("")
    assert "Python" in mgr.check_install()

    (comfy / "venv" / "Scripts").mkdir(parents=True)
    (comfy / "venv" / "Scripts" / "python.exe").write_bytes(b"")
    assert mgr.check_install() is None


def test_spawn_launches_main_py_with_listen_and_port(tmp_path):
    comfy = tmp_path / "ComfyUI"
    (comfy / "venv" / "Scripts").mkdir(parents=True)
    (comfy / "venv" / "Scripts" / "python.exe").write_bytes(b"")
    (comfy / "main.py").write_text("")
    cfg = Config({}, tmp_path / "c.json")
    cfg.set("comfyui.path", str(comfy))
    mgr = ComfyManager(cfg, tmp_path / "work")
    mgr.api.ping = lambda: False
    started = {}
    real_popen = subprocess.Popen
    subprocess.Popen = lambda *a, **k: started.update(args=a, kwargs=k) or type("P", (), {"pid": 1, "poll": lambda s: None})()
    try:
        mgr.start()
    finally:
        subprocess.Popen = real_popen
    args = started["args"][0]
    assert args[0] == str(comfy / "venv" / "Scripts" / "python.exe")
    assert args[1:] == [str(comfy / "main.py"), "--listen", "127.0.0.1", "--port", str(mgr.port)]
    assert started["kwargs"]["cwd"] == comfy
    assert mgr.state == ServiceState.STARTING


def test_spawn_raises_when_not_installed(tmp_path):
    cfg = Config({}, tmp_path / "c.json")
    mgr = ComfyManager(cfg, tmp_path / "work")
    mgr.api.ping = lambda: False
    with pytest.raises(ComfyError, match="not set"):
        mgr.start()


def test_attaches_to_an_already_running_server_instead_of_spawning(tmp_path):
    cfg = Config({}, tmp_path / "c.json")
    mgr = ComfyManager(cfg, tmp_path / "work")
    mgr.api.ping = lambda: True
    assert mgr.start() == ServiceState.EXTERNAL


def test_log_file_path(tmp_path):
    mgr = ComfyManager(Config({}, tmp_path / "c.json"), tmp_path / "work")
    assert mgr.log_file == tmp_path / "work" / "logs" / "comfyui.log"


# --- GpuScheduler ---------------------------------------------------------------------------------------------

def test_try_acquire_is_exclusive_and_reentrant_for_the_same_owner():
    sched = GpuScheduler()
    assert sched.try_acquire("forge") is True
    assert sched.try_acquire("forge") is True          # the same owner re-entering does not block itself
    assert sched.try_acquire("comfyui") is False
    assert sched.holder == "forge"
    sched.release("forge")
    assert sched.holder is None
    assert sched.try_acquire("comfyui") is True


def test_release_by_a_non_holder_is_a_no_op():
    sched = GpuScheduler()
    sched.try_acquire("forge")
    sched.release("comfyui")
    assert sched.holder == "forge"


def test_acquire_blocks_until_released_then_the_waiter_gets_it():
    sched = GpuScheduler()
    assert sched.try_acquire("forge") is True
    order = []

    def waiter():
        assert sched.acquire("comfyui", timeout=5) is True
        order.append("comfyui")

    t = threading.Thread(target=waiter)
    t.start()
    time.sleep(0.1)
    assert sched.holder == "forge" and not order  # still waiting
    order.append("forge-done")
    sched.release("forge")
    t.join(5)
    assert order == ["forge-done", "comfyui"] and sched.holder == "comfyui"


def test_acquire_times_out_without_acquiring():
    sched = GpuScheduler()
    sched.try_acquire("forge")
    t0 = time.time()
    assert sched.acquire("comfyui", timeout=0.2) is False
    assert time.time() - t0 < 2
    assert sched.holder == "forge"
