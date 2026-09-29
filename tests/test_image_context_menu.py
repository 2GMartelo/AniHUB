"""ui/image_context_menu.py (Copy image / Save as / Copy path / Open folder) and its wiring into Viewer and the
manga reader (PagedCanvas/WebtoonView)."""
from pathlib import Path

from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QFileDialog, QWidget

from anihub.ui.image_context_menu import build_image_menu, show_image_menu


def make_image(color: str = "red") -> QImage:
    img = QImage(8, 8, QImage.Format.Format_RGBA8888)
    img.fill(QColor(color))
    return img


def make_file(tmp_path: Path, name: str = "a.png") -> Path:
    path = tmp_path / name
    assert make_image().save(str(path), "PNG")
    return path


def test_no_menu_when_neither_image_nor_file(qapp):
    assert build_image_menu(QWidget(), image=None, path=None) is None


def test_image_only_offers_copy_and_save_as(qapp):
    menu = build_image_menu(QWidget(), image=make_image())
    labels = [a.text() for a in menu.actions()]
    assert labels == ["Копировать изображение", "Сохранить как…"]


def test_file_only_offers_save_copy_path_and_open_folder(qapp, tmp_path):
    path = make_file(tmp_path)
    menu = build_image_menu(QWidget(), path=path)
    labels = [a.text() for a in menu.actions()]
    assert labels == ["Сохранить как…", "Копировать путь к файлу", "Показать в папке"]


def test_both_image_and_file_prefers_the_file_copy_for_save_as(qapp, tmp_path):
    path = make_file(tmp_path)
    menu = build_image_menu(QWidget(), image=make_image(), path=path)
    labels = [a.text() for a in menu.actions()]
    assert labels == ["Копировать изображение", "Сохранить как…", "Копировать путь к файлу", "Показать в папке"]


def test_a_missing_path_is_treated_as_no_file(qapp, tmp_path):
    menu = build_image_menu(QWidget(), image=make_image(), path=tmp_path / "does_not_exist.png")
    assert [a.text() for a in menu.actions()] == ["Копировать изображение", "Сохранить как…"]  # the image-only Save As branch


def test_copy_image_action_puts_the_picture_on_the_clipboard(qapp):
    from PySide6.QtGui import QGuiApplication

    menu = build_image_menu(QWidget(), image=make_image("blue"))
    menu.actions()[0].trigger()
    clip = QGuiApplication.clipboard().image()
    assert not clip.isNull() and clip.pixelColor(0, 0) == QColor("blue")


def test_copy_path_action_puts_the_path_on_the_clipboard(qapp, tmp_path):
    from PySide6.QtGui import QGuiApplication

    path = make_file(tmp_path)
    menu = build_image_menu(QWidget(), path=path)
    copy_path = next(a for a in menu.actions() if a.text() == "Копировать путь к файлу")
    copy_path.trigger()
    assert QGuiApplication.clipboard().text() == str(path)


def test_save_as_for_a_real_file_copies_the_exact_bytes(qapp, tmp_path, monkeypatch):
    src = make_file(tmp_path, "src.png")
    dest = tmp_path / "out.png"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(dest), "")))
    menu = build_image_menu(QWidget(), path=src)
    next(a for a in menu.actions() if a.text() == "Сохранить как…").trigger()
    assert dest.read_bytes() == src.read_bytes()


def test_save_as_for_an_in_memory_image_writes_a_png(qapp, tmp_path, monkeypatch):
    dest = tmp_path / "out.png"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(dest), "")))
    menu = build_image_menu(QWidget(), image=make_image("green"))
    next(a for a in menu.actions() if a.text() == "Сохранить как…").trigger()
    assert dest.exists()
    assert QImage(str(dest)).pixelColor(0, 0) == QColor("green")


def test_save_as_does_nothing_when_the_dialog_is_cancelled(qapp, tmp_path, monkeypatch):
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: ("", "")))
    menu = build_image_menu(QWidget(), image=make_image())
    next(a for a in menu.actions() if a.text() == "Сохранить как…").trigger()  # must not raise


def test_show_image_menu_execs_only_when_there_is_something_to_show(qapp, monkeypatch):
    """QMenu.exec() blocks for a real click, so the class itself can't be monkeypatched (PySide6 does not let a
    plain attribute assignment override a C++-bound method's dispatch -- confirmed by hand: it just hangs). A
    subclass overriding exec() as an ordinary Python method works correctly, so image_context_menu's own QMenu
    name is swapped for one instead."""
    from anihub.ui import image_context_menu
    from PySide6.QtCore import QPoint
    from PySide6.QtWidgets import QMenu

    calls = []

    class NoExecMenu(QMenu):
        def exec(self, pos):
            calls.append(pos)

    monkeypatch.setattr(image_context_menu, "QMenu", NoExecMenu)
    pos = QPoint(1, 2)
    show_image_menu(QWidget(), pos, image=None, path=None)
    assert calls == []
    show_image_menu(QWidget(), pos, image=make_image())
    assert calls == [pos]


# --- Viewer wiring -----------------------------------------------------------------------------------------------

def test_viewer_tracks_the_current_path_and_builds_the_right_menu(qapp, tmp_path, monkeypatch):
    from anihub.ui import viewer as viewer_module
    from anihub.ui.viewer import ViewItem, Viewer

    path = make_file(tmp_path)
    item = ViewItem("a", "", lambda: path)
    win = Viewer([item], 0)
    for _ in range(200):
        qapp.processEvents()
        if win._current_path is not None:
            break
    assert win._current_path == path

    seen = {}
    monkeypatch.setattr(viewer_module, "show_image_menu", lambda parent, pos, **kw: seen.update(kw))
    win.image.customContextMenuRequested.emit(win.image.pos())  # goes through the real signal, so self.sender() works
    assert seen["path"] == path
    assert seen["image"] is not None and not seen["image"].isNull()
    win.close()


# --- manga reader wiring -----------------------------------------------------------------------------------------

def test_paged_canvas_right_click_never_flips_the_page():
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtCore import QEvent, Qt as QtNS

    from anihub.ui.manga_reader import PagedCanvas

    canvas = PagedCanvas()
    canvas.resize(400, 300)
    flips = []
    canvas.clicked_side.connect(flips.append)
    press = QMouseEvent(QEvent.Type.MouseButtonPress, QPointF(50, 50), QtNS.MouseButton.RightButton,
                        QtNS.MouseButton.RightButton, QtNS.KeyboardModifier.NoModifier)
    release = QMouseEvent(QEvent.Type.MouseButtonRelease, QPointF(50, 50), QtNS.MouseButton.RightButton,
                          QtNS.MouseButton.NoButton, QtNS.KeyboardModifier.NoModifier)
    canvas.mousePressEvent(press)
    canvas.mouseReleaseEvent(release)
    assert flips == []


def test_paged_canvas_context_menu_emits_the_click_position():
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QContextMenuEvent

    from anihub.ui.manga_reader import PagedCanvas

    canvas = PagedCanvas()
    canvas.resize(400, 300)
    seen = []
    canvas.menu_requested.connect(seen.append)
    event = QContextMenuEvent(QContextMenuEvent.Reason.Mouse, QPoint(120, 80))
    canvas.contextMenuEvent(event)
    assert seen == [QPoint(120, 80)]


def test_webtoon_view_emits_page_index_and_a_global_position(qapp):
    from PySide6.QtCore import QPoint

    from anihub.ui.manga_reader import WebtoonView

    web = WebtoonView()
    web.set_pages(3)
    seen = []
    web.page_menu_requested.connect(lambda i, pos: seen.append((i, pos)))
    web.labels[1].customContextMenuRequested.emit(QPoint(5, 5))
    assert len(seen) == 1 and seen[0][0] == 1
    assert isinstance(seen[0][1], QPoint)
