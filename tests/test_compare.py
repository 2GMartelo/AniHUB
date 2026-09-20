from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QImage, QPixmap

from anihub.ui import theme
from anihub.ui.compare import CompareCanvas, CompareDialog, fit_rect


def solid(color: str, w=100, h=80, path=None):
    image = QImage(w, h, QImage.Format.Format_RGB32)
    image.fill(QColor(color))
    if path:
        image.save(str(path))
    return QPixmap.fromImage(image)


def test_fit_rect_keeps_aspect_and_centres():
    r = fit_rect(QSize(200, 100), QRectF(0, 0, 100, 100))
    assert (r.width(), r.height()) == (100, 50) and r.y() == 25
    assert fit_rect(QSize(0, 0), QRectF(0, 0, 10, 10)).isNull()


def test_divider_reveals_before_on_the_left(qapp):
    theme.apply_theme(qapp, "dark")
    canvas = CompareCanvas(solid("#ff0000"), solid("#0000ff"))
    canvas.resize(500, 400)
    canvas.set_split(0.5)
    image = QImage(canvas.size(), QImage.Format.Format_ARGB32_Premultiplied)
    canvas.render(image)
    assert image.pixelColor(150, 200).red() > 200 and image.pixelColor(150, 200).blue() < 60      # before (red) on the left
    assert image.pixelColor(350, 200).blue() > 200 and image.pixelColor(350, 200).red() < 60      # after (blue) on the right
    canvas.set_split(1.7)
    assert canvas.split == 1.0
    canvas.swap()
    canvas.set_split(0.5)
    canvas.render(image)
    assert image.pixelColor(150, 200).blue() > 200


def test_side_by_side_shows_both(qapp):
    canvas = CompareCanvas(solid("#ff0000"), solid("#0000ff"))
    canvas.resize(600, 300)
    canvas.set_side_by_side(True)
    image = QImage(canvas.size(), QImage.Format.Format_ARGB32_Premultiplied)
    canvas.render(image)
    assert image.pixelColor(150, 150).red() > 200 and image.pixelColor(450, 150).blue() > 200


def test_dialog_describes_both_files_and_swaps(qapp, tmp_path):
    a, b = tmp_path / "a.png", tmp_path / "b.png"
    solid("#ff0000", 100, 80, a)
    solid("#00ff00", 200, 160, b)
    dlg = CompareDialog((a, "a.png"), (b, "b.png"))
    assert "100×80" in dlg.info.text() and "200×160" in dlg.info.text()
    assert dlg.info.text().index("a.png") < dlg.info.text().index("b.png")
    dlg._swap()
    assert dlg.info.text().index("b.png") < dlg.info.text().index("a.png")
    dlg.close()
