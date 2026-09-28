"""One shared "VRAM slot" (ТЗ_rasshirenie_prilozheniya.md): across every heavy backend AniHUB drives -- Forge's own
generation queue, ComfyUI jobs, and anything a later stage adds -- at most one of them may hold it at a time, since
a 10-12 GB card cannot keep two of these models loaded together.

Not wired into anything yet. services/sd_queue.py's QueueController pumps Forge jobs today without going through
this at all, because Forge is the only heavy backend that exists so far. The first real ComfyUI job (Stage 3's
See-through layer split) is what wires this in: both sides acquire the slot before starting a job and release it
when done -- calling the loser's `free()` (Forge has no such call today; ComfyUI's is services.comfyui.ComfyApi.free)
so the next job's backend can actually reclaim the VRAM the previous one is still holding onto, not just get in
line for it."""
from __future__ import annotations

import threading


class GpuScheduler:
    """`owner` is any short backend name ("forge", "comfyui", "forge:second-gpu", ...). Acquiring with the name that
    already holds the slot succeeds immediately (a backend re-entering its own turn, e.g. queuing a second job right
    after its first, never blocks on itself)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._condition = threading.Condition(self._lock)
        self._holder: str | None = None

    @property
    def holder(self) -> str | None:
        with self._lock:
            return self._holder

    def try_acquire(self, owner: str) -> bool:
        """Non-blocking: True (and holds the slot) if it was free or already held by `owner`; False otherwise."""
        with self._lock:
            if self._holder in (None, owner):
                self._holder = owner
                return True
            return False

    def acquire(self, owner: str, timeout: float | None = None) -> bool:
        """Blocking -- call from a worker thread, never the GUI thread. Waits for the slot to be free (or already
        `owner`'s). Returns False only if `timeout` seconds elapsed first; True means the slot is now held."""
        with self._condition:
            ok = self._condition.wait_for(lambda: self._holder in (None, owner), timeout=timeout)
            if ok:
                self._holder = owner
            return ok

    def release(self, owner: str) -> None:
        """No-op if `owner` does not hold the slot (a job that never acquired it, or already released)."""
        with self._condition:
            if self._holder == owner:
                self._holder = None
                self._condition.notify_all()
