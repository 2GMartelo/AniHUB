from anihub.context import AppContext
from anihub.core.config import Config


def make_window(qapp, tmp_path, **cfg_values):
    from anihub.ui.main_window import MainWindow

    cfg = Config.load(tmp_path / "c.json")
    cfg.set("library_path", str(tmp_path / "lib"), save=False)
    cfg.set("first_run_done", True, save=False)
    cfg.set("forge.path", str(tmp_path / "forge"), save=False)
    for k, v in cfg_values.items():
        cfg.set(k, v, save=False)
    ctx = AppContext.build(cfg)
    win = MainWindow(ctx)
    win.resize(1400, 850)
    return win, ctx


# --- ServiceController's own pause/resume --------------------------------------------------------------------------

def test_pause_polling_stops_the_timer_unless_busy(qapp, tmp_path):
    win, ctx = make_window(qapp, tmp_path)
    controller = win.forge
    controller.resume_polling()                       # starts paused (arts is the initial tab, not sd): activate it first
    assert controller.poll_timer.isActive()

    controller.set_busy(True)
    controller.pause_polling()
    assert controller.poll_timer.isActive()          # an active job: must not go quiet mid-generation

    controller.set_busy(False)
    controller.pause_polling()
    assert not controller.poll_timer.isActive()

    controller.resume_polling()
    assert controller.poll_timer.isActive()
    win._quitting = True
    win.close()


# --- MainWindow wiring: sections start inactive, resume when visited, pause a while after leaving -------------------

def test_sd_and_manga_start_paused_since_arts_is_the_initial_tab(qapp, tmp_path):
    win, ctx = make_window(qapp, tmp_path)
    assert not win.forge.poll_timer.isActive()
    assert not win.manga_ctrl.service.poll_timer.isActive()
    win._quitting = True
    win.close()


def test_visiting_a_section_resumes_its_polling_immediately(qapp, tmp_path):
    win, ctx = make_window(qapp, tmp_path)
    win.go("sd")
    assert win.forge.poll_timer.isActive()
    win.go("manga")
    assert win.manga_ctrl.service.poll_timer.isActive()
    win._quitting = True
    win.close()


def test_leaving_a_section_schedules_a_pause_instead_of_pausing_immediately(qapp, tmp_path):
    """The 30-minute-away grace period: leaving must not pause on the spot, or switching tabs back and forth would
    constantly stop and restart polling."""
    win, ctx = make_window(qapp, tmp_path)
    win.go("sd")
    assert win.forge.poll_timer.isActive()
    win.go("manga")
    assert win.forge.poll_timer.isActive()            # still running: only a pause timer was scheduled
    assert "sd" in win._away_timers and win._away_timers["sd"].isActive()
    win._quitting = True
    win.close()


def test_coming_back_before_the_grace_period_cancels_the_pending_pause(qapp, tmp_path):
    win, ctx = make_window(qapp, tmp_path)
    win.go("sd")
    win.go("manga")
    assert "sd" in win._away_timers
    win.go("sd")
    assert "sd" not in win._away_timers
    assert win.forge.poll_timer.isActive()
    win._quitting = True
    win.close()


def test_the_pause_actually_firing_stops_polling_unless_the_section_is_busy(qapp, tmp_path):
    """Simulates the 30-minute timer firing (waiting for the real interval isn't practical in a test) by calling the
    same handler it would call."""
    win, ctx = make_window(qapp, tmp_path)
    win.go("sd")
    win.go("manga")
    win._pause_section("sd")                          # as if the away-timer had just fired
    assert not win.forge.poll_timer.isActive()

    win.go("sd")                                       # visiting again resumes it
    assert win.forge.poll_timer.isActive()
    win.go("manga")
    win.forge.set_busy(True)                            # an active generation now
    win._pause_section("sd")
    assert win.forge.poll_timer.isActive()               # must not be paused mid-job
    win._quitting = True
    win.close()
