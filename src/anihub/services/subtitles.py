"""Subtitle files (WebVTT, SRT, ASS/SSA) as timed lines of plain text, for the anime player's subtitle overlay. Styles, positions and fonts are
dropped: only the words and when they are shown."""
from __future__ import annotations

import bisect
import re
from dataclasses import dataclass

TIME = re.compile(r"(?:(\d+):)?(\d{1,2}):(\d{2})[.,](\d{1,3})")
TAGS = re.compile(r"<[^>]+>|\{[^}]*\}")


@dataclass(frozen=True)
class Cue:
    start: int             # ms
    end: int
    text: str


def _ms(match: re.Match) -> int:
    h, m, s, frac = match.groups()
    return (int(h or 0) * 3600 + int(m) * 60 + int(s)) * 1000 + int(frac.ljust(3, "0")[:3])


def _ass_ms(value: str) -> int | None:
    m = re.match(r"\s*(\d+):(\d{2}):(\d{2})[.](\d{1,3})", value)
    if not m:
        return None
    h, mi, s, frac = m.groups()
    return (int(h) * 3600 + int(mi) * 60 + int(s)) * 1000 + int(frac.ljust(3, "0")[:3])


def clean(text: str) -> str:
    text = TAGS.sub("", text).replace("\\N", "\n").replace("\\n", "\n").replace("\\h", " ")
    return "\n".join(line.strip() for line in text.replace("&nbsp;", " ").replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&").split("\n")).strip()


def parse(text: str) -> list[Cue]:
    """Cues sorted by start time. The format is recognised by its content; unknown text gives no cues."""
    text = text.lstrip("﻿").replace("\r\n", "\n").replace("\r", "\n")
    cues = _parse_ass(text) if "[Events]" in text else _parse_timed_blocks(text)
    return sorted((c for c in cues if c.text), key=lambda c: (c.start, c.end))


def _parse_timed_blocks(text: str) -> list[Cue]:
    cues = []
    for block in re.split(r"\n\s*\n", text):
        lines = [ln for ln in block.split("\n") if ln.strip()]
        for i, line in enumerate(lines):
            if "-->" in line:
                a, _, b = line.partition("-->")
                ma, mb = TIME.search(a), TIME.search(b)
                if ma and mb:
                    cues.append(Cue(_ms(ma), _ms(mb), clean("\n".join(lines[i + 1:]))))
                break
    return cues


def _parse_ass(text: str) -> list[Cue]:
    cues, fields = [], []
    in_events = False
    for line in text.split("\n"):
        line = line.strip()
        if line.startswith("["):
            in_events = line.lower() == "[events]"
            continue
        if not in_events:
            continue
        if line.lower().startswith("format:"):
            fields = [f.strip().lower() for f in line.split(":", 1)[1].split(",")]
        elif line.lower().startswith("dialogue:") and fields:
            values = line.split(":", 1)[1].split(",", len(fields) - 1)
            row = dict(zip(fields, values))
            start, end = _ass_ms(row.get("start", "")), _ass_ms(row.get("end", ""))
            if start is not None and end is not None:
                cues.append(Cue(start, end, clean(row.get("text", ""))))
    return cues


class Track:
    """The cues of one subtitle file with a fast "what is shown at this time" lookup (lines may overlap, as in ASS)."""

    def __init__(self, cues: list[Cue]):
        self.cues = cues
        self._starts = [c.start for c in cues]
        self._longest = max((c.end - c.start for c in cues), default=0)

    def at(self, ms: int) -> list[str]:
        lo = bisect.bisect_left(self._starts, ms - self._longest)
        hi = bisect.bisect_right(self._starts, ms)
        return [c.text for c in self.cues[lo:hi] if c.start <= ms < c.end]

    def __bool__(self) -> bool:
        return bool(self.cues)
