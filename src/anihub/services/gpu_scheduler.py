"""One shared VRAM slot *per GPU* (ТЗ_rasshirenie_prilozheniya.md): on a given GPU, at most one heavy backend --
Forge's own generation queue, a ComfyUI job, or anything a later stage adds -- may hold it at a time, since a 10-12
GB card cannot keep two of these models loaded together. A machine with several physical GPUs gets one independent
slot per GPU index, so backends pinned to different cards never block each other (sd_queue.py's own multi-GPU
support already assumes exactly this).

Wired into sd_queue.py's QueueController (every Forge job acquires its backend's GPU slot before it runs, and the
whole queue releases every slot it might be holding -- unloading each backend's checkpoint in the process -- once it
goes fully idle) and into services/seethrough.py's `run()` (acquires its GPU slot for the one ComfyUI job it submits,
releases it when done -- see that module for why holding it any longer would buy nothing). Both sides share the same
GpuScheduler instance via AppContext.gpu_scheduler, so a Forge job and a ComfyUI job aimed at the same physical GPU
never run at once.

Known gap: sd_queue.py only releases a Forge backend's slot once its *whole* queue goes idle (keeping a checkpoint
loaded across consecutive queued jobs is the entire point of a queue), not after each individual job. That is safe
against ComfyUI (a ComfyUI job just waits for Forge's queue to fully drain -- Forge's own progress never depends on
ComfyUI finishing anything, so it always eventually releases) but would deadlock two *Forge* backends deliberately
pinned to the same physical GPU, each waiting for the other's queue to drain before its own can start. Multi-GPU
Forge backends (services/backends.py) are meant to be pinned to *different* GPUs; nothing currently stops someone
from configuring two on the same one, but doing so already meant they'd race for the same VRAM before this module
existed. Fixing that properly needs per-GPU "queue idle" tracking, not just whole-controller-set idle -- left for
when it is actually needed."""
from __future__ import annotations

import threading


class GpuScheduler:
    """`gpu` is a GPU index (0, 1, ...). `owner` is any label identifying who's asking (e.g. "forge:main",
    "comfyui") -- acquiring with the label that already holds that GPU's slot succeeds immediately (a backend
    re-entering its own turn, e.g. queuing a second job right after its first, never blocks on itself)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._condition = threading.Condition(self._lock)
        self._holders: dict[int, str] = {}

    def holder(self, gpu: int = 0) -> str | None:
        with self._lock:
            return self._holders.get(gpu)

    def try_acquire(self, gpu: int, owner: str) -> bool:
        """Non-blocking: True (and holds the slot) if it was free or already held by `owner`; False otherwise."""
        with self._lock:
            current = self._holders.get(gpu)
            if current in (None, owner):
                self._holders[gpu] = owner
                return True
            return False

    def acquire(self, gpu: int, owner: str, timeout: float | None = None) -> bool:
        """Blocking -- call from a worker thread, never the GUI thread. Waits for `gpu`'s slot to be free (or
        already `owner`'s). Returns False only if `timeout` seconds elapsed first; True means the slot is now held."""
        with self._condition:
            ok = self._condition.wait_for(lambda: self._holders.get(gpu) in (None, owner), timeout=timeout)
            if ok:
                self._holders[gpu] = owner
            return ok

    def release(self, gpu: int, owner: str) -> None:
        """No-op if `owner` does not hold `gpu`'s slot (never acquired it, or already released)."""
        with self._condition:
            if self._holders.get(gpu) == owner:
                del self._holders[gpu]
                self._condition.notify_all()
