r"""Builds extensions/index.json (the repository index) from the plugin files of extensions/.

    .venv\Scripts\python tools\make_index.py [folder] [repository name]

Every plugin file starts with an `EXTENSION = {...}` dict (id, kind, name, lang, version, description); the tool adds the file
name and the SHA-256 of the file. Run it after changing a plugin and commit the index together with it.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from anihub.services.extensions import build_index  # noqa: E402

folder = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "extensions"
name = sys.argv[2] if len(sys.argv) > 2 else "AniHUB extensions"
index = build_index(folder, name)
(folder / "index.json").write_text(json.dumps(index, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print(f"{len(index['extensions'])} extension(s) -> {folder / 'index.json'}")
