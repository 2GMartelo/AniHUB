"""Anime openings and endings from AnimeThemes (animethemes.moe): search by anime title, play the audio, download it.

The community database has an open JSON API (https://api.animethemes.moe); every theme comes with an .ogg audio file.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from anihub.net.http import HttpClient, HttpError

API = "https://api.animethemes.moe"
INCLUDE = "animethemes.song.performances.artist,animethemes.animethemeentries.videos.audio"
PER_PAGE = 15


class ThemesError(Exception):
    """User-presentable error."""


@dataclass(frozen=True)
class ThemeTrack:
    anime: str
    year: int
    slug: str                 # OP1, ED2...
    title: str
    artists: str
    audio_url: str
    nsfw: bool = False

    @property
    def label(self) -> str:
        return f"{self.slug} · {self.title}" + (f" — {self.artists}" if self.artists else "")

    @property
    def filename(self) -> str:
        return safe_name(f"{self.slug} - {self.title}" + (f" - {self.artists}" if self.artists else "")) + ".ogg"


def safe_name(text: str) -> str:
    return re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", text).strip(" .")[:120] or "track"


def parse_anime(raw: dict) -> list[ThemeTrack]:
    """One anime of the API answer -> its themes that have audio."""
    tracks = []
    for theme in raw.get("animethemes") or []:
        audio, nsfw = "", False
        for entry in theme.get("animethemeentries") or []:
            for video in entry.get("videos") or []:
                link = (video.get("audio") or {}).get("link")
                if link:
                    audio, nsfw = link, bool(entry.get("nsfw"))
                    break
            if audio:
                break
        if not audio:
            continue
        song = theme.get("song") or {}
        artists = ", ".join(dict.fromkeys(
            (p.get("artist") or {}).get("name", "") for p in song.get("performances") or [] if (p.get("artist") or {}).get("name")))
        tracks.append(ThemeTrack(str(raw.get("name") or ""), int(raw.get("year") or 0), str(theme.get("slug") or theme.get("type") or ""),
                                 str(song.get("title") or theme.get("slug") or ""), artists, audio, nsfw))
    return tracks


class AnimeThemes:
    def __init__(self, http: HttpClient):
        self.http = http

    def search(self, query: str, page: int = 1) -> tuple[list[ThemeTrack], bool]:
        """(tracks of one page of anime, has_next_page). An empty query lists the newest anime."""
        params = {"include": INCLUDE, "page[size]": PER_PAGE, "page[number]": page}
        if query.strip():
            params["q"] = query.strip()
        else:
            params["sort"] = "-year"
        try:
            data = self.http.get_json(f"{API}/anime", params=params, interval_ms=500)
        except (HttpError, ValueError) as exc:
            raise ThemesError(f"AnimeThemes: {exc}") from exc
        if not isinstance(data, dict) or "anime" not in data:
            raise ThemesError("AnimeThemes: unexpected answer")
        tracks = [t for anime in data["anime"] for t in parse_anime(anime)]
        more = bool((data.get("links") or {}).get("next"))
        return tracks, more

    def download(self, track: ThemeTrack, music_root: Path, progress=None, cancelled=None) -> Path:
        """Saves the audio as <music>/<Anime>/<OP1 - Title - Artist>.ogg (the folder name is the album the Music tab shows)."""
        dest = Path(music_root) / safe_name(track.anime) / track.filename
        if dest.exists() and dest.stat().st_size > 0:
            return dest
        try:
            self.http.download(track.audio_url, dest, progress=progress, cancelled=cancelled)
        except HttpError as exc:
            raise ThemesError(f"{track.label}: {exc}") from exc
        return dest
