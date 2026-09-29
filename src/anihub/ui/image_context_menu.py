"""A shared right-click menu for anywhere a full-size picture is shown: Copy image, Copy file path, Save as,
Open containing folder. Works two ways: with a real file on disk (Copy path / Open folder become available, and
Save As copies the exact original bytes) or with just an in-memory QImage -- manga pages are fetched straight
from the server into memory and never written to a file of their own; there, Save As re-encodes the QImage."""
from __future__ import annotations

import os
import shutil
from pathlib import Path

from PySide6.QtGui import QGuiApplication, QImage
from PySide6.QtWidgets import QFileDialog, QMenu, QWidget

from anihub.core.i18n import tr


def build_image_menu(parent: QWidget, image: QImage | None = None, path: Path | None = None,
                     suggested_name: str = "image.png") -> QMenu | None:
    """Built separately from showing it (mirrors LibraryView._fill_menu/_grid_context) so a test can inspect or
    trigger an action without going through a blocking QMenu.exec()."""
    have_image = image is not None and not image.isNull()
    have_file = path is not None and path.exists()
    if not have_image and not have_file:
        return None
    menu = QMenu(parent)
    if have_image:
        menu.addAction(tr("imgmenu.copy"), lambda: QGuiApplication.clipboard().setImage(image))
    if have_file:
        menu.addAction(tr("imgmenu.save_as"), lambda: _save_file(parent, path))
        menu.addAction(tr("imgmenu.copy_path"), lambda: QGuiApplication.clipboard().setText(str(path)))
        menu.addAction(tr("imgmenu.open_folder"), lambda: os.startfile(path.parent))
    elif have_image:
        menu.addAction(tr("imgmenu.save_as"), lambda: _save_image(parent, image, suggested_name))
    return menu


def show_image_menu(parent: QWidget, global_pos, image: QImage | None = None, path: Path | None = None,
                    suggested_name: str = "image.png") -> None:
    menu = build_image_menu(parent, image, path, suggested_name)
    if menu is not None:
        menu.exec(global_pos)


def _save_file(parent: QWidget, path: Path) -> None:
    dest, _ = QFileDialog.getSaveFileName(parent, tr("imgmenu.save_as"), path.name, f"*{path.suffix}" if path.suffix else "*")
    if dest:
        shutil.copy2(path, dest)


def _save_image(parent: QWidget, image: QImage, suggested_name: str) -> None:
    dest, _ = QFileDialog.getSaveFileName(parent, tr("imgmenu.save_as"), suggested_name, "PNG (*.png)")
    if dest:
        image.save(dest, "PNG")
