"""Perceptual hashing for near-duplicate detection (dHash: survives resizing and re-encoding)."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage

MASK = (1 << 64) - 1


def _to_signed(value: int) -> int:
    return value - (1 << 64) if value >= (1 << 63) else value


def _to_unsigned(value: int) -> int:
    return value & MASK


def dhash(image: QImage) -> int | None:
    """64-bit difference hash, returned as a signed int so SQLite can store it in an INTEGER column."""
    if image.isNull():
        return None
    small = image.scaled(9, 8, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
    small = small.convertToFormat(QImage.Format.Format_Grayscale8)
    bits = 0
    for y in range(8):
        for x in range(8):
            bits = (bits << 1) | (1 if (small.pixel(x, y) & 0xFF) > (small.pixel(x + 1, y) & 0xFF) else 0)
    return _to_signed(bits)


def dhash_file(path: Path) -> int | None:
    return dhash(QImage(str(path)))


def hamming(a: int, b: int) -> int:
    return bin(_to_unsigned(a) ^ _to_unsigned(b)).count("1")


def find_near(rows: list[tuple[int, int]], phash: int, threshold: int) -> list[int]:
    """Ids whose hash is within `threshold` bits of `phash` (linear scan: fine for one lookup)."""
    return [item_id for item_id, other in rows if hamming(phash, other) <= threshold]


def similar_groups(rows: list[tuple[int, int]], threshold: int = 6) -> list[list[int]]:
    """Clusters of ids whose hashes are within `threshold` bits of each other (transitively).

    Avoids the O(n^2) all-pairs scan: split the 64 bits into 8 chunks; two hashes that differ in at most 7 bits
    must share at least one identical chunk (pigeonhole), so only items sharing a chunk are compared.
    """
    if not 0 <= threshold <= 7:
        raise ValueError("threshold must be 0..7")
    hashes = {item_id: _to_unsigned(p) for item_id, p in rows}
    buckets: dict[tuple[int, int], list[int]] = {}
    for item_id, h in hashes.items():
        for chunk in range(8):
            buckets.setdefault((chunk, (h >> (chunk * 8)) & 0xFF), []).append(item_id)

    parent = {i: i for i in hashes}

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for members in buckets.values():
        if len(members) < 2:
            continue
        for idx, a in enumerate(members):
            for b in members[idx + 1:]:
                if find(a) != find(b) and bin(hashes[a] ^ hashes[b]).count("1") <= threshold:
                    parent[find(a)] = find(b)
    groups: dict[int, list[int]] = {}
    for item_id in hashes:
        groups.setdefault(find(item_id), []).append(item_id)
    return [sorted(g) for g in groups.values() if len(g) > 1]
