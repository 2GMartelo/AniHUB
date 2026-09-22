import sys
import time
from pathlib import Path

import pytest
from PySide6.QtGui import QColor, QImage

from anihub.services import lora_train as lt


def picture(tmp_path, name, color="#3366ff") -> Path:
    img = QImage(32, 32, QImage.Format.Format_RGB32)
    img.fill(QColor(color))
    path = tmp_path / name
    img.save(str(path))
    return path


# --- sd-scripts detection -----------------------------------------------------------------------------------------------------

def test_list_checkpoints_reads_the_forge_stable_diffusion_folder(tmp_path):
    class FakeCfg:
        def __init__(self, forge_path):
            self.forge_path = forge_path

        def get(self, key, default=None):
            return self.forge_path if key == "forge.path" else default

    assert lt.list_checkpoints(FakeCfg("")) == []
    forge = tmp_path / "forge"
    models = forge / "models" / "Stable-diffusion"
    models.mkdir(parents=True)
    (models / "b.safetensors").write_bytes(b"")
    (models / "a.ckpt").write_bytes(b"")
    (models / "notes.txt").write_bytes(b"")
    assert lt.list_checkpoints(FakeCfg(str(forge))) == [models / "a.ckpt", models / "b.safetensors"]
    assert lt.list_checkpoints(FakeCfg(str(tmp_path / "missing"))) == []


def test_find_script_and_python_and_check_install(tmp_path, monkeypatch):
    root = tmp_path / "sd-scripts"
    root.mkdir()
    assert lt.check_install(tmp_path / "missing") == "err.train.no_folder"
    assert lt.check_install(root) == "err.train.no_script"
    (root / lt.SD15_SCRIPT).write_text("x")
    assert lt.find_script(root, sdxl=False) == root / lt.SD15_SCRIPT and lt.find_script(root, sdxl=True) is None
    assert lt.check_install(root) == "err.train.no_venv"
    venv_py = root / "venv" / "Scripts" / "python.exe"
    venv_py.parent.mkdir(parents=True)
    venv_py.write_bytes(b"")
    assert lt.find_python(root) == venv_py

    monkeypatch.setattr(lt, "torch_importable", lambda p: False)
    assert lt.check_install(root) == "err.train.no_torch"
    monkeypatch.setattr(lt, "torch_importable", lambda p: True)
    assert lt.check_install(root) is None


def test_torch_importable_is_false_for_a_real_python_without_torch():
    """AniHUB's own interpreter is a real, working Python -- just one without torch installed, which is exactly the
    "venv exists but the install of it failed partway" case this exists to catch."""
    assert lt.torch_importable(Path(sys.executable)) is False


def test_torch_importable_is_false_for_a_nonexistent_or_bogus_executable(tmp_path):
    assert lt.torch_importable(tmp_path / "does-not-exist.exe") is False
    bogus = tmp_path / "not_really_an_exe.exe"
    bogus.write_bytes(b"not a real executable")
    assert lt.torch_importable(bogus) is False


# --- captions and the dataset folder --------------------------------------------------------------------------------------------

def test_caption_text_puts_the_trigger_first_without_a_dangling_comma():
    assert lt.caption_text("mikustyle", "masterpiece, blue hair") == "mikustyle, masterpiece, blue hair"
    assert lt.caption_text("", "blue hair") == "blue hair"
    assert lt.caption_text("mikustyle", "") == "mikustyle"
    assert lt.caption_text("", "") == ""


def test_build_dataset_writes_numbered_images_and_captions(tmp_path):
    images = [(picture(tmp_path, "a.png"), "mikustyle, blue hair"), (picture(tmp_path, "b.png", "#ff0000"), "mikustyle, red dress")]
    dest = tmp_path / "job"
    train_dir = lt.build_dataset(images, dest, "My LoRA!", repeats=8)
    folder = train_dir / "8_My LoRA!"
    assert folder.is_dir()
    files = sorted(p.name for p in folder.iterdir())
    assert files == ["0001.png", "0001.txt", "0002.png", "0002.txt"]
    assert (folder / "0001.txt").read_text(encoding="utf-8") == "mikustyle, blue hair"
    assert (folder / "0002.txt").read_text(encoding="utf-8") == "mikustyle, red dress"
    assert QImage(str(folder / "0001.png")).width() == 32


def test_build_dataset_replaces_old_contents_on_a_second_run(tmp_path):
    images = [(picture(tmp_path, "a.png"), "one")]
    dest = tmp_path / "job"
    lt.build_dataset(images, dest, "x", repeats=5)
    folder = dest / "img" / "5_x"
    (folder / "leftover.txt").write_text("stale")
    lt.build_dataset(images, dest, "x", repeats=5)
    assert not (folder / "leftover.txt").exists() and (folder / "0001.png").exists()


def test_build_dataset_sanitises_bad_filename_characters(tmp_path):
    images = [(picture(tmp_path, "a.png"), "c")]
    train_dir = lt.build_dataset(images, tmp_path, 'na<>me:"/\\|?*', repeats=1)
    assert (train_dir / "1_na__me_______").is_dir()


# --- the command line ----------------------------------------------------------------------------------------------------------

def test_build_command_has_the_right_flags_and_output_name():
    cfg = lt.TrainConfig(name="My Miku!", base_model="D:/ckpt.safetensors", sdxl=True, network_dim=16, network_alpha=8,
                         epochs=5, batch_size=1, resolution=896)
    cmd = lt.build_command(Path("D:/py/python.exe"), Path("D:/sd/sdxl_train_network.py"), cfg, Path("D:/data/img"), Path("D:/out"))
    assert cmd[:2] == ["D:\\py\\python.exe", "D:\\sd\\sdxl_train_network.py"]
    assert "--output_name" in cmd and cmd[cmd.index("--output_name") + 1] == "My Miku!"
    assert cmd[cmd.index("--network_dim") + 1] == "16" and cmd[cmd.index("--resolution") + 1] == "896,896"
    assert cmd[cmd.index("--pretrained_model_name_or_path") + 1] == "D:/ckpt.safetensors"
    assert "--save_last_n_epochs" in cmd and "--save_every_n_epochs" not in cmd
    assert "--sdpa" in cmd and "--xformers" not in cmd    # needs no extra install, unlike xformers (a real user hit this)


def test_build_command_uses_save_every_n_epochs_when_set():
    cfg = lt.TrainConfig(name="x", base_model="m", save_every_n_epochs=2)
    cmd = lt.build_command(Path("py"), Path("script"), cfg, Path("data"), Path("out"))
    assert cmd[cmd.index("--save_every_n_epochs") + 1] == "2" and "--save_last_n_epochs" not in cmd


# --- progress parsing -----------------------------------------------------------------------------------------------------------

def test_parse_progress_reads_the_last_tqdm_line_and_the_epoch():
    log = ("epoch 2/10\n"
          "steps:   0%|          | 0/280 [00:00<?, ?it/s]\n"
          "steps:  12%|#3        | 34/280 [00:45<05:12,  1.27s/it, avr_loss=0.112]\n"
          "steps:  50%|#####     | 140/280 [01:50<02:30,  1.10it/s, avr_loss=0.098]\n")
    p = lt.parse_progress(log)
    assert p["frac"] == 0.5 and p["step"] == 140 and p["total_steps"] == 280 and p["epoch"] == 2 and p["total_epochs"] == 10
    assert "avr_loss=0.098" in p["rate"]
    assert lt.parse_progress("nothing useful here") == {}


# --- the subprocess wrapper -------------------------------------------------------------------------------------------------------

def wait_state(trainer, target, limit=3):
    end = time.time() + limit
    while time.time() < end and trainer.state != target:
        time.sleep(0.01)
    return trainer.state


def test_trainer_runs_and_reports_success(tmp_path):
    trainer = lt.Trainer(tmp_path / "log.txt")
    script = tmp_path / "fake.py"
    script.write_text("import sys, time\nfor i in range(3):\n print(f'steps: {(i+1)*33}%|#|{i+1}/3 [00:0{i}<00:01, 1.0it/s]')\n")
    trainer.start([sys.executable, str(script)], cwd=tmp_path)
    assert wait_state(trainer, "done") == "done"
    assert "steps: 99%" in trainer.log_tail()
    prog = trainer.progress()
    assert prog["step"] == 3 and prog["total_steps"] == 3


def test_trainer_survives_non_ascii_output_from_the_child(tmp_path):
    """sd-scripts logs bilingual EN/JA lines (e.g. "running training / 学習開始"); on a non-UTF-8 system locale
    (a real report: cp1251 on a Russian Windows machine) printing one used to crash the child process outright with
    UnicodeEncodeError the moment it hit a Japanese character -- Trainer.start() must force UTF-8 I/O regardless."""
    trainer = lt.Trainer(tmp_path / "log.txt")
    script = tmp_path / "fake.py"
    script.write_text("print('running training / 学習開始')\n", encoding="utf-8")
    trainer.start([sys.executable, str(script)], cwd=tmp_path)
    assert wait_state(trainer, "done") == "done", trainer.log_tail()
    assert "学習開始" in trainer.log_tail()


def test_trainer_reports_failure_and_keeps_the_log(tmp_path):
    trainer = lt.Trainer(tmp_path / "log.txt")
    script = tmp_path / "bad.py"
    script.write_text("import sys\nprint('about to fail')\nsys.exit(3)\n")
    trainer.start([sys.executable, str(script)], cwd=tmp_path)
    assert wait_state(trainer, "failed") == "failed"
    assert "exit code 3" in trainer.error
    assert "about to fail" in trainer.log_tail()


def test_trainer_start_failure_is_reported_without_raising(tmp_path):
    trainer = lt.Trainer(tmp_path / "log.txt")
    trainer.start([str(tmp_path / "does-not-exist.exe")], cwd=tmp_path)
    assert trainer.state == "failed" and trainer.error


def test_trainer_cancel_kills_a_running_process(tmp_path):
    trainer = lt.Trainer(tmp_path / "log.txt")
    script = tmp_path / "loop.py"
    script.write_text("import time\nwhile True:\n time.sleep(0.05)\n")
    trainer.start([sys.executable, str(script)], cwd=tmp_path)
    time.sleep(0.3)
    assert trainer.state == "running"
    trainer.cancel()
    assert trainer.state == "cancelled"
    time.sleep(0.5)
    assert trainer.proc.poll() is not None                                                                  # really stopped, not just marked
