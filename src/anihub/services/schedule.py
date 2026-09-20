"""Scheduling of the generation queue (ТЗ 5.7): "run at night while the PC is idle"."""
from __future__ import annotations

import ctypes
import sys
from datetime import datetime, timedelta

DEFAULT_SCHEDULE = {
    "enabled": False, "time": "02:00", "repeat": "daily",  # repeat: daily | once
    "window_hours": 6,        # a missed slot is still run within this window (the app may start a bit late)
    "start_forge": True,      # start the backends that are not running
    "stop_forge_after": True,  # ...and stop exactly those afterwards (frees the VRAM)
    "idle_minutes": 0,        # 0 = do not require an idle PC
    "last_run": "",           # ISO date of the last run: at most one run per day
}


def parse_time(text: str) -> tuple[int, int]:
    try:
        hh, mm = (int(p) for p in text.split(":"))
        if 0 <= hh < 24 and 0 <= mm < 60:
            return hh, mm
    except ValueError:
        pass
    return 2, 0


def schedule_due(now: datetime, schedule: dict) -> bool:
    """True when the scheduled slot has come, has not been used today and is not older than the window."""
    s = {**DEFAULT_SCHEDULE, **(schedule or {})}
    if not s["enabled"] or s["last_run"] == now.date().isoformat():
        return False
    hh, mm = parse_time(s["time"])
    slot = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    return slot <= now <= slot + timedelta(hours=float(s["window_hours"]))


def next_run(now: datetime, schedule: dict) -> datetime | None:
    s = {**DEFAULT_SCHEDULE, **(schedule or {})}
    if not s["enabled"]:
        return None
    hh, mm = parse_time(s["time"])
    slot = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if s["last_run"] == now.date().isoformat() or slot + timedelta(hours=float(s["window_hours"])) < now:
        slot += timedelta(days=1)
    return slot


def system_idle_seconds() -> float:
    """Seconds since the last keyboard/mouse input (Windows); 0 when unknown."""
    if sys.platform != "win32":
        return 0.0

    class LASTINPUTINFO(ctypes.Structure):
        _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]

    info = LASTINPUTINFO()
    info.cbSize = ctypes.sizeof(info)
    if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
        return 0.0
    return max(0.0, (ctypes.windll.kernel32.GetTickCount() - info.dwTime) / 1000.0)
