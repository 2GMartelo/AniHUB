from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler

from anihub.core.config import config_dir


def setup_logging() -> None:
    log_dir = config_dir() / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(log_dir / "anihub.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)

    def excepthook(exc_type, exc, tb):
        logging.getLogger("anihub").critical("Unhandled exception", exc_info=(exc_type, exc, tb))
        sys.__excepthook__(exc_type, exc, tb)

    sys.excepthook = excepthook
