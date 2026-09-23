import time
from pathlib import Path
from types import SimpleNamespace

from PySide6.QtGui import QColor, QGuiApplication, QImage

from anihub.core.i18n import tr
from anihub.services.autotag import TagResult
from anihub.ui.rule34_upload_dialog import UPLOAD_URL, Rule34UploadDialog


def pump(app, cond, limit=5.0):
    end = time.time() + limit
    while time.time() < end:
        app.processEvents()
        if cond():
            return True
        time.sleep(0.01)
    return bool(cond())


def picture(tmp_path, name="a.png") -> Path:
    img = QImage(32, 32, QImage.Format.Format_RGB32)
    img.fill(QColor("#3366ff"))
    path = tmp_path / name
    img.save(str(path))
    return path


class FakeTagger:
    def __init__(self, result=None, available=True):
        self.result, self._available = result, available

    @property
    def available(self):
        return self._available

    def tag_file(self, path):
        return self.result


def make_ctx(tagger):
    return SimpleNamespace(autotagger=tagger)


def test_dialog_fills_tags_from_the_autotagger(qapp, tmp_path):
    result = TagResult(tags=[("1girl", "general"), ("teal_hair", "general")], rating="questionable")
    dlg = Rule34UploadDialog(make_ctx(FakeTagger(result)), picture(tmp_path))
    assert pump(qapp, lambda: dlg.tags == ["1girl", "teal_hair"])
    assert "questionable" in dlg.rating_label.text()
    dlg.close()


def test_dialog_without_a_downloaded_model_says_so_and_starts_empty(qapp, tmp_path):
    dlg = Rule34UploadDialog(make_ctx(FakeTagger(None, available=False)), picture(tmp_path))
    assert dlg.tags == [] and dlg.rating_label.text() == tr("lt.no_autotagger")
    dlg.close()


def test_add_and_remove_tags_by_hand(qapp, tmp_path):
    dlg = Rule34UploadDialog(make_ctx(FakeTagger(None, available=False)), picture(tmp_path))
    dlg.add_line.setText("new tag")
    dlg.add_line.returnPressed.emit()
    assert dlg.tags == ["new_tag"]                                  # spaces become underscores, tag style
    dlg._remove_tag("new_tag")
    assert dlg.tags == []
    dlg.close()


def test_copy_and_open_copies_the_tags_and_opens_the_upload_page(qapp, tmp_path, monkeypatch):
    opened = []
    monkeypatch.setattr("anihub.ui.rule34_upload_dialog.QDesktopServices.openUrl", lambda url: opened.append(url.toString()))
    dlg = Rule34UploadDialog(make_ctx(FakeTagger(None, available=False)), picture(tmp_path))
    dlg.tags = ["1girl", "teal_hair"]
    dlg._copy_and_open()
    assert QGuiApplication.clipboard().text() == "1girl teal_hair"
    assert opened[0] == UPLOAD_URL
    assert len(opened) == 2                                          # the upload page, then the picture's folder
    assert dlg.message.text()
    dlg.close()
