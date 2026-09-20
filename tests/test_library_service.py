import os
import random
import time
from pathlib import Path

import numpy as np
import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage, QPainter

from anihub.core.config import Config
from anihub.core.db import Database
from anihub.core.paths import LibraryPaths
from anihub.library.phash import dhash, hamming, similar_groups
from anihub.library.service import LibraryService, collect_image_files
from anihub.services.autotag import Autotagger, TagResult, preprocess
from anihub.sources.base import Post


def make_image(seed: int, w: int = 96, h: int = 128) -> QImage:
    """A deterministic picture with structure (random blobs) so different seeds hash differently."""
    rnd = random.Random(seed)
    img = QImage(w, h, QImage.Format.Format_RGB32)
    img.fill(QColor(rnd.randrange(256), rnd.randrange(256), rnd.randrange(256)))
    p = QPainter(img)
    for _ in range(14):
        p.setBrush(QColor(rnd.randrange(256), rnd.randrange(256), rnd.randrange(256)))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(rnd.randrange(w), rnd.randrange(h), rnd.randrange(10, w // 2), rnd.randrange(10, h // 2))
    p.end()
    return img


def save_png(path: Path, img: QImage) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    assert img.save(str(path), "PNG")
    return path


class FileHttp:
    """download() copies a prepared file: url -> local source path."""
    def __init__(self, files: dict[str, Path]):
        self.files = files

    def download(self, url, dest, progress=None, cancelled=None):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(self.files[url].read_bytes())

    def get_bytes(self, url):
        return b""


@pytest.fixture
def lib(tmp_path):
    paths = LibraryPaths(tmp_path / "lib")
    paths.ensure()
    cfg = Config.load(tmp_path / "c.json")
    src = tmp_path / "src"
    svc = LibraryService(Database(paths.db_file), paths, FileHttp({}), cfg)
    return svc, paths, cfg, src


# --- perceptual hash ---------------------------------------------------------------------------

def test_dhash_survives_resize_but_not_a_different_picture():
    base = make_image(1, 200, 300)
    smaller = base.scaled(100, 150, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
    other = make_image(2, 200, 300)
    h1, h2, h3 = dhash(base), dhash(smaller), dhash(other)
    assert hamming(h1, h2) <= 6 < hamming(h1, h3)
    assert -(1 << 63) <= h1 < (1 << 63)            # fits a signed SQLite INTEGER
    assert dhash(QImage()) is None


def test_similar_groups_uses_chunks_and_matches_bruteforce():
    rnd = random.Random(7)
    base = [rnd.getrandbits(64) for _ in range(40)]
    rows, expected = [], set()
    for i, b in enumerate(base):
        rows.append((i, b - (1 << 64) if b >= 1 << 63 else b))
    # add near copies (flip up to 5 bits) of items 0..9
    for k in range(10):
        flipped = base[k]
        for bit in rnd.sample(range(64), rnd.randrange(1, 6)):
            flipped ^= 1 << bit
        rows.append((100 + k, flipped - (1 << 64) if flipped >= 1 << 63 else flipped))
        expected.add(frozenset((k, 100 + k)))
    groups = {frozenset(g) for g in similar_groups(rows, 6)}
    assert groups == expected
    with pytest.raises(ValueError):
        similar_groups(rows, 8)


# --- trash ---------------------------------------------------------------------------------------

def add_file_item(svc, paths, name="a.png", seed=1):
    path = save_png(paths.arts / "x" / name, make_image(seed))
    return svc.db.add_item(kind="art", path=path.relative_to(paths.root).as_posix(), ext="png", rating="general",
                           source_site="s", source_post_id=name, tags=[("cat", "general")]), path


def test_trash_restore_purge_cycle(lib):
    svc, paths, cfg, _ = lib
    item_id, path = add_file_item(svc, paths)
    thumb = paths.thumbs / f"{item_id}_180.jpg"
    thumb.write_bytes(b"t")
    assert svc.trash([item_id]) == 1
    assert not path.exists() and (paths.trash / f"{item_id}.png").exists()   # moved, not deleted
    assert svc.db.count_items() == 0 and svc.db.count_search(trashed=True) == 1
    assert svc.trash([item_id]) == 0                                          # already there
    assert svc.restore([item_id]) == 1
    assert path.exists() and svc.db.count_items() == 1
    svc.trash([item_id])
    assert svc.purge([item_id]) == 1
    assert not (paths.trash / f"{item_id}.png").exists() and not thumb.exists()
    assert svc.db.get_item(item_id) is None


def test_purge_of_live_item_removes_its_file_too(lib):
    svc, paths, *_ = lib
    item_id, path = add_file_item(svc, paths)
    svc.purge([item_id])
    assert not path.exists() and svc.db.get_item(item_id) is None


def test_auto_purge_only_after_the_grace_period(lib):
    svc, paths, *_ = lib
    old_id, _ = add_file_item(svc, paths, "old.png", 1)
    new_id, _ = add_file_item(svc, paths, "new.png", 2)
    svc.trash([old_id, new_id])
    svc.db.update_fields(old_id, trashed_at=time.time() - 8 * 86400)          # trashed 8 days ago
    assert svc.auto_purge(7) == 1
    assert svc.db.get_item(old_id) is None and svc.db.get_item(new_id) is not None
    assert svc.auto_purge(0) == 0                                              # 0 days = feature off


def test_empty_trash(lib):
    svc, paths, *_ = lib
    ids = [add_file_item(svc, paths, f"{i}.png", i)[0] for i in range(3)]
    svc.trash(ids[:2])
    assert svc.empty_trash() == 2 and svc.db.count_items() == 1


def test_saving_something_trashed_restores_it(lib, tmp_path):
    svc, paths, *_ = lib
    item_id, _ = add_file_item(svc, paths)
    svc.trash([item_id])
    post = Post("s", "a.png", "u", "p", ext="png")
    res = svc.save_post(post)
    assert res.status == "saved" and res.item_id == item_id and svc.db.count_items() == 1


# --- saving with dedup -----------------------------------------------------------------------------

def test_save_post_sets_hash_default_category_and_reports_near_duplicates(lib, tmp_path):
    svc, paths, cfg, src = lib
    base = make_image(3, 200, 300)
    near = base.scaled(120, 180, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
    files = {"u1": save_png(src / "1.png", base), "u2": save_png(src / "2.png", near)}
    svc.http = FileHttp(files)
    cat = svc.db.create_category("Inbox")
    svc.db.set_default_category(cat)
    first = svc.save_post(Post("s", "1", "u1", "p", ext="png", tags=[("cat", "general")]))
    assert first.status == "saved" and svc.db.get_item(first.item_id)["phash"] is not None
    assert svc.db.item_category_ids(first.item_id) == {cat}                    # default category applied
    second = svc.save_post(Post("s", "2", "u2", "p", ext="png"))
    assert second.status == "saved" and second.similar == [first.item_id]      # warn mode: saved, but flagged
    cfg.set("library.near_dedup", "skip", save=False)
    files["u3"] = save_png(src / "3.png", base.scaled(150, 225))
    third = svc.save_post(Post("s", "3", "u3", "p", ext="png"))
    assert third.status == "duplicate" and not (paths.arts / "s" / "s_3.png").exists()
    cfg.set("library.near_dedup", "off", save=False)
    files["u4"] = save_png(src / "4.png", base.scaled(160, 240))
    assert svc.save_post(Post("s", "4", "u4", "p", ext="png")).similar == []


def test_save_posts_counts_similar(lib):
    svc, paths, cfg, src = lib
    base = make_image(4, 200, 300)
    svc.http = FileHttp({"a": save_png(src / "a.png", base), "b": save_png(src / "b.png", base.scaled(100, 150))})
    counts = svc.save_posts([Post("s", "a", "a", "p", ext="png"), Post("s", "b", "b", "p", ext="png")])
    assert counts["saved"] == 2 and counts["similar"] == 1


# --- import -----------------------------------------------------------------------------------------------

class FakeTagger:
    def tag_file(self, path):
        return TagResult([("1girl", "general"), ("miku", "character")], "sensitive")


def test_collect_image_files_walks_folders_and_filters(tmp_path):
    save_png(tmp_path / "a" / "1.png", make_image(1))
    save_png(tmp_path / "a" / "b" / "2.png", make_image(2))
    (tmp_path / "a" / "notes.txt").write_text("x")
    assert [p.name for p in collect_image_files([tmp_path / "a"])] == ["1.png", "2.png"]
    assert collect_image_files([tmp_path / "a" / "notes.txt"]) == []


def test_import_copies_dedups_tags_and_categorises(lib, tmp_path):
    svc, paths, cfg, src = lib
    a = save_png(src / "one.png", make_image(10))
    b = save_png(src / "two.png", make_image(11))
    same_as_a = save_png(src / "sub" / "copy.png", make_image(10))     # byte-identical content
    svc.tagger = FakeTagger()
    cat = svc.db.create_category("Imported")
    progress = []
    counts = svc.import_files(collect_image_files([src]), category_id=cat, progress=lambda d, t: progress.append((d, t)))
    assert counts["saved"] == 2 and counts["duplicate"] == 1 and counts["failed"] == 0
    assert progress[-1] == (3, 3)
    rows = svc.db.search_items()
    assert len(rows) == 2 and all(r["source_site"] == "local" and r["rating"] == "sensitive" for r in rows)
    assert all((paths.root / r["path"]).exists() for r in rows)               # copied into the library
    assert a.exists()                                                          # originals are untouched
    assert svc.db.item_tags(rows[0]["id"]) == ["1girl", "miku"]
    assert svc.db.item_category_ids(rows[0]["id"]) == {cat}


def test_import_without_tagger_uses_chosen_rating_and_skips_broken_files(lib, tmp_path):
    svc, paths, cfg, src = lib
    good = save_png(src / "ok.png", make_image(20))
    bad = src / "broken.png"
    bad.write_bytes(b"not an image")
    counts = svc.import_files([good, bad], rating="explicit")
    assert counts["saved"] == 1 and counts["failed"] == 1
    assert svc.db.search_items(ratings=["explicit"])[0]["source_site"] == "local"


def test_import_can_be_cancelled(lib):
    svc, paths, cfg, src = lib
    files = [save_png(src / f"{i}.png", make_image(30 + i)) for i in range(4)]
    stop = {"n": 0}

    def cancelled():
        stop["n"] += 1
        return stop["n"] > 2

    counts = svc.import_files(files, cancelled=cancelled)
    assert counts["saved"] == 2 and counts["cancelled"] == 2


def test_duplicate_groups_backfill_and_sort_by_size(lib):
    svc, paths, cfg, src = lib
    base = make_image(40, 200, 300)
    big = save_png(paths.arts / "big.png", base)
    small = save_png(paths.arts / "small.png", base.scaled(80, 120))
    other = save_png(paths.arts / "other.png", make_image(41, 200, 300))
    for p in (big, small, other):
        svc.db.add_item(kind="art", path=p.relative_to(paths.root).as_posix(), ext="png", size=p.stat().st_size)
    groups = svc.duplicate_groups()
    assert len(groups) == 1 and [r["path"].split("/")[-1] for r in groups[0]] == ["big.png", "small.png"]


def test_autotag_items_adds_tags_and_optionally_rating(lib):
    svc, paths, *_ = lib
    item_id, _ = add_file_item(svc, paths)
    assert svc.autotag_items([item_id]) == 0                    # no tagger configured
    svc.tagger = FakeTagger()
    assert svc.autotag_items([item_id], set_rating=True) == 1
    assert set(svc.db.item_tags(item_id)) == {"cat", "1girl", "miku"}
    assert svc.db.get_item(item_id)["rating"] == "sensitive"


# --- autotagger internals ---------------------------------------------------------------------------

def test_preprocess_letterboxes_on_white_and_swaps_to_bgr():
    img = QImage(100, 50, QImage.Format.Format_RGB32)
    img.fill(QColor(255, 0, 0))                                  # pure red, wide picture
    arr = preprocess(img, 64)
    assert arr.shape == (1, 64, 64, 3) and arr.dtype == np.float32
    assert list(arr[0, 32, 32]) == [0.0, 0.0, 255.0]             # centre: red as BGR
    assert list(arr[0, 0, 0]) == [255.0, 255.0, 255.0]           # padding is white


def test_interpret_thresholds_ratings_and_ordering(tmp_path):
    t = Autotagger(tmp_path)
    t._tags = [("general", 9), ("sensitive", 9), ("questionable", 9), ("explicit", 9),
               ("1girl", 0), ("solo", 0), ("hatsune_miku", 4), ("some_char", 4), ("rare", 0)]
    probs = [0.1, 0.6, 0.2, 0.05, 0.99, 0.5, 0.9, 0.5, 0.2]
    r = t.interpret(probs)
    assert r.rating == "sensitive"
    assert r.tags == [("1girl", "general"), ("hatsune_miku", "character"), ("solo", "general")]  # by confidence
    assert not t.available


def test_model_availability_needs_both_files(tmp_path):
    t = Autotagger(tmp_path)
    (tmp_path / "model.onnx").write_bytes(b"x")
    assert not t.available
    (tmp_path / "selected_tags.csv").write_text("x")
    assert t.available
