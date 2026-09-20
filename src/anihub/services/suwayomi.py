"""Suwayomi-Server (Tachidesk): local backend process + GraphQL client.

It runs Tachiyomi extensions for us: the app only talks to its API. The server is started on demand from the
JRE bundled in the Suwayomi build, bound to 127.0.0.1, with its web UI disabled.
"""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
from pathlib import Path

import httpx

from anihub.core.config import Config
from anihub.services.procservice import NO_WINDOW, NEW_GROUP, ManagedProcess, ServiceState
from anihub.services.suwayomi_install import find_runtime, installed_version

log = logging.getLogger(__name__)

DEFAULT_STORE = "https://raw.githubusercontent.com/keiyoushi/extensions/repo/index.min.json"


class SuwayomiError(Exception):
    """User-presentable Suwayomi problem."""


# --- server.conf -------------------------------------------------------------------------------------------

def set_conf_values(text: str, values: dict[str, str]) -> str:
    """Set `key = value` lines in a HOCON server.conf, keeping trailing comments; append keys that are missing."""
    for key, value in values.items():
        pattern = re.compile(rf"^({re.escape(key)}\s*=\s*)[^#\r\n]*?(\s*(?:#.*)?)$", re.M)
        if pattern.search(text):
            text = pattern.sub(lambda m: f"{m.group(1)}{value}{m.group(2) or ''}", text, count=1)
        else:
            text = text.rstrip("\n") + f"\n{key} = {value}\n"
    return text


def conf_values(cfg: Config, download_as_cbz: bool = True) -> dict[str, str]:
    values = {
        "server.ip": '"127.0.0.1"',                 # never expose the server to the network
        "server.port": str(int(cfg.get("manga.port", 4567))),
        "server.webUIEnabled": "false",             # AniHUB is the UI
        "server.initialOpenInBrowserEnabled": "false",
        "server.systemTrayEnabled": "false",
        "server.downloadAsCbz": "true" if download_as_cbz else "false",
    }
    proxy = str(cfg.get("network.proxy") or "")
    m = re.match(r"^socks(?:4|5)h?://(?:(?P<user>[^:@]*):?(?P<pw>[^@]*)@)?(?P<host>[^:/]+):(?P<port>\d+)", proxy)
    if m:  # Suwayomi only supports SOCKS for its outgoing (source) traffic
        values.update({
            "server.socksProxyEnabled": "true",
            "server.socksProxyVersion": "4" if proxy.startswith("socks4") else "5",
            "server.socksProxyHost": f'"{m.group("host")}"',
            "server.socksProxyPort": f'"{m.group("port")}"',
            "server.socksProxyUsername": f'"{m.group("user") or ""}"',
            "server.socksProxyPassword": f'"{m.group("pw") or ""}"',
        })
    else:
        values["server.socksProxyEnabled"] = "false"
    return values


# --- process -----------------------------------------------------------------------------------------------

class SuwayomiManager(ManagedProcess):
    def __init__(self, cfg: Config, install_dir: Path, data_dir: Path, log_dir: Path):
        super().__init__()
        self.cfg = cfg
        self.install_dir = install_dir  # %APPDATA%/AniHUB/suwayomi (server binaries + bundled JRE)
        self.data_dir = data_dir        # <library>/manga/suwayomi (database, extensions, downloads)
        self.log_file = log_dir / "suwayomi.log"
        self.api = SuwayomiApi(cfg)

    @property
    def server_dir(self) -> Path:
        return self.install_dir / "server"

    def installed(self) -> str | None:
        return installed_version(self.install_dir) if find_runtime(self.server_dir) else None

    def ping(self) -> bool:
        return self.api.ping()

    def write_conf(self) -> None:
        conf = self.data_dir / "server.conf"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        text = conf.read_text(encoding="utf-8") if conf.exists() else ""
        conf.write_text(set_conf_values(text, conf_values(self.cfg)), encoding="utf-8")

    def _spawn(self) -> subprocess.Popen:
        runtime = find_runtime(self.server_dir)
        if runtime is None:
            raise SuwayomiError("Suwayomi is not installed")
        java, jar = runtime
        self.write_conf()
        cmd = [str(java), f"-Dsuwayomi.tachidesk.config.server.rootDir={self.data_dir}",
               "-jar", str(jar)]
        env = {**os.environ, "PYTHONUTF8": "1"}
        return subprocess.Popen(cmd, cwd=jar.parent.parent, stdin=subprocess.DEVNULL, stdout=self._open_log(),
                                stderr=subprocess.STDOUT, env=env, creationflags=NO_WINDOW | NEW_GROUP)


# --- API ---------------------------------------------------------------------------------------------------

MANGA_FIELDS = ("id title thumbnailUrl inLibrary unreadCount downloadCount sourceId status author artist "
                "description genre url realUrl initialized")
CHAPTER_FIELDS = ("id name chapterNumber scanlator uploadDate isRead isBookmarked isDownloaded lastPageRead "
                  "pageCount sourceOrder mangaId")
EXTENSION_FIELDS = ("pkgName name lang versionName isInstalled hasUpdate isObsolete iconUrl apkUrl contentWarning "
                    "source { nodes { id displayName lang } }")
SOURCE_FIELDS = "id displayName lang name supportsLatest iconUrl isConfigurable extension { pkgName contentWarning }"
CATEGORY_FIELDS = "id name order default"

# Every filter/preference type reports its value under `default` / `currentValue` with a different GraphQL type,
# so each one needs its own alias.
_FILTER_LEAF = ("__typename ... on HeaderFilter { name } ... on SeparatorFilter { name } "
                "... on SelectFilter { name values selDef: default } ... on TextFilter { name txtDef: default } "
                "... on CheckBoxFilter { name boolDef: default } ... on TriStateFilter { name triDef: default } "
                "... on SortFilter { name values sortDef: default { ascending index } }")
FILTERS_QUERY = ("query($id:LongString!){ source(id:$id){ filters { %s ... on GroupFilter { name filters { %s } } } } }"
                 % (_FILTER_LEAF, _FILTER_LEAF))
PREFERENCES_QUERY = ("query($id:LongString!){ source(id:$id){ preferences { __typename "
                     "... on EditTextPreference { key title summary text dialogTitle textValue: currentValue } "
                     "... on SwitchPreference { key title summary switchValue: currentValue } "
                     "... on CheckBoxPreference { key title summary checkValue: currentValue } "
                     "... on ListPreference { key title summary entries entryValues listValue: currentValue } "
                     "... on MultiSelectListPreference { key title summary entries entryValues multiValue: currentValue } "
                     "} } }")

_FILTER_KINDS = {"HeaderFilter": "header", "SeparatorFilter": "separator", "SelectFilter": "select", "TextFilter": "text",
                 "CheckBoxFilter": "checkbox", "TriStateFilter": "tristate", "SortFilter": "sort", "GroupFilter": "group"}
_PREF_KINDS = {"EditTextPreference": ("text", "textValue", "editTextState"),
               "SwitchPreference": ("switch", "switchValue", "switchState"),
               "CheckBoxPreference": ("check", "checkValue", "checkBoxState"),
               "ListPreference": ("list", "listValue", "listState"),
               "MultiSelectListPreference": ("multi", "multiValue", "multiSelectState")}
# where the value lives in FilterChangeInput, per filter kind
_CHANGE_FIELD = {"select": "selectState", "text": "textState", "checkbox": "checkBoxState", "tristate": "triState",
                 "sort": "sortState"}


def _normalize_filter(raw: dict, position: int) -> dict:
    kind = _FILTER_KINDS.get(raw.get("__typename"), "header")
    node = {"kind": kind, "name": raw.get("name") or "", "pos": position, "values": raw.get("values") or []}
    default = {"select": "selDef", "text": "txtDef", "checkbox": "boolDef", "tristate": "triDef", "sort": "sortDef"}.get(kind)
    node["default"] = raw.get(default) if default else None
    if kind == "group":
        node["children"] = [_normalize_filter(c, i) for i, c in enumerate(raw.get("filters") or [])]
    return node


def filter_changes(filters: list[dict], state: dict[tuple[int, ...], object]) -> list[dict]:
    """GraphQL FilterChangeInput list for the values the user changed. `state` maps a filter's position path
    (e.g. (2,) or (2, 5) for a member of group 2) to its value; entries equal to the default are skipped."""
    changes: list[dict] = []
    for node in filters:
        if node["kind"] == "group":
            for child in node["children"]:
                value = state.get((node["pos"], child["pos"]), child["default"])
                field = _CHANGE_FIELD.get(child["kind"])
                if field and value != child["default"]:
                    changes.append({"position": node["pos"], "groupChange": {"position": child["pos"], field: value}})
            continue
        value = state.get((node["pos"],), node["default"])
        field = _CHANGE_FIELD.get(node["kind"])
        if field and value != node["default"]:
            changes.append({"position": node["pos"], field: value})
    return changes


def normalize_preference(raw: dict, position: int) -> dict | None:
    """One flat dict per source preference: kind, key, title, summary, value, options (entries/values) and the
    GraphQL field that changes it. Returns None for kinds we cannot edit."""
    spec = _PREF_KINDS.get(raw.get("__typename"))
    if spec is None:
        return None
    kind, value_key, change_field = spec
    return {"kind": kind, "pos": position, "key": raw.get("key") or "", "title": raw.get("title") or raw.get("key") or "",
            "summary": raw.get("summary") or "", "value": raw.get(value_key), "field": change_field,
            "entries": raw.get("entries") or [], "entry_values": raw.get("entryValues") or []}


class SuwayomiApi:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self._client = httpx.Client(trust_env=False, timeout=httpx.Timeout(60.0, connect=3.0))

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{int(self.cfg.get('manga.port', 4567))}"

    # -- transport

    def gql(self, query: str, variables: dict | None = None, timeout: float | None = None) -> dict:
        try:
            resp = self._client.post(self.base_url + "/api/graphql", json={"query": query, "variables": variables or {}},
                                     timeout=timeout if timeout is not None else httpx.USE_CLIENT_DEFAULT)
        except httpx.TransportError as exc:
            raise SuwayomiError("Suwayomi is not responding") from exc
        try:
            body = resp.json()
        except ValueError as exc:
            raise SuwayomiError(f"Suwayomi HTTP {resp.status_code}") from exc
        if body.get("errors"):
            raise SuwayomiError("; ".join(e.get("message", "?") for e in body["errors"])[:400])
        return body["data"]

    def fetch_bytes(self, path: str) -> bytes:
        """Cover / page image. `path` is what the server returned (relative to the API root, or absolute)."""
        url = path if path.startswith("http") else self.base_url + (path if path.startswith("/") else "/" + path)
        try:
            resp = self._client.get(url, timeout=httpx.Timeout(120.0, connect=3.0))
        except httpx.TransportError as exc:
            raise SuwayomiError("Suwayomi is not responding") from exc
        if resp.status_code >= 400:
            raise SuwayomiError(f"Suwayomi HTTP {resp.status_code} for {path}")
        return resp.content

    def ping(self) -> bool:
        try:
            self._client.post(self.base_url + "/api/graphql", json={"query": "{ aboutServer { version } }"},
                              timeout=httpx.Timeout(2.0, connect=1.0)).raise_for_status()
            return True
        except (httpx.HTTPError, OSError):
            return False

    def about(self) -> dict:
        return self.gql("{ aboutServer { name version buildType } }")["aboutServer"]

    # -- extensions

    def stores(self) -> list[dict]:
        return self.gql("{ extensionStores { nodes { indexUrl name } } }")["extensionStores"]["nodes"]

    def add_store(self, index_url: str) -> None:
        self.gql("mutation($u:String!){ addExtensionStore(input:{indexUrl:$u}){ clientMutationId } }", {"u": index_url})

    def remove_store(self, index_url: str) -> None:
        self.gql("mutation($u:String!){ removeExtensionStore(input:{indexUrl:$u}){ clientMutationId } }", {"u": index_url})

    def ensure_default_store(self) -> bool:
        """Adds the default extension index on first use. Returns True if it had to be added."""
        if self.stores():
            return False
        self.add_store(DEFAULT_STORE)
        return True

    def refresh_extensions(self) -> list[dict]:
        """Re-download the extension catalogue from the stores, then return it."""
        self.gql("mutation{ fetchExtensions(input:{}){ clientMutationId } }", timeout=180)
        return self.extensions()

    def extensions(self) -> list[dict]:
        return self.gql("{ extensions(order:[{by:NAME}]) { nodes { %s } } }" % EXTENSION_FIELDS)["extensions"]["nodes"]

    def set_extension(self, pkg: str, action: str) -> None:
        """action: install | uninstall | update"""
        if action not in ("install", "uninstall", "update"):
            raise ValueError(action)
        self.gql("mutation($id:String!,$p:UpdateExtensionPatchInput!){ updateExtension(input:{id:$id, patch:$p})"
                 "{ clientMutationId } }", {"id": pkg, "p": {action: True}}, timeout=300)

    def install_external(self, path: Path) -> None:
        """Manual installation from an .apk file (GraphQL multipart upload)."""
        query = "mutation($f:Upload!){ installExternalExtension(input:{extensionFile:$f}){ clientMutationId } }"
        with path.open("rb") as fh:
            files = {"operations": (None, json.dumps({"query": query, "variables": {"f": None}})),
                     "map": (None, json.dumps({"0": ["variables.f"]})),
                     "0": (path.name, fh, "application/vnd.android.package-archive")}
            try:
                resp = self._client.post(self.base_url + "/api/graphql", files=files, timeout=httpx.Timeout(300.0, connect=3.0))
            except httpx.TransportError as exc:
                raise SuwayomiError("Suwayomi is not responding") from exc
        body = resp.json()
        if body.get("errors"):
            raise SuwayomiError("; ".join(e.get("message", "?") for e in body["errors"])[:400])

    # -- sources / browsing

    def sources(self) -> list[dict]:
        return self.gql("{ sources { nodes { %s } } }" % SOURCE_FIELDS)["sources"]["nodes"]

    def browse(self, source_id: str, kind: str, page: int, query: str = "",
               filters: list[dict] | None = None) -> tuple[list[dict], bool]:
        """kind: POPULAR | LATEST | SEARCH. `filters` = filter_changes(...) (only used for SEARCH).
        Returns (mangas, has_next_page)."""
        data = self.gql(
            "mutation($s:LongString!,$t:FetchSourceMangaType!,$p:Int!,$q:String,$f:[FilterChangeInput!]){ "
            "fetchSourceManga(input:{source:$s,type:$t,page:$p,query:$q,filters:$f}){ hasNextPage mangas { %s } } }"
            % MANGA_FIELDS,
            {"s": source_id, "t": kind, "p": page, "q": query or None, "f": filters or None}, timeout=120)["fetchSourceManga"]
        return data["mangas"], data["hasNextPage"]

    def source_filters(self, source_id: str) -> list[dict]:
        """The source's search filters (genres, tags, status, sort...) as normalized nodes."""
        raw = self.gql(FILTERS_QUERY, {"id": source_id})["source"]["filters"] or []
        return [_normalize_filter(f, i) for i, f in enumerate(raw)]

    def source_preferences(self, source_id: str) -> list[dict]:
        """Source settings (login, quality, mirrors...) as flat dicts; unsupported kinds are dropped."""
        raw = self.gql(PREFERENCES_QUERY, {"id": source_id})["source"]["preferences"] or []
        return [p for p in (normalize_preference(r, i) for i, r in enumerate(raw)) if p]

    def set_source_preference(self, source_id: str, pref: dict, value) -> None:
        self.gql("mutation($s:LongString!,$c:SourcePreferenceChangeInput!){ updateSourcePreference("
                 "input:{source:$s,change:$c}){ clientMutationId } }",
                 {"s": source_id, "c": {"position": pref["pos"], pref["field"]: value}})

    # -- manga / chapters

    def manga(self, manga_id: int) -> dict:
        return self.gql("query($id:Int!){ manga(id:$id){ %s categories { nodes { id name } } } }" % MANGA_FIELDS,
                        {"id": manga_id})["manga"]

    def refresh_manga(self, manga_id: int) -> tuple[dict, list[dict]]:
        """Fetch details and the chapter list from the source."""
        data = self.gql("mutation($id:Int!){ fetchMangaAndChapters(input:{id:$id, fetchManga:true, fetchChapters:true})"
                        "{ manga { %s } chapters { %s } } }" % (MANGA_FIELDS, CHAPTER_FIELDS), {"id": manga_id},
                        timeout=120)["fetchMangaAndChapters"]
        return data["manga"], data["chapters"]

    def chapters(self, manga_id: int) -> list[dict]:
        return self.gql("query($id:Int!){ chapters(condition:{mangaId:$id}, order:[{by:SOURCE_ORDER, byType:DESC}])"
                        "{ nodes { %s } } }" % CHAPTER_FIELDS, {"id": manga_id})["chapters"]["nodes"]

    def chapter_pages(self, chapter_id: int) -> list[str]:
        return self.gql("mutation($id:Int!){ fetchChapterPages(input:{chapterId:$id}){ pages } }",
                        {"id": chapter_id}, timeout=120)["fetchChapterPages"]["pages"]

    def update_chapters(self, ids: list[int], *, is_read: bool | None = None, last_page_read: int | None = None,
                        bookmarked: bool | None = None) -> None:
        patch = {k: v for k, v in (("isRead", is_read), ("lastPageRead", last_page_read),
                                   ("isBookmarked", bookmarked)) if v is not None}
        if patch and ids:
            self.gql("mutation($ids:[Int!]!,$p:UpdateChapterPatchInput!){ updateChapters(input:{ids:$ids, patch:$p})"
                     "{ clientMutationId } }", {"ids": ids, "p": patch})

    # -- library / categories

    def library(self, category_id: int | None = None) -> list[dict]:
        flt = {"inLibrary": {"equalTo": True}}
        if category_id is not None:
            flt["categoryId"] = {"equalTo": category_id}
        return self.gql("query($f:MangaFilterInput){ mangas(filter:$f, order:[{by:TITLE}]){ nodes { %s } } }" % MANGA_FIELDS,
                        {"f": flt})["mangas"]["nodes"]

    def set_in_library(self, manga_id: int, value: bool) -> None:
        self.gql("mutation($id:Int!,$v:Boolean!){ updateManga(input:{id:$id, patch:{inLibrary:$v}}){ clientMutationId } }",
                 {"id": manga_id, "v": value})

    def categories(self) -> list[dict]:
        return self.gql("{ categories(order:[{by:ORDER}]) { nodes { %s } } }" % CATEGORY_FIELDS)["categories"]["nodes"]

    def create_category(self, name: str) -> dict:
        return self.gql("mutation($n:String!){ createCategory(input:{name:$n}){ category { %s } } }" % CATEGORY_FIELDS,
                        {"n": name})["createCategory"]["category"]

    def set_manga_categories(self, manga_id: int, add: list[int], remove: list[int]) -> None:
        self.gql("mutation($id:Int!,$p:UpdateMangaCategoriesPatchInput!){ updateMangaCategories(input:{id:$id, patch:$p})"
                 "{ clientMutationId } }", {"id": manga_id, "p": {"addToCategories": add, "removeFromCategories": remove}})

    # -- downloads (explicit "read offline")

    def enqueue_downloads(self, chapter_ids: list[int]) -> None:
        self.gql("mutation($ids:[Int!]!){ enqueueChapterDownloads(input:{ids:$ids}){ clientMutationId } }", {"ids": chapter_ids})
        self.gql("mutation{ startDownloader(input:{}){ clientMutationId } }")

    def delete_downloads(self, chapter_ids: list[int]) -> None:
        self.gql("mutation($ids:[Int!]!){ deleteDownloadedChapters(input:{ids:$ids}){ clientMutationId } }", {"ids": chapter_ids})

    def download_status(self) -> dict:
        return self.gql("{ downloadStatus { state queue { progress state chapter { id name mangaId } } } }")["downloadStatus"]

    # -- updates

    def update_library(self) -> None:
        self.gql("mutation{ updateLibrary(input:{}){ clientMutationId } }")

    def chapters_after(self, chapter_id: int) -> list[dict]:
        """Chapters of library manga with an id above `chapter_id`, oldest first (new-chapter detection)."""
        return self.gql(
            "query($id:Int!){ chapters(filter:{id:{greaterThan:$id}, inLibrary:{equalTo:true}}, "
            "order:[{by:ID, byType:ASC}]){ nodes { %s manga { id title } } } }" % CHAPTER_FIELDS,
            {"id": chapter_id})["chapters"]["nodes"]

    def max_chapter_id(self) -> int:
        nodes = self.gql("{ chapters(order:[{by:ID, byType:DESC}], first:1){ nodes { id } } }")["chapters"]["nodes"]
        return nodes[0]["id"] if nodes else 0
