import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from anihub.services import lora_train_install as ti


# --- picking the right PyTorch build -----------------------------------------------------------------------------------

def test_pick_torch_matches_the_newest_supported_cuda():
    assert ti.pick_torch(12.9) == "cu129"
    assert ti.pick_torch(12.4) == "cu124"
    assert ti.pick_torch(12.5) == "cu124"          # between tiers: the next one down
    assert ti.pick_torch(11.8) == "cu118"
    assert ti.pick_torch(10.0) == ti.DEFAULT_CUDA_TAG   # too old for anything listed
    assert ti.pick_torch(None) == ti.DEFAULT_CUDA_TAG


def test_driver_cuda_version_reads_nvidia_smis_header(monkeypatch):
    monkeypatch.setattr(ti.shutil, "which", lambda name: "nvidia-smi.exe" if name == "nvidia-smi" else None)
    monkeypatch.setattr(ti.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(
        a[0], 0, stdout="... Driver Version: 551.23   CUDA Version: 12.4 ...", stderr=""))
    assert ti.driver_cuda_version() == 12.4


def test_driver_cuda_version_reads_the_newer_umd_header_too(monkeypatch):
    """A real RTX 5070 (Blackwell) machine's nvidia-smi prints "CUDA UMD Version:", not "CUDA Version:" -- matching
    only the classic wording silently returned None, which made pick_torch() default to a build with no compiled
    kernels for that GPU's architecture at all (real crash: "no kernel image is available for execution on the
    device")."""
    monkeypatch.setattr(ti.shutil, "which", lambda name: "nvidia-smi.exe" if name == "nvidia-smi" else None)
    monkeypatch.setattr(ti.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(
        a[0], 0, stdout="NVIDIA-SMI 616.92   KMD Version: 616.92   CUDA UMD Version: 13.4", stderr=""))
    assert ti.driver_cuda_version() == 13.4
    assert ti.pick_torch(13.4) == "cu129"


def test_driver_cuda_version_none_without_nvidia_smi(monkeypatch):
    monkeypatch.setattr(ti.shutil, "which", lambda name: None)
    assert ti.driver_cuda_version() is None


# --- finding a usable system Python --------------------------------------------------------------------------------------

def test_find_system_python_accepts_a_supported_version(monkeypatch):
    monkeypatch.setattr(ti.shutil, "which", lambda name: None if name == "py" else (f"/usr/bin/{name}" if name == "python3.11" else None))

    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 0, stdout="Python 3.11.9\n", stderr="")

    monkeypatch.setattr(ti.subprocess, "run", fake_run)
    assert ti.find_system_python() == ["/usr/bin/python3.11"]


def test_find_system_python_rejects_too_old_or_too_new(monkeypatch):
    monkeypatch.setattr(ti.shutil, "which", lambda name: f"/usr/bin/{name}" if name == "python" else None)

    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 0, stdout="Python 3.9.0\n", stderr="")

    monkeypatch.setattr(ti.subprocess, "run", fake_run)
    assert ti.find_system_python() is None


def test_find_system_python_none_when_nothing_on_path(monkeypatch):
    monkeypatch.setattr(ti.shutil, "which", lambda name: None)
    assert ti.find_system_python() is None


# --- extracting the source archive -----------------------------------------------------------------------------------------

def make_repo_zip(tmp_path: Path, branch_folder="sd-scripts-main") -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    archive = tmp_path / "src.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr(f"{branch_folder}/train_network.py", "# training script")
        zf.writestr(f"{branch_folder}/requirements.txt", "accelerate\n")
        zf.writestr(f"{branch_folder}/sub/nested.py", "# nested file")
    return archive


def test_extract_flattens_the_single_top_level_folder(tmp_path):
    archive = make_repo_zip(tmp_path)
    dest = tmp_path / "dest"
    dest.mkdir()
    ti._extract(archive, dest)
    assert (dest / "train_network.py").is_file()
    assert (dest / "requirements.txt").is_file()
    assert (dest / "sub" / "nested.py").is_file()
    assert not (dest / "sd-scripts-main").exists()


def test_extract_raises_without_a_recognisable_root_folder(tmp_path):
    archive = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("random/file.txt", "x")
    dest = tmp_path / "dest"
    dest.mkdir()
    with pytest.raises(ti.InstallError):
        ti._extract(archive, dest)


# --- running one subprocess step: log, exit code, cancellation ------------------------------------------------------------

def test_run_step_writes_the_log_and_succeeds(tmp_path):
    log = tmp_path / "install.log"
    script = tmp_path / "ok.py"
    script.write_text("print('hello from step')")
    ti._run_step([sys.executable, str(script)], tmp_path, log, None)
    assert "hello from step" in log.read_text(encoding="utf-8", errors="replace")


def test_run_step_raises_on_nonzero_exit(tmp_path):
    log = tmp_path / "install.log"
    script = tmp_path / "bad.py"
    script.write_text("import sys\nsys.exit(2)")
    with pytest.raises(ti.InstallError):
        ti._run_step([sys.executable, str(script)], tmp_path, log, None)


def test_run_step_can_be_cancelled_mid_run(tmp_path):
    log = tmp_path / "install.log"
    script = tmp_path / "loop.py"
    script.write_text("import time\nwhile True:\n time.sleep(0.05)\n")
    with pytest.raises(ti.InstallError):
        ti._run_step([sys.executable, str(script)], tmp_path, log, lambda: True)


@pytest.mark.skipif(sys.platform != "win32", reason="process suspend is Windows-only")
def test_run_step_pauses_a_running_subprocess_and_resumes_it(tmp_path):
    import threading
    import time

    log = tmp_path / "install.log"
    counter = tmp_path / "n.txt"
    script = tmp_path / "counting.py"
    script.write_text(
        "import time\nn = 0\nwhile True:\n n += 1\n open(r'%s', 'w').write(str(n))\n time.sleep(0.02)\n" % counter)

    state = {"paused": False, "cancel": False}
    errors = []

    def run():
        try:
            ti._run_step([sys.executable, str(script)], tmp_path, log, lambda: state["cancel"], lambda: state["paused"])
        except ti.InstallError:
            pass
        except Exception as exc:  # noqa: BLE001 - surfaced via `errors`, not raised on a background thread
            errors.append(exc)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    end = time.time() + 5
    while not counter.exists() and time.time() < end:
        time.sleep(0.02)

    state["paused"] = True
    time.sleep(0.5)                                        # a few rescans: catches a respawned worker too
    frozen_at = int(counter.read_text() or 0)
    time.sleep(0.4)
    assert int(counter.read_text() or 0) == frozen_at

    state["paused"] = False
    end = time.time() + 5
    while int(counter.read_text() or 0) <= frozen_at and time.time() < end:
        time.sleep(0.02)
    assert int(counter.read_text() or 0) > frozen_at

    state["cancel"] = True
    thread.join(timeout=5)
    assert not errors


# --- the full install(), with a fake HttpClient and fake commands ------------------------------------------------------

class FakeHttp:
    def __init__(self, archive_src: Path):
        self.archive_src = archive_src

    def download(self, url, dest, progress=None, cancelled=None, paused=None):
        dest.write_bytes(self.archive_src.read_bytes())
        if progress:
            progress(dest.stat().st_size, dest.stat().st_size)


def test_install_runs_every_stage_in_order(tmp_path, monkeypatch):
    archive_src = make_repo_zip(tmp_path / "src_holder")
    http = FakeHttp(archive_src)
    dest = tmp_path / "sd-scripts"

    monkeypatch.setattr(ti, "find_system_python", lambda: [sys.executable])
    monkeypatch.setattr(ti, "driver_cuda_version", lambda: None)
    monkeypatch.setattr(ti.shutil, "disk_usage", lambda p: type("D", (), {"free": 999 * 1024**3})())

    calls: list[list[str]] = []

    def fake_run_step(cmd, cwd, log_path, cancelled, paused=None):
        calls.append(cmd)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("ab") as f:
            f.write((" ".join(cmd) + "\n").encode())

    monkeypatch.setattr(ti, "_run_step", fake_run_step)

    stages: list[str] = []
    result = ti.install(http, dest, progress=lambda s, d, t: stages.append(s))

    assert result == dest
    ordered = ["preflight", "download", "extract", "venv", "pip", "torch", "requirements", "accelerate", "done"]
    assert [s for s in ordered if s in stages] == ordered      # each stage seen, in the right order
    assert (dest / "train_network.py").is_file()
    assert len(calls) == 5          # venv, pip upgrade, torch, requirements, accelerate


def test_install_reports_not_enough_disk_space(tmp_path, monkeypatch):
    http = FakeHttp(make_repo_zip(tmp_path / "src_holder"))
    monkeypatch.setattr(ti.shutil, "disk_usage", lambda p: type("D", (), {"free": 1 * 1024**3})())
    with pytest.raises(ti.InstallError):
        ti.install(http, tmp_path / "sd-scripts")


def test_install_reports_no_python_found(tmp_path, monkeypatch):
    http = FakeHttp(make_repo_zip(tmp_path / "src_holder"))
    monkeypatch.setattr(ti.shutil, "disk_usage", lambda p: type("D", (), {"free": 999 * 1024**3})())
    monkeypatch.setattr(ti, "find_system_python", lambda: None)
    with pytest.raises(ti.InstallError):
        ti.install(http, tmp_path / "sd-scripts")


def test_install_can_be_cancelled_before_any_subprocess_runs(tmp_path, monkeypatch):
    http = FakeHttp(make_repo_zip(tmp_path / "src_holder"))
    monkeypatch.setattr(ti, "find_system_python", lambda: [sys.executable])
    monkeypatch.setattr(ti.shutil, "disk_usage", lambda p: type("D", (), {"free": 999 * 1024**3})())
    with pytest.raises(ti.InstallError):
        ti.install(http, tmp_path / "sd-scripts", cancelled=lambda: True)


class PausableFakeHttp:
    """Mimics HttpClient.download's own contract: a paused call writes nothing and just returns."""

    def __init__(self, archive_src: Path):
        self.archive_src = archive_src
        self.calls = 0

    def download(self, url, dest, progress=None, cancelled=None, paused=None):
        self.calls += 1
        if paused and paused():
            return
        dest.write_bytes(self.archive_src.read_bytes())
        if progress:
            progress(dest.stat().st_size, dest.stat().st_size)


def test_install_blocks_while_paused_during_the_download_then_continues(tmp_path, monkeypatch):
    import threading
    import time

    http = PausableFakeHttp(make_repo_zip(tmp_path / "src_holder"))
    dest = tmp_path / "sd-scripts"
    monkeypatch.setattr(ti, "find_system_python", lambda: [sys.executable])
    monkeypatch.setattr(ti, "driver_cuda_version", lambda: None)
    monkeypatch.setattr(ti.shutil, "disk_usage", lambda p: type("D", (), {"free": 999 * 1024**3})())
    monkeypatch.setattr(ti, "_run_step", lambda cmd, cwd, log_path, cancelled, paused=None: None)

    state = {"paused": True}
    result_box: dict = {}

    def run():
        result_box["result"] = ti.install(http, dest, paused=lambda: state["paused"])

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    time.sleep(0.3)
    assert "result" not in result_box          # install() is still blocked, waiting for the pause to lift
    assert http.calls >= 1                     # it did try the download and was told to stand down

    state["paused"] = False
    thread.join(timeout=5)
    assert result_box.get("result") == dest    # picked back up and finished once unpaused
