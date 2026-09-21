import time

from PySide6.QtCore import QRectF, QSizeF
from PySide6.QtWidgets import QMainWindow, QPushButton, QWidget

from anihub.ui.tutorial import Step, TutorialOverlay, place_card


def pump(app, seconds=0.0, cond=None, limit=3.0):
    end = time.time() + (limit if cond else seconds)
    while time.time() < end:
        app.processEvents()
        if cond and cond():
            return True
        time.sleep(0.01)
    return True if cond is None else bool(cond())


def test_card_placement_prefers_below_then_right_above_left_and_stays_inside():
    bounds, size = QRectF(0, 0, 1000, 700), QSizeF(300, 150)
    hole = QRectF(400, 100, 200, 50)
    below = place_card(size, hole, bounds)
    assert below.y() >= hole.bottom() and abs(below.x() + 150 - hole.center().x()) < 1                 # centred under it
    at_bottom = place_card(size, QRectF(400, 620, 200, 50), bounds)
    assert at_bottom.y() + 150 <= 620                                                                     # no room below: above
    rail = place_card(size, QRectF(0, 100, 84, 76), bounds)
    assert rail.x() >= 84 and rail.y() >= 100 - 150                                                       # a rail button: to the right or below
    huge = place_card(size, QRectF(0, 0, 1000, 700), bounds)
    assert bounds.adjusted(14, 14, -14, -14).contains(QRectF(huge, size))                                 # nothing fits: pushed inside
    assert place_card(size, QRectF(), bounds).x() == 350 and place_card(size, QRectF(), bounds).y() == 275   # no target: centred


def settled(overlay, index):
    return overlay.shown_index == index and overlay._anim.state() != overlay._anim.State.Running


def make_window(qapp):
    win = QMainWindow()
    win.resize(900, 600)
    central = QWidget()
    win.setCentralWidget(central)
    buttons = []
    for i in range(3):
        b = QPushButton(f"B{i}", central)
        b.setGeometry(50 + i * 200, 80 + i * 100, 120, 40)
        buttons.append(b)
    win.show()
    pump(qapp, 0.05)
    return win, buttons


def test_tour_walks_the_steps_moves_the_light_and_reports_completion(qapp):
    win, (b0, b1, b2) = make_window(qapp)
    switched = []
    steps = [Step("welcome", None, lambda: switched.append("w")), Step("nav_arts", lambda: b0, lambda: switched.append(0)),
             Step("tabs", lambda: b1), Step("source", lambda: b2)]
    overlay = TutorialOverlay(win, steps)
    results = []
    overlay.finished.connect(results.append)
    overlay.start()
    assert overlay.isVisible() and overlay.geometry() == win.rect()
    assert pump(qapp, cond=lambda: settled(overlay, 0))
    assert overlay._hole.isEmpty() and not overlay.back_btn.isVisible() and "1" in overlay.counter.text()
    overlay.next()
    assert pump(qapp, cond=lambda: settled(overlay, 1))
    rect = b0.geometry()
    assert abs(overlay._hole.center().x() - rect.center().x()) <= 1 and abs(overlay._hole.center().y() - rect.center().y()) <= 1
    assert overlay._hole.width() > rect.width()                                                          # a little bigger than the control
    first_card = overlay.card.pos()
    overlay.next()
    assert pump(qapp, cond=lambda: settled(overlay, 2))
    assert overlay.card.pos() != first_card and overlay.back_btn.isVisible()                             # the card slid along
    overlay.back()
    assert pump(qapp, cond=lambda: settled(overlay, 1))
    overlay.next(); overlay.next()
    assert pump(qapp, cond=lambda: settled(overlay, 3))
    assert overlay.next_btn.text() in ("Готово", "Done")
    overlay.next()
    assert results == [True] and switched == ["w", 0, 0]              # step 1 was prepared twice: Back returned to it
    win.close()


def test_skipping_and_missing_targets(qapp):
    win, (b0, b1, b2) = make_window(qapp)
    b1.hide()                                                                                             # this control is not there
    overlay = TutorialOverlay(win, [Step("welcome", None), Step("nav_arts", lambda: b1), Step("tabs", lambda: b2)])
    results = []
    overlay.finished.connect(results.append)
    overlay.start()
    assert pump(qapp, cond=lambda: settled(overlay, 0))
    overlay.next()
    assert pump(qapp, cond=lambda: settled(overlay, 2), limit=3.0)                                        # the hidden one was skipped
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QKeyEvent
    from PySide6.QtCore import QEvent
    overlay.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier))
    assert results == [False]                                                                            # Esc = skipped
    win.close()


def test_the_wizard_asks_for_the_tour_and_the_main_window_marks_it_done(qapp, tmp_path):
    from anihub.context import AppContext
    from anihub.core.config import Config
    from anihub.ui.main_window import MainWindow
    from anihub.ui.wizard import SetupWizard

    cfg = Config.load(tmp_path / "c.json")
    cfg.set("library_path", str(tmp_path / "lib"), save=False)
    wizard = SetupWizard(cfg)
    wizard.accept()
    assert cfg.get("first_run_done") and cfg.get("tutorial.pending") is True
    ctx = AppContext.build(cfg)
    win = MainWindow(ctx)
    win.resize(1400, 850)
    win.show()
    steps = win.tutorial_steps()
    assert len(steps) >= 12 and steps[0].target is None and steps[-1].target is None
    win.start_tutorial()
    overlay = win._tutorial
    for _ in range(len(steps)):
        assert pump(qapp, 0.15)
        overlay.next()
    pump(qapp, 0.1)
    assert win._tutorial is None and cfg.get("tutorial.pending") is False
    win._quitting = True
    win.close()
