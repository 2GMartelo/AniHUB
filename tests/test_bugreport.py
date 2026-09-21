import sys
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from anihub import __version__
from anihub.services import bugreport


def test_redact_removes_keys_tokens_passwords_and_user_names():
    text = ('GET https://danbooru.donmai.us/posts.json?login=me&api_key=SECRETKEY123&limit=5\n'
            '"token": "ghp_abcdefghijklmnopqrstuvwxyz0123456789", password=hunter2 Authorization: Bearer abc.def-ghi\n'
            'user_id=123456 file C:\\Users\\Alice\\AppData\\Local\\AniHUB\\logs\\x.log and /home/x\n'
            'sha aabbccdd11223344556677889900aabbccddeeff00112233445566778899aabbccdd')
    out = bugreport.redact(text)
    for secret in ("SECRETKEY123", "ghp_abcdef", "hunter2", "abc.def-ghi", "123456", "Alice", "aabbccdd11223344"):
        assert secret not in out, secret
    assert "posts.json" in out and "limit=5" in out and "AppData" in out              # the useful context survives
    assert out.count("<hidden>") >= 5


def test_redact_hides_the_home_directory_name(monkeypatch):
    monkeypatch.setattr(Path, "home", staticmethod(lambda: Path("C:/Users/Ann")))
    out = bugreport.redact("open C:\\Users\\Ann\\Pictures\\a.png")
    assert "Ann" not in out and "Pictures" in out
    assert "Ann" not in bugreport.redact("C:/Users/Ann/x")
    assert "Bob" not in bugreport.redact("C:\\Users\\Bob\\x")                          # another user's path too


def test_report_has_version_system_error_and_log(tmp_path):
    (tmp_path / "anihub.log").write_text("\n".join(f"line {i} api_key=ABCDEF" for i in range(300)), encoding="utf-8")
    bugreport.clear_last_error()
    try:
        raise ValueError("kaboom token=zzz")
    except ValueError:
        bugreport.record_exception(*sys.exc_info())
    report = bugreport.build_report("The reader crashed", log_lines=20, log_folder=tmp_path)
    assert "The reader crashed" in report and f"AniHUB {__version__}" in report and "Python" in report
    assert "ValueError: kaboom" in report and "zzz" not in report and "ABCDEF" not in report
    assert "line 299" in report and "line 200" not in report                          # only the last 20 lines
    assert "Recent log" not in bugreport.build_report("x", include_log=False, log_folder=tmp_path)
    assert "Last error" not in bugreport.build_report("x", include_error=False, log_folder=tmp_path)
    assert "describe what you did" in bugreport.build_report("", include_log=False)
    bugreport.clear_last_error()
    assert "Last error" not in bugreport.build_report("x", include_log=False)


def test_unseen_errors_are_reported_once():
    bugreport.clear_last_error()
    assert bugreport.take_unseen_error() is None
    try:
        1 / 0
    except ZeroDivisionError:
        bugreport.record_exception(*sys.exc_info())
    assert "ZeroDivisionError" in bugreport.take_unseen_error()
    assert bugreport.take_unseen_error() is None and "ZeroDivisionError" in bugreport.last_error_text()
    bugreport.clear_last_error()


def test_issue_url_is_prefilled_and_bounded():
    url = bugreport.issue_url("2GMartelo/AniHUB", "Crash & burn", "body\nwith lines")
    parts = urlsplit(url)
    assert parts.path == "/2GMartelo/AniHUB/issues/new"
    query = parse_qs(parts.query)
    assert query["title"] == ["Crash & burn"] and query["body"] == ["body\nwith lines"]
    long = bugreport.issue_url("a/b", "t", "x" * 20000)
    assert len(long) < 20000 and "clipboard" in parse_qs(urlsplit(long).query)["body"][0]


def test_excepthook_from_logging_setup_records_the_error(tmp_path, monkeypatch):
    from anihub.core import logging_setup

    monkeypatch.setattr(logging_setup, "config_dir", lambda: tmp_path)
    old_hook = sys.excepthook
    try:
        bugreport.clear_last_error()
        monkeypatch.setattr(sys, "__excepthook__", lambda *a: None)
        logging_setup.setup_logging()
        try:
            raise RuntimeError("from a slot")
        except RuntimeError:
            sys.excepthook(*sys.exc_info())
        assert "RuntimeError: from a slot" in bugreport.last_error_text()
        assert "Unhandled exception" in (tmp_path / "logs" / "anihub.log").read_text(encoding="utf-8")
    finally:
        sys.excepthook = old_hook
        import logging

        for h in list(logging.getLogger().handlers):
            if getattr(h, "baseFilename", "").startswith(str(tmp_path)):
                logging.getLogger().removeHandler(h)
                h.close()
        bugreport.clear_last_error()


def test_dialog_builds_edits_and_copies(qapp, monkeypatch):
    from PySide6.QtGui import QGuiApplication

    from anihub.core.config import Config
    from anihub.ui import bugreport_dialog
    from anihub.ui.bugreport_dialog import BugReportDialog

    opened = []
    monkeypatch.setattr(bugreport_dialog.QDesktopServices, "openUrl", staticmethod(lambda url: opened.append(url.toString(bugreport_dialog.QUrl.ComponentFormattingOption.FullyEncoded))))
    cfg = Config.load(Path(__file__).parent / "does_not_exist.json")
    dlg = BugReportDialog(cfg, description="Something broke\nsecond line")
    assert "Something broke" in dlg.report_text() and __version__ in dlg.report_text()
    dlg.include_log.setChecked(False)
    assert "Recent log" not in dlg.report_text()
    dlg.copy()
    assert "Something broke" in QGuiApplication.clipboard().text()
    dlg.open_issue()
    assert opened and opened[0].startswith("https://github.com/2GMartelo/AniHUB/issues/new?title=Something%20broke")
    dlg.close()
