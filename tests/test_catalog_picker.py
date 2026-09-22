from types import SimpleNamespace

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage, QPixmap
from PySide6.QtWidgets import QMessageBox

from anihub.core.db import Database
from anihub.core.paths import LibraryPaths
from anihub.services.promptbook import PromptBook
from anihub.ui.catalog_picker import CatalogPickerDialog
from anihub.ui.viewer import TagRow, ViewItem, Viewer

ROLE = Qt.ItemDataRole.UserRole


@pytest.fixture
def book(tmp_path):
    db = Database(tmp_path / "lib.db")
    b = PromptBook(db, tmp_path)
    b.seed()
    yield b
    db.close()


@pytest.fixture
def env(tmp_path):
    """A ctx and a PromptBook that agree on the same root (so pictures a test writes are found by both)."""
    paths = LibraryPaths(tmp_path / "lib")
    paths.ensure()
    db = Database(paths.db_file)
    ctx = SimpleNamespace(db=db, paths=paths, sd_enabled=True)
    book = PromptBook(db, paths.root)
    book.seed()
    yield SimpleNamespace(ctx=ctx, book=book, tmp_path=tmp_path)
    db.close()


def picture(color="#3366ff"):
    img = QImage(64, 64, QImage.Format.Format_RGB32)
    img.fill(QColor(color))
    return QPixmap.fromImage(img)                                                                          # self._pixmap is always a QPixmap


# --- PromptBook.find_tag ------------------------------------------------------------------------------------------------------

def test_find_tag_matches_case_and_spacing_and_ignores_hidden(book):
    assert book.find_tag("Blue Hair") is not None and book.find_tag("blue_hair")["text"] == "blue hair"
    assert book.find_tag("not a real tag") is None
    row = book.find_tag("blue hair")
    book.delete_tag(row["id"])
    assert book.find_tag("blue hair") is None                                                            # hidden: no longer "found"


# --- CatalogPickerDialog -------------------------------------------------------------------------------------------------------

def test_picker_requires_a_real_category_and_can_create_one(qapp, book):
    dlg = CatalogPickerDialog(book, "my new tag")
    assert not dlg.ok_btn.isEnabled()                                                                     # nothing picked yet
    top = dlg.tree.topLevelItem(0)                                                                        # a slot heading, not a category
    dlg.tree.setCurrentItem(top)
    assert not dlg.ok_btn.isEnabled()
    child = top.child(0)
    dlg.tree.setCurrentItem(child)
    assert dlg.ok_btn.isEnabled()
    dlg._accept()
    assert dlg.chosen_node_id == child.data(0, ROLE)[1]
    assert dlg.result() == 1                                                                              # QDialog.Accepted


def test_picker_creates_a_category_and_subcategory(qapp, book, monkeypatch):
    from PySide6.QtWidgets import QInputDialog

    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("My clothes", True)))
    dlg = CatalogPickerDialog(book, "cool hat")
    top = next(dlg.tree.topLevelItem(i) for i in range(dlg.tree.topLevelItemCount())
              if dlg.tree.topLevelItem(i).data(0, ROLE) == ("slot", "clothing"))
    dlg.tree.setCurrentItem(top)
    dlg._new_category(None)
    assert dlg.ok_btn.isEnabled()
    node = book.node(dlg._selection()[1])
    assert node["name"] == "My clothes" and node["slot"] == "clothing"
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("Winter", True)))
    dlg._new_category(node["id"])
    sub = book.node(dlg._selection()[1])
    assert sub["parent_id"] == node["id"] and sub["slot"] == "clothing"


def test_picker_without_a_name_or_category_does_not_accept(qapp, book):
    dlg = CatalogPickerDialog(book, "   ")
    top = dlg.tree.topLevelItem(0).child(0)
    dlg.tree.setCurrentItem(top)
    dlg._accept()
    assert dlg.chosen_node_id is None and dlg.result() == 0                                                # still open: blank text refused


# --- the viewer's fourth tag button ---------------------------------------------------------------------------------------------

def rows_of(viewer):
    return [viewer.tags.itemWidget(viewer.tags.item(i)) for i in range(viewer.tags.count())
            if isinstance(viewer.tags.itemWidget(viewer.tags.item(i)), TagRow)]


def test_no_constructor_button_without_generation(qapp, tmp_path):
    paths = LibraryPaths(tmp_path / "lib")
    paths.ensure()
    db = Database(paths.db_file)
    ctx = SimpleNamespace(db=db, paths=paths, sd_enabled=False)
    viewer = Viewer([ViewItem("t", "i", lambda: tmp_path / "x.png", tags=[("blue hair", "general")])], 0, ctx=ctx)
    assert viewer.book is None
    row = rows_of(viewer)[0]
    assert row.constructor_btn is None
    viewer.close()
    db.close()


def test_constructor_button_shows_absent_and_present_states(qapp, env):
    viewer = Viewer([ViewItem("t", "i", lambda: env.tmp_path / "x.png", tags=[("blue hair", "general"), ("a brand new tag", "general")])],
                    0, ctx=env.ctx)
    assert viewer.book is not None
    present = next(r for r in rows_of(viewer) if r.name == "blue hair")
    absent = next(r for r in rows_of(viewer) if r.name == "a brand new tag")
    assert present.constructor_btn is not None and absent.constructor_btn is not None
    assert viewer._constructor_state("blue hair") == "no_picture"                                          # a built-in tag with no picture yet
    assert viewer._constructor_state("a brand new tag") == "absent"
    viewer.close()


def test_clicking_absent_opens_the_picker_and_adds_the_tag(qapp, env, monkeypatch):
    viewer = Viewer([ViewItem("t", "i", lambda: env.tmp_path / "x.png")], 0, ctx=env.ctx)
    viewer._pixmap = picture()                                                                              # simulate a loaded still image
    outfit = next(n for n in env.book.nodes("clothing") if n["key"] == "clothing.outfit")

    class FakeDialog:
        def __init__(self, book, text, has_picture=False, parent=None):
            self.text = SimpleNamespace(text=lambda: "sailor collar shirt")
            self.label = SimpleNamespace(text=lambda: "")
            self.use_picture = SimpleNamespace(isChecked=lambda: True)
            self.chosen_node_id = outfit["id"]

        def exec(self):
            return 1

    monkeypatch.setattr("anihub.ui.viewer.CatalogPickerDialog", FakeDialog)
    viewer._on_constructor("sailor collar shirt")
    row = env.book.find_tag("sailor collar shirt")
    assert row is not None and row["node_id"] == outfit["id"] and row["image"]
    viewer.close()


def test_clicking_present_without_a_picture_offers_to_use_the_current_one(qapp, env, monkeypatch):
    viewer = Viewer([ViewItem("t", "i", lambda: env.tmp_path / "x.png", tags=[("blue hair", "general")])], 0, ctx=env.ctx)
    viewer._pixmap = picture()
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes))
    row = env.book.find_tag("blue hair")
    assert not row["image"]
    viewer._on_constructor("blue hair")
    assert env.book.find_tag("blue hair")["image"]
    viewer.close()


def test_clicking_present_with_a_picture_does_nothing(qapp, env, monkeypatch):
    row = env.book.find_tag("blue hair")
    env.book.set_image(row["id"], picture().toImage())
    asked = []
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: asked.append(1) or QMessageBox.StandardButton.Yes))
    viewer = Viewer([ViewItem("t", "i", lambda: env.tmp_path / "x.png", tags=[("blue hair", "general")])], 0, ctx=env.ctx)
    viewer._pixmap = picture("#ff0000")
    viewer._on_constructor("blue hair")
    assert not asked                                                                                        # nothing to offer: it already has one
    viewer.close()
