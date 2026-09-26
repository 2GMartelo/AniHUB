"""SQLite index of the library. One connection per thread (workers run in a thread pool)."""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Iterable

SCHEMA_VERSION = 12

SD_TABLES = '''
CREATE TABLE sd_presets (
    id INTEGER PRIMARY KEY, kind TEXT NOT NULL, name TEXT NOT NULL, data TEXT NOT NULL, created_at REAL NOT NULL,
    UNIQUE(kind, name));                                   -- kind: preset (all parameters) | style (prompt snippet)
CREATE TABLE sd_history (
    id INTEGER PRIMARY KEY, created_at REAL NOT NULL, path TEXT NOT NULL, seed INTEGER, model TEXT,
    prompt TEXT, negative TEXT, params TEXT NOT NULL, backend TEXT);
CREATE INDEX idx_sd_history_created ON sd_history(created_at);
CREATE TABLE sd_queue (
    id INTEGER PRIMARY KEY, position REAL NOT NULL, status TEXT NOT NULL DEFAULT 'pending', params TEXT NOT NULL,
    label TEXT, created_at REAL NOT NULL, finished_at REAL, error TEXT, backend TEXT,
    result_count INTEGER NOT NULL DEFAULT 0);              -- status: pending | running | done | failed | cancelled
'''

RULES_TABLE = '''
CREATE TABLE auto_rules (
    id INTEGER PRIMARY KEY, name TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1, position INTEGER NOT NULL DEFAULT 0,
    conditions TEXT NOT NULL, actions TEXT NOT NULL);       -- both JSON, see library/rules.py
'''

ANIME_TABLE = '''
CREATE TABLE anime_list (
    media_id INTEGER PRIMARY KEY,                 -- AniList media id
    kind TEXT NOT NULL DEFAULT 'anime',
    title TEXT NOT NULL, title_native TEXT, cover_url TEXT, format TEXT,
    episodes INTEGER,                             -- total, NULL while unknown
    airing_status TEXT, next_episode INTEGER, next_airing REAL,
    status TEXT NOT NULL,                         -- CURRENT | PLANNING | COMPLETED | PAUSED | DROPPED | REPEATING
    progress INTEGER NOT NULL DEFAULT 0,          -- episodes watched
    score INTEGER NOT NULL DEFAULT 0,             -- 0..100 like AniList's raw score
    entry_id INTEGER,                             -- AniList list entry id once synced
    updated_at REAL NOT NULL,
    synced INTEGER NOT NULL DEFAULT 0);           -- 1 = the tracker has this exact state
CREATE INDEX idx_anime_status ON anime_list(status, updated_at);
'''

# the shape migration 6 created; migration 9 adds the online columns
NOVEL_TABLE_V6 = '''
CREATE TABLE novels (
    id INTEGER PRIMARY KEY, title TEXT NOT NULL, author TEXT,
    path TEXT NOT NULL,                           -- relative to the library root
    ext TEXT NOT NULL, sha256 TEXT NOT NULL UNIQUE, cover TEXT,   -- cover: relative path of a jpg, if the book has one
    chapters INTEGER NOT NULL DEFAULT 0, added_at REAL NOT NULL, last_read_at REAL,
    chapter_index INTEGER NOT NULL DEFAULT 0, scroll REAL NOT NULL DEFAULT 0,   -- where the reader stopped
    finished INTEGER NOT NULL DEFAULT 0);
'''

NOVEL_TABLE = '''
CREATE TABLE novels (
    id INTEGER PRIMARY KEY, title TEXT NOT NULL, author TEXT,
    path TEXT NOT NULL,                           -- relative to the library root
    ext TEXT NOT NULL, sha256 TEXT NOT NULL UNIQUE, cover TEXT,   -- cover: relative path of a jpg, if the book has one
    chapters INTEGER NOT NULL DEFAULT 0, added_at REAL NOT NULL, last_read_at REAL,
    chapter_index INTEGER NOT NULL DEFAULT 0, scroll REAL NOT NULL DEFAULT 0,   -- where the reader stopped
    finished INTEGER NOT NULL DEFAULT 0,
    source TEXT, remote_id TEXT, remote TEXT);        -- online novels (path is empty, sha256 is "online:<source>:<id>")
'''

SAVED_ANIME_TABLE = '''
CREATE TABLE anime_saved (                        -- the user's own shelf of titles from the anime sources (no tracker needed)
    source TEXT NOT NULL, entry_id TEXT NOT NULL, title TEXT NOT NULL, cover TEXT NOT NULL DEFAULT '', url TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL,                         -- later | watching | done
    added_at REAL NOT NULL, updated_at REAL NOT NULL, PRIMARY KEY (source, entry_id));
CREATE INDEX idx_anime_saved_status ON anime_saved(status, updated_at);
'''

PROMPTBOOK_TABLES = '''
CREATE TABLE pb_nodes (                            -- prompt builder: categories of the tag catalogue (a slot = one paragraph of the prompt)
    id INTEGER PRIMARY KEY, parent_id INTEGER REFERENCES pb_nodes(id) ON DELETE CASCADE,
    slot TEXT NOT NULL, name TEXT NOT NULL, name_ru TEXT NOT NULL DEFAULT '',
    exclusive INTEGER NOT NULL DEFAULT 0,          -- only one tag of it at a time (hair colour, count...)
    position INTEGER NOT NULL DEFAULT 0, hidden INTEGER NOT NULL DEFAULT 0, key TEXT UNIQUE);   -- key: built-in rows
CREATE TABLE pb_tags (
    id INTEGER PRIMARY KEY, node_id INTEGER NOT NULL REFERENCES pb_nodes(id) ON DELETE CASCADE,
    text TEXT NOT NULL, label TEXT NOT NULL DEFAULT '', image TEXT NOT NULL DEFAULT '',   -- image: relative path of a jpg
    position INTEGER NOT NULL DEFAULT 0, hidden INTEGER NOT NULL DEFAULT 0, key TEXT UNIQUE);
CREATE INDEX idx_pb_tags_node ON pb_tags(node_id);
'''

WATCH_TABLES = '''
CREATE TABLE anime_links (                        -- which AniList show a title of an anime source is
    source TEXT NOT NULL, entry_id TEXT NOT NULL, media_id INTEGER NOT NULL, media TEXT NOT NULL,   -- media: JSON (normalize_media)
    PRIMARY KEY (source, entry_id));
CREATE TABLE anime_positions (                    -- where you stopped in each episode
    source TEXT NOT NULL, entry_id TEXT NOT NULL, episode_id TEXT NOT NULL, number REAL,
    position_ms INTEGER NOT NULL DEFAULT 0, duration_ms INTEGER NOT NULL DEFAULT 0, watched INTEGER NOT NULL DEFAULT 0,
    updated_at REAL NOT NULL, PRIMARY KEY (source, entry_id, episode_id));
'''

SUBSCRIPTION_TABLE = '''
CREATE TABLE subscriptions (
    id INTEGER PRIMARY KEY, name TEXT NOT NULL, source TEXT NOT NULL, query TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1, auto_save INTEGER NOT NULL DEFAULT 0,
    last_seen_id INTEGER NOT NULL DEFAULT 0,       -- the newest post the user has looked at / saved
    new_count INTEGER NOT NULL DEFAULT 0,          -- posts newer than that, as of the last check
    last_check REAL, last_error TEXT, created_at REAL NOT NULL);
'''

# Each step upgrades from version N to N+1 (fresh databases run SCHEMA, then jump to SCHEMA_VERSION).
MIGRATIONS = {
    1: "ALTER TABLE items ADD COLUMN meta TEXT",  # JSON: generation parameters for SD items
    2: """
        ALTER TABLE items ADD COLUMN phash INTEGER;
        ALTER TABLE items ADD COLUMN stars INTEGER NOT NULL DEFAULT 0;
        ALTER TABLE items ADD COLUMN trash_path TEXT;
        CREATE INDEX idx_items_phash ON items(phash) WHERE phash IS NOT NULL;
        CREATE TABLE categories (
            id INTEGER PRIMARY KEY, kind TEXT NOT NULL DEFAULT 'art', name TEXT NOT NULL,
            position INTEGER NOT NULL DEFAULT 0, is_default INTEGER NOT NULL DEFAULT 0, UNIQUE(kind, name));
        CREATE TABLE item_categories (
            item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
            category_id INTEGER NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
            PRIMARY KEY (item_id, category_id));
        CREATE INDEX idx_item_categories_cat ON item_categories(category_id, item_id);
        CREATE TABLE collections (
            id INTEGER PRIMARY KEY, kind TEXT NOT NULL DEFAULT 'art', name TEXT NOT NULL,
            position INTEGER NOT NULL DEFAULT 0, created_at REAL NOT NULL, UNIQUE(kind, name));
        CREATE TABLE collection_items (
            collection_id INTEGER NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
            item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
            added_at REAL NOT NULL, PRIMARY KEY (collection_id, item_id));
        CREATE INDEX idx_collection_items_item ON collection_items(item_id);
        CREATE TABLE smart_tags (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, tags TEXT NOT NULL);
    """,
    3: SD_TABLES,
    4: RULES_TABLE,
    5: ANIME_TABLE,
    6: NOVEL_TABLE_V6,
    7: WATCH_TABLES,
    8: SUBSCRIPTION_TABLE,
    9: """
        ALTER TABLE novels ADD COLUMN source TEXT;        -- online novels: the source plugin and the title's id there
        ALTER TABLE novels ADD COLUMN remote_id TEXT;
        ALTER TABLE novels ADD COLUMN remote TEXT;        -- JSON: {"entry": ..., "chapters": [...]} (opens without the network)
    """,
    10: PROMPTBOOK_TABLES,
    11: SAVED_ANIME_TABLE,
}

SCHEMA = """
CREATE TABLE items (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL DEFAULT 'art',          -- art | manga | sd
    path TEXT NOT NULL,                        -- relative to library root
    sha256 TEXT,
    width INTEGER, height INTEGER, size INTEGER,
    ext TEXT,
    rating TEXT NOT NULL DEFAULT 'general',    -- content rating: general | sensitive | questionable | explicit
    source_site TEXT, source_post_id TEXT, source_url TEXT, page_url TEXT,
    author TEXT,
    added_at REAL NOT NULL,
    favorite INTEGER NOT NULL DEFAULT 0,
    score INTEGER,                             -- score on the source site
    trashed_at REAL,
    meta TEXT,
    phash INTEGER,                             -- 64-bit dHash (signed) for near-duplicate search
    stars INTEGER NOT NULL DEFAULT 0,          -- the user's own 0..5 rating
    trash_path TEXT                            -- where the file lives while the item is in the trash
);
CREATE UNIQUE INDEX idx_items_source ON items(source_site, source_post_id)
    WHERE source_site IS NOT NULL;
CREATE INDEX idx_items_sha ON items(sha256);
CREATE INDEX idx_items_kind_added ON items(kind, trashed_at, added_at);
CREATE INDEX idx_items_phash ON items(phash) WHERE phash IS NOT NULL;

CREATE TABLE tags (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    category TEXT NOT NULL DEFAULT 'general',
    parent_id INTEGER REFERENCES tags(id)
);
CREATE TABLE item_tags (
    item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    tag_id INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    PRIMARY KEY (item_id, tag_id)
);
CREATE INDEX idx_item_tags_tag ON item_tags(tag_id, item_id);

CREATE TABLE categories (
    id INTEGER PRIMARY KEY, kind TEXT NOT NULL DEFAULT 'art', name TEXT NOT NULL,
    position INTEGER NOT NULL DEFAULT 0, is_default INTEGER NOT NULL DEFAULT 0, UNIQUE(kind, name));
CREATE TABLE item_categories (
    item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    category_id INTEGER NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
    PRIMARY KEY (item_id, category_id));
CREATE INDEX idx_item_categories_cat ON item_categories(category_id, item_id);
CREATE TABLE collections (
    id INTEGER PRIMARY KEY, kind TEXT NOT NULL DEFAULT 'art', name TEXT NOT NULL,
    position INTEGER NOT NULL DEFAULT 0, created_at REAL NOT NULL, UNIQUE(kind, name));
CREATE TABLE collection_items (
    collection_id INTEGER NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
    item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    added_at REAL NOT NULL, PRIMARY KEY (collection_id, item_id));
CREATE INDEX idx_collection_items_item ON collection_items(item_id);
CREATE TABLE smart_tags (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, tags TEXT NOT NULL);
""" + SD_TABLES + RULES_TABLE + ANIME_TABLE + NOVEL_TABLE + WATCH_TABLES + SUBSCRIPTION_TABLE + PROMPTBOOK_TABLES + SAVED_ANIME_TABLE

SORTS = {
    "added": "i.added_at",
    "size": "COALESCE(i.size, 0)",
    "rating": "CASE i.rating WHEN 'general' THEN 0 WHEN 'sensitive' THEN 1 WHEN 'questionable' THEN 2 ELSE 3 END",
    "name": "lower(i.path)",
    "stars": "i.stars",
    "score": "COALESCE(i.score, 0)",
    "author": "lower(COALESCE(i.author, ''))",
}
BULK_FIELDS = {"rating", "stars", "favorite"}
UPDATABLE = {"rating", "stars", "favorite", "phash", "trashed_at", "trash_path", "width", "height", "size", "author", "meta"}


def _like_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class Database:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._local = threading.local()
        self._migrate()

    @property
    def conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self.path, timeout=30)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.create_function("py_lower", 1, lambda v: v.lower() if isinstance(v, str) else v, deterministic=True)  # SQLite lower() is ASCII-only
            self._local.conn = conn
        return conn

    def _migrate(self) -> None:
        version = self.conn.execute("PRAGMA user_version").fetchone()[0]
        if version == 0:
            self.conn.executescript(SCHEMA)
            version = SCHEMA_VERSION
        while version < SCHEMA_VERSION:
            self.conn.executescript(MIGRATIONS[version])
            version += 1
        self.conn.execute(f"PRAGMA user_version={version}")
        self.conn.commit()

    def close(self) -> None:
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            conn.close()
            self._local.conn = None

    # --- items -----------------------------------------------------------------

    def has_source_post(self, site: str, post_id: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM items WHERE source_site=? AND source_post_id=? AND trashed_at IS NULL",
            (site, str(post_id)),
        ).fetchone()
        return row is not None

    def find_by_source(self, site: str, post_id: str) -> sqlite3.Row | None:
        """Includes trashed items (the unique index covers them too)."""
        return self.conn.execute(
            "SELECT * FROM items WHERE source_site=? AND source_post_id=?", (site, str(post_id))).fetchone()

    def find_by_hash(self, sha256: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM items WHERE sha256=? AND trashed_at IS NULL", (sha256,)
        ).fetchone()

    def items_without_meta(self, exts: Iterable[str]) -> list[sqlite3.Row]:
        """(id, path) of the untrashed pictures with the given extensions that carry no generation parameters yet."""
        exts = list(exts)
        marks = ", ".join("?" for _ in exts)
        return self.conn.execute(
            f"SELECT id, path FROM items WHERE (meta IS NULL OR meta='') AND trashed_at IS NULL AND ext IN ({marks}) "
            "ORDER BY id", exts).fetchall()

    def set_meta_many(self, pairs: list[tuple[int, str]]) -> None:
        """Store generation parameters for many items in one transaction (a scan writes thousands; one commit each
        would hold the database for seconds)."""
        with self.conn:
            self.conn.executemany("UPDATE items SET meta=? WHERE id=?", [(meta, item_id) for item_id, meta in pairs])

    def get_item(self, item_id: int) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()

    def get_items(self, ids: Iterable[int]) -> list[sqlite3.Row]:
        ids = list(ids)
        if not ids:
            return []
        return self.conn.execute(f"SELECT * FROM items WHERE id IN ({','.join('?' * len(ids))})", ids).fetchall()

    def add_item(self, *, tags: Iterable[tuple[str, str]] = (), **fields) -> int:
        fields.setdefault("added_at", time.time())
        cols = ", ".join(fields)
        marks = ", ".join("?" for _ in fields)
        with self.conn:
            cur = self.conn.execute(f"INSERT INTO items ({cols}) VALUES ({marks})", tuple(fields.values()))
            item_id = cur.lastrowid
            for name, category in tags:
                self._link_tag(item_id, name, category)
        return item_id

    def _link_tag(self, item_id: int, name: str, category: str = "general") -> None:
        self.conn.execute("INSERT OR IGNORE INTO tags(name, category) VALUES (?, ?)", (name, category))
        tag_id = self.conn.execute("SELECT id FROM tags WHERE name=?", (name,)).fetchone()[0]
        self.conn.execute("INSERT OR IGNORE INTO item_tags VALUES (?, ?)", (item_id, tag_id))

    def update_fields(self, item_id: int, **fields) -> None:
        bad = set(fields) - UPDATABLE
        if bad:
            raise ValueError(f"cannot update {sorted(bad)}")
        if fields:
            sets = ", ".join(f"{k}=?" for k in fields)
            with self.conn:
                self.conn.execute(f"UPDATE items SET {sets} WHERE id=?", (*fields.values(), item_id))

    def set_field(self, ids: Iterable[int], field: str, value) -> None:
        """Bulk update of rating / stars / favorite."""
        if field not in BULK_FIELDS:
            raise ValueError(field)
        ids = list(ids)
        with self.conn:
            self.conn.executemany(f"UPDATE items SET {field}=? WHERE id=?", [(value, i) for i in ids])

    def delete_items(self, ids: Iterable[int]) -> None:
        with self.conn:
            self.conn.executemany("DELETE FROM items WHERE id=?", [(i,) for i in ids])

    # --- tags ------------------------------------------------------------------

    def item_tags(self, item_id: int) -> list[str]:
        rows = self.conn.execute(
            "SELECT t.name FROM tags t JOIN item_tags it ON it.tag_id=t.id WHERE it.item_id=? ORDER BY t.name",
            (item_id,),
        ).fetchall()
        return [r[0] for r in rows]

    def item_tags_categorized(self, item_id: int) -> list[tuple[str, str]]:
        rows = self.conn.execute(
            "SELECT t.name, t.category FROM tags t JOIN item_tags it ON it.tag_id=t.id "
            "WHERE it.item_id=? ORDER BY t.name", (item_id,),
        ).fetchall()
        return [(r[0], r[1]) for r in rows]

    def tags_of_items(self, item_ids: Iterable[int]) -> list[tuple[str, str, int]]:
        """(name, category, number of the given items that carry it), most common first."""
        ids = list(item_ids)
        if not ids:
            return []
        rows = self.conn.execute(
            f"SELECT t.name, t.category, COUNT(*) c FROM item_tags it JOIN tags t ON t.id=it.tag_id "
            f"WHERE it.item_id IN ({','.join('?' * len(ids))}) GROUP BY t.id ORDER BY c DESC, t.name", ids).fetchall()
        return [(r[0], r[1], r[2]) for r in rows]

    def add_tags(self, item_ids: Iterable[int], tags: Iterable[tuple[str, str]]) -> None:
        tags = list(tags)
        with self.conn:
            for item_id in item_ids:
                for name, category in tags:
                    self._link_tag(item_id, name, category)

    def remove_tags(self, item_ids: Iterable[int], names: Iterable[str]) -> None:
        ids, names = list(item_ids), list(names)
        if not ids or not names:
            return
        with self.conn:
            self.conn.execute(
                f"DELETE FROM item_tags WHERE item_id IN ({','.join('?' * len(ids))}) AND tag_id IN "
                f"(SELECT id FROM tags WHERE name IN ({','.join('?' * len(names))}))", (*ids, *names))

    def tag_id(self, name: str) -> int | None:
        row = self.conn.execute("SELECT id FROM tags WHERE name=?", (name,)).fetchone()
        return row[0] if row else None

    def ensure_tag(self, name: str, category: str = "general") -> int:
        with self.conn:
            self.conn.execute("INSERT OR IGNORE INTO tags(name, category) VALUES (?, ?)", (name, category))
        return self.tag_id(name)

    def tag_family(self, name: str) -> set[str]:
        """The tag's name plus the names of all its descendants (a parent tag stands for its children)."""
        tag_id = self.tag_id(name)
        if tag_id is None:
            return {name}
        ids = self.descendant_ids([tag_id])
        rows = self.conn.execute(f"SELECT name FROM tags WHERE id IN ({','.join('?' * len(ids))})", list(ids)).fetchall()
        return {r[0] for r in rows}

    def descendant_ids(self, tag_ids: Iterable[int]) -> set[int]:
        """The tags themselves plus every child, grandchild... (cycle-safe)."""
        result = set(tag_ids)
        frontier = set(result)
        while frontier:
            rows = self.conn.execute(
                f"SELECT id FROM tags WHERE parent_id IN ({','.join('?' * len(frontier))})", list(frontier)).fetchall()
            frontier = {r[0] for r in rows} - result
            result |= frontier
        return result

    def set_tag_parent(self, name: str, parent: str | None) -> None:
        child_id = self.ensure_tag(name)
        if parent is None:
            parent_id = None
        else:
            parent_id = self.ensure_tag(parent)
            if parent_id in self.descendant_ids([child_id]):
                raise ValueError("A tag cannot be placed under itself or its own descendant")
        with self.conn:
            self.conn.execute("UPDATE tags SET parent_id=? WHERE id=?", (parent_id, child_id))

    def tag_tree(self, query: str = "", limit: int = 500) -> list[sqlite3.Row]:
        """Tags that take part in the hierarchy (have a parent or children), optionally filtered by name."""
        sql = ("SELECT t.id, t.name, t.category, t.parent_id, "
               "(SELECT COUNT(*) FROM item_tags it WHERE it.tag_id=t.id) AS n FROM tags t "
               "WHERE (t.parent_id IS NOT NULL OR EXISTS (SELECT 1 FROM tags c WHERE c.parent_id=t.id))")
        args: list = []
        if query:
            sql += " AND t.name LIKE ? ESCAPE '\\'"
            args.append(f"%{_like_escape(query)}%")
        return self.conn.execute(sql + " ORDER BY t.name LIMIT ?", (*args, limit)).fetchall()

    def suggest_tags(self, prefix: str, limit: int = 15) -> list[tuple[str, str, int]]:
        """Autocomplete: (name, category, item count). '@prefix' completes smart tags."""
        if prefix.startswith("@"):
            rows = self.conn.execute("SELECT name FROM smart_tags WHERE name LIKE ? ESCAPE '\\' ORDER BY name LIMIT ?",
                                     (_like_escape(prefix[1:]) + "%", limit)).fetchall()
            return [("@" + r[0], "smart", 0) for r in rows]
        like = _like_escape(prefix)
        rows = self.conn.execute(
            "SELECT t.name, t.category, (SELECT COUNT(*) FROM item_tags it WHERE it.tag_id=t.id) AS n "
            "FROM tags t WHERE t.name LIKE ? ESCAPE '\\' ORDER BY n DESC, t.name LIMIT ?", (like + "%", limit)).fetchall()
        out = [(r[0], r[1], r[2]) for r in rows]
        if len(out) < limit and len(prefix) >= 2:  # then substring matches ("blue" finds "light_blue_hair")
            seen = {o[0] for o in out}
            rows = self.conn.execute(
                "SELECT t.name, t.category, (SELECT COUNT(*) FROM item_tags it WHERE it.tag_id=t.id) AS n "
                "FROM tags t WHERE t.name LIKE ? ESCAPE '\\' ORDER BY n DESC, t.name LIMIT ?",
                ("%" + like + "%", limit)).fetchall()
            out += [(r[0], r[1], r[2]) for r in rows if r[0] not in seen][: limit - len(out)]
        return out

    def rename_tag(self, old: str, new: str) -> None:
        """Renames a tag; if `new` already exists the two are merged."""
        old_id, new_id = self.tag_id(old), self.tag_id(new)
        if old_id is None or old == new:
            return
        with self.conn:
            if new_id is None:
                self.conn.execute("UPDATE tags SET name=? WHERE id=?", (new, old_id))
                return
            self.conn.execute("INSERT OR IGNORE INTO item_tags(item_id, tag_id) "
                              "SELECT item_id, ? FROM item_tags WHERE tag_id=?", (new_id, old_id))
            self.conn.execute("UPDATE tags SET parent_id=? WHERE parent_id=?", (new_id, old_id))
            self.conn.execute("DELETE FROM tags WHERE id=?", (old_id,))

    def delete_tag(self, name: str) -> None:
        with self.conn:
            self.conn.execute("UPDATE tags SET parent_id=(SELECT parent_id FROM tags WHERE name=?) WHERE parent_id="
                              "(SELECT id FROM tags WHERE name=?)", (name, name))
            self.conn.execute("DELETE FROM tags WHERE name=?", (name,))

    # --- smart tags (a named group of tags: matches items carrying ANY of them) -----

    def smart_tags(self) -> list[tuple[int, str, list[str]]]:
        rows = self.conn.execute("SELECT id, name, tags FROM smart_tags ORDER BY name").fetchall()
        return [(r[0], r[1], json.loads(r[2])) for r in rows]

    def save_smart_tag(self, name: str, tags: list[str], smart_id: int | None = None) -> int:
        payload = json.dumps(tags, ensure_ascii=False)
        with self.conn:
            if smart_id is None:
                cur = self.conn.execute("INSERT INTO smart_tags(name, tags) VALUES (?, ?)", (name, payload))
                return cur.lastrowid
            self.conn.execute("UPDATE smart_tags SET name=?, tags=? WHERE id=?", (name, payload, smart_id))
            return smart_id

    def delete_smart_tag(self, smart_id: int) -> None:
        with self.conn:
            self.conn.execute("DELETE FROM smart_tags WHERE id=?", (smart_id,))

    def _term_tag_ids(self, term: str) -> set[int]:
        """Tag ids matched by a search term: the tag and its descendants; '@name' = smart tag members likewise."""
        if term.startswith("@"):
            row = self.conn.execute("SELECT tags FROM smart_tags WHERE name=?", (term[1:],)).fetchone()
            names = json.loads(row[0]) if row else []
        else:
            names = [term]
        ids = {i for i in (self.tag_id(n) for n in names) if i is not None}
        return self.descendant_ids(ids) if ids else set()

    # --- categories & collections (both kind-scoped) ----------------------------------------

    def categories(self, kind: str = "art") -> list[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM categories WHERE kind=? ORDER BY position, id", (kind,)).fetchall()

    def create_category(self, name: str, kind: str = "art") -> int:
        with self.conn:
            pos = self.conn.execute("SELECT COALESCE(MAX(position), -1) + 1 FROM categories WHERE kind=?", (kind,)).fetchone()[0]
            return self.conn.execute("INSERT INTO categories(kind, name, position) VALUES (?, ?, ?)",
                                     (kind, name, pos)).lastrowid

    def rename_category(self, category_id: int, name: str) -> None:
        with self.conn:
            self.conn.execute("UPDATE categories SET name=? WHERE id=?", (name, category_id))

    def delete_category(self, category_id: int) -> None:
        with self.conn:
            self.conn.execute("DELETE FROM categories WHERE id=?", (category_id,))

    def reorder_categories(self, ordered_ids: list[int]) -> None:
        with self.conn:
            self.conn.executemany("UPDATE categories SET position=? WHERE id=?", [(p, i) for p, i in enumerate(ordered_ids)])

    def set_default_category(self, category_id: int | None, kind: str = "art") -> None:
        with self.conn:
            self.conn.execute("UPDATE categories SET is_default=0 WHERE kind=?", (kind,))
            if category_id is not None:
                self.conn.execute("UPDATE categories SET is_default=1 WHERE id=?", (category_id,))

    def default_category(self, kind: str = "art") -> int | None:
        row = self.conn.execute("SELECT id FROM categories WHERE kind=? AND is_default=1", (kind,)).fetchone()
        return row[0] if row else None

    def set_item_categories(self, item_ids: Iterable[int], add: Iterable[int] = (), remove: Iterable[int] = ()) -> None:
        ids, add, remove = list(item_ids), list(add), list(remove)
        with self.conn:
            for item_id in ids:
                for cid in add:
                    self.conn.execute("INSERT OR IGNORE INTO item_categories VALUES (?, ?)", (item_id, cid))
                for cid in remove:
                    self.conn.execute("DELETE FROM item_categories WHERE item_id=? AND category_id=?", (item_id, cid))

    def item_category_ids(self, item_id: int) -> set[int]:
        return {r[0] for r in self.conn.execute("SELECT category_id FROM item_categories WHERE item_id=?", (item_id,))}

    def category_counts(self, kind: str = "art") -> dict[int, int]:
        rows = self.conn.execute(
            "SELECT ic.category_id, COUNT(*) FROM item_categories ic JOIN items i ON i.id=ic.item_id "
            "WHERE i.kind=? AND i.trashed_at IS NULL GROUP BY ic.category_id", (kind,)).fetchall()
        return {r[0]: r[1] for r in rows}

    def collections(self, kind: str = "art") -> list[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM collections WHERE kind=? ORDER BY position, name", (kind,)).fetchall()

    def create_collection(self, name: str, kind: str = "art") -> int:
        with self.conn:
            return self.conn.execute("INSERT INTO collections(kind, name, position, created_at) VALUES (?, ?, 0, ?)",
                                     (kind, name, time.time())).lastrowid

    def rename_collection(self, collection_id: int, name: str) -> None:
        with self.conn:
            self.conn.execute("UPDATE collections SET name=? WHERE id=?", (name, collection_id))

    def delete_collection(self, collection_id: int) -> None:
        with self.conn:
            self.conn.execute("DELETE FROM collections WHERE id=?", (collection_id,))

    def add_to_collection(self, item_ids: Iterable[int], collection_id: int) -> None:
        now = time.time()
        with self.conn:
            self.conn.executemany("INSERT OR IGNORE INTO collection_items VALUES (?, ?, ?)",
                                  [(collection_id, i, now) for i in item_ids])

    def remove_from_collection(self, item_ids: Iterable[int], collection_id: int) -> None:
        with self.conn:
            self.conn.executemany("DELETE FROM collection_items WHERE collection_id=? AND item_id=?",
                                  [(collection_id, i) for i in item_ids])

    def collection_counts(self, kind: str = "art") -> dict[int, int]:
        rows = self.conn.execute(
            "SELECT ci.collection_id, COUNT(*) FROM collection_items ci JOIN items i ON i.id=ci.item_id "
            "WHERE i.kind=? AND i.trashed_at IS NULL GROUP BY ci.collection_id", (kind,)).fetchall()
        return {r[0]: r[1] for r in rows}

    # --- subscriptions ---------------------------------------------------------------

    def subscriptions(self) -> list[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM subscriptions ORDER BY name COLLATE NOCASE, id").fetchall()

    def subscription(self, sub_id: int) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM subscriptions WHERE id=?", (sub_id,)).fetchone()

    def add_subscription(self, name: str, source: str, query: str, last_seen_id: int = 0, auto_save: bool = False) -> int:
        with self.conn:
            return self.conn.execute(
                "INSERT INTO subscriptions(name, source, query, last_seen_id, auto_save, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (name, source, query, last_seen_id, int(auto_save), time.time())).lastrowid

    def update_subscription(self, sub_id: int, **fields) -> None:
        allowed = {"name", "enabled", "auto_save", "last_seen_id", "new_count", "last_check", "last_error"}
        if set(fields) - allowed:
            raise ValueError(f"cannot update {sorted(set(fields) - allowed)}")
        if fields:
            with self.conn:
                self.conn.execute(f"UPDATE subscriptions SET {', '.join(f'{k}=?' for k in fields)} WHERE id=?", [*fields.values(), sub_id])

    def delete_subscription(self, sub_id: int) -> None:
        with self.conn:
            self.conn.execute("DELETE FROM subscriptions WHERE id=?", (sub_id,))

    # --- watching anime -------------------------------------------------------------

    def watch_link(self, source: str, entry_id: str) -> dict | None:
        row = self.conn.execute("SELECT media_id, media FROM anime_links WHERE source=? AND entry_id=?", (source, entry_id)).fetchone()
        return {"media_id": row["media_id"], "media": json.loads(row["media"])} if row else None

    def watch_set_link(self, source: str, entry_id: str, media: dict | None) -> None:
        with self.conn:
            if media is None:
                self.conn.execute("DELETE FROM anime_links WHERE source=? AND entry_id=?", (source, entry_id))
            else:
                self.conn.execute("INSERT OR REPLACE INTO anime_links VALUES (?, ?, ?, ?)",
                                  (source, entry_id, media["id"], json.dumps(media, ensure_ascii=False)))

    def watch_positions(self, source: str, entry_id: str) -> dict[str, sqlite3.Row]:
        rows = self.conn.execute("SELECT * FROM anime_positions WHERE source=? AND entry_id=?", (source, entry_id)).fetchall()
        return {r["episode_id"]: r for r in rows}

    def watch_save(self, source: str, entry_id: str, episode_id: str, *, number: float | None = None,
                   position_ms: int | None = None, duration_ms: int | None = None, watched: bool | None = None) -> None:
        with self.conn:
            row = self.conn.execute("SELECT * FROM anime_positions WHERE source=? AND entry_id=? AND episode_id=?",
                                    (source, entry_id, episode_id)).fetchone()
            if row is None:
                self.conn.execute("INSERT INTO anime_positions VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                                  (source, entry_id, episode_id, number, position_ms or 0, duration_ms or 0, int(bool(watched)), time.time()))
                return
            values = {"number": number, "position_ms": position_ms, "duration_ms": duration_ms,
                      "watched": None if watched is None else int(watched)}
            values = {k: v for k, v in values.items() if v is not None}
            values["updated_at"] = time.time()
            self.conn.execute(f"UPDATE anime_positions SET {', '.join(f'{k}=?' for k in values)} "
                              "WHERE source=? AND entry_id=? AND episode_id=?", [*values.values(), source, entry_id, episode_id])

    # --- light novels ------------------------------------------------------------

    def novels(self, query: str = "", unfinished: bool = False) -> list[sqlite3.Row]:
        sql, args = "SELECT * FROM novels WHERE 1", []
        if query:
            sql += " AND (py_lower(title) LIKE ? ESCAPE '\\' OR py_lower(author) LIKE ? ESCAPE '\\')"
            args += [f"%{_like_escape(query.lower())}%"] * 2
        if unfinished:
            sql += " AND finished=0"
        return self.conn.execute(sql + " ORDER BY COALESCE(last_read_at, added_at) DESC", args).fetchall()

    def novel_get(self, novel_id: int) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM novels WHERE id=?", (novel_id,)).fetchone()

    def novel_by_hash(self, sha256: str) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM novels WHERE sha256=?", (sha256,)).fetchone()

    def novel_by_remote(self, source: str, remote_id: str) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM novels WHERE source=? AND remote_id=?", (source, remote_id)).fetchone()

    def novel_add(self, **fields) -> int:
        fields.setdefault("added_at", time.time())
        with self.conn:
            return self.conn.execute(f"INSERT INTO novels ({', '.join(fields)}) VALUES ({', '.join('?' * len(fields))})",
                                     list(fields.values())).lastrowid

    def novel_update(self, novel_id: int, **fields) -> None:
        allowed = {"title", "author", "cover", "chapters", "last_read_at", "chapter_index", "scroll", "finished", "remote"}
        if set(fields) - allowed:
            raise ValueError(f"cannot update {sorted(set(fields) - allowed)}")
        if fields:
            with self.conn:
                self.conn.execute(f"UPDATE novels SET {', '.join(f'{k}=?' for k in fields)} WHERE id=?", [*fields.values(), novel_id])

    def novel_delete(self, novel_id: int) -> None:
        with self.conn:
            self.conn.execute("DELETE FROM novels WHERE id=?", (novel_id,))

    # --- anime list (own tracking, optionally mirrored to AniList) -----------------

    ANIME_COLS = ("media_id", "kind", "title", "title_native", "cover_url", "format", "episodes", "airing_status",
                  "next_episode", "next_airing", "status", "progress", "score", "entry_id", "updated_at", "synced")

    def anime_entries(self, status: str | None = None) -> list[sqlite3.Row]:
        sql, args = "SELECT * FROM anime_list", ()
        if status:
            sql, args = sql + " WHERE status=?", (status,)
        return self.conn.execute(sql + " ORDER BY updated_at DESC", args).fetchall()

    def anime_get(self, media_id: int) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM anime_list WHERE media_id=?", (media_id,)).fetchone()

    def anime_counts(self) -> dict[str, int]:
        return {r[0]: r[1] for r in self.conn.execute("SELECT status, COUNT(*) FROM anime_list GROUP BY status")}

    def anime_upsert(self, **fields) -> None:
        """Insert or update by media_id; only the given columns change on update."""
        unknown = set(fields) - set(self.ANIME_COLS)
        if unknown or "media_id" not in fields:
            raise ValueError(f"bad anime fields: {sorted(unknown) or 'media_id missing'}")
        fields.setdefault("updated_at", time.time())
        with self.conn:
            if self.conn.execute("SELECT 1 FROM anime_list WHERE media_id=?", (fields["media_id"],)).fetchone():
                cols = [c for c in fields if c != "media_id"]
                self.conn.execute(f"UPDATE anime_list SET {', '.join(f'{c}=?' for c in cols)} WHERE media_id=?",
                                  [fields[c] for c in cols] + [fields["media_id"]])
            else:
                cols = list(fields)
                self.conn.execute(f"INSERT INTO anime_list ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                                  [fields[c] for c in cols])

    def anime_delete(self, media_id: int) -> None:
        with self.conn:
            self.conn.execute("DELETE FROM anime_list WHERE media_id=?", (media_id,))

    # --- the shelf of source titles (later / watching / done) ------------------------------------------------------

    SAVED_STATUSES = ("later", "watching", "done")

    def saved_get(self, source: str, entry_id: str) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM anime_saved WHERE source=? AND entry_id=?", (source, entry_id)).fetchone()

    def saved_list(self, status: str | None = None) -> list[sqlite3.Row]:
        sql, args = "SELECT * FROM anime_saved", ()
        if status:
            sql, args = sql + " WHERE status=?", (status,)
        return self.conn.execute(sql + " ORDER BY updated_at DESC", args).fetchall()

    def saved_counts(self) -> dict[str, int]:
        return {r[0]: r[1] for r in self.conn.execute("SELECT status, COUNT(*) FROM anime_saved GROUP BY status")}

    def saved_set(self, source: str, entry_id: str, title: str, cover: str, url: str, status: str) -> None:
        if status not in self.SAVED_STATUSES:
            raise ValueError(f"bad status {status!r}")
        now = time.time()
        with self.conn:
            self.conn.execute(
                "INSERT INTO anime_saved(source, entry_id, title, cover, url, status, added_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(source, entry_id) DO UPDATE SET title=excluded.title, cover=excluded.cover, url=excluded.url, "
                "status=excluded.status, updated_at=excluded.updated_at", (source, entry_id, title, cover, url, status, now, now))

    def saved_remove(self, source: str, entry_id: str) -> None:
        with self.conn:
            self.conn.execute("DELETE FROM anime_saved WHERE source=? AND entry_id=?", (source, entry_id))

    def anime_unsynced(self) -> list[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM anime_list WHERE synced=0 ORDER BY updated_at").fetchall()

    # --- automatic rules -------------------------------------------------------

    def rules(self) -> list[dict]:
        rows = self.conn.execute("SELECT * FROM auto_rules ORDER BY position, id").fetchall()
        return [{"id": r["id"], "name": r["name"], "enabled": bool(r["enabled"]), "position": r["position"],
                 "conditions": json.loads(r["conditions"]), "actions": json.loads(r["actions"])} for r in rows]

    def save_rule(self, name: str, conditions: dict, actions: dict, enabled: bool = True, rule_id: int | None = None) -> int:
        cond, act = json.dumps(conditions, ensure_ascii=False), json.dumps(actions, ensure_ascii=False)
        with self.conn:
            if rule_id is None:
                pos = self.conn.execute("SELECT COALESCE(MAX(position), -1) + 1 FROM auto_rules").fetchone()[0]
                return self.conn.execute(
                    "INSERT INTO auto_rules(name, enabled, position, conditions, actions) VALUES (?, ?, ?, ?, ?)",
                    (name, int(enabled), pos, cond, act)).lastrowid
            self.conn.execute("UPDATE auto_rules SET name=?, enabled=?, conditions=?, actions=? WHERE id=?",
                              (name, int(enabled), cond, act, rule_id))
            return rule_id

    def set_rule_enabled(self, rule_id: int, enabled: bool) -> None:
        with self.conn:
            self.conn.execute("UPDATE auto_rules SET enabled=? WHERE id=?", (int(enabled), rule_id))

    def delete_rule(self, rule_id: int) -> None:
        with self.conn:
            self.conn.execute("DELETE FROM auto_rules WHERE id=?", (rule_id,))

    def move_rule(self, rule_id: int, delta: int) -> None:
        ids = [r["id"] for r in self.rules()]
        if rule_id not in ids:
            return
        i, j = ids.index(rule_id), ids.index(rule_id) + delta
        if 0 <= j < len(ids):
            ids[i], ids[j] = ids[j], ids[i]
            with self.conn:
                self.conn.executemany("UPDATE auto_rules SET position=? WHERE id=?", [(p, r) for p, r in enumerate(ids)])

    # --- search ----------------------------------------------------------------

    # --- hidden tags (age mode + the user's filter) -----------------------------------------------------------

    blocked_names: frozenset[str] = frozenset()
    blocked_prefixes: tuple[str, ...] = ()

    def set_blocked(self, names, prefixes=()) -> None:
        """Items carrying any of these tags disappear from every library search and count (the trash view excepted)."""
        self.blocked_names, self.blocked_prefixes = frozenset(names), tuple(prefixes)

    def _blocked_ids(self) -> list[int]:
        ids: set[int] = set()
        names = sorted(self.blocked_names)
        for i in range(0, len(names), 500):
            chunk = names[i:i + 500]
            ids.update(r[0] for r in self.conn.execute(f"SELECT id FROM tags WHERE name IN ({','.join('?' * len(chunk))})", chunk))
        for prefix in self.blocked_prefixes:
            ids.update(r[0] for r in self.conn.execute("SELECT id FROM tags WHERE name LIKE ? ESCAPE '\\'", (_like_escape(prefix) + "%",)))
        return sorted(ids)

    def _where(self, include, exclude, ratings, kind, category_id, collection_id, favorites, min_stars, trashed):
        where = ["i.kind=?", "i.trashed_at IS NOT NULL" if trashed else "i.trashed_at IS NULL"]
        args: list = [kind]
        if not trashed and (self.blocked_names or self.blocked_prefixes):
            blocked = self._blocked_ids()
            if blocked:
                where.append(f"NOT EXISTS (SELECT 1 FROM item_tags bt WHERE bt.item_id=i.id AND bt.tag_id IN ({','.join('?' * len(blocked))}))")
                args += blocked
        if ratings is not None:
            ratings = list(ratings)
            if not ratings:
                return None, []
            where.append(f"i.rating IN ({','.join('?' * len(ratings))})")
            args += ratings
        for term in include:
            ids = self._term_tag_ids(term)
            if not ids:
                return None, []  # an unknown tag can never match
            where.append(f"EXISTS (SELECT 1 FROM item_tags it WHERE it.item_id=i.id AND it.tag_id IN ({','.join('?' * len(ids))}))")
            args += sorted(ids)
        for term in exclude:
            ids = self._term_tag_ids(term)
            if ids:
                where.append(f"NOT EXISTS (SELECT 1 FROM item_tags it WHERE it.item_id=i.id AND it.tag_id IN ({','.join('?' * len(ids))}))")
                args += sorted(ids)
        if category_id is not None:
            where.append("EXISTS (SELECT 1 FROM item_categories ic WHERE ic.item_id=i.id AND ic.category_id=?)")
            args.append(category_id)
        if collection_id is not None:
            where.append("EXISTS (SELECT 1 FROM collection_items ci WHERE ci.item_id=i.id AND ci.collection_id=?)")
            args.append(collection_id)
        if favorites:
            where.append("i.favorite=1")
        if min_stars:
            where.append("i.stars>=?")
            args.append(min_stars)
        return " AND ".join(where), args

    def search_items(
        self,
        include: Iterable[str] = (),
        exclude: Iterable[str] = (),
        ratings: Iterable[str] | None = None,
        kind: str = "art",
        limit: int = 100,
        offset: int = 0,
        *,
        sort: str = "added",
        desc: bool = True,
        category_id: int | None = None,
        collection_id: int | None = None,
        favorites: bool = False,
        min_stars: int = 0,
        trashed: bool = False,
    ) -> list[sqlite3.Row]:
        where, args = self._where(list(include), list(exclude), ratings, kind, category_id, collection_id,
                                  favorites, min_stars, trashed)
        if where is None:
            return []
        expr = "i.trashed_at" if trashed else SORTS.get(sort, SORTS["added"])
        direction = "DESC" if desc else "ASC"
        sql = f"SELECT i.* FROM items i WHERE {where} ORDER BY {expr} {direction}, i.id {direction} LIMIT ? OFFSET ?"
        return self.conn.execute(sql, (*args, limit, offset)).fetchall()

    def count_search(self, include: Iterable[str] = (), exclude: Iterable[str] = (),
                     ratings: Iterable[str] | None = None, kind: str = "art", *, category_id: int | None = None,
                     collection_id: int | None = None, favorites: bool = False, min_stars: int = 0,
                     trashed: bool = False) -> int:
        where, args = self._where(list(include), list(exclude), ratings, kind, category_id, collection_id,
                                  favorites, min_stars, trashed)
        if where is None:
            return 0
        return self.conn.execute(f"SELECT COUNT(*) FROM items i WHERE {where}", args).fetchone()[0]

    def count_items(self, kind: str = "art") -> int:
        return self.conn.execute(
            "SELECT COUNT(*) FROM items WHERE kind=? AND trashed_at IS NULL", (kind,)
        ).fetchone()[0]

    # --- trash & duplicates -----------------------------------------------------

    def trashed_before(self, timestamp: float) -> list[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM items WHERE trashed_at IS NOT NULL AND trashed_at < ?", (timestamp,)).fetchall()

    def all_trashed(self, kind: str | None = None) -> list[sqlite3.Row]:
        if kind is None:
            return self.conn.execute("SELECT * FROM items WHERE trashed_at IS NOT NULL").fetchall()
        return self.conn.execute("SELECT * FROM items WHERE trashed_at IS NOT NULL AND kind=?", (kind,)).fetchall()

    def phash_rows(self, kind: str | None = None) -> list[tuple[int, int]]:
        sql = "SELECT id, phash FROM items WHERE phash IS NOT NULL AND trashed_at IS NULL"
        if kind:
            return [(r[0], r[1]) for r in self.conn.execute(sql + " AND kind=?", (kind,))]
        return [(r[0], r[1]) for r in self.conn.execute(sql)]

    def items_without_phash(self, kind: str = "art") -> list[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM items WHERE kind=? AND phash IS NULL AND trashed_at IS NULL "
                                 "AND ext NOT IN ('mp4','webm','mkv','mov','zip')", (kind,)).fetchall()

    # --- Stable Diffusion: presets, history, queue -----------------------------------------------

    def save_preset(self, kind: str, name: str, data: dict) -> int:
        """Insert or replace by (kind, name). kind: 'preset' (all parameters) or 'style' (prompt snippet)."""
        payload = json.dumps(data, ensure_ascii=False)
        with self.conn:
            self.conn.execute(
                "INSERT INTO sd_presets(kind, name, data, created_at) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(kind, name) DO UPDATE SET data=excluded.data", (kind, name, payload, time.time()))
            return self.conn.execute("SELECT id FROM sd_presets WHERE kind=? AND name=?", (kind, name)).fetchone()[0]

    def presets(self, kind: str) -> list[tuple[int, str, dict]]:
        rows = self.conn.execute("SELECT id, name, data FROM sd_presets WHERE kind=? ORDER BY lower(name)", (kind,)).fetchall()
        return [(r[0], r[1], json.loads(r[2])) for r in rows]

    def delete_preset(self, preset_id: int) -> None:
        with self.conn:
            self.conn.execute("DELETE FROM sd_presets WHERE id=?", (preset_id,))

    def add_history(self, rows: Iterable[dict]) -> None:
        """rows: dicts with path, seed, model, prompt, negative, params (dict), backend."""
        now = time.time()
        with self.conn:
            self.conn.executemany(
                "INSERT INTO sd_history(created_at, path, seed, model, prompt, negative, params, backend) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [(now, r["path"], r.get("seed"), r.get("model"), r.get("prompt"), r.get("negative"),
                  json.dumps(r["params"], ensure_ascii=False), r.get("backend")) for r in rows])

    def _history_where(self, query: str) -> tuple[str, list]:
        if not query:
            return "", []
        like = f"%{_like_escape(query)}%"
        return (" WHERE prompt LIKE ? ESCAPE '\\' OR negative LIKE ? ESCAPE '\\' OR CAST(seed AS TEXT)=?",
                [like, like, query.strip()])

    def history(self, query: str = "", limit: int = 200, offset: int = 0) -> list[sqlite3.Row]:
        where, args = self._history_where(query)
        return self.conn.execute(f"SELECT * FROM sd_history{where} ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?",
                                 (*args, limit, offset)).fetchall()

    def history_count(self, query: str = "") -> int:
        where, args = self._history_where(query)
        return self.conn.execute(f"SELECT COUNT(*) FROM sd_history{where}", args).fetchone()[0]

    def delete_history(self, ids: Iterable[int]) -> None:
        with self.conn:
            self.conn.executemany("DELETE FROM sd_history WHERE id=?", [(i,) for i in ids])

    def clear_history(self) -> None:
        with self.conn:
            self.conn.execute("DELETE FROM sd_history")

    QUEUE_FIELDS = {"status", "finished_at", "error", "backend", "result_count", "params", "label"}

    def queue_add(self, params: dict, label: str = "") -> int:
        with self.conn:
            pos = self.conn.execute("SELECT COALESCE(MAX(position), 0) + 1 FROM sd_queue").fetchone()[0]
            return self.conn.execute(
                "INSERT INTO sd_queue(position, status, params, label, created_at) VALUES (?, 'pending', ?, ?, ?)",
                (pos, json.dumps(params, ensure_ascii=False), label, time.time())).lastrowid

    def queue_list(self) -> list[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM sd_queue ORDER BY position, id").fetchall()

    def queue_get(self, job_id: int) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM sd_queue WHERE id=?", (job_id,)).fetchone()

    def queue_claim(self, backend: str) -> sqlite3.Row | None:
        """Atomically take the first pending job for `backend` (two backends never get the same job)."""
        conn = self.conn
        conn.execute("BEGIN IMMEDIATE")
        try:
            row = conn.execute("SELECT * FROM sd_queue WHERE status='pending' ORDER BY position, id LIMIT 1").fetchone()
            if row is not None:
                conn.execute("UPDATE sd_queue SET status='running', backend=? WHERE id=?", (backend, row["id"]))
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        return self.queue_get(row["id"]) if row is not None else None

    def queue_update(self, job_id: int, **fields) -> None:
        bad = set(fields) - self.QUEUE_FIELDS
        if bad:
            raise ValueError(f"cannot update {sorted(bad)}")
        if "params" in fields and not isinstance(fields["params"], str):
            fields["params"] = json.dumps(fields["params"], ensure_ascii=False)
        sets = ", ".join(f"{k}=?" for k in fields)
        with self.conn:
            self.conn.execute(f"UPDATE sd_queue SET {sets} WHERE id=?", (*fields.values(), job_id))

    def queue_remove(self, ids: Iterable[int]) -> None:
        with self.conn:
            self.conn.executemany("DELETE FROM sd_queue WHERE id=? AND status!='running'", [(i,) for i in ids])

    def queue_move(self, job_id: int, delta: int) -> None:
        """Swap with the neighbour above (delta<0) or below (delta>0)."""
        rows = self.queue_list()
        ids = [r["id"] for r in rows]
        if job_id not in ids:
            return
        i = ids.index(job_id)
        j = i + (-1 if delta < 0 else 1)
        if 0 <= j < len(rows):
            with self.conn:
                self.conn.execute("UPDATE sd_queue SET position=? WHERE id=?", (rows[j]["position"], rows[i]["id"]))
                self.conn.execute("UPDATE sd_queue SET position=? WHERE id=?", (rows[i]["position"], rows[j]["id"]))

    def queue_clear_finished(self) -> None:
        with self.conn:
            self.conn.execute("DELETE FROM sd_queue WHERE status IN ('done','failed','cancelled')")

    def queue_recover(self) -> int:
        """After a crash/exit: jobs that were 'running' go back to 'pending'."""
        with self.conn:
            return self.conn.execute("UPDATE sd_queue SET status='pending', backend=NULL WHERE status='running'").rowcount
