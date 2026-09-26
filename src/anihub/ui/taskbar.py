"""Windows taskbar identity: the icon of the taskbar button and the .ico file that goes with it.

The window's own icon (Qt's setWindowIcon) only shows in the title bar and the thumbnail popup. The taskbar *button* takes
its icon from the shortcut / executable of the process -- which for a run from source is pythonw.exe's generic one. The
"relaunch" properties of the window (the same ones a pinned shortcut is made from) override that with our own file."""
from __future__ import annotations

import ctypes
import struct
import sys
from ctypes import wintypes
from pathlib import Path

from PySide6.QtCore import QBuffer, QIODevice

ICON_SIZES = (16, 24, 32, 48, 64, 128, 256)


def write_ico(pixmaps: list, out: Path) -> None:
    """Write a multi-size .ico with PNG-compressed entries (what Windows Vista+ expects). Qt's own "ICO" writer stores
    only the one pixmap it is given, so the taskbar / Start menu / Explorer had no small size to pick and could show a
    blank icon instead of scaling the 256 px one."""
    blobs = []
    for pm in pixmaps:
        buf = QBuffer()
        buf.open(QIODevice.OpenModeFlag.WriteOnly)
        assert pm.save(buf, "PNG"), "could not encode an icon size"
        blobs.append((pm.width(), bytes(buf.data())))
    header = struct.pack("<HHH", 0, 1, len(blobs))
    offset = len(header) + 16 * len(blobs)
    entries, data = b"", b""
    for size, blob in blobs:
        entries += struct.pack("<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32, len(blob), offset + len(data))
        data += blob
    out.write_bytes(header + entries + data)


class _GUID(ctypes.Structure):
    _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD), ("Data3", wintypes.WORD),
                ("Data4", ctypes.c_ubyte * 8)]


class _PropertyKey(ctypes.Structure):
    _fields_ = [("fmtid", _GUID), ("pid", wintypes.DWORD)]


def _guid(text: str) -> _GUID:
    import uuid

    u = uuid.UUID(text)
    return _GUID(u.time_low, u.time_mid, u.time_hi_version, (ctypes.c_ubyte * 8)(*u.bytes[8:]))


_APPUSERMODEL = "9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3"      # System.AppUserModel.* property set
_IID_PROPERTY_STORE = "886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99"


def _string_variant(ole32, text: str):
    """A PROPVARIANT of type VT_LPWSTR (InitPropVariantFromString is an inline helper, not an exported function). The
    string lives in COM memory, so PropVariantClear frees it."""
    raw = text.encode("utf-16-le") + bytes(2)
    memory = ole32.CoTaskMemAlloc(len(raw))
    ctypes.memmove(memory, raw, len(raw))
    variant = ctypes.create_string_buffer(24)
    struct.pack_into("<H", variant, 0, 31)                                     # VT_LPWSTR
    struct.pack_into("<Q", variant, 8, memory)
    return variant


def set_relaunch_identity(hwnd: int, icon_file: Path, command: str, name: str) -> bool:
    """Give the window's taskbar button `icon_file`, and `command` / `name` as its relaunch entry (Windows ignores any
    of the three unless all are present). False when not on Windows or when the shell refused."""
    if sys.platform != "win32":
        return False
    try:
        shell32, ole32 = ctypes.windll.shell32, ctypes.windll.ole32
        ole32.CoTaskMemAlloc.restype = ctypes.c_void_p
        ole32.CoTaskMemAlloc.argtypes = [ctypes.c_size_t]
        store = ctypes.c_void_p()
        iid = _guid(_IID_PROPERTY_STORE)
        shell32.SHGetPropertyStoreForWindow.argtypes = [wintypes.HWND, ctypes.POINTER(_GUID), ctypes.POINTER(ctypes.c_void_p)]
        if shell32.SHGetPropertyStoreForWindow(hwnd, ctypes.byref(iid), ctypes.byref(store)) != 0 or not store.value:
            return False
        vtable = ctypes.cast(ctypes.cast(store, ctypes.POINTER(ctypes.c_void_p))[0], ctypes.POINTER(ctypes.c_void_p))
        set_value = ctypes.WINFUNCTYPE(ctypes.HRESULT, ctypes.c_void_p, ctypes.POINTER(_PropertyKey), ctypes.c_void_p)(vtable[6])
        commit = ctypes.WINFUNCTYPE(ctypes.HRESULT, ctypes.c_void_p)(vtable[7])
        release = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(vtable[2])
        try:
            for pid, value in ((2, command), (3, f"{icon_file},0"), (4, name)):     # RelaunchCommand / IconResource / DisplayName
                variant = _string_variant(ole32, value)
                key = _PropertyKey(_guid(_APPUSERMODEL), pid)
                set_value(store, ctypes.byref(key), variant)
                ole32.PropVariantClear(variant)
            commit(store)
        finally:
            release(store)
        return True
    except (OSError, AttributeError, ValueError):
        return False
