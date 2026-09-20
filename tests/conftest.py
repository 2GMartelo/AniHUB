import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")  # widgets in tests without a display

import pytest


@pytest.fixture(scope="session")
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])
