"""Draws a picture for every built-in tag of the prompt builder with Forge and packs them as the pack that ships with the app.

    .venv\\Scripts\\python tools\\make_tag_pictures.py --library D:\\somewhere\\pblib --pack src\\anihub\\data\\promptbook_pack.zip

The work happens in its OWN library folder (a database with the seeded catalogue + the pictures), so it can be stopped and started again: tags
that already have a picture are skipped. Forge is started if it is not running (and stopped afterwards only if this script started it).
Quality words and negative-prompt tags are drawn too (each with its own seed, the negative ones show the flaw they keep away); only
tags like `nsfw` are left without a picture.
"""
from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from PySide6.QtGui import QGuiApplication  # noqa: E402

from anihub.core.config import Config, config_dir  # noqa: E402
from anihub.core.db import Database  # noqa: E402
from anihub.services import promptbook as pb  # noqa: E402
from anihub.services.forge import ForgeManager  # noqa: E402
from anihub.services.generation import GenParams, run_generation  # noqa: E402


def wait_for_forge(manager: ForgeManager, minutes: float) -> None:
    end = time.time() + minutes * 60
    while time.time() < end:
        if manager.ping():
            return
        if manager.proc is not None and manager.proc.poll() is not None:
            sys.exit("Forge stopped while starting; see " + str(manager.log_file))
        time.sleep(3)
    sys.exit("Forge did not answer in time")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--library", required=True, type=Path, help="working folder (database + pictures)")
    ap.add_argument("--pack", type=Path, help="write the pack zip here when done")
    ap.add_argument("--model", default="", help="part of the checkpoint name to use")
    ap.add_argument("--size", type=int, default=832)
    ap.add_argument("--steps", type=int, default=24)
    ap.add_argument("--cfg", type=float, default=5.5)
    ap.add_argument("--seed", type=int, default=12345)
    ap.add_argument("--only", default="", help="comma separated tags to draw (default: all without a picture)")
    ap.add_argument("--categories", default="", help="comma separated category keys or their beginnings, e.g. style,appearance.body")
    ap.add_argument("--redo", action="store_true", help="draw again even when there is a picture (with --only / --categories)")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    QGuiApplication.instance() or QGuiApplication([])
    args.library.mkdir(parents=True, exist_ok=True)
    db = Database(args.library / "pb.db")
    book = pb.PromptBook(db, args.library)
    book.seed()
    only = {t.strip().lower() for t in args.only.split(",") if t.strip()}
    wanted = [c.strip() for c in args.categories.split(",") if c.strip()]
    nodes = {n["id"]: n["key"] or "" for n in book.nodes()}
    for row in book.tags():                                                  # tags that are never illustrated get no picture at all
        if row["text"] in pb.NO_PICTURE_TAGS and row["image"]:
            book.clear_image(row["id"])
    todo = [t for t in book.tags() if t["text"] not in pb.NO_PICTURE_TAGS and (not t["image"] or args.redo and (only or wanted))]
    if only:
        todo = [t for t in todo if t["text"].lower() in only]
    if wanted:
        todo = [t for t in todo if any(nodes.get(t["group_id"], "").startswith(w) for w in wanted)]
    if args.limit:
        todo = todo[: args.limit]
    print(f"{len(todo)} tags to draw", flush=True)

    if todo:
        cfg = Config.load()
        manager = ForgeManager(cfg, config_dir())
        started_by_us = not manager.ping()
        manager.start()
        try:
            wait_for_forge(manager, 15)
            api = manager.api
            title = ""
            if args.model:
                title = next((m["title"] for m in api.models() if args.model.lower() in m["title"].lower()), "")
                if not title:
                    sys.exit(f"no checkpoint matches {args.model!r}")
            print("checkpoint:", title or "(Forge's current)", flush=True)
            began = time.time()
            for i, row in enumerate(todo, 1):
                node = book.node(row["group_id"]) or {}
                prompt, negative = pb.preview_prompt(row["slot"], row["text"], node.get("key") or "")
                tmp = Path(tempfile.mkdtemp(prefix="anihub_tag_"))
                try:
                    params = GenParams(prompt=prompt, negative_prompt=negative, model=title, steps=args.steps, cfg_scale=args.cfg,
                                       width=args.size, height=args.size, seed=args.seed + (row['id'] if row['slot'] in pb.VARIED_SEED_SLOTS else 0), sampler_name="Euler a")
                    results = run_generation(api, params, tmp)
                    book.set_image(row["id"], Path(results[0].path))
                    per = (time.time() - began) / i
                    print(f"[{i}/{len(todo)}] {row['slot']}/{row['text']}  ({per:.1f}s each, ~{per * (len(todo) - i) / 60:.0f} min left)", flush=True)
                except Exception as exc:  # noqa: BLE001 - one failed picture must not stop the rest
                    print(f"[{i}/{len(todo)}] FAILED {row['text']}: {exc}", flush=True)
                finally:
                    shutil.rmtree(tmp, ignore_errors=True)
        finally:
            if started_by_us:
                manager.stop()
                print("Forge stopped", flush=True)
    if args.pack:
        print("pack:", book.export_pack(args.pack), "pictures ->", args.pack, flush=True)
    db.close()


if __name__ == "__main__":
    main()
