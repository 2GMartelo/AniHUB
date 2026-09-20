"""Helpers for turning a tag click in the viewer into a search query."""
from __future__ import annotations


def apply_tag(query: str, tag: str, mode: str) -> str:
    """mode: 'search' (replace the query), 'add' (AND the tag), 'exclude' (-tag)."""
    if mode == "search":
        return tag
    rest = [t for t in query.split() if t.lstrip("-") != tag]
    return " ".join(rest + [tag if mode == "add" else f"-{tag}"])
