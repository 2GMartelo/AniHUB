import struct
import time
import zlib
from pathlib import Path
from types import SimpleNamespace

from PySide6.QtGui import QDesktopServices, QGuiApplication

from anihub.core.config import Config
from anihub.services import lora as lo
from anihub.services.lora import Lora
from anihub.ui.civitai_publish_dialog import UPLOAD_URL, CivitPublishDialog


def pump(app, seconds=0.0, cond=None, limit=5.0):
    end = time.time() + (limit if cond else seconds)
    while time.time() < end:
        app.processEvents()
        if cond and cond():
            return True
        time.sleep(0.01)
    return True if cond is None else bool(cond())


def chunk(kind: bytes, body: bytes) -> bytes:
    return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))


def make_png(extra_chunks: list[bytes]) -> bytes:
    ihdr = chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
    idat = chunk(b"IDAT", zlib.compress(b"\x00\xff\x00\x00"))
    return b"\x89PNG\r\n\x1a\n" + ihdr + b"".join(extra_chunks) + idat + chunk(b"IEND", b"")


INFO = "1girl\nSteps: 10, Sampler: Euler a, CFG scale: 6.0, Seed: 7, Size: 512x512, Model hash: bdb59bac77, Model: waiIllustriousSDXL_v140"


def picture_with_hash(tmp_path, name="a.png") -> Path:
    path = tmp_path / name
    path.write_bytes(make_png([chunk(b"tEXt", b"parameters\0" + INFO.encode())]))
    return path


def picture_without_hash(tmp_path, name="b.png") -> Path:
    path = tmp_path / name
    path.write_bytes(make_png([]))
    return path


class HashHttp:
    def __init__(self, response=None, error=None):
        self.response, self.error = response, error

    def get_json(self, url, params=None, headers=None, **kw):
        if self.error:
            raise self.error
        return self.response


def make_ctx(tmp_path, http=None):
    return SimpleNamespace(cfg=Config({}, tmp_path / "c.json"), http=http or HashHttp())


def make_lora(tmp_path) -> Lora:
    path = tmp_path / "miku.safetensors"
    path.write_bytes(b"x")
    return Lora(path, tmp_path, keywords="hatsune miku", base="SDXL", weight=0.9, negative="bad hands")


def test_dialog_starts_with_the_default_description_and_no_rows(qapp, tmp_path):
    dlg = CivitPublishDialog(make_ctx(tmp_path), make_lora(tmp_path))
    assert dlg.description.toPlainText() == lo.default_description(make_lora(tmp_path))
    assert dlg.rows == [] and not dlg.open_folder_btn.isEnabled()
    dlg.close()


def test_add_pictures_creates_a_row_and_resolves_the_model_async(qapp, tmp_path, monkeypatch):
    response = {"id": 128713, "modelId": 257749, "name": "v1.0", "model": {"name": "hassakuXLIllustrious"}}
    ctx = make_ctx(tmp_path, http=HashHttp(response))
    dlg = CivitPublishDialog(ctx, make_lora(tmp_path))
    art = picture_with_hash(tmp_path)
    monkeypatch.setattr("anihub.ui.civitai_publish_dialog.QFileDialog.getOpenFileNames", lambda *a, **k: ([str(art)], ""))
    dlg._add_pictures()
    assert len(dlg.rows) == 1 and dlg.open_folder_btn.isEnabled()
    row = dlg.rows[0]
    assert pump(qapp, cond=lambda: "hassakuXLIllustrious" in row.model_label.text())
    assert "257749" in row.model_label.text()
    dlg.close()


def test_add_pictures_skips_a_picture_already_added(qapp, tmp_path, monkeypatch):
    dlg = CivitPublishDialog(make_ctx(tmp_path), make_lora(tmp_path))
    art = picture_without_hash(tmp_path)
    monkeypatch.setattr("anihub.ui.civitai_publish_dialog.QFileDialog.getOpenFileNames", lambda *a, **k: ([str(art)], ""))
    dlg._add_pictures()
    dlg._add_pictures()
    assert len(dlg.rows) == 1
    dlg.close()


def test_a_picture_without_metadata_shows_model_unknown(qapp, tmp_path, monkeypatch):
    dlg = CivitPublishDialog(make_ctx(tmp_path), make_lora(tmp_path))
    art = picture_without_hash(tmp_path)
    monkeypatch.setattr("anihub.ui.civitai_publish_dialog.QFileDialog.getOpenFileNames", lambda *a, **k: ([str(art)], ""))
    dlg._add_pictures()
    from anihub.core.i18n import tr

    assert dlg.rows[0].model_label.text() == tr("civpub.model_unknown")
    dlg.close()


def test_a_hash_lookup_failure_leaves_the_row_as_unknown(qapp, tmp_path, monkeypatch):
    from anihub.net.http import HttpError

    ctx = make_ctx(tmp_path, http=HashHttp(error=HttpError(404)))
    dlg = CivitPublishDialog(ctx, make_lora(tmp_path))
    art = picture_with_hash(tmp_path)
    monkeypatch.setattr("anihub.ui.civitai_publish_dialog.QFileDialog.getOpenFileNames", lambda *a, **k: ([str(art)], ""))
    dlg._add_pictures()
    from anihub.core.i18n import tr

    assert pump(qapp, cond=lambda: dlg.rows[0].model_label.text() == tr("civpub.model_unknown"))
    dlg.close()


def test_remove_row_disables_open_folder_once_empty(qapp, tmp_path, monkeypatch):
    dlg = CivitPublishDialog(make_ctx(tmp_path), make_lora(tmp_path))
    art = picture_without_hash(tmp_path)
    monkeypatch.setattr("anihub.ui.civitai_publish_dialog.QFileDialog.getOpenFileNames", lambda *a, **k: ([str(art)], ""))
    dlg._add_pictures()
    assert dlg.open_folder_btn.isEnabled()
    dlg._remove_row(dlg.rows[0])
    assert dlg.rows == [] and not dlg.open_folder_btn.isEnabled()
    dlg.close()


def test_copy_and_open_copies_the_description_and_opens_the_upload_page(qapp, tmp_path, monkeypatch):
    opened = []
    monkeypatch.setattr("anihub.ui.civitai_publish_dialog.QDesktopServices.openUrl", lambda url: opened.append(url.toString()))
    dlg = CivitPublishDialog(make_ctx(tmp_path), make_lora(tmp_path))
    dlg.description.setPlainText("my custom listing text")
    dlg._copy_and_open()
    assert QGuiApplication.clipboard().text() == "my custom listing text"
    assert opened[0] == UPLOAD_URL
    assert dlg.message.text()
    dlg.close()
