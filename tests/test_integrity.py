import time

import pytest
from PySide6.QtWidgets import QMessageBox

from anihub.core.db import Database
from anihub.core.paths import LibraryPaths
from anihub.services import integrity


def make(tmp_path):
    paths = LibraryPaths(tmp_path / "lib")
    paths.ensure()
    return paths, Database(paths.db_file)


def add_file_item(paths, db, name, content=b"data", sha=None, **kw):
    import hashlib

    f = paths.arts / "site" / name
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_bytes(content)
    return db.add_item(kind="art", path=f.relative_to(paths.root).as_posix(),
                       sha256=sha or hashlib.sha256(content).hexdigest(), tags=[("cat", "general")], **kw)


def test_clean_library_reports_nothing(tmp_path):
    paths, db = make(tmp_path)
    add_file_item(paths, db, "a.png")
    add_file_item(paths, db, "b.png", b"other")
    report = integrity.check_library(db, paths, verify_hashes=True)
    assert report.clean and report.checked == 2 and report.db_ok


def test_missing_damaged_and_orphan_files_are_found(tmp_path):
    paths, db = make(tmp_path)
    ok = add_file_item(paths, db, "ok.png")
    gone = add_file_item(paths, db, "gone.png")
    bad = add_file_item(paths, db, "bad.png", sha="0" * 64)
    (paths.arts / "site" / "gone.png").unlink()
    (paths.arts / "site" / "stranger.png").write_bytes(b"who am i")
    (paths.arts / "site" / "half.png.part").write_bytes(b"partial download")      # unfinished downloads are not orphans
    (paths.sd / "generated" / "2026").mkdir(parents=True)
    (paths.sd / "generated" / "2026" / "scratch.png").write_bytes(b"x")            # sd/generated is a scratch folder
    quick = integrity.check_library(db, paths)
    assert [p.item_id for p in quick.of("missing")] == [gone] and not quick.of("damaged")
    assert [p.path for p in quick.of("orphan")] == ["arts/site/stranger.png"] and not quick.clean
    full = integrity.check_library(db, paths, verify_hashes=True)
    assert [p.item_id for p in full.of("damaged")] == [bad]
    assert ok not in {p.item_id for p in full.problems}


def test_trashed_items_are_checked_at_their_trash_path(tmp_path):
    paths, db = make(tmp_path)
    item = add_file_item(paths, db, "t.png")
    (paths.arts / "site" / "t.png").rename(paths.trash / "t.png")
    db.update_fields(item, trashed_at=time.time(), trash_path="trash/t.png")
    assert integrity.check_library(db, paths).clean
    (paths.trash / "t.png").unlink()
    assert [p.item_id for p in integrity.check_library(db, paths).of("missing")] == [item]


def test_remove_missing_drops_records_with_their_tags(tmp_path):
    paths, db = make(tmp_path)
    gone = add_file_item(paths, db, "gone.png")
    keep = add_file_item(paths, db, "keep.png", b"keep")
    (paths.arts / "site" / "gone.png").unlink()
    assert integrity.remove_missing(db, [gone]) == 1 and integrity.remove_missing(db, []) == 0
    assert db.get_item(gone) is None and db.get_item(keep) is not None and db.item_tags(gone) == []


def test_cancel_and_progress_and_optimize(tmp_path):
    paths, db = make(tmp_path)
    for i in range(120):
        add_file_item(paths, db, f"{i}.png", str(i).encode())
    seen = []
    report = integrity.check_library(db, paths, progress=lambda d, t: seen.append((d, t)))
    assert report.checked == 120 and seen[-1] == (120, 120) and len(seen) >= 3
    stopped = integrity.check_library(db, paths, cancelled=lambda: True)
    assert stopped.checked == 0
    integrity.optimize(db)                                                        # must simply work on a live database
    assert db.count_items() == 120


def test_pausing_blocks_before_the_next_item_without_losing_progress(tmp_path):
    paths, db = make(tmp_path)
    for i in range(3):
        add_file_item(paths, db, f"{i}.png", str(i).encode())
    polls = {"n": 0}

    def paused():
        polls["n"] += 1
        return polls["n"] == 1              # paused for exactly the first poll, then lets go

    report = integrity.check_library(db, paths, paused=paused)
    assert report.checked == 3              # nothing skipped, just delayed
    assert polls["n"] >= 2                  # actually waited (polled more than once) before continuing


def test_dialog_finds_and_cleans(qapp, tmp_path, monkeypatch):
    from types import SimpleNamespace

    from anihub.core.config import Config
    from anihub.ui.integrity_dialog import IntegrityDialog

    paths, db = make(tmp_path)
    add_file_item(paths, db, "ok.png")
    gone = add_file_item(paths, db, "gone.png", b"g")
    (paths.arts / "site" / "gone.png").unlink()
    ctx = SimpleNamespace(db=db, paths=paths, cfg=Config.load(tmp_path / "c.json"))
    dlg = IntegrityDialog(ctx)
    assert not dlg.fix_btn.isEnabled()
    dlg.start()
    end = time.time() + 5
    while time.time() < end and dlg.report is None:
        qapp.processEvents()
        time.sleep(0.01)
    assert dlg.report and dlg.tree.topLevelItemCount() == 1 and dlg.fix_btn.isEnabled() and dlg.start_btn.isEnabled()
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes))
    changed = []
    dlg.changed.connect(lambda: changed.append(1))
    dlg._fix()
    assert changed and db.get_item(gone) is None and not dlg.fix_btn.isEnabled()
    dlg._optimize()
    end = time.time() + 5
    while time.time() < end and not dlg.optimize_btn.isEnabled():
        qapp.processEvents()
        time.sleep(0.01)
    assert dlg.optimize_btn.isEnabled()
