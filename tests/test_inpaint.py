import base64
from pathlib import Path

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QImage, QPixmap

from anihub.services.generation import GenParams
from anihub.ui import theme
from anihub.ui.mask_editor import MaskCanvas, MaskDialog


def picture(w=200, h=100) -> QPixmap:
    image = QImage(w, h, QImage.Format.Format_RGB32)
    image.fill(QColor("#336699"))
    return QPixmap.fromImage(image)


def test_payload_carries_the_mask_only_with_an_init_image(tmp_path):
    src, mask = tmp_path / "s.png", tmp_path / "m.png"
    src.write_bytes(b"IMG")
    mask.write_bytes(b"MASK")
    p = GenParams(prompt="x", init_image=str(src), mask_image=str(mask), mask_blur=8, inpaint_fill=2, inpaint_only_masked=False)
    payload = p.to_payload()
    assert base64.b64decode(payload["mask"]) == b"MASK" and payload["mask_blur"] == 8
    assert payload["inpainting_fill"] == 2 and payload["inpaint_full_res"] == 0 and payload["inpainting_mask_invert"] == 0
    assert "mask" not in GenParams(prompt="x", init_image=str(src)).to_payload()          # plain img2img
    assert "mask" not in GenParams(prompt="x", mask_image=str(mask)).to_payload()         # txt2img ignores a stray mask


def test_painting_produces_a_white_mask_at_picture_resolution(qapp):
    theme.apply_theme(qapp, "dark")
    canvas = MaskCanvas(picture())
    canvas.resize(420, 240)
    canvas.set_brush(20)
    assert canvas.is_empty()
    frame = canvas._frame()
    centre = QPointF(frame.center())
    canvas._stroke(canvas._to_image(centre), canvas._to_image(centre))
    gray = canvas.mask_gray()
    assert gray.size() == canvas.source.size() and gray.format() == QImage.Format.Format_Grayscale8
    assert gray.pixelColor(100, 50).red() == 255 and gray.pixelColor(5, 5).red() == 0
    assert not canvas.is_empty()


def test_erase_undo_clear_and_invert(qapp):
    canvas = MaskCanvas(picture())
    canvas.resize(420, 240)
    canvas.set_brush(40)
    from PySide6.QtCore import QPointF as P
    canvas._push_undo()
    canvas._stroke(P(100, 50), P(100, 50))
    assert canvas.mask_gray().pixelColor(100, 50).red() == 255
    canvas.erasing = True
    canvas._push_undo()
    canvas._stroke(P(100, 50), P(100, 50))
    canvas.erasing = False
    assert canvas.mask_gray().pixelColor(100, 50).red() == 0                   # eraser removed it
    canvas.undo()
    assert canvas.mask_gray().pixelColor(100, 50).red() == 255                 # ...and undo brought it back
    canvas.invert()
    assert canvas.mask_gray().pixelColor(100, 50).red() == 0 and canvas.mask_gray().pixelColor(5, 5).red() == 255
    canvas.clear()
    assert canvas.is_empty()


def test_dialog_reopens_an_existing_mask(qapp):
    first = MaskDialog(picture())
    first.canvas.resize(420, 240)
    first.canvas.set_brush(30)
    first.canvas._stroke(QPointF(50, 50), QPointF(60, 50))
    assert first.has_mask()
    saved = first.result_mask()
    second = MaskDialog(picture(), saved)
    assert second.has_mask()
    assert second.result_mask().pixelColor(55, 50).red() > 200 and second.result_mask().pixelColor(150, 90).red() < 20
    assert not MaskDialog(picture()).has_mask()
    first.close(); second.close()
