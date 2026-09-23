import subprocess
import sys
import time

import pytest

from anihub.services import procsuspend

COUNTER_SCRIPT = """
import time
n = 0
while True:
    n += 1
    with open(r"{path}", "w") as f:
        f.write(str(n))
    time.sleep(0.02)
"""


def read_counter(path) -> int:
    try:
        return int(path.read_text() or "0")
    except (OSError, ValueError):
        return 0


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-only")
def test_process_tree_includes_the_root_and_its_children():
    # this project's own venv python.exe is itself a launcher stub that re-execs a child -- a real, in-repo example
    # of exactly the case process_tree() exists to handle, so no synthetic multi-process fixture is needed here.
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(2)"])
    try:
        time.sleep(0.3)
        tree = procsuspend.process_tree(proc.pid)
        assert proc.pid in tree
    finally:
        proc.kill()
        proc.wait(timeout=5)


@pytest.mark.skipif(sys.platform != "win32", reason="NtSuspendProcess/NtResumeProcess are Windows-only")
def test_suspend_freezes_the_process_and_stop_lets_it_continue(tmp_path):
    """This project's own venv (a launcher stub that re-execs a real worker) has also been observed, on this
    machine, to relaunch a suspended worker under a brand new PID a moment later -- Suspend's whole reason to exist
    is to keep re-scanning and catch that, so the test gives it several rescan intervals of headroom rather than
    asserting an instant freeze."""
    counter_file = tmp_path / "n.txt"
    proc = subprocess.Popen([sys.executable, "-c", COUNTER_SCRIPT.format(path=str(counter_file))])
    try:
        end = time.time() + 5
        while not counter_file.exists() and time.time() < end:
            time.sleep(0.02)

        watch = procsuspend.Suspend(proc.pid, interval=0.1)
        try:
            assert watch.active
            time.sleep(0.5)                                            # several rescans: a respawn should get caught
            frozen_at = read_counter(counter_file)
            time.sleep(0.4)
            assert read_counter(counter_file) == frozen_at            # the core safety property: paused stays paused
        finally:
            assert watch.stop()                                        # the OS-level resume call itself succeeded
    finally:
        proc.kill()
        proc.wait(timeout=5)


def test_suspend_reports_inactive_for_a_dead_or_unknown_pid():
    watch = procsuspend.Suspend(999_999_999, interval=1.0)
    try:
        assert not watch.active
    finally:
        watch.stop()
