import json
import zipfile
from pathlib import Path

import pytest

from anihub.core.config import Config
from anihub.core.db import Database
from anihub.core.paths import LibraryPaths
from anihub.library.service import LibraryService
from anihub.services import export
from anihub.services.export import ExportError
from tests.test_library_service import FileHttp, make_image, save_png


def make_lib(tmp_path, name="lib"):
    paths = LibraryPaths(tmp_path / name)
    paths.ensure()
    cfg = Config.load(tmp_path / f"{name}.json")
    db = Database(paths.db_file)
    return LibraryService(db, paths, FileHttp({}), cfg), db, paths


def add(db, paths, name, seed, **kw):
    f = save_png(paths.arts / "site" / f"{name}.png", make_image(seed))
    return db.add_item(kind="art", path=f.relative_to(paths.root).as_posix(), ext="png", **kw)


def test_pack_roundtrip_keeps_files_tags_and_metadata(tmp_path):
    lib_a, db_a, paths_a = make_lib(tmp_path, "a")
    one = add(db_a, paths_a, "one", 1, author="artistA", rating="sensitive", source_url="https://s/1", page_url="https://p/1",
              tags=[("cat", "general"), ("miku", "artist")], sha256="x1")
    two = add(db_a, paths_a, "two", 2, tags=[("dog", "general")], sha256="x2")
    db_a.set_field([one], "stars", 5)
    db_a.set_field([one], "favorite", 1)
    trashed = add(db_a, paths_a, "gone", 3, sha256="x3")
    db_a.update_fields(trashed, trashed_at=1.0)
    pack = tmp_path / "pack.zip"
    seen = []
    assert export.export_pack(db_a, paths_a, [one, two, trashed], pack, "My pack", lambda d, t: seen.append((d, t))) == 2
    with zipfile.ZipFile(pack) as z:
        meta = json.loads(z.read("pack.json"))
        assert meta["name"] == "My pack" and len(meta["items"]) == 2 and all(i["file"] in z.namelist() for i in meta["items"])
    assert seen[-1] == (2, 2)

    lib_b, db_b, paths_b = make_lib(tmp_path, "b")
    result = export.import_pack(db_b, lib_b, pack)
    assert (result["name"], result["saved"], result["duplicate"], result["failed"]) == ("My pack", 2, 0, 0)
    items = {r["author"] or "": r for r in db_b.search_items(limit=10, ratings=["general", "sensitive"])}
    got = items["artistA"]
    assert got["rating"] == "sensitive" and got["stars"] == 5 and got["favorite"] == 1 and got["source_url"] == "https://s/1"
    assert set(db_b.item_tags(got["id"])) == {"cat", "miku"} and (paths_b.root / got["path"]).is_file()
    assert [r["id"] for r in db_b.search_items(collection_id=result["collection_id"], limit=10)] and \
        len(db_b.search_items(collection_id=result["collection_id"], limit=10)) == 2
    again = export.import_pack(db_b, lib_b, pack)                                    # same pack again: nothing new, same collection
    assert (again["saved"], again["duplicate"]) == (0, 2) and again["collection_id"] == result["collection_id"]
    assert db_b.count_items() == 2


def test_import_rejects_foreign_or_unsafe_packs(tmp_path):
    lib, db, paths = make_lib(tmp_path)
    junk = tmp_path / "junk.zip"
    junk.write_bytes(b"nope")
    with pytest.raises(ExportError):
        export.import_pack(db, lib, junk)
    other = tmp_path / "other.zip"
    with zipfile.ZipFile(other, "w") as z:
        z.writestr("readme.txt", "hi")
    with pytest.raises(ExportError):
        export.import_pack(db, lib, other)
    future = tmp_path / "future.zip"
    with zipfile.ZipFile(future, "w") as z:
        z.writestr("pack.json", json.dumps({"format": 99, "items": []}))
    with pytest.raises(ExportError, match="unsupported"):
        export.import_pack(db, lib, future)
    evil = tmp_path / "evil.zip"
    with zipfile.ZipFile(evil, "w") as z:
        z.writestr("pack.json", json.dumps({"format": 1, "name": "e", "items": [{"file": "../../outside.png"}, {"file": "missing.png"}]}))
        z.writestr("../../outside.png", b"x")
    result = export.import_pack(db, lib, evil)
    assert result["saved"] == 0 and result["failed"] == 2                            # both refused, nothing written outside
    assert not (tmp_path / "outside.png").exists() and db.count_items() == 0


def test_nothing_to_export_is_an_error(tmp_path):
    lib, db, paths = make_lib(tmp_path)
    gone = db.add_item(kind="art", path="arts/missing.png", ext="png")
    with pytest.raises(ExportError):
        export.export_pack(db, paths, [gone], tmp_path / "x.zip", "n")
    with pytest.raises(ExportError):
        export.export_pack(db, paths, [], tmp_path / "x.zip", "n")


def test_html_gallery_has_page_thumbs_and_escaped_text(qapp, tmp_path):
    lib, db, paths = make_lib(tmp_path)
    a = add(db, paths, "a", 1, tags=[("cat", "general"), ("<script>", "general")])
    b = add(db, paths, "b", 2)
    video = paths.arts / "site" / "v.mp4"
    video.write_bytes(b"not a picture")
    v = db.add_item(kind="art", path=video.relative_to(paths.root).as_posix(), ext="mp4")
    out = tmp_path / "gallery.zip"
    assert export.export_html(db, paths, [a, b, v], out, "Cats & <Dogs>") == 2               # the video is left out
    with zipfile.ZipFile(out) as z:
        names = z.namelist()
        page = z.read("index.html").decode("utf-8")
        assert sum(n.startswith("images/") for n in names) == 2 and sum(n.startswith("thumbs/") for n in names) == 2
        assert all(z.read(n)[:2] == b"\xff\xd8" for n in names if n.startswith("thumbs/"))     # JPEG previews
    assert "Cats &amp; &lt;Dogs&gt;" in page and "<script>alert" not in page and "&lt;script&gt;" in page
    assert page.count('<a href="images/') == 2 and "2 pictures" in page
    with pytest.raises(ExportError):
        export.export_html(db, paths, [v], tmp_path / "v.zip", "t")


def test_library_menu_entries_export_and_import(qapp, tmp_path, monkeypatch):
    """The two file dialogs are answered by the test; the worker threads do the real work."""
    import time
    from types import SimpleNamespace

    from PySide6.QtWidgets import QFileDialog

    from anihub.ui import library_view

    lib, db, paths = make_lib(tmp_path)
    one = add(db, paths, "one", 1, tags=[("cat", "general")], sha256="q1")
    ctx = SimpleNamespace(db=db, paths=paths, library=lib, cfg=lib.cfg)
    stub = SimpleNamespace(status=SimpleNamespace(setText=lambda t: texts.append(t)), ctx=ctx, kind="art",
                           refresh_sidebar=lambda: None, reload=lambda: None, changed=SimpleNamespace(emit=lambda: None))
    texts: list[str] = []
    target = tmp_path / "out.zip"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(target), "")))
    library_view.LibraryView._export(stub, [one], "pack", "Named")
    end = time.time() + 5
    while time.time() < end and not target.exists():
        qapp.processEvents()
        time.sleep(0.01)
    while time.time() < end and not any("1" in t and "out.zip" in t for t in texts):
        qapp.processEvents()
        time.sleep(0.01)
    assert target.exists() and any("out.zip" in t for t in texts)
    lib2, db2, paths2 = make_lib(tmp_path, "b")
    ctx2 = SimpleNamespace(db=db2, paths=paths2, library=lib2, cfg=lib2.cfg)
    stub2 = SimpleNamespace(status=SimpleNamespace(setText=lambda t: texts.append(t)), ctx=ctx2, kind="art",
                            refresh_sidebar=lambda: None, reload=lambda: None, changed=SimpleNamespace(emit=lambda: None))
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(target), "")))
    library_view.LibraryView._import_pack(stub2)
    while time.time() < end and db2.count_items() == 0:
        qapp.processEvents()
        time.sleep(0.01)
    assert db2.count_items() == 1
