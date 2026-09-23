"""Pausing a whole external process TREE on Windows: NtSuspendProcess/NtResumeProcess (undocumented but stable
since NT4 -- what Process Explorer and Task Manager's own "Suspend" use) freezes every thread of one process at
once, which is what a paused LoRA training run or a paused pip install actually needs. There is no public,
portable API for this on Windows (unlike POSIX's SIGSTOP); `psutil` would add a whole new dependency just for a
few calls, so this goes straight to ctypes instead.

Suspending only the PID `subprocess.Popen` hands back is not enough, for two reasons observed against this
project's own machine: (1) a modern CPython Windows venv's own `python.exe` is a small launcher stub that
re-execs the real interpreter as a *child* process, so the actual work keeps running right through a "successful"
suspend of just the parent; and (2) once that real worker is suspended, something in this environment (most likely
the Store-distributed Python's own launcher machinery) has been observed to quietly relaunch it under a *new* PID
a moment later, so even a correct one-time suspend of the whole tree does not reliably stay suspended. `Suspend`
below works around both: it keeps re-scanning the process's descendants for as long as it is active and suspends
anything new it finds, so a respawned worker gets caught within one scan interval instead of running free.

HANDLE is pointer-sized: without explicit argtypes/restype, ctypes treats OpenProcess's return as a plain 32-bit
int and truncates it on 64-bit Windows, so calls would silently "succeed" against a garbage handle instead of the
real process. Everything below is typed explicitly to avoid exactly that."""
from __future__ import annotations

import ctypes
import threading

PROCESS_SUSPEND_RESUME = 0x0800
TH32CS_SNAPPROCESS = 0x00000002
RESCAN_INTERVAL = 0.2


class _ProcessEntry32(ctypes.Structure):
    _fields_ = [
        ("dwSize", ctypes.c_uint32), ("cntUsage", ctypes.c_uint32), ("th32ProcessID", ctypes.c_uint32),
        ("th32DefaultHeapID", ctypes.c_void_p), ("th32ModuleID", ctypes.c_uint32), ("cntThreads", ctypes.c_uint32),
        ("th32ParentProcessID", ctypes.c_uint32), ("pcPriClassBase", ctypes.c_long), ("dwFlags", ctypes.c_uint32),
        ("szExeFile", ctypes.c_char * 260),
    ]


def _kernel32():
    k = ctypes.windll.kernel32
    k.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
    k.OpenProcess.restype = ctypes.c_void_p
    k.CloseHandle.argtypes = [ctypes.c_void_p]
    k.CloseHandle.restype = ctypes.c_int
    k.CreateToolhelp32Snapshot.argtypes = [ctypes.c_uint32, ctypes.c_uint32]
    k.CreateToolhelp32Snapshot.restype = ctypes.c_void_p
    k.Process32First.argtypes = [ctypes.c_void_p, ctypes.POINTER(_ProcessEntry32)]
    k.Process32Next.argtypes = [ctypes.c_void_p, ctypes.POINTER(_ProcessEntry32)]
    return k


def process_tree(root_pid: int) -> list[int]:
    """`root_pid` and every process descended from it (children, grandchildren, ...), in no particular order."""
    kernel32 = _kernel32()
    snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snap in (0, -1, None):
        return [root_pid]
    parent_of: dict[int, int] = {}
    try:
        entry = _ProcessEntry32()
        entry.dwSize = ctypes.sizeof(_ProcessEntry32)
        if kernel32.Process32First(snap, ctypes.byref(entry)):
            while True:
                parent_of[entry.th32ProcessID] = entry.th32ParentProcessID
                if not kernel32.Process32Next(snap, ctypes.byref(entry)):
                    break
    finally:
        kernel32.CloseHandle(snap)
    tree = {root_pid}
    changed = True
    while changed:  # repeat until nothing new is added: catches grandchildren regardless of snapshot ordering
        changed = False
        for pid, parent in parent_of.items():
            if parent in tree and pid not in tree:
                tree.add(pid)
                changed = True
    return list(tree)


def _one(kernel32, pid: int, fn_name: str) -> bool:
    ntdll = ctypes.windll.ntdll
    ntdll.NtSuspendProcess.argtypes = ntdll.NtResumeProcess.argtypes = [ctypes.c_void_p]
    ntdll.NtSuspendProcess.restype = ntdll.NtResumeProcess.restype = ctypes.c_int32
    handle = kernel32.OpenProcess(PROCESS_SUSPEND_RESUME, False, pid)
    if not handle:
        return False
    try:
        return getattr(ntdll, fn_name)(handle) == 0
    finally:
        kernel32.CloseHandle(handle)


class Suspend:
    """Keeps `root_pid`'s whole process tree paused for as long as this object is running: a background thread
    re-scans for descendants every `interval` seconds and suspends any it has not already suspended, so a process
    that gets relaunched under a new PID while paused (observed on this project's own machine) is caught on the
    next scan instead of running free indefinitely. `stop()` resumes everything this instance actually suspended
    and returns whether all of them came back cleanly."""

    def __init__(self, root_pid: int, interval: float = RESCAN_INTERVAL):
        self._root_pid = root_pid
        self._interval = interval
        self._kernel32 = _kernel32()
        self._suspended: set[int] = set()
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._scan_once()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _scan_once(self) -> None:
        for pid in process_tree(self._root_pid):
            with self._lock:
                already = pid in self._suspended
            if not already and _one(self._kernel32, pid, "NtSuspendProcess"):
                with self._lock:
                    self._suspended.add(pid)

    def _run(self) -> None:
        while not self._stop_event.wait(self._interval):
            self._scan_once()

    @property
    def active(self) -> bool:
        with self._lock:
            return bool(self._suspended)

    def stop(self) -> bool:
        self._stop_event.set()
        self._thread.join(timeout=2)
        with self._lock:
            pids = list(self._suspended)
            self._suspended.clear()
        return all(_one(self._kernel32, pid, "NtResumeProcess") for pid in pids)
