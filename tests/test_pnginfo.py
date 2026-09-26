"""PNG Info: reading generation parameters back out of pictures (service, library scan, the SD tab), plus the
GIL-friendly thumbnail decoder and the multi-size icon that came with the same round of fixes."""
import importlib.util
import struct
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QGuiApplication, QImage

from anihub.core.config import Config
from anihub.core.db import Database
from anihub.core.paths import LibraryPaths
from anihub.library.service import LibraryService
from anihub.services.generation import (
    parse_infotext, png_info_meta, read_png_text, split_infotext, split_prompt)
from anihub.ui.grid import decode_image, image_to_thumb
from anihub.ui.pnginfo_view import PngInfoView

INFOTEXT = ("1girl, (blue eyes:1.2), <lora:foo:0.8>, smile\n"
            "Negative prompt: lowres, bad hands\n"
            "Steps: 25, Sampler: Euler a, Schedule type: Karras, CFG scale: 6, Seed: 1234, Size: 832x1216, "
            "Model hash: abc123, Model: cool_model")


def make_png(path: Path, text: str | None = INFOTEXT, color: str = "red") -> Path:
    img = QImage(64, 64, QImage.Format.Format_RGB32)
    img.fill(QColor(color))
    if text is not None:
        img.setText("parameters", text)
    path.parent.mkdir(parents=True, exist_ok=True)
    assert img.save(str(path), "PNG")
    return path


@pytest.fixture
def lib(tmp_path):
    paths = LibraryPaths(tmp_path / "lib")
    paths.ensure()
    cfg = Config.load(tmp_path / "c.json")
    return LibraryService(Database(paths.db_file), paths, SimpleNamespace(), cfg), paths, tmp_path


# --- services -------------------------------------------------------------------------------------------

def test_split_prompt_keeps_weights_loras_and_bracketed_commas():
    assert split_prompt("a, (b, c:1.2), <lora:x:0.8>, d\ne,  ,") == ["a", "(b, c:1.2)", "<lora:x:0.8>", "d", "e"]


def test_split_prompt_falls_back_to_plain_commas_when_brackets_do_not_balance():
    assert split_prompt("a, (b, c") == ["a", "(b", "c"]
    assert split_prompt("") == []


def test_split_infotext_parts_and_parse_infotext_agree():
    prompt, negative, settings = split_infotext(INFOTEXT)
    assert prompt.startswith("1girl") and negative == "lowres, bad hands" and settings.startswith("Steps: 25")
    parsed = parse_infotext(INFOTEXT)
    assert parsed["prompt"] == prompt and parsed["negative_prompt"] == negative and parsed["seed"] == 1234
    assert split_infotext("just a prompt") == ("just a prompt", "", "")


def test_png_info_meta_reads_forge_parameters(tmp_path):
    meta = png_info_meta(make_png(tmp_path / "a.png"))
    assert meta["prompt"].startswith("1girl") and meta["seed"] == 1234 and meta["infotext"] == INFOTEXT
    assert meta["width"] == 832 and meta["model_hash"] == "abc123"


def test_png_info_meta_is_none_without_parameters_or_for_other_formats(tmp_path):
    assert png_info_meta(make_png(tmp_path / "plain.png", text=None)) is None
    jpg = tmp_path / "a.jpg"
    jpg.write_bytes(b"\xff\xd8\xff")
    assert png_info_meta(jpg) is None
    assert png_info_meta(tmp_path / "missing.png") is None
    junk = tmp_path / "junk.png"
    junk.write_text("not a png")
    assert png_info_meta(junk) is None


def test_read_png_text_seeks_over_pixel_data_and_finds_text_before_or_after_it(tmp_path):
    path = make_png(tmp_path / "a.png")
    assert read_png_text(path)["parameters"] == INFOTEXT
    data = path.read_bytes()

    def chunk(kind, body):
        return struct.pack(">I", len(body)) + kind + body + b"\0\0\0\0"

    end = data.rindex(struct.pack(">I", 0) + b"IEND")
    late = tmp_path / "late.png"
    late.write_bytes(data[:end] + chunk(b"tEXt", b"parameters\0after the pixels") + data[end:])
    assert read_png_text(late)["parameters"] == "after the pixels"                       # a chunk after the pixel data is found too; the later one wins
    truncated = tmp_path / "cut.png"
    truncated.write_bytes(data[:40])
    assert read_png_text(truncated) == {}


# --- thumbnails ------------------------------------------------------------------------------------------

def test_decode_image_and_thumb_accept_bytes_and_paths(qapp, tmp_path):
    path = make_png(tmp_path / "a.png")
    from_path, from_bytes = decode_image(path), decode_image(path.read_bytes())
    assert not from_path.isNull() and from_path.size() == from_bytes.size()
    assert decode_image(b"garbage").isNull() and decode_image(tmp_path / "nope.png").isNull()
    thumb = image_to_thumb(path, 32)
    assert thumb is not None and max(thumb.width(), thumb.height()) == 32
    assert image_to_thumb(path.read_bytes(), 32, badge="GIF").size() == thumb.size()
    assert image_to_thumb(b"garbage", 32) is None


# --- library ---------------------------------------------------------------------------------------------

def test_import_reads_parameters_from_the_png(qapp, lib):
    svc, paths, tmp = lib
    counts = svc.import_files([make_png(tmp / "src" / "a.png"), make_png(tmp / "src" / "b.png", text=None, color="blue")])
    assert counts["saved"] == 2
    assert len(svc.db.items_without_meta(("png",))) == 1                    # only the plain one has no parameters
    with_meta = [r for r in svc.db.conn.execute("SELECT * FROM items") if r["meta"]]
    assert len(with_meta) == 1 and "1girl" in with_meta[0]["meta"] and with_meta[0]["source_site"] == "local"


def test_scan_fills_only_empty_records_and_reports_counts(qapp, lib):
    svc, paths, tmp = lib
    a = make_png(paths.arts / "local" / "a.png", color="green")
    b = make_png(paths.arts / "local" / "b.png", text=None, color="blue")
    c = make_png(paths.arts / "local" / "c.png", text="other prompt\nSteps: 5, Seed: 9", color="yellow")
    ids = {}
    for name, path in (("a", a), ("b", b), ("c", c)):
        ids[name] = svc.db.add_item(kind="art", path=path.relative_to(paths.root).as_posix(), sha256=name * 8,
                                    ext="png", source_site="local", source_post_id=name)
    svc.db.update_fields(ids["c"], meta='{"prompt": "kept as it was"}')     # already has a record: never overwritten
    progress = []
    counts = svc.scan_png_info(progress=lambda i, n: progress.append((i, n)))
    assert counts == {"scanned": 2, "found": 1} and progress[-1] == (2, 2)
    assert "1girl" in svc.db.get_item(ids["a"])["meta"]
    assert not svc.db.get_item(ids["b"])["meta"]
    assert svc.db.get_item(ids["c"])["meta"] == '{"prompt": "kept as it was"}'
    assert svc.scan_png_info() == {"scanned": 1, "found": 0}               # b is still empty, a is settled


def test_scan_skips_missing_files_and_can_be_cancelled(qapp, lib):
    svc, paths, _tmp = lib
    svc.db.add_item(kind="art", path="arts/local/gone.png", sha256="x" * 8, ext="png", source_site="local",
                    source_post_id="1")
    assert svc.scan_png_info() == {"scanned": 1, "found": 0}
    assert svc.scan_png_info(cancelled=lambda: True) == {"scanned": 0, "found": 0}


# --- the PNG Info tab ------------------------------------------------------------------------------------

def test_tab_shows_editable_parameters_and_tags(qapp, tmp_path):
    view = PngInfoView()
    assert view.load_path(make_png(tmp_path / "a.png")) is True
    assert view.prompt.toPlainText().startswith("1girl") and view.negative.toPlainText() == "lowres, bad hands"
    assert view.params.toPlainText().startswith("Steps: 25")
    assert [view.tags.item(i).text() for i in range(view.tags.count())] == ["1girl", "(blue eyes:1.2)", "<lora:foo:0.8>", "smile"]
    view.prompt.setPlainText("cat, dog")                                       # editing refreshes the tag list
    assert view.tags.count() == 2


def test_tab_reports_a_picture_without_parameters(qapp, tmp_path):
    view = PngInfoView()
    assert view.load_path(make_png(tmp_path / "plain.png", text=None)) is False
    assert view.prompt.toPlainText() == "" and view.tags.count() == 0 and view.status.text()
    assert view.insert_btn.isEnabled() is False


def test_tab_copies_and_sends_selected_tags(qapp, tmp_path):
    view = PngInfoView()
    view.load_path(make_png(tmp_path / "a.png"))
    sent = []
    view.add_to_prompt.connect(lambda p, n: sent.append((p, n)))
    view._copy(["smile"])
    assert QGuiApplication.clipboard().text() == "smile"
    assert view.copy_btn.isEnabled() is False
    view.tags.item(0).setSelected(True)
    view.tags.item(3).setSelected(True)
    assert view.copy_btn.isEnabled() and view.selected_tags() == ["1girl", "smile"]
    view.copy_btn.click()
    assert QGuiApplication.clipboard().text() == "1girl, smile"
    view.tags_prompt_btn.click()
    view.tags_negative_btn.click()
    assert sent == [("1girl, smile", ""), ("", "1girl, smile")]


def test_tab_sends_the_edited_prompt_and_settings(qapp, tmp_path):
    view = PngInfoView()
    view.load_path(make_png(tmp_path / "a.png"))
    view.prompt.setPlainText("edited prompt")
    view.negative.setPlainText("edited negative")
    added, replaced, params = [], [], []
    view.add_to_prompt.connect(lambda p, n: added.append((p, n)))
    view.replace_prompt.connect(lambda p, n: replaced.append((p, n)))
    view.load_params.connect(params.append)
    view.insert_btn.click()
    view.replace_btn.click()
    view.send_btn.click()
    assert added == replaced == [("edited prompt", "edited negative")]
    data = params[0]
    assert data["prompt"] == "edited prompt" and data["negative_prompt"] == "edited negative"
    assert data["seed"] == 1234 and data["steps"] == 25 and data["width"] == 832


def test_tab_takes_parameters_from_pasted_text(qapp):
    view = PngInfoView()
    QGuiApplication.clipboard().setText("  ")
    view.paste_btn.click()
    assert view.status.text() and view.prompt.toPlainText() == ""
    QGuiApplication.clipboard().setText("just, a plain prompt")                  # not an infotext: still a prompt to split up
    view.paste_btn.click()
    assert view.prompt.toPlainText() == "just, a plain prompt" and view.tags.count() == 2
    QGuiApplication.clipboard().setText(INFOTEXT)
    view.paste_btn.click()
    assert view.prompt.toPlainText().startswith("1girl") and view.tags.count() == 4


# --- the once-per-version scan ---------------------------------------------------------------------------

def test_startup_scan_runs_once_per_version(qapp, monkeypatch):
    from anihub import __version__
    from anihub.ui import main_window

    calls, messages, reloads = [], [], []
    monkeypatch.setattr(main_window, "run_async", lambda fn, on_done=None, on_error=None: on_done(fn()))
    cfg = SimpleNamespace(store={}, get=lambda k, d=None: cfg.store.get(k, d), set=lambda k, v: cfg.store.__setitem__(k, v))
    ctx = SimpleNamespace(cfg=cfg, library=SimpleNamespace(scan_png_info=lambda: calls.append(1) or {"scanned": 3, "found": 2}))
    win = SimpleNamespace(ctx=ctx, library=SimpleNamespace(reload=lambda: reloads.append("lib")), sd_page=None,
                          statusBar=lambda: SimpleNamespace(showMessage=lambda text, ms=0: messages.append(text)))
    main_window.MainWindow._scan_png_info(win)
    main_window.MainWindow._scan_png_info(win)                                # same version: nothing more to do
    assert calls == [1] and cfg.store["library.pnginfo_scanned"] == __version__
    assert reloads == ["lib"] and messages and "2" in messages[0]
    cfg.store["library.pnginfo_scanned"] = "0.0.1"                            # an update: scan again
    main_window.MainWindow._scan_png_info(win)
    assert calls == [1, 1]


# --- start-up / packaging fixes --------------------------------------------------------------------------

def test_gpu_list_is_cached(monkeypatch):
    from anihub.services import backends

    calls = []
    monkeypatch.setattr(backends.shutil, "which", lambda name: calls.append(name) or None)
    backends.gpu_list.cache_clear()
    try:
        assert backends.gpu_list() == () and backends.gpu_list() == ()
        assert calls == ["nvidia-smi"]
    finally:
        backends.gpu_list.cache_clear()


def test_icon_file_has_every_size_as_png(qapp, tmp_path):
    from anihub.ui.taskbar import ICON_SIZES, write_ico
    from anihub.ui.theme import make_app_icon

    out = tmp_path / "x.ico"
    icon = make_app_icon()
    write_ico([icon.pixmap(s, s) for s in ICON_SIZES], out)
    data = out.read_bytes()
    reserved, kind, count = struct.unpack("<HHH", data[:6])
    assert (reserved, kind, count) == (0, 1, len(ICON_SIZES))
    sizes = []
    for i in range(count):
        w, h, _c, _r, _planes, _bits, length, offset = struct.unpack("<BBBBHHII", data[6 + 16 * i:22 + 16 * i])
        sizes.append(w or 256)
        assert data[offset:offset + 8] == b"\x89PNG\r\n\x1a\n" and offset + length <= len(data)
    assert sizes == list(ICON_SIZES)


def test_build_script_uses_the_shared_icon_writer(qapp, tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("build_script", Path(__file__).resolve().parents[1] / "packaging" / "build.py")
    build = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(build)
    monkeypatch.setattr(build, "ROOT", tmp_path)
    out = build.make_icon()
    assert struct.unpack("<HHH", out.read_bytes()[:6])[2] == 7


def test_relaunch_icon_is_accepted_by_the_shell(qapp, tmp_path):
    import sys

    from PySide6.QtWidgets import QWidget

    from anihub.ui.taskbar import set_relaunch_identity

    win = QWidget()
    win.show()
    ok = set_relaunch_identity(int(win.winId()), tmp_path / "a.ico", '"x.exe"', "AniHUB")
    assert isinstance(ok, bool) and (ok is False or sys.platform == "win32")      # offscreen test windows have no real HWND
    win.close()
