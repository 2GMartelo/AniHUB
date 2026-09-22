import sys

import pytest

from anihub.app import set_taskbar_identity


@pytest.mark.skipif(sys.platform != "win32", reason="AppUserModelID is a Windows-only concept")
def test_set_taskbar_identity_uses_a_distinct_id_for_the_music_launcher(monkeypatch):
    calls = []
    monkeypatch.setattr("ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID", lambda aumid: calls.append(aumid))

    monkeypatch.setattr(sys, "argv", ["AniHUB.exe"])
    set_taskbar_identity()
    monkeypatch.setattr(sys, "argv", ["AniHUB.exe", "--music"])
    set_taskbar_identity()

    assert calls[0] != calls[1] and all(calls)


def test_set_taskbar_identity_never_raises_even_off_windows(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    set_taskbar_identity()  # must simply do nothing, not raise
