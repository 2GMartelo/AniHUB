"""Library backups (п. 6.16): a zip with a consistent copy of the database (and, optionally, the settings), automatic by interval,
old ones pruned. Restoring is staged and applied at the next start, before the database is opened."""
from __future__ import annotations

import json
import shutil
import sqlite3
import tempfile
import time
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from anihub import __version__
from anihub.core.config import Config
from anihub.core.paths import LibraryPaths

DB_ENTRY = "db/anihub.db"
PENDING = "restore.pending.zip"


class BackupError(Exception):
    pass


@dataclass
class BackupInfo:
    path: Path
    created: float
    size: int
    version: str = ""

    @property
    def label(self) -> str:
        return datetime.fromtimestamp(self.created).strftime("%Y-%m-%d %H:%M")


def backup_dir(paths: LibraryPaths) -> Path:
    return paths.root / "backups"


def _copy_database(source: Path, dest: Path) -> None:
    """sqlite3's online backup: a consistent copy even while the app is writing (WAL included)."""
    src = sqlite3.connect(source, timeout=30)
    try:
        dst = sqlite3.connect(dest)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()


def create_backup(paths: LibraryPaths, cfg: Config | None = None, include_config: bool = True, now: float | None = None) -> Path:
    if not paths.db_file.exists():
        raise BackupError("the library database does not exist yet")
    stamp = time.time() if now is None else now
    folder = backup_dir(paths)
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / f"anihub_{datetime.fromtimestamp(stamp).strftime('%Y%m%d_%H%M%S')}.zip"
    with tempfile.TemporaryDirectory() as tmp:
        copy = Path(tmp) / "anihub.db"
        _copy_database(paths.db_file, copy)
        conn = sqlite3.connect(copy)
        try:
            items = conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]
        finally:
            conn.close()
        manifest = {"app_version": __version__, "created": stamp, "items": items, "config_included": False}
        with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
            z.write(copy, DB_ENTRY)
            if include_config and cfg is not None and cfg.path.exists():
                z.write(cfg.path, "config.json")
                manifest["config_included"] = True
            z.writestr("manifest.json", json.dumps(manifest, indent=2))
    return dest


def list_backups(paths: LibraryPaths) -> list[BackupInfo]:
    """Newest first."""
    found = []
    for f in backup_dir(paths).glob("anihub_*.zip") if backup_dir(paths).exists() else []:
        version = ""
        try:
            with zipfile.ZipFile(f) as z:
                manifest = json.loads(z.read("manifest.json"))
            created, version = float(manifest.get("created", f.stat().st_mtime)), manifest.get("app_version", "")
        except (zipfile.BadZipFile, KeyError, ValueError, OSError):
            created = f.stat().st_mtime
        found.append(BackupInfo(f, created, f.stat().st_size, version))
    return sorted(found, key=lambda b: b.created, reverse=True)


def prune(paths: LibraryPaths, keep: int) -> int:
    removed = 0
    for old in list_backups(paths)[max(keep, 1):]:
        old.path.unlink(missing_ok=True)
        removed += 1
    return removed


def is_due(cfg: Config, now: float | None = None) -> bool:
    if not cfg.get("backup.auto", True):
        return False
    days = max(float(cfg.get("backup.interval_days", 7) or 7), 0.01)
    return (time.time() if now is None else now) - float(cfg.get("backup.last", 0) or 0) >= days * 86400


def run_if_due(paths: LibraryPaths, cfg: Config, now: float | None = None) -> Path | None:
    """Automatic backup: when the interval has passed. Returns the new file, or None when nothing was due."""
    if not is_due(cfg, now):
        return None
    dest = create_backup(paths, cfg, bool(cfg.get("backup.include_config", True)), now)
    cfg.set("backup.last", time.time() if now is None else now)
    prune(paths, int(cfg.get("backup.keep", 5) or 5))
    return dest


# --- restoring -------------------------------------------------------------------------------------------------

def check_database(path: Path) -> int:
    """SQLite's own integrity check plus a sanity look at the schema. Returns the number of items."""
    conn = sqlite3.connect(path)
    try:
        if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise BackupError("the database in the backup is damaged")
        return conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]
    except sqlite3.DatabaseError as exc:
        raise BackupError(f"not a AniHUB database: {exc}") from exc
    finally:
        conn.close()


def stage_restore(paths: LibraryPaths, backup: Path) -> int:
    """Checks the backup and schedules it: it replaces the database when AniHUB starts next. Returns its item count."""
    try:
        with zipfile.ZipFile(backup) as z, tempfile.TemporaryDirectory() as tmp:
            if DB_ENTRY not in z.namelist():
                raise BackupError("this zip is not an AniHUB backup")
            extracted = Path(tmp) / "check.db"
            with z.open(DB_ENTRY) as src, extracted.open("wb") as out:
                shutil.copyfileobj(src, out)
            items = check_database(extracted)
    except zipfile.BadZipFile as exc:
        raise BackupError("not a valid zip file") from exc
    pending = paths.db_file.parent / PENDING
    pending.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(backup, pending)
    return items


def pending_restore(paths: LibraryPaths) -> Path | None:
    p = paths.db_file.parent / PENDING
    return p if p.exists() else None


def cancel_restore(paths: LibraryPaths) -> None:
    (paths.db_file.parent / PENDING).unlink(missing_ok=True)


def apply_pending_restore(paths: LibraryPaths) -> bool:
    """Call at start-up BEFORE the database is opened. The current database is kept as anihub.db.before_restore."""
    pending = pending_restore(paths)
    if pending is None:
        return False
    try:
        with zipfile.ZipFile(pending) as z, tempfile.TemporaryDirectory() as tmp:
            staged = Path(tmp) / "restored.db"
            with z.open(DB_ENTRY) as src, staged.open("wb") as out:
                shutil.copyfileobj(src, out)
            check_database(staged)
            db = paths.db_file
            if db.exists():
                shutil.copy2(db, db.with_name(db.name + ".before_restore"))
            for extra in ("-wal", "-shm"):
                db.with_name(db.name + extra).unlink(missing_ok=True)      # leftovers of the old database must not be replayed
            shutil.copy2(staged, db)
    except (zipfile.BadZipFile, KeyError, BackupError, OSError):
        pending.rename(pending.with_name(pending.name + ".failed"))
        return False
    pending.unlink(missing_ok=True)
    return True
