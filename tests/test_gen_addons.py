from pathlib import Path

from PySide6.QtGui import QColor, QImage

from anihub.context import AppContext
from anihub.core.config import Config
from anihub.services.generation import GenParams
from anihub.ui.gen_addons import GenAddonsPanel


def make_ctx(tmp_path):
    cfg = Config.load(tmp_path / "c.json")
    cfg.set("library_path", str(tmp_path / "lib"), save=False)
    cfg.set("forge.path", str(tmp_path / "forge"), save=False)
    return AppContext.build(cfg)


def picture(tmp_path, name="pose.png") -> Path:
    img = QImage(16, 16, QImage.Format.Format_RGB32)
    img.fill(QColor("#3366ff"))
    path = tmp_path / name
    img.save(str(path))
    return path


class FakeApi:
    def __init__(self, adetailer=False, couple=False, animate=False, model=("openpose_full", "control_v11p [abc]")):
        self._scripts = ([] + (["ADetailer"] if adetailer else []) + (["Forge Couple"] if couple else [])
                        + (["AnimateDiff"] if animate else []))
        self._model = model

    def scripts(self):
        return {"txt2img": self._scripts, "img2img": self._scripts}

    def controlnet_model_for(self, control_type):
        return self._model


def wait(qapp, cond, timeout=5):
    import time
    end = time.time() + timeout
    while time.time() < end:
        qapp.processEvents()
        if cond():
            return True
        time.sleep(0.01)
    return False


def test_initial_state_hides_addons_until_a_refresh_happens(qapp, tmp_path):
    panel = GenAddonsPanel(make_ctx(tmp_path))
    assert panel.adetailer_check.isHidden() and panel.adetailer_install_btn.isHidden()
    assert not panel.openpose_check.isEnabled()
    assert panel.couple_check.isHidden()


def test_refresh_shows_installed_addons_and_install_buttons_for_missing_ones(qapp, tmp_path):
    panel = GenAddonsPanel(make_ctx(tmp_path))
    panel.refresh(FakeApi(adetailer=True, couple=False))
    assert wait(qapp, lambda: not panel.adetailer_check.isHidden())
    assert panel.adetailer_install_btn.isHidden()
    assert panel.couple_check.isHidden() and not panel.couple_install_btn.isHidden()
    assert panel.openpose_check.isEnabled()                                 # a model was found
    assert panel.openpose_no_model_hint.isHidden()


def test_refresh_disables_openpose_when_no_model_is_installed(qapp, tmp_path):
    panel = GenAddonsPanel(make_ctx(tmp_path))
    panel.refresh(FakeApi(model=("", "")))
    assert wait(qapp, lambda: not panel.openpose_no_model_hint.isHidden())
    assert not panel.openpose_check.isEnabled()


def test_refresh_populates_the_motion_model_list_once_installed(qapp, tmp_path):
    model_dir = tmp_path / "forge" / "extensions" / "animatediff" / "model"
    model_dir.mkdir(parents=True)
    (model_dir / "mm_sd_v15_v2.ckpt").write_bytes(b"x")
    panel = GenAddonsPanel(make_ctx(tmp_path))
    panel.refresh(FakeApi(animate=True))
    assert wait(qapp, lambda: not panel.animate_check.isHidden())
    assert panel.animate_install_btn.isHidden()
    assert panel.animate_model.count() == 1 and panel.animate_model.itemText(0) == "mm_sd_v15_v2.ckpt"
    assert panel.animate_check.isEnabled() and panel.animate_no_model_hint.isHidden()


def test_refresh_shows_a_hint_when_animatediff_is_installed_but_has_no_model(qapp, tmp_path):
    panel = GenAddonsPanel(make_ctx(tmp_path))
    panel.refresh(FakeApi(animate=True))
    assert wait(qapp, lambda: not panel.animate_check.isHidden())
    assert not panel.animate_check.isEnabled()
    assert not panel.animate_no_model_hint.isHidden()


def test_animatediff_install_button_reveals_controls_and_rescans_for_models(qapp, tmp_path, monkeypatch):
    model_dir = tmp_path / "forge" / "extensions" / "animatediff" / "model"

    class FakeDialog:
        def __init__(self, ctx, forge_dir, key, parent=None):
            self.installed = Path(forge_dir) / "extensions" / key

        def exec(self):
            model_dir.mkdir(parents=True)                              # simulate the install actually landing
            (model_dir / "mm_sd_v15_v2.ckpt").write_bytes(b"x")

    monkeypatch.setattr("anihub.ui.addon_install_dialog.AddonInstallDialog", FakeDialog)
    panel = GenAddonsPanel(make_ctx(tmp_path))
    panel.refresh(FakeApi())                                           # not installed yet
    assert wait(qapp, lambda: not panel.animate_install_btn.isHidden())

    panel.animate_install_btn.click()
    assert not panel.animate_check.isHidden() and panel.animate_install_btn.isHidden()
    assert wait(qapp, lambda: panel.animate_model.count() == 1)        # refreshed itself after the install


def test_choosing_and_clearing_a_pose_reference_image(qapp, tmp_path):
    panel = GenAddonsPanel(make_ctx(tmp_path))
    panel._set_openpose_image(picture(tmp_path))
    assert panel.openpose_check.isChecked() and panel.openpose_clear_btn.isEnabled()
    panel._clear_openpose()
    assert not panel.openpose_check.isChecked() and not panel.openpose_clear_btn.isEnabled()


def test_params_kwargs_reflects_the_current_ui_state(qapp, tmp_path):
    model_dir = tmp_path / "forge" / "extensions" / "animatediff" / "model"
    model_dir.mkdir(parents=True)
    (model_dir / "mm_sd_v15_v2.ckpt").write_bytes(b"x")
    panel = GenAddonsPanel(make_ctx(tmp_path))
    panel.refresh(FakeApi(adetailer=True, couple=True, animate=True))
    assert wait(qapp, lambda: not panel.adetailer_check.isHidden())

    kwargs = panel.params_kwargs()
    assert kwargs["adetailer"] is False and kwargs["openpose_image"] == "" and kwargs["couple_enabled"] is False
    assert kwargs["animate"] is False

    panel.adetailer_check.setChecked(True)
    panel._set_openpose_image(picture(tmp_path))
    panel.openpose_weight.setValue(0.6)
    panel.couple_check.setChecked(True)
    panel.couple_direction.setCurrentIndex(panel.couple_direction.findData("Vertical"))
    panel.animate_check.setChecked(True)
    panel.animate_frames.setValue(12)
    panel.animate_fps.setValue(24)
    kwargs = panel.params_kwargs()
    assert kwargs["adetailer"] is True
    assert kwargs["openpose_image"] and kwargs["openpose_weight"] == 0.6
    assert kwargs["openpose_module"] == "openpose_full" and kwargs["openpose_model"] == "control_v11p [abc]"
    assert kwargs["couple_enabled"] is True and kwargs["couple_direction"] == "Vertical"
    assert kwargs["animate"] is True and kwargs["animate_model"] == "mm_sd_v15_v2.ckpt"
    assert kwargs["animate_frames"] == 12 and kwargs["animate_fps"] == 24


def test_apply_round_trips_a_genparams_back_into_the_ui(qapp, tmp_path):
    model_dir = tmp_path / "forge" / "extensions" / "animatediff" / "model"
    model_dir.mkdir(parents=True)
    (model_dir / "mm_sd_v15_v2.ckpt").write_bytes(b"x")
    panel = GenAddonsPanel(make_ctx(tmp_path))
    panel.refresh(FakeApi(animate=True))
    assert wait(qapp, lambda: panel.animate_model.count() == 1)

    img = picture(tmp_path)
    p = GenParams(prompt="a\nb", adetailer=True, openpose_image=str(img), openpose_weight=0.4,
                 couple_enabled=True, couple_direction="Vertical", animate=True, animate_model="mm_sd_v15_v2.ckpt",
                 animate_frames=12, animate_fps=24)
    panel.apply(p)
    assert panel.adetailer_check.isChecked()
    assert panel._openpose_path == img and panel.openpose_weight.value() == 0.4
    assert panel.couple_check.isChecked() and panel.couple_direction.currentData() == "Vertical"
    assert panel.animate_check.isChecked() and panel.animate_model.currentText() == "mm_sd_v15_v2.ckpt"
    assert panel.animate_frames.value() == 12 and panel.animate_fps.value() == 24


def test_install_button_shows_the_dialog_and_reveals_the_checkbox_on_success(qapp, tmp_path, monkeypatch):
    import anihub.ui.gen_addons as ga

    calls = []

    class FakeDialog:
        def __init__(self, ctx, forge_dir, key, parent=None):
            calls.append(key)
            self.installed = Path(forge_dir) / "extensions" / key

        def exec(self):
            calls.append("exec")

    monkeypatch.setattr("anihub.ui.addon_install_dialog.AddonInstallDialog", FakeDialog)
    panel = GenAddonsPanel(make_ctx(tmp_path))
    panel.adetailer_install_btn.show()
    panel.adetailer_install_btn.click()
    assert calls == ["adetailer", "exec"]
    assert not panel.adetailer_check.isHidden() and panel.adetailer_install_btn.isHidden()


def test_wildcards_button_opens_the_manager_dialog(qapp, tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr("anihub.ui.wildcards_dialog.WildcardsDialog",
                        lambda ctx, parent=None: type("D", (), {"exec": lambda self: calls.append("exec")})())
    panel = GenAddonsPanel(make_ctx(tmp_path))
    panel.wildcards_btn.click()
    assert calls == ["exec"]
