"""Shared lifecycle for external local services (Forge, Suwayomi): spawn on demand, poll, stop, keep a log."""
from __future__ import annotations

import logging
import os
import subprocess
import threading
from enum import Enum
from pathlib import Path

log = logging.getLogger(__name__)

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
NEW_GROUP = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)


class ServiceState(str, Enum):
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"    # started by AniHUB
    EXTERNAL = "external"  # was already running; AniHUB will never stop it
    FAILED = "failed"      # the process exited before the API came up

    @property
    def ready(self) -> bool:
        return self in (ServiceState.RUNNING, ServiceState.EXTERNAL)


class ManagedProcess:
    """Subclasses implement ping() and _spawn(); everything else is shared."""

    log_file: Path

    def __init__(self):
        self.proc: subprocess.Popen | None = None
        self.state = ServiceState.STOPPED
        self._lock = threading.Lock()

    def ping(self) -> bool:  # pragma: no cover - abstract
        raise NotImplementedError

    def _spawn(self) -> subprocess.Popen:  # pragma: no cover - abstract
        raise NotImplementedError

    def _open_log(self):
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
        return self.log_file.open("wb")

    def start(self) -> ServiceState:
        with self._lock:
            if self.proc is not None and self.proc.poll() is None:
                return self.state
            if self.ping():  # already running (started by the user): attach, never kill
                self.state = ServiceState.EXTERNAL
                return self.state
            self.proc = self._spawn()
            self.state = ServiceState.STARTING
            log.info("%s started, pid %s", type(self).__name__, self.proc.pid)
            return self.state

    def stop(self) -> None:
        """Stop the process we started (never an external one)."""
        with self._lock:
            proc, self.proc = self.proc, None
            if proc is not None and proc.poll() is None:
                # /T kills the whole tree: cmd.exe -> python/java -> child workers
                subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True,
                               creationflags=NO_WINDOW)
                log.info("%s stopped (pid %s)", type(self).__name__, proc.pid)
            self.state = ServiceState.STOPPED

    def refresh(self) -> ServiceState:
        """Recompute the state; does a network ping, so call from a worker thread."""
        up = self.ping()
        with self._lock:
            alive = self.proc is not None and self.proc.poll() is None
            if up:
                self.state = ServiceState.RUNNING if alive else ServiceState.EXTERNAL
            elif alive:
                self.state = ServiceState.STARTING
            elif self.state in (ServiceState.STARTING, ServiceState.RUNNING) and self.proc is not None:
                self.state = ServiceState.FAILED  # died without being asked to stop
            elif self.state != ServiceState.FAILED:
                self.state = ServiceState.STOPPED
            return self.state

    def log_tail(self, lines: int = 200) -> str:
        try:
            with self.log_file.open("rb") as fh:
                fh.seek(0, os.SEEK_END)
                size = fh.tell()
                fh.seek(max(0, size - 60_000))
                data = fh.read().decode("utf-8", errors="replace")
        except OSError:
            return ""
        return "\n".join(data.splitlines()[-lines:])
