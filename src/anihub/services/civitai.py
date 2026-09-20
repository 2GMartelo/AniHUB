"""CivitAI: search models, resolve a pasted link, download straight into the right Forge folder (ТЗ 5.2)."""
from __future__ import annotations

import hashlib
import html
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from anihub.net.http import HttpClient, HttpError

log = logging.getLogger(__name__)

API = "https://civitai.com/api/v1"
TYPES = ["Checkpoint", "LORA", "TextualInversion", "VAE"]
SORTS = ["Most Downloaded", "Highest Rated", "Newest"]
# model type -> folder inside the Forge installation, and which list Forge must rescan afterwards
TARGET_DIRS = {"Checkpoint": ("models", "Stable-diffusion"), "LORA": ("models", "Lora"), "LoCon": ("models", "Lora"),
               "DoRA": ("models", "Lora"), "TextualInversion": ("embeddings",), "VAE": ("models", "VAE"),
               "Hypernetwork": ("models", "hypernetworks")}
REFRESH_KIND = {"Checkpoint": "checkpoints", "LORA": "loras", "LoCon": "loras", "DoRA": "loras",
                "TextualInversion": "embeddings", "VAE": "vae"}


class CivitaiError(Exception):
    """User-presentable CivitAI problem."""


@dataclass
class CivitFile:
    id: int
    name: str
    size_kb: float
    sha256: str
    url: str
    primary: bool = False
    format: str = ""
    kind: str = "Model"


@dataclass
class CivitVersion:
    id: int
    name: str
    base_model: str
    files: list[CivitFile] = field(default_factory=list)
    images: list[dict] = field(default_factory=list)  # {url, nsfwLevel}
    trained_words: list[str] = field(default_factory=list)


@dataclass
class CivitModel:
    id: int
    name: str
    type: str
    creator: str
    description: str
    nsfw: bool
    downloads: int
    rating: float
    versions: list[CivitVersion] = field(default_factory=list)

    @property
    def page_url(self) -> str:
        return f"https://civitai.com/models/{self.id}"


def headers(token: str = "") -> dict[str, str]:
    h = {"User-Agent": "AniHUB", "Accept": "application/json"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def plain_text(markup: str) -> str:
    """Model descriptions are HTML from strangers: reduce them to plain text."""
    text = re.sub(r"<\s*(br|/p|/li|/h\d)\s*/?>", "\n", markup or "", flags=re.I)
    return html.unescape(re.sub(r"<[^>]+>", "", text)).strip()


def parse_model(raw: dict) -> CivitModel:
    versions = []
    for v in raw.get("modelVersions") or []:
        files = [CivitFile(id=f.get("id", 0), name=f.get("name", ""), size_kb=float(f.get("sizeKB") or 0),
                           sha256=((f.get("hashes") or {}).get("SHA256") or "").lower(),
                           url=f.get("downloadUrl") or v.get("downloadUrl") or "", primary=bool(f.get("primary")),
                           format=(f.get("metadata") or {}).get("format", ""), kind=f.get("type", "Model"))
                 for f in v.get("files") or []]
        versions.append(CivitVersion(id=v["id"], name=v.get("name", ""), base_model=v.get("baseModel", ""),
                                     files=files, images=v.get("images") or [], trained_words=v.get("trainedWords") or []))
    stats = raw.get("stats") or {}
    return CivitModel(id=raw["id"], name=raw.get("name", ""), type=raw.get("type", ""),
                      creator=(raw.get("creator") or {}).get("username", ""), description=plain_text(raw.get("description", "")),
                      nsfw=bool(raw.get("nsfw")), downloads=int(stats.get("downloadCount") or 0),
                      rating=float(stats.get("rating") or 0), versions=versions)


def parse_model_url(text: str) -> tuple[int, int | None] | None:
    """'https://civitai.com/models/12345/name?modelVersionId=678' -> (12345, 678). A bare number is a model id."""
    text = text.strip()
    if text.isdigit():
        return int(text), None
    m = re.search(r"civitai\.com/models/(\d+)", text)
    if not m:
        return None
    v = re.search(r"modelVersionId=(\d+)", text)
    return int(m.group(1)), int(v.group(1)) if v else None


def search(http: HttpClient, query: str = "", model_type: str = "Checkpoint", sort: str = "Most Downloaded",
           nsfw: bool = False, token: str = "", next_url: str | None = None, limit: int = 20) -> tuple[list[CivitModel], str | None]:
    """One page of results and the URL of the next page (None at the end)."""
    try:
        if next_url:
            data = http.get_json(next_url, headers=headers(token))
        else:
            params = {"limit": limit, "types": model_type, "sort": sort, "nsfw": "true" if nsfw else "false"}
            if query.strip():
                params["query"] = query.strip()
            data = http.get_json(f"{API}/models", params=params, headers=headers(token))
    except HttpError as exc:
        raise CivitaiError(f"CivitAI: {exc}") from exc
    if not isinstance(data, dict):
        raise CivitaiError("CivitAI: unexpected response")
    return [parse_model(m) for m in data.get("items", [])], (data.get("metadata") or {}).get("nextPage")


def get_model(http: HttpClient, model_id: int, token: str = "") -> CivitModel:
    try:
        data = http.get_json(f"{API}/models/{model_id}", headers=headers(token))
    except HttpError as exc:
        raise CivitaiError("Model not found" if exc.status == 404 else f"CivitAI: {exc}") from exc
    return parse_model(data)


def safe_filename(name: str) -> str:
    """CivitAI file names can hold characters Windows rejects (<lora:x:>.safetensors, embedding:x.safetensors)."""
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .")
    return cleaned or "model.safetensors"


def target_dir(forge_dir: Path, model_type: str) -> Path:
    parts = TARGET_DIRS.get(model_type)
    if parts is None:
        raise CivitaiError(f"Unsupported model type: {model_type}")
    return forge_dir.joinpath(*parts)


def pick_file(version: CivitVersion) -> CivitFile | None:
    """The file to install: the primary model file, safetensors preferred; pickle formats only as a last resort."""
    models = [f for f in version.files if f.kind == "Model"] or version.files
    if not models:
        return None
    ranked = sorted(models, key=lambda f: (not f.primary, "safe" not in f.format.lower(), f.size_kb))
    return ranked[0]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def download(http: HttpClient, file: CivitFile, dest_dir: Path, token: str = "",
             progress: Callable[[int, int], None] | None = None, cancelled: Callable[[], bool] | None = None) -> Path:
    """Blocking. Verifies the SHA256 when CivitAI provides one. Never overwrites a different existing file."""
    if not file.url:
        raise CivitaiError("This version has no downloadable file")
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / safe_filename(file.name)
    if dest.exists():
        if file.sha256 and sha256_file(dest) == file.sha256:
            return dest  # already installed
        raise CivitaiError(f"{dest.name} already exists in {dest_dir} (different content)")
    tmp = dest.with_name(dest.name + ".download")
    try:
        try:
            http.download(file.url, tmp, progress=progress, cancelled=cancelled, headers=headers(token))
        except HttpError as exc:
            if exc.status in (401, 403):
                raise CivitaiError("CivitAI requires a login for this file: add your API key in Settings") from exc
            raise CivitaiError(f"CivitAI download failed: {exc}") from exc
        if file.sha256 and sha256_file(tmp) != file.sha256:
            raise CivitaiError("Checksum mismatch: the download is corrupted, try again")
        tmp.replace(dest)
    finally:
        tmp.unlink(missing_ok=True)
    return dest
