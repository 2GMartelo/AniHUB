"""Stable Diffusion Forge: process management + REST client (/sdapi/v1/...).

Forge is an external installation (path in settings). It is started on demand through a generated launcher
that runs the user's own webui-user.bat settings and only appends --api/--port, so their setup stays untouched.
The API is local, so it deliberately bypasses the app-wide proxy.
"""
from __future__ import annotations

import logging
import os
import re
import subprocess
import sys
from pathlib import Path

import httpx

from anihub.core.config import Config
from anihub.services.procservice import NEW_GROUP, NO_WINDOW, ManagedProcess, ServiceState

log = logging.getLogger(__name__)

class ForgeError(Exception):
    """User-presentable Forge problem."""


ForgeState = ServiceState  # kept for callers that already import the Forge name


class ForgeApi:
    def __init__(self, cfg: Config, port: int | None = None):
        self.cfg = cfg
        self._port = port  # None = the primary backend's port from the settings
        self._client = httpx.Client(trust_env=False, timeout=httpx.Timeout(30.0, connect=3.0))

    @property
    def port(self) -> int:
        return self._port or int(self.cfg.get("forge.port", 7860))

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def _call(self, method: str, path: str, *, json=None, params=None, timeout=None):
        try:
            resp = self._client.request(method, self.base_url + path, json=json, params=params,
                                        timeout=timeout if timeout is not None else httpx.USE_CLIENT_DEFAULT)
        except httpx.TransportError as exc:
            raise ForgeError("Forge is not responding") from exc
        if resp.status_code >= 400:
            try:
                body = resp.json()
                detail = body.get("errors") or body.get("detail") or body
            except ValueError:
                detail = resp.text
            raise ForgeError(f"Forge HTTP {resp.status_code}: {str(detail)[:300]}")
        return resp.json() if resp.content else None

    def ping(self) -> bool:
        try:
            self._client.get(self.base_url + "/sdapi/v1/progress", params={"skip_current_image": "true"},
                             timeout=httpx.Timeout(2.0, connect=1.0)).raise_for_status()
            return True
        except (httpx.HTTPError, OSError):
            return False

    def models(self) -> list[dict]:
        return self._call("GET", "/sdapi/v1/sd-models")

    def samplers(self) -> list[str]:
        return [s["name"] for s in self._call("GET", "/sdapi/v1/samplers")]

    def schedulers(self) -> list[str]:
        try:
            return [s.get("label") or s["name"] for s in self._call("GET", "/sdapi/v1/schedulers")]  # labels: "Karras", "Automatic"
        except ForgeError:
            return ["Automatic"]

    def options(self) -> dict:
        return self._call("GET", "/sdapi/v1/options")

    def progress(self) -> dict:
        return self._call("GET", "/sdapi/v1/progress", params={"skip_current_image": "true"},
                          timeout=httpx.Timeout(5.0))

    def txt2img(self, payload: dict) -> dict:
        # Generation can take minutes (plus model loading): no read timeout.
        return self._call("POST", "/sdapi/v1/txt2img", json=payload, timeout=httpx.Timeout(None, connect=5.0))

    def loras(self) -> list[dict]:
        """Installed LoRAs (the sd_forge_lora extension): dicts with name, alias, path."""
        return self._call("GET", "/sdapi/v1/loras") or []

    def embeddings(self) -> list[str]:
        return sorted(((self._call("GET", "/sdapi/v1/embeddings") or {}).get("loaded") or {}))

    def modules(self) -> list[dict]:
        """VAEs / text encoders Forge can load: dicts with model_name, filename."""
        return self._call("GET", "/sdapi/v1/sd-modules") or []

    def upscalers(self) -> list[str]:
        return [u["name"] for u in (self._call("GET", "/sdapi/v1/upscalers") or []) if u.get("name") and u["name"] != "None"]

    def latent_modes(self) -> list[str]:
        try:
            return [m["name"] for m in (self._call("GET", "/sdapi/v1/latent-upscale-modes") or [])]
        except ForgeError:
            return ["Latent"]

    def scripts(self) -> dict:
        """The txt2img/img2img scripts (built-in and extension-provided, e.g. "ADetailer") this Forge currently
        knows about: {"txt2img": [names...], "img2img": [names...]}. What services/addons.py checks a generation
        addon against to know whether it is actually installed."""
        return self._call("GET", "/sdapi/v1/scripts") or {"txt2img": [], "img2img": []}

    REFRESH = {"checkpoints": "refresh-checkpoints", "loras": "refresh-loras", "embeddings": "refresh-embeddings",
               "vae": "refresh-vae"}

    def refresh(self, what: str) -> None:
        """Make Forge rescan a models folder after a download (checkpoints | loras | embeddings | vae)."""
        self._call("POST", f"/sdapi/v1/{self.REFRESH[what]}", timeout=httpx.Timeout(60.0))

    def extra_single(self, payload: dict) -> dict:
        return self._call("POST", "/sdapi/v1/extra-single-image", json=payload, timeout=httpx.Timeout(None, connect=5.0))

    def img2img(self, payload: dict) -> dict:
        return self._call("POST", "/sdapi/v1/img2img", json=payload, timeout=httpx.Timeout(None, connect=5.0))

    def interrupt(self) -> None:
        self._call("POST", "/sdapi/v1/interrupt", timeout=httpx.Timeout(5.0))


def _oem_encoding() -> str:
    if sys.platform != "win32":
        return "utf-8"
    import ctypes
    return f"cp{ctypes.windll.kernel32.GetOEMCP()}"


def build_launcher_script(forge_dir: Path, port: int, nowebui: bool, extra_args: str, offline: bool = False) -> str:
    """Batch file: the user's webui-user.bat settings, minus its final `call webui.bat`, plus our flags."""
    user_bat = forge_dir / "webui-user.bat"
    lines: list[str] = []
    if user_bat.exists():
        text = user_bat.read_text(encoding="utf-8", errors="replace")
        lines = [ln for ln in text.splitlines() if not re.match(r"^\s*call\s+webui\.bat\s*$", ln, re.I)]
    ours = f"--api --port {port}" + (" --nowebui" if nowebui else "") + (f" {extra_args.strip()}" if extra_args.strip() else "")
    # One-click packages keep webui/ next to an environment.bat that puts their bundled Python/Git on PATH
    # (run.bat calls it first); without it Forge would fall back to a broken/other interpreter.
    env_bat = forge_dir.parent / "environment.bat"
    env_call = [f'call "{env_bat}"'] if env_bat.exists() else []
    # Full path in `call`: a bare `call webui.bat` fails when the parent environment defines
    # NoDefaultCurrentDirectoryInExePath (cmd then no longer looks in the current directory).
    # Offline mode: model libraries must not try to reach the Hugging Face hub for anything.
    offline_env = ["set HF_HUB_OFFLINE=1", "set TRANSFORMERS_OFFLINE=1", "set HF_DATASETS_OFFLINE=1"] if offline else []
    script = ["@echo off", *env_call, f'cd /d "{forge_dir}"', *lines, *offline_env,
              f"set COMMANDLINE_ARGS=%COMMANDLINE_ARGS% {ours}", f'call "{forge_dir / "webui.bat"}"']
    return "\r\n".join(script) + "\r\n"


class ForgeManager(ManagedProcess):
    """One Forge backend. The primary ("main") follows the forge.* settings; extra backends (multi-GPU, ТЗ 5.9/5.11)
    are the same installation started on another port, pinned to one GPU through CUDA_VISIBLE_DEVICES."""

    def __init__(self, cfg: Config, work_dir: Path, name: str = "main", port: int | None = None,
                 gpu: int | None = None, nowebui: bool | None = None):
        super().__init__()
        self.cfg = cfg
        self.work_dir = work_dir
        self.name = name
        self.gpu = gpu
        self._nowebui = nowebui
        self.api = ForgeApi(cfg, port)

    @property
    def port(self) -> int:
        return self.api.port

    @property
    def forge_dir(self) -> Path | None:
        raw = self.cfg.get("forge.path")
        return Path(raw) if raw else None

    @property
    def log_file(self) -> Path:  # type: ignore[override]
        return self.work_dir / "logs" / ("forge.log" if self.name == "main" else f"forge-{self.name}.log")

    @property
    def log_path(self) -> Path:
        return self.log_file

    def ping(self) -> bool:
        return self.api.ping()

    def check_install(self) -> str | None:
        """Error message, or None when the configured folder looks like Forge."""
        path = self.forge_dir
        if path is None:
            return "Forge folder is not set"
        if not (path / "webui.bat").exists():
            return f"webui.bat not found in {path}"
        return None

    def _spawn(self) -> subprocess.Popen:
        problem = self.check_install()
        if problem:
            raise ForgeError(problem)
        forge_dir = self.forge_dir
        launcher = self.work_dir / ("forge_launch.bat" if self.name == "main" else f"forge_launch_{self.name}.bat")
        launcher.parent.mkdir(parents=True, exist_ok=True)
        nowebui = self._nowebui if self._nowebui is not None else bool(self.cfg.get("forge.nowebui", False))
        # write_bytes: text mode on Windows would double the CR of our CRLF line ends and cmd would then look for "webui.bat<CR>".
        # cmd reads batch files in the OEM code page, so that is what non-ASCII paths must be encoded with.
        launcher.write_bytes(
            build_launcher_script(forge_dir, self.port, nowebui,
                                  str(self.cfg.get("forge.extra_args", "")),
                                  bool(self.cfg.get("network.offline", False))).encode(_oem_encoding(), errors="replace"))
        env = {**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONUTF8": "1"}
        if self.gpu is not None:
            env["CUDA_VISIBLE_DEVICES"] = str(self.gpu)  # this backend sees only its own GPU (as device 0)
        return subprocess.Popen(
            ["cmd.exe", "/c", str(launcher)], cwd=forge_dir, stdin=subprocess.DEVNULL, stdout=self._open_log(),
            stderr=subprocess.STDOUT, env=env, creationflags=NO_WINDOW | NEW_GROUP)
