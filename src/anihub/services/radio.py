"""Internet radio: built-in Anison.FM streams plus the user's own stations (a stream address, or a .pls / .m3u playlist)."""
from __future__ import annotations

import html
import re
from dataclasses import dataclass

ANISON_STATUS = "https://anison.fm/status.php?widget=true"


@dataclass(frozen=True)
class Station:
    name: str
    url: str
    custom: bool = False
    status_url: str = ""          # a JSON "now playing" endpoint (Anison.FM); other stations rely on the stream's own title tags


BUILTIN = [
    Station("Anison.FM · 320 kbps", "https://pool.anison.fm:9000/AniSonFM(320)", status_url=ANISON_STATUS),
    Station("Anison.FM · 128 kbps", "https://pool.anison.fm:9000/AniSonFM(128)", status_url=ANISON_STATUS),
]


def stations(cfg) -> list[Station]:
    """Built-in stations, then the user's (config `music.radios`: [{"name": ..., "url": ...}])."""
    custom = []
    for raw in cfg.get("music.radios", []) or []:
        if isinstance(raw, dict) and str(raw.get("url", "")).startswith(("http://", "https://")):
            custom.append(Station(str(raw.get("name") or raw["url"]), str(raw["url"]), custom=True))
    return BUILTIN + custom


def add_station(cfg, name: str, url: str) -> bool:
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        return False
    radios = [r for r in (cfg.get("music.radios", []) or []) if isinstance(r, dict) and r.get("url") != url]
    radios.append({"name": name.strip() or url, "url": url})
    cfg.set("music.radios", radios)
    return True


def remove_station(cfg, url: str) -> None:
    cfg.set("music.radios", [r for r in (cfg.get("music.radios", []) or []) if isinstance(r, dict) and r.get("url") != url])


def is_playlist_url(url: str) -> bool:
    path = url.split("?", 1)[0].lower()
    return path.endswith((".pls", ".m3u"))


def first_stream(text: str) -> str | None:
    """The first stream address in a .pls ('File1=http://...') or .m3u playlist."""
    for line in text.splitlines():
        line = line.strip()
        m = re.match(r"(?i)file\d*\s*=\s*(https?://\S+)", line)
        if m:
            return m.group(1)
        if line.lower().startswith(("http://", "https://")):
            return line
    return None


def now_playing(data) -> str:
    """Anison.FM status JSON -> 'Anime — Song' ('' when unknown). The site sends HTML in the field."""
    if not isinstance(data, dict):
        return ""
    text = re.sub(r"<[^>]+>", "", str(data.get("on_air") or ""))
    text = html.unescape(text).replace("\x97", "—")
    text = re.sub(r"^\s*В эфире:\s*", "", text)
    return re.sub(r"\s+", " ", text).strip()
