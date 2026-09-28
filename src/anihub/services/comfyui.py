"""ComfyUI: process management + HTTP client for node-graph workflows (video, sound, PSD layer split, 3D --
everything Forge itself does not do; ТЗ_rasshirenie_prilozheniya.md).

ComfyUI is a separate local server, started on demand exactly like Forge (comfyui.path/port in settings). This
module never installs ComfyUI itself or downloads any model weights -- that is services/comfyui_install.py (not
built yet: it needs its own explicit go-ahead, since ComfyUI plus the custom nodes this app will use pull down
several GB of Python packages and model files).

Endpoints below are taken from ComfyUI's own server.py (github.com/comfyanonymous/ComfyUI) rather than guessed;
`run_workflow()` follows the same submit-then-poll shape as its own script_examples/websockets_api_example.py, but
polls /history over plain HTTP instead of opening a WebSocket -- one less dependency, and the same style sd_page.py
already uses to show Forge's progress."""
from __future__ import annotations

import logging
import os
import subprocess
import time
import uuid
from pathlib import Path
from typing import Callable

import httpx

from anihub.core.config import Config
from anihub.services.procservice import NEW_GROUP, NO_WINDOW, ManagedProcess, ServiceState

log = logging.getLogger(__name__)


class ComfyError(Exception):
    """User-presentable ComfyUI problem."""


ComfyState = ServiceState  # kept for callers that already import the Forge-style name


class ComfyApi:
    def __init__(self, cfg: Config, port: int | None = None):
        self.cfg = cfg
        self._port = port  # None = comfyui.port from settings
        # verify=False: only ever talks plain http to 127.0.0.1 (see forge.py for why this also saves ~0.15s/start)
        self._client = httpx.Client(trust_env=False, verify=False, timeout=httpx.Timeout(30.0, connect=3.0))
        self.client_id = uuid.uuid4().hex  # one id per running AniHUB instance; ComfyUI itself does not need it
                                            # to be stable across restarts, only unique per client

    @property
    def port(self) -> int:
        return self._port or int(self.cfg.get("comfyui.port", 8188))

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def _call(self, method: str, path: str, *, json=None, params=None, timeout=None):
        try:
            resp = self._client.request(method, self.base_url + path, json=json, params=params,
                                        timeout=timeout if timeout is not None else httpx.USE_CLIENT_DEFAULT)
        except httpx.TransportError as exc:
            raise ComfyError("ComfyUI is not responding") from exc
        if resp.status_code >= 400:
            try:
                body = resp.json()
                detail = body.get("error") or body
            except ValueError:
                detail = resp.text
            raise ComfyError(f"ComfyUI HTTP {resp.status_code}: {str(detail)[:300]}")
        return resp.json() if resp.content else None

    def ping(self) -> bool:
        try:
            self._client.get(self.base_url + "/system_stats", timeout=httpx.Timeout(2.0, connect=1.0)).raise_for_status()
            return True
        except (httpx.HTTPError, OSError):
            return False

    def system_stats(self) -> dict:
        return self._call("GET", "/system_stats") or {}

    def vram_free_mb(self) -> int | None:
        """Free VRAM on the primary device, in MB -- None when ComfyUI reports no GPU device (CPU-only build)."""
        devices = self.system_stats().get("devices") or []
        return int(devices[0]["vram_free"] / (1024 * 1024)) if devices else None

    def object_info(self) -> dict:
        """Every node class ComfyUI currently knows about, with its inputs -- the ComfyUI equivalent of Forge's
        /sdapi/v1/scripts: what services/addons.py-style code checks to tell whether a custom-node pack (Wan,
        HunyuanVideo-Foley, See-through, TRELLIS...) is actually installed before building a workflow that needs it."""
        return self._call("GET", "/object_info") or {}

    def has_node(self, class_type: str) -> bool:
        try:
            return class_type in self.object_info()
        except ComfyError:
            return False

    def queue_prompt(self, workflow: dict, prompt_id: str | None = None) -> str:
        """Submit an API-format workflow (the JSON ComfyUI's "Save (API Format)" produces, or one built in code).
        Returns the prompt_id `run_workflow` / `history` poll for."""
        payload = {"prompt": workflow, "client_id": self.client_id}
        if prompt_id:
            payload["prompt_id"] = prompt_id
        data = self._call("POST", "/prompt", json=payload, timeout=httpx.Timeout(30.0, connect=5.0)) or {}
        if data.get("error"):
            node_errors = data.get("node_errors") or {}
            raise ComfyError(f"{data['error']}" + (f" ({node_errors})" if node_errors else ""))
        return data["prompt_id"]

    def history(self, prompt_id: str) -> dict | None:
        """None while the job has not finished yet (queued or running); once present, has "outputs" and "status"."""
        data = self._call("GET", f"/history/{prompt_id}") or {}
        return data.get(prompt_id)

    def queue_status(self) -> dict:
        return self._call("GET", "/queue") or {"queue_running": [], "queue_pending": []}

    def clear_queue(self) -> None:
        self._call("POST", "/queue", json={"clear": True})

    def view_bytes(self, filename: str, subfolder: str = "", kind: str = "output") -> bytes:
        """Downloads one output file (image/video/etc.) named by a workflow's own outputs entry."""
        try:
            resp = self._client.get(self.base_url + "/view",
                                    params={"filename": filename, "subfolder": subfolder, "type": kind},
                                    timeout=httpx.Timeout(120.0, connect=5.0))
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise ComfyError(f"could not fetch {filename}") from exc
        return resp.content

    def upload_image(self, path: Path, subfolder: str = "", overwrite: bool = True) -> str:
        """Sends a local picture (e.g. a Forge-generated art, for image-to-video or a PSD layer redo) into ComfyUI's
        input/ folder so a LoadImage node can use it by name; returns that name."""
        try:
            resp = self._client.post(
                self.base_url + "/upload/image",
                files={"image": (path.name, path.read_bytes())},
                data={"subfolder": subfolder, "overwrite": "true" if overwrite else "false"},
                timeout=httpx.Timeout(60.0, connect=5.0))
            resp.raise_for_status()
        except (httpx.HTTPError, OSError) as exc:
            raise ComfyError(f"could not upload {path.name}") from exc
        return resp.json()["name"]

    def interrupt(self, prompt_id: str | None = None) -> None:
        self._call("POST", "/interrupt", json={"prompt_id": prompt_id} if prompt_id else {}, timeout=httpx.Timeout(5.0))

    def free(self, unload_models: bool = True, free_memory: bool = True) -> None:
        """Asks ComfyUI to drop whatever it currently holds in VRAM. Called before Forge (or a differently-sized
        ComfyUI job) is allowed to start, per the ТЗ's "only one heavy model in VRAM at a time"."""
        self._call("POST", "/free", json={"unload_models": unload_models, "free_memory": free_memory},
                   timeout=httpx.Timeout(15.0))


def run_workflow(api: ComfyApi, workflow: dict, on_progress: Callable[[dict], None] | None = None,
                 should_stop: Callable[[], bool] | None = None, poll_interval: float = 0.7) -> dict:
    """Blocking: queue a workflow and wait for it to finish. Returns the finished job's `outputs`: node id -> its
    output dict (e.g. `{"images": [{"filename", "subfolder", "type"}, ...]}` for an image/video-producing node;
    the caller knows which node ids to look at because it built the workflow).

    `on_progress`, if given, is called with the raw /queue reply on every poll (its own queue position, nothing more
    granular -- see the module docstring for why this does not use ComfyUI's WebSocket). `should_stop`, if given, is
    checked on every poll; once true the job is interrupted server-side and ComfyError is raised."""
    prompt_id = api.queue_prompt(workflow)
    while True:
        if should_stop is not None and should_stop():
            api.interrupt(prompt_id)
            raise ComfyError("cancelled")
        entry = api.history(prompt_id)
        if entry is not None:
            status = entry.get("status") or {}
            if status.get("status_str") == "error":
                messages = status.get("messages") or []
                raise ComfyError(f"ComfyUI job failed: {messages[-1] if messages else 'unknown error'}")
            return entry.get("outputs") or {}
        if on_progress is not None:
            try:
                on_progress(api.queue_status())
            except ComfyError:
                pass
        time.sleep(poll_interval)


def find_python(comfy_dir: Path) -> Path | None:
    """The interpreter to launch main.py with, for the two common ComfyUI layouts: a portable Windows build (root/
    ComfyUI + a sibling root/python_embeded/python.exe) or a git checkout with its own venv/. None if neither is
    found -- check_install() then reports the folder as unrecognised instead of guessing further."""
    embedded = comfy_dir.parent / "python_embeded" / "python.exe"
    if embedded.exists():
        return embedded
    venv_python = comfy_dir / "venv" / "Scripts" / "python.exe"
    if venv_python.exists():
        return venv_python
    return None


class ComfyManager(ManagedProcess):
    """One local ComfyUI server."""

    def __init__(self, cfg: Config, work_dir: Path, port: int | None = None):
        super().__init__()
        self.cfg = cfg
        self.work_dir = work_dir
        self.api = ComfyApi(cfg, port)

    @property
    def port(self) -> int:
        return self.api.port

    @property
    def comfy_dir(self) -> Path | None:
        raw = self.cfg.get("comfyui.path")
        return Path(raw) if raw else None

    @property
    def log_file(self) -> Path:  # type: ignore[override]
        return self.work_dir / "logs" / "comfyui.log"

    def ping(self) -> bool:
        return self.api.ping()

    def check_install(self) -> str | None:
        """Error message, or None when the configured folder looks like a runnable ComfyUI."""
        path = self.comfy_dir
        if path is None:
            return "ComfyUI folder is not set"
        if not (path / "main.py").exists():
            return f"main.py not found in {path}"
        if find_python(path) is None:
            return f"no Python found for {path} (expected a sibling python_embeded\\ or a venv\\ inside it)"
        return None

    def _spawn(self) -> subprocess.Popen:
        problem = self.check_install()
        if problem:
            raise ComfyError(problem)
        comfy_dir = self.comfy_dir
        python = find_python(comfy_dir)
        args = [str(python), str(comfy_dir / "main.py"), "--listen", "127.0.0.1", "--port", str(self.port)]
        if self.cfg.get("network.offline", False):
            args.append("--disable-metadata")  # nothing here calls out to the internet on its own either way
        env = {**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONUTF8": "1"}
        return subprocess.Popen(args, cwd=comfy_dir, stdin=subprocess.DEVNULL, stdout=self._open_log(),
                                stderr=subprocess.STDOUT, env=env, creationflags=NO_WINDOW | NEW_GROUP)
