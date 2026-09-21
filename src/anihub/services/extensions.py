"""Extension repositories (like Aniyomi's): a repository is a JSON index that lists source plugins; installing one downloads
a .py file into `<config>/plugins/<kind>/`, where the source loader picks it up.

Index format (`index.json`, `file` may be relative to the index):
    {"name": "My repository",
     "extensions": [{"id": "archive_org", "kind": "anime" | "novel", "name": "Internet Archive", "lang": "en",
                     "version": "1.0", "file": "archive_org.py", "sha256": "<hex of the file>", "description": "...",
                     "nsfw": false}]}

A plugin is Python code that runs with the user's rights, so nothing is installed without the SHA-256 the index promises
(a file that differs is refused) and the UI asks the user before every install.
"""
from __future__ import annotations

import ast
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin

from anihub.net.http import HttpClient, HttpError

KINDS = ("anime", "novel")
FOLDERS = {"anime": "anime", "novel": "novels"}
ID_RE = re.compile(r"^[a-z][a-z0-9_]{1,39}$")
DEFAULT_REPOS = ["https://raw.githubusercontent.com/2GMartelo/AniHUB/main/extensions/index.json"]


class ExtensionError(Exception):
    """User-presentable error."""


def version_key(version: str) -> tuple:
    return tuple(int(p) if p.isdigit() else 0 for p in re.split(r"[.\-]", str(version)))


@dataclass(frozen=True)
class ExtInfo:
    id: str
    kind: str
    name: str
    lang: str
    version: str
    url: str
    sha256: str
    description: str = ""
    nsfw: bool = False
    repo: str = ""

    @property
    def key(self) -> tuple[str, str]:
        return self.kind, self.id


def parse_index(data, index_url: str) -> list[ExtInfo]:
    """Validate an index; entries that are malformed are skipped, they never break the rest."""
    if not isinstance(data, dict) or not isinstance(data.get("extensions"), list):
        raise ExtensionError("not an extension index")
    found: list[ExtInfo] = []
    for raw in data["extensions"]:
        try:
            ext_id, kind = str(raw["id"]), str(raw["kind"])
            sha = str(raw["sha256"]).lower()
            if not ID_RE.match(ext_id) or kind not in KINDS or not re.fullmatch(r"[0-9a-f]{64}", sha):
                continue
            found.append(ExtInfo(ext_id, kind, str(raw.get("name") or ext_id), str(raw.get("lang") or "multi"),
                                 str(raw.get("version") or "1"), urljoin(index_url, str(raw["file"])), sha,
                                 str(raw.get("description") or ""), bool(raw.get("nsfw")), index_url))
        except (KeyError, TypeError):
            continue
    return found


class ExtensionManager:
    def __init__(self, http: HttpClient, cfg, plugin_root: Path):
        self.http, self.cfg, self.root = http, cfg, Path(plugin_root)

    # --- repositories ---------------------------------------------------------------------------------------

    def repos(self) -> list[str]:
        repos = self.cfg.get("extensions.repos")
        return list(DEFAULT_REPOS if repos is None else repos)

    def set_repos(self, repos: list[str]) -> None:
        self.cfg.set("extensions.repos", list(dict.fromkeys(r.strip() for r in repos if r.strip())))

    def fetch(self, repo: str) -> list[ExtInfo]:
        try:
            return parse_index(self.http.get_json(repo, interval_ms=300), repo)
        except (HttpError, ValueError) as exc:
            raise ExtensionError(f"{repo}: {exc}") from exc

    def available(self) -> tuple[list[ExtInfo], list[str]]:
        """Everything the repositories offer (the newest version of each id) and the errors of those that failed."""
        best: dict[tuple, ExtInfo] = {}
        errors: list[str] = []
        for repo in self.repos():
            try:
                for info in self.fetch(repo):
                    if info.key not in best or version_key(info.version) > version_key(best[info.key].version):
                        best[info.key] = info
            except ExtensionError as exc:
                errors.append(str(exc))
        return sorted(best.values(), key=lambda i: (i.kind, i.lang, i.name.lower())), errors

    # --- installed ------------------------------------------------------------------------------------------

    @property
    def manifest_file(self) -> Path:
        return self.root / "installed.json"

    def installed(self) -> dict[tuple[str, str], str]:
        """(kind, id) -> installed version."""
        try:
            raw = json.loads(self.manifest_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return {(k.split(":", 1)[0], k.split(":", 1)[1]): str(v) for k, v in raw.items() if ":" in k}

    def _save_manifest(self, installed: dict[tuple[str, str], str]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self.manifest_file.write_text(json.dumps({f"{k}:{i}": v for (k, i), v in installed.items()}, indent=1), encoding="utf-8")

    def file_of(self, kind: str, ext_id: str) -> Path:
        return self.root / FOLDERS[kind] / f"{ext_id}.py"

    def status(self, info: ExtInfo) -> str:
        """'new' / 'installed' / 'update'"""
        have = self.installed().get(info.key)
        if have is None or not self.file_of(info.kind, info.id).exists():
            return "new"
        return "update" if version_key(info.version) > version_key(have) else "installed"

    def install(self, info: ExtInfo) -> Path:
        try:
            data = self.http.get_bytes(info.url)
        except HttpError as exc:
            raise ExtensionError(f"{info.name}: {exc}") from exc
        if hashlib.sha256(data).hexdigest() != info.sha256:
            raise ExtensionError(f"{info.name}: the file does not match the checksum of the repository, not installed")
        try:
            ast.parse(data.decode("utf-8"))
        except (SyntaxError, UnicodeDecodeError, ValueError) as exc:
            raise ExtensionError(f"{info.name}: not a valid Python file ({exc})") from exc
        dest = self.file_of(info.kind, info.id)
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(".tmp")
        tmp.write_bytes(data)
        tmp.replace(dest)
        installed = self.installed()
        installed[info.key] = info.version
        self._save_manifest(installed)
        return dest

    def uninstall(self, kind: str, ext_id: str) -> None:
        self.file_of(kind, ext_id).unlink(missing_ok=True)
        installed = self.installed()
        installed.pop((kind, ext_id), None)
        self._save_manifest(installed)


def read_meta(path: Path) -> dict:
    """The `EXTENSION = {...}` dict at the top level of a plugin file, read without running the file (used by tools/make_index.py)."""
    tree = ast.parse(Path(path).read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", "") == "EXTENSION" for t in node.targets):
            return ast.literal_eval(node.value)
    raise ExtensionError(f"{path}: no EXTENSION = {{...}} dict")


def build_index(folder: Path, name: str = "AniHUB extensions") -> dict:
    """index.json for every plugin file of `folder` (each has an EXTENSION dict)."""
    items = []
    for file in sorted(Path(folder).glob("*.py")):
        meta = read_meta(file)
        items.append({**meta, "file": file.name, "sha256": hashlib.sha256(file.read_bytes()).hexdigest()})
    return {"name": name, "extensions": items}
