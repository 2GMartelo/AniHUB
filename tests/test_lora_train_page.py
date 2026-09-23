import time

from PySide6.QtGui import QColor, QImage

from anihub.context import AppContext
from anihub.core.config import Config
from anihub.services import lora as lo
from anihub.services import lora_train as lt
from anihub.services.autotag import TagResult
from anihub.ui.lora_train_page import ImageRow, LoraTrainPage


def pump(app, seconds=0.0, cond=None, limit=5.0):
    end = time.time() + (limit if cond else seconds)
    while time.time() < end:
        app.processEvents()
        if cond and cond():
            return True
        time.sleep(0.01)
    return True if cond is None else bool(cond())


def picture(tmp_path, name, color="#3366ff"):
    img = QImage(32, 32, QImage.Format.Format_RGB32)
    img.fill(QColor(color))
    path = tmp_path / name
    img.save(str(path))
    return path


def make_ctx(tmp_path, **cfg_values):
    cfg = Config.load(tmp_path / "c.json")
    cfg.set("library_path", str(tmp_path / "lib"), save=False)
    cfg.set("lora_train.enabled", True, save=False)
    for k, v in cfg_values.items():
        cfg.set(k, v, save=False)
    return AppContext.build(cfg)


# --- ImageRow: the per-picture caption editor --------------------------------------------------------------------

def test_image_row_tags_are_deduplicated_and_editable(tmp_path, qapp):
    path = picture(tmp_path, "a.png")
    row = ImageRow(path, ["blue hair", "blue hair", " smile "])
    assert row.tags == ["blue hair", "smile"]
    assert row.caption() == "blue hair, smile"

    row.add_line.setText("blue hair")     # already present: no duplicate
    row._add_tag()
    assert row.tags == ["blue hair", "smile"]

    row.add_line.setText("1girl")
    row._add_tag()
    assert row.tags == ["blue hair", "smile", "1girl"]

    row._remove_tag("smile")
    assert row.tags == ["blue hair", "1girl"]


def test_image_row_set_tags_replaces_and_dedupes(tmp_path, qapp):
    row = ImageRow(picture(tmp_path, "a.png"), [])
    seen = []
    row.changed.connect(lambda: seen.append(1))
    row.set_tags(["a", "a", "b", ""])
    assert row.tags == ["a", "b"] and seen


# --- the page: checkpoint discovery, add/remove images, start-time validation --------------------------------------

def test_checkpoint_discovery_follows_forge_path(tmp_path, qapp):
    forge = tmp_path / "forge"
    models = forge / "models" / "Stable-diffusion"
    models.mkdir(parents=True)
    (models / "illustrious.safetensors").write_bytes(b"")
    ctx = make_ctx(tmp_path, **{"forge.path": str(forge)})
    page = LoraTrainPage(ctx)
    assert page._checkpoint_paths == {"illustrious": models / "illustrious.safetensors"}
    assert page._checkpoint_path == models / "illustrious.safetensors"


def test_start_refuses_with_too_few_images(tmp_path, qapp):
    ctx = make_ctx(tmp_path)
    page = LoraTrainPage(ctx)
    page.name_edit.setText("X")
    page._start()
    assert page.trainer is None and tr_contains(page.status_label.text(), "2")


def test_start_refuses_without_a_name(tmp_path, qapp):
    ctx = make_ctx(tmp_path)
    page = LoraTrainPage(ctx)
    for i in range(2):
        row = ImageRow(picture(tmp_path, f"{i}.png"), ["x"])
        page.rows.append(row)
    page._start()
    assert page.trainer is None


def test_start_refuses_without_a_checkpoint(tmp_path, qapp):
    ctx = make_ctx(tmp_path)          # no forge.path -> no checkpoints found
    page = LoraTrainPage(ctx)
    for i in range(2):
        page.rows.append(ImageRow(picture(tmp_path, f"{i}.png"), ["x"]))
    page.name_edit.setText("MyLora")
    page._start()
    assert page.trainer is None and page._checkpoint_path is None


def test_start_refuses_without_a_lora_folder_configured(tmp_path, qapp):
    """A checkpoint can come from a browsed-to file even with no Forge configured and no lora.dir set -- but then
    there is nowhere to put the finished LoRA, so _start() must refuse before ever launching a training run."""
    ctx = make_ctx(tmp_path)          # neither forge.path nor lora.dir set
    page = LoraTrainPage(ctx)
    for i in range(2):
        page.rows.append(ImageRow(picture(tmp_path, f"{i}.png"), ["x"]))
    page.name_edit.setText("MyLora")
    page._checkpoint_path = tmp_path / "some_checkpoint.safetensors"    # as if picked via "Browse"
    page._start()
    assert page.trainer is None


def tr_contains(text: str, needle: str) -> bool:
    return needle in text


# --- finishing a (simulated) successful run: moving the file and writing the LoRA card -----------------------------

def test_finish_success_moves_the_file_and_writes_the_card(tmp_path, qapp):
    ctx = make_ctx(tmp_path, **{"lora.dir": str(tmp_path / "loras")})
    page = LoraTrainPage(ctx)
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    out_file = out_dir / f"{lt.sanitize_name('My LoRA')}.safetensors"
    out_file.write_bytes(b"weights")

    page._pending_cfg = lt.TrainConfig(name="My LoRA", trigger="mytrig", negative="bad hands")
    page._output_file = out_file
    page.weight.setValue(0.75)
    page._finish_success()

    dest = tmp_path / "loras" / "My LoRA.safetensors"
    assert page._trained_path == dest and dest.is_file() and not out_file.exists()
    card = lo.load(dest, tmp_path / "loras")
    assert card.keywords == "mytrig" and card.negative == "bad hands" and card.weight == 0.75


def test_finish_success_avoids_overwriting_an_existing_lora(tmp_path, qapp):
    ctx = make_ctx(tmp_path, **{"lora.dir": str(tmp_path / "loras")})
    page = LoraTrainPage(ctx)
    loras = tmp_path / "loras"
    loras.mkdir()
    (loras / "My LoRA.safetensors").write_bytes(b"already here")
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    out_file = out_dir / "My LoRA.safetensors"
    out_file.write_bytes(b"new weights")

    page._pending_cfg = lt.TrainConfig(name="My LoRA")
    page._output_file = out_file
    page._finish_success()
    assert page._trained_path == loras / "My LoRA (2).safetensors"
    assert (loras / "My LoRA.safetensors").read_bytes() == b"already here"


def test_finish_success_reports_a_missing_output_file(tmp_path, qapp):
    ctx = make_ctx(tmp_path)
    page = LoraTrainPage(ctx)
    page._pending_cfg = lt.TrainConfig(name="Ghost")
    page._output_file = tmp_path / "does-not-exist.safetensors"
    page._finish_success()
    assert page._trained_path is None


def test_finish_success_reports_a_write_failure_instead_of_raising(tmp_path, qapp):
    """The LoRA folder can't always be created or written to (permissions, a full disk, a path that turns out to be a
    file); _finish_success() runs from a QTimer callback with no caller to catch an exception, so it must handle this
    itself instead of crashing out of the timer."""
    lora_dir = tmp_path / "loras"
    lora_dir.write_bytes(b"")                     # a FILE sits where the LoRA folder should be -> mkdir() fails
    ctx = make_ctx(tmp_path, **{"lora.dir": str(lora_dir)})
    page = LoraTrainPage(ctx)
    out_file = tmp_path / "out" / "X.safetensors"
    out_file.parent.mkdir()
    out_file.write_bytes(b"weights")

    page._pending_cfg = lt.TrainConfig(name="X")
    page._output_file = out_file
    page._finish_success()                         # must not raise

    assert page._trained_path is None
    assert str(out_file) in page.status_label.text()   # tells the user where the raw file still is
    assert out_file.is_file()                           # the trained file was not lost


# --- quitting AniHUB while a training job is running ------------------------------------------------------------------

def test_quit_app_cancels_a_running_training_job(tmp_path, qapp, monkeypatch):
    """Forge and the manga service are both stopped on quit; a running "Train LoRA" job must be too, or sd-scripts is
    left running in the background holding the GPU after AniHUB itself has closed."""
    from PySide6.QtWidgets import QApplication

    from anihub.ui.main_window import MainWindow

    cfg = Config.load(tmp_path / "c.json")
    cfg.set("library_path", str(tmp_path / "lib"), save=False)
    cfg.set("forge.path", str(tmp_path / "forge"), save=False)
    cfg.set("lora_train.enabled", True, save=False)
    cfg.set("lora_train.sd_scripts_path", str(tmp_path / "sd-scripts"), save=False)
    win = MainWindow(AppContext.build(cfg))
    win.tray.isVisible = lambda: True

    trainer = lt.Trainer(tmp_path / "log.txt")
    trainer.state = "running"                            # no real subprocess: proc stays None, so cancel() just marks it
    win.lora_train_page.trainer = trainer

    monkeypatch.setattr(QApplication, "quit", lambda: None)
    win.quit_app()

    assert trainer.state == "cancelled"
    win.close()


# --- autotagging: one picture at a time, not a single big frozen batch ------------------------------------------------

def make_page_with_rows(tmp_path, qapp, count=3, tags=None):
    ctx = make_ctx(tmp_path)
    page = LoraTrainPage(ctx)
    for i in range(count):
        row = ImageRow(picture(tmp_path, f"{i}.png"), list(tags) if tags else [])
        page.rows.append(row)
        page.rows_layout.insertWidget(page.rows_layout.count() - 2, row)
    return page


def test_autotag_all_tags_pictures_one_at_a_time_not_in_one_batch(tmp_path, qapp, monkeypatch):
    page = make_page_with_rows(tmp_path, qapp, count=3)
    monkeypatch.setattr(type(page.ctx.autotagger), "available", True)

    seen_concurrently = []
    in_flight = []

    def fake_tag_file(path):
        in_flight.append(path)
        seen_concurrently.append(len(in_flight))          # how many calls were in flight at once
        time.sleep(0.02)
        in_flight.pop()
        return TagResult(tags=[("blue_hair", "general"), ("1girl", "general")], rating="general")

    monkeypatch.setattr(page.ctx.autotagger, "tag_file", fake_tag_file)

    page._autotag_all()
    assert page._autotagging and page.autotag_btn.text() == "Остановить"
    assert pump(qapp, cond=lambda: not page._autotagging)

    assert max(seen_concurrently) == 1                    # never two tag_file calls running at the same time
    assert all(row.tags == ["blue hair", "1girl"] for row in page.rows)
    assert page.autotag_btn.text() != "Остановить"
    assert not page._autotagging


def test_autotag_all_can_be_stopped_mid_run(tmp_path, qapp, monkeypatch):
    page = make_page_with_rows(tmp_path, qapp, count=6)
    monkeypatch.setattr(type(page.ctx.autotagger), "available", True)

    def slow_tag_file(path):
        time.sleep(0.05)
        return TagResult(tags=[("tag", "general")], rating="general")

    monkeypatch.setattr(page.ctx.autotagger, "tag_file", slow_tag_file)

    page._autotag_all()
    assert pump(qapp, seconds=0.06)          # let one or two finish
    page._autotag_all()                      # clicking the button again while running: stop
    assert page._autotag_cancelled
    assert pump(qapp, cond=lambda: not page._autotagging)

    tagged = sum(1 for row in page.rows if row.tags)
    assert 0 < tagged < 6                    # stopped partway, not everything got tagged


def test_autotag_all_does_nothing_without_the_model_downloaded(tmp_path, qapp, monkeypatch):
    page = make_page_with_rows(tmp_path, qapp, count=2)
    monkeypatch.setattr(type(page.ctx.autotagger), "available", False)
    page._autotag_all()
    assert not page._autotagging
    assert page.status_label.text()


def test_autotag_all_skips_rows_that_already_have_tags(tmp_path, qapp, monkeypatch):
    page = make_page_with_rows(tmp_path, qapp, count=2, tags=["already", "tagged"])
    monkeypatch.setattr(type(page.ctx.autotagger), "available", True)
    calls = []
    monkeypatch.setattr(page.ctx.autotagger, "tag_file", lambda path: calls.append(path))
    page._autotag_all()
    assert not page._autotagging and not calls    # nothing queued: every row already had tags


# --- Settings: ticking "enable LoRA training" shows the system requirements right away -----------------------------

def test_enabling_the_checkbox_shows_the_suitability_verdict_immediately(tmp_path, qapp):
    from anihub.ui.settings import SettingsPage

    ctx = make_ctx(tmp_path, **{"lora_train.enabled": False})   # make_ctx's own default is True: start unchecked
    page = SettingsPage(ctx)
    assert not page.train_enabled.isChecked() and page.train_status.text() == ""

    page.train_enabled.setChecked(True)
    assert pump(qapp, cond=lambda: page.train_status.text() != "")
    assert page.train_status.text()                # some verdict/report text is now showing, unprompted


def test_toggling_it_again_does_not_re_trigger_the_check(tmp_path, qapp, monkeypatch):
    from anihub.ui.settings import SettingsPage

    ctx = make_ctx(tmp_path, **{"lora_train.enabled": False})
    page = SettingsPage(ctx)
    page.train_status.setText("already checked once")
    calls = []
    monkeypatch.setattr(page, "_recheck_train", lambda: calls.append(1))
    page.train_enabled.setChecked(True)               # a real False -> True transition, but a verdict is already shown
    assert not calls
