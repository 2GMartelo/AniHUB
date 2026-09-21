import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")  # widgets in tests without a display

import pytest


@pytest.fixture(autouse=True)
def no_shipped_picture_pack(request, monkeypatch, tmp_path_factory):
    """The prompt builder's picture pack that ships with the app must not leak into tests (611 files per seeded database)."""
    if "shipped_pack" not in request.keywords:
        from anihub.services import promptbook
        monkeypatch.setattr(promptbook, "PACK_FILE", tmp_path_factory.getbasetemp() / "no-such-pack.zip")


@pytest.fixture(scope="session")
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])
