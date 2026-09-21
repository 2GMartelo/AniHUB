"""Bug reports (раздел 9): collect version, system and the recent log, strip secrets, and hand the text to the user, who
decides whether to post it (copy it, or open a prefilled GitHub issue). Nothing is ever sent automatically."""
from __future__ import annotations

import platform
import re
import sys
import threading
import traceback
from pathlib import Path
from urllib.parse import quote

from anihub import __version__
from anihub.core.config import config_dir

ISSUE_URL = "https://github.com/{repo}/issues/new"
MAX_URL_BODY = 5500                     # what still fits into a browser URL comfortably

_SECRET_KEYS = re.compile(r'(?i)((?:api[_-]?key|token|password|passwd|secret|authorization|cookie|user_id|login)["\']?\s*[:=]\s*["\']?)([^\s"\'&,;]+)')
_BEARER = re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-]+")
_URL_SECRET = re.compile(r"(?i)([?&](?:api_key|key|token|access_token|password|user_id|login)=)[^&\s]+")
_LONG_TOKEN = re.compile(r"\b[A-Za-z0-9_\-]{32,}\b")

_last_error: dict = {"text": "", "seen": True}
_lock = threading.Lock()


def redact(text: str) -> str:
    """Removes what must not end up in a public issue: keys, tokens, passwords, and the user's name in paths."""
    text = _BEARER.sub(lambda m: m.group(1) + "<hidden>", text)
    text = _SECRET_KEYS.sub(lambda m: m.group(1) + "<hidden>", text)
    text = _URL_SECRET.sub(lambda m: m.group(1) + "<hidden>", text)
    text = _LONG_TOKEN.sub("<hidden>", text)
    for home in {str(Path.home()), str(Path.home()).replace("\\", "/")}:
        text = text.replace(home, "~")
    return re.sub(r"(?i)(users[\\/])[^\\/\s]+", r"\1<user>", text)


def system_info() -> str:
    try:
        import PySide6
        from PySide6.QtCore import qVersion

        qt = f"PySide6 {PySide6.__version__} / Qt {qVersion()}"
    except Exception:  # noqa: BLE001
        qt = "PySide6 ?"
    return "\n".join([f"AniHUB {__version__}", f"Windows: {platform.platform()}", f"Python {sys.version.split()[0]} ({platform.machine()})", qt])


def recent_log(lines: int = 150, folder: Path | None = None) -> str:
    log = (folder or config_dir() / "logs") / "anihub.log"
    if not log.exists():
        return ""
    try:
        text = log.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    return "\n".join(text.splitlines()[-lines:])


def build_report(description: str, include_log: bool = True, log_lines: int = 150, log_folder: Path | None = None,
                 include_error: bool = True) -> str:
    parts = ["### What happened", (description.strip() or "(describe what you did and what went wrong)"), "", "### Version and system", system_info()]
    error = last_error_text()
    if include_error and error:
        parts += ["", "### Last error", "```", error, "```"]
    if include_log:
        log = recent_log(log_lines, log_folder)
        if log:
            parts += ["", "### Recent log", "```", log, "```"]
    return redact("\n".join(parts))


def issue_url(repo: str, title: str, body: str) -> str:
    """A new-issue page with the title and (the start of) the report filled in. The full text goes to the clipboard as well."""
    if len(body) > MAX_URL_BODY:
        body = body[:MAX_URL_BODY] + "\n\n(the report was cut here: paste the rest from the clipboard)"
    return ISSUE_URL.format(repo=repo) + f"?title={quote(title)}&body={quote(body)}"


# --- unhandled exceptions ---------------------------------------------------------------------------------------

def record_exception(exc_type, exc, tb) -> None:
    """Called by the global excepthook: remembers the last error so the UI can offer to report it."""
    text = "".join(traceback.format_exception(exc_type, exc, tb))[-4000:]
    with _lock:
        _last_error.update(text=text, seen=False)


def last_error_text() -> str:
    with _lock:
        return str(_last_error["text"])


def take_unseen_error() -> str | None:
    """The newest error the user has not been told about yet (once)."""
    with _lock:
        if _last_error["seen"] or not _last_error["text"]:
            return None
        _last_error["seen"] = True
        return str(_last_error["text"])


def clear_last_error() -> None:
    with _lock:
        _last_error.update(text="", seen=True)
