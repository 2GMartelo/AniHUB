"""A tiny shared helper for loop-driven batch services (library integrity check, backup, export, autotag-all) to
support pausing between items: each item's work is already fully committed (to disk/DB) by the time the loop moves
on to the next one, so "pause" here just means "don't start the next item yet" -- the background thread running the
loop blocks in place, polling both `paused` and `cancelled` so a paused-then-cancelled run can still stop instead
of blocking forever."""
from __future__ import annotations

import time
from typing import Callable


def wait_while_paused(paused: Callable[[], bool] | None, cancelled: Callable[[], bool] | None = None,
                      interval: float = 0.2) -> None:
    if paused is None:
        return
    while paused() and not (cancelled and cancelled()):
        time.sleep(interval)
