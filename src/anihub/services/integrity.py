"""Library integrity check (раздел 9 / п. 6.17): the database itself, records whose file is gone, files nobody knows about,
and (optionally) files whose content no longer matches the recorded hash."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from anihub.core.db import Database
from anihub.core.paths import LibraryPaths
from anihub.services.pausing import wait_while_paused

# folders whose files must all be known to the database (sd/generated is a scratch folder: only chosen pictures get records)
ITEM_FOLDERS = ("arts",)
IGNORED_SUFFIXES = (".part", ".tmp")


@dataclass
class Problem:
    kind: str                     # missing | damaged | orphan
    path: str
    item_id: int | None = None


@dataclass
class Report:
    db_ok: bool = True
    db_message: str = "ok"
    checked: int = 0
    problems: list[Problem] = field(default_factory=list)

    def of(self, kind: str) -> list[Problem]:
        return [p for p in self.problems if p.kind == kind]

    @property
    def clean(self) -> bool:
        return self.db_ok and not self.problems


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def check_library(db: Database, paths: LibraryPaths, verify_hashes: bool = False,
                  progress: Callable[[int, int], None] | None = None,
                  cancelled: Callable[[], bool] | None = None,
                  paused: Callable[[], bool] | None = None) -> Report:
    report = Report()
    result = db.conn.execute("PRAGMA integrity_check").fetchone()[0]
    report.db_ok, report.db_message = result == "ok", str(result)

    rows = db.conn.execute("SELECT id, path, trashed_at, trash_path, sha256, kind FROM items").fetchall()
    known: set[str] = set()
    for i, row in enumerate(rows, 1):
        wait_while_paused(paused, cancelled)
        if cancelled and cancelled():
            break
        rel = row["trash_path"] if row["trashed_at"] and row["trash_path"] else row["path"]
        known.add(Path(row["path"]).as_posix())
        file = paths.root / rel
        report.checked += 1
        if not file.is_file():
            report.problems.append(Problem("missing", rel, row["id"]))
        elif verify_hashes and row["sha256"] and row["kind"] != "manga" and _sha256(file) != row["sha256"]:
            report.problems.append(Problem("damaged", rel, row["id"]))
        if progress and i % 50 == 0:
            progress(i, len(rows))

    for folder in ITEM_FOLDERS:
        root = paths.root / folder
        if not root.is_dir():
            continue
        for f in root.rglob("*"):
            if cancelled and cancelled():
                break
            if f.is_file() and not f.name.endswith(IGNORED_SUFFIXES):
                rel = f.relative_to(paths.root).as_posix()
                if rel not in known:
                    report.problems.append(Problem("orphan", rel))
    if progress:
        progress(len(rows), len(rows))
    return report


def remove_missing(db: Database, item_ids: list[int]) -> int:
    """Forget records whose file is gone (tags and collection links go with them). Returns how many were removed."""
    if not item_ids:
        return 0
    db.delete_items(item_ids)
    return len(item_ids)


def optimize(db: Database) -> None:
    """Statistics for the query planner, WAL folded back into the main file, free pages returned to the disk."""
    conn = db.conn
    conn.execute("ANALYZE")
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.execute("VACUUM")
