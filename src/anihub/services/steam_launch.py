"""Launching a Steam install/run from AniHUB, for the apps that only distribute through Steam (VTube Studio).
`steam://` is a URI scheme Steam's own installer registers with Windows; os.startfile() hands it to whatever is
registered the same way it would open a .txt file in Notepad -- if Steam itself is not installed, Windows has
nothing registered for the scheme and os.startfile() raises FileNotFoundError, which the caller falls back on
(usually by opening the app's store page in a browser instead)."""
from __future__ import annotations

import os


def steam_installed() -> bool:
    """Best-effort: the common install locations, not a registry lookup (good enough to decide whether to try
    steam:// before falling back to a browser link)."""
    for base in (r"C:\Program Files (x86)\Steam", r"C:\Program Files\Steam"):
        if os.path.isdir(base):
            return True
    return False


def open_steam_install(app_id: int) -> None:
    """Opens Steam's own "install this app" flow. Raises OSError (FileNotFoundError on Windows) if nothing is
    registered for steam:// -- the caller should catch that and offer the store page instead."""
    os.startfile(f"steam://install/{app_id}")  # noqa: S606 - a fixed, hard-coded scheme + a caller-given int, no user text
