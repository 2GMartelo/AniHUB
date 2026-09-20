"""Automatic rules (ТЗ 6.4): 'when a new item matches X, put it into collection Y / add tags / rate it'.

A rule is a dict {id, name, enabled, conditions, actions}:
  conditions (all given ones must hold; a rule without any condition never matches):
    tags_all: [tag]   the item has every one of them (a parent tag also matches items with its children)
    tags_any: [tag]   at least one of them
    tags_none: [tag]  none of them
    authors: [name]   the item's author is one of them (case-insensitive)
    sites: [site]     the item comes from one of these sources ('danbooru', 'local', 'forge'...)
    ratings: [rating] general | sensitive | questionable | explicit
    kinds: [kind]     art | sd | manga
  actions (applied to every matching item):
    collection_id, category_id, add_tags: [tag], rating, favorite: bool, stars: 0..5
"""
from __future__ import annotations

import logging
import re
import sqlite3
from typing import Iterable

from anihub.core.db import Database

log = logging.getLogger(__name__)

LIST_CONDITIONS = ("tags_all", "tags_any", "tags_none", "authors", "sites", "ratings", "kinds")
ACTION_KEYS = ("collection_id", "category_id", "add_tags", "rating", "favorite", "stars")


def _names(values: Iterable[str]) -> list[str]:
    return [v for v in (str(x).strip() for x in values) if v]


def parse_list(text: str) -> list[str]:
    """'a b, c' -> ['a', 'b', 'c'] (spaces and commas both separate; tag words use underscores)."""
    return _names(re.split(r"[\s,]+", text or ""))


def has_conditions(conditions: dict) -> bool:
    return any(conditions.get(k) for k in LIST_CONDITIONS)


def has_actions(actions: dict) -> bool:
    return bool(actions.get("collection_id") or actions.get("category_id") or actions.get("add_tags")
                or actions.get("rating") or actions.get("favorite") or actions.get("stars") is not None)


def describe_conditions(c: dict) -> str:
    parts = []
    for key, label in (("tags_all", "теги"), ("tags_any", "любой из"), ("tags_none", "без"), ("authors", "автор"),
                       ("sites", "источник"), ("ratings", "рейтинг"), ("kinds", "тип")):
        if c.get(key):
            parts.append(f"{label}: {' '.join(c[key])}")
    return "; ".join(parts)


class RuleEngine:
    def __init__(self, db: Database):
        self.db = db

    # --- matching -------------------------------------------------------------------------------

    def matches(self, conditions: dict, row: sqlite3.Row, tags: set[str], family: dict[str, set[str]]) -> bool:
        if not has_conditions(conditions):
            return False

        def fam(name: str) -> set[str]:
            return family.setdefault(name, self.db.tag_family(name))

        if any(not (fam(t) & tags) for t in conditions.get("tags_all", [])):
            return False
        any_of = conditions.get("tags_any", [])
        if any_of and not any(fam(t) & tags for t in any_of):
            return False
        if any(fam(t) & tags for t in conditions.get("tags_none", [])):
            return False
        authors = {a.lower() for a in conditions.get("authors", [])}
        if authors:
            item_authors = {a.lower() for a in re.split(r"[\s,]+", row["author"] or "") if a}
            if not authors & item_authors:
                return False
        sites = {s.lower() for s in conditions.get("sites", [])}
        if sites and (row["source_site"] or "").lower() not in sites:
            return False
        ratings = conditions.get("ratings", [])
        if ratings and row["rating"] not in ratings:
            return False
        kinds = conditions.get("kinds", [])
        if kinds and row["kind"] not in kinds:
            return False
        return True

    # --- applying -------------------------------------------------------------------------------

    def _do_actions(self, actions: dict, ids: list[int]) -> None:
        db = self.db
        try:
            if actions.get("collection_id"):
                db.add_to_collection(ids, int(actions["collection_id"]))
            if actions.get("category_id"):
                db.set_item_categories(ids, add=[int(actions["category_id"])])
        except sqlite3.IntegrityError as exc:  # the collection/category was deleted after the rule was made
            log.warning("rule action skipped: %s", exc)
        if actions.get("add_tags"):
            db.add_tags(ids, [(t, "general") for t in actions["add_tags"]])
        if actions.get("rating"):
            db.set_field(ids, "rating", actions["rating"])
        if actions.get("favorite"):
            db.set_field(ids, "favorite", 1)
        if actions.get("stars") is not None and actions.get("stars") != "":
            db.set_field(ids, "stars", int(actions["stars"]))

    def apply(self, item_ids: Iterable[int], rules: list[dict] | None = None) -> dict[int, int]:
        """Runs the enabled rules (in order) over the items. Returns {rule id: number of items it matched}.
        Rules run one after another on fresh data, so a rule that adds a tag can feed the next one."""
        ids = list(item_ids)
        rules = [r for r in (rules if rules is not None else self.db.rules()) if r["enabled"]]
        result: dict[int, int] = {}
        if not ids or not rules:
            return result
        family: dict[str, set[str]] = {}
        for rule in rules:
            matched: list[int] = []
            for row in self.db.get_items(ids):
                if row["trashed_at"] is not None:
                    continue
                if self.matches(rule["conditions"], row, set(self.db.item_tags(row["id"])), family):
                    matched.append(row["id"])
            if matched:
                self._do_actions(rule["actions"], matched)
                result[rule["id"]] = len(matched)
                if rule["actions"].get("add_tags"):
                    family.clear()  # the tag hierarchy did not change, but keep the cache honest
        return result

    def apply_all(self, kind: str | None = None, progress=None) -> dict[int, int]:
        """Runs the rules over the whole library (or one kind), in chunks."""
        sql = "SELECT id FROM items WHERE trashed_at IS NULL" + (" AND kind=?" if kind else "")
        ids = [r[0] for r in self.db.conn.execute(sql, (kind,) if kind else ())]
        total: dict[int, int] = {}
        for start in range(0, len(ids), 500):
            for rule_id, n in self.apply(ids[start:start + 500]).items():
                total[rule_id] = total.get(rule_id, 0) + n
            if progress:
                progress(min(start + 500, len(ids)), len(ids))
        return total
