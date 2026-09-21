import json
import sqlite3
import time
import zipfile
from pathlib import Path

import pytest

from anihub.core.config import Config
from anihub.core.db import Database
from anihub.core.paths import LibraryPaths
from anihub.services import backup
from anihub.services.backup import BackupError


def make_library(tmp_path, n_items=3):
    paths = LibraryPaths(tmp_path / "lib")
    paths.ensure()
    db = Database(paths.db_file)
    for i in range(n_items):
        db.add_item(kind="art", path=f"arts/{i}.png", tags=[("cat", "general")])
    cfg = Config.load(tmp_path / "config.json")
    cfg.set("language", "ru")
    return paths, db, cfg


def item_count(path: Path) -> int:
    conn = sqlite3.connect(path)
    try:
        return conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]
    finally:
        conn.close()


def test_backup_contains_a_consistent_database_manifest_and_config(tmp_path):
    paths, db, cfg = make_library(tmp_path)
    zip_path = backup.create_backup(paths, cfg, now=1_700_000_000)
    assert zip_path.parent == paths.root / "backups" and zip_path.name.startswith("anihub_2023")
    with zipfile.ZipFile(zip_path) as z:
        assert sorted(z.namelist()) == ["config.json", "db/anihub.db", "manifest.json"]
        manifest = json.loads(z.read("manifest.json"))
        z.extract("db/anihub.db", tmp_path / "x")
    assert manifest["items"] == 3 and manifest["config_included"] and manifest["created"] == 1_700_000_000
    assert item_count(tmp_path / "x" / "db" / "anihub.db") == 3
    plain = backup.create_backup(paths, cfg, include_config=False, now=1_700_000_100)
    with zipfile.ZipFile(plain) as z:
        assert "config.json" not in z.namelist()


def test_backup_of_a_missing_database_is_refused(tmp_path):
    paths = LibraryPaths(tmp_path / "lib")
    with pytest.raises(BackupError):
        backup.create_backup(paths)


def test_listing_is_newest_first_and_pruning_keeps_the_latest(tmp_path):
    paths, db, cfg = make_library(tmp_path)
    for i in range(4):
        backup.create_backup(paths, cfg, now=1_700_000_000 + i * 86400)
    listed = backup.list_backups(paths)
    assert [b.created for b in listed] == sorted((b.created for b in listed), reverse=True) and len(listed) == 4
    assert listed[0].version and listed[0].size > 0
    assert backup.prune(paths, keep=2) == 2
    assert len(backup.list_backups(paths)) == 2 and backup.list_backups(paths)[0].created == 1_700_000_000 + 3 * 86400
    (paths.root / "backups" / "anihub_broken.zip").write_bytes(b"not a zip")
    assert len(backup.list_backups(paths)) == 3                                   # a damaged file is listed, not fatal


def test_automatic_backup_follows_the_interval_and_switch(tmp_path):
    paths, db, cfg = make_library(tmp_path)
    assert backup.is_due(cfg, now=1_800_000_000)                                  # never ran
    first = backup.run_if_due(paths, cfg, now=1_800_000_000)
    assert first and first.exists() and cfg.get("backup.last") == 1_800_000_000
    assert backup.run_if_due(paths, cfg, now=1_800_000_000 + 3 * 86400) is None   # 3 days < the 7 day default
    cfg.set("backup.interval_days", 1, save=False)
    assert backup.run_if_due(paths, cfg, now=1_800_000_000 + 2 * 86400) is not None
    cfg.set("backup.auto", False, save=False)
    assert not backup.is_due(cfg, now=9_999_999_999)
    cfg.set("backup.auto", True, save=False)
    cfg.set("backup.keep", 1, save=False)
    cfg.set("backup.last", 0, save=False)
    backup.run_if_due(paths, cfg, now=1_800_000_000 + 30 * 86400)
    assert len(backup.list_backups(paths)) == 1                                   # older ones pruned by `keep`


def test_restore_is_staged_and_applied_before_the_database_opens(tmp_path):
    paths, db, cfg = make_library(tmp_path, n_items=3)
    zip_path = backup.create_backup(paths, cfg)
    db.add_item(kind="art", path="arts/new.png")                                  # changes after the backup
    db.add_item(kind="art", path="arts/new2.png")
    db.close()
    assert item_count(paths.db_file) == 5
    assert backup.stage_restore(paths, zip_path) == 3 and backup.pending_restore(paths)
    assert backup.apply_pending_restore(paths) is True
    assert item_count(paths.db_file) == 3 and backup.pending_restore(paths) is None
    assert item_count(paths.db_file.with_name("anihub.db.before_restore")) == 5   # nothing is lost: the old one is kept
    assert backup.apply_pending_restore(paths) is False                            # nothing pending any more
    reopened = Database(paths.db_file)                                             # and the restored file is a working database
    assert reopened.count_items() == 3


def test_bad_backups_are_rejected_and_a_bad_pending_file_is_set_aside(tmp_path):
    paths, db, cfg = make_library(tmp_path)
    junk = tmp_path / "junk.zip"
    junk.write_bytes(b"nope")
    with pytest.raises(BackupError):
        backup.stage_restore(paths, junk)
    other = tmp_path / "other.zip"
    with zipfile.ZipFile(other, "w") as z:
        z.writestr("readme.txt", "hi")
    with pytest.raises(BackupError, match="not an AniHUB backup"):
        backup.stage_restore(paths, other)
    notdb = tmp_path / "notdb.zip"
    with zipfile.ZipFile(notdb, "w") as z:
        z.writestr("db/anihub.db", b"this is not sqlite at all" * 50)
    with pytest.raises(BackupError):
        backup.stage_restore(paths, notdb)
    assert backup.pending_restore(paths) is None
    pending = paths.db_file.parent / backup.PENDING                                # a corrupt pending file appears by itself
    pending.write_bytes(b"garbage")
    assert backup.apply_pending_restore(paths) is False
    assert not pending.exists() and pending.with_name(pending.name + ".failed").exists()
    assert item_count(paths.db_file) == 3                                          # the live database was not touched
    backup.stage_restore(paths, backup.create_backup(paths, cfg))
    backup.cancel_restore(paths)
    assert backup.pending_restore(paths) is None


def test_backup_box_creates_stages_and_cancels(qapp, tmp_path, monkeypatch):
    from types import SimpleNamespace

    from PySide6.QtWidgets import QFileDialog, QMessageBox

    from anihub.core.i18n import tr
    from anihub.ui.backup_box import BackupBox

    paths, db, cfg = make_library(tmp_path)
    ctx = SimpleNamespace(cfg=cfg, paths=paths)
    box = BackupBox(ctx)
    assert box.status.text() == tr("backup.none") and box.cancel_btn.isHidden()
    box.backup_now()
    end = time.time() + 5
    while time.time() < end and not backup.list_backups(paths):
        qapp.processEvents()
        time.sleep(0.01)
    assert len(backup.list_backups(paths)) == 1 and cfg.get("backup.last")
    box.interval.setValue(3)
    box.auto.setChecked(False)
    assert cfg.get("backup.interval_days") == 3 and cfg.get("backup.auto") is False
    zip_path = backup.list_backups(paths)[0].path
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(zip_path), "")))
    shown = []
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **k: shown.append(a[2])))
    box.restore()
    assert backup.pending_restore(paths) is not None
    assert shown and "3" in shown[0]
    box.cancel_btn.click()
    assert backup.pending_restore(paths) is None
