"""Watching anime (ТЗ 10.1): resume positions, 'watched' marks, and progress that flows into the watch list / AniList."""
from __future__ import annotations

from anihub.core.db import Database
from anihub.services.anilist import AniList
from anihub.sources.anime.base import Episode

WATCHED_FRACTION = 0.9          # an episode counts as watched at 90% ...
WATCHED_TAIL_MS = 90_000        # ... or when less than 1.5 min (the ending) is left
MIN_RESUME_MS = 15_000          # do not resume from the first seconds


def is_watched(position_ms: int, duration_ms: int) -> bool:
    if duration_ms <= 0:
        return False
    return position_ms >= duration_ms * WATCHED_FRACTION or duration_ms - position_ms <= WATCHED_TAIL_MS


class WatchService:
    def __init__(self, db: Database, anilist: AniList):
        self.db, self.anilist = db, anilist

    # --- links -----------------------------------------------------------------------------------

    def link(self, source: str, entry_id: str, media: dict | None) -> None:
        """Say which AniList show this title is (None removes the link)."""
        self.db.watch_set_link(source, entry_id, media)

    def linked_media(self, source: str, entry_id: str) -> dict | None:
        found = self.db.watch_link(source, entry_id)
        return found["media"] if found else None

    # --- positions ---------------------------------------------------------------------------------

    def positions(self, source: str, entry_id: str) -> dict[str, dict]:
        return {ep: {"position_ms": r["position_ms"], "duration_ms": r["duration_ms"], "watched": bool(r["watched"])}
                for ep, r in self.db.watch_positions(source, entry_id).items()}

    def resume_ms(self, source: str, entry_id: str, episode: Episode) -> int:
        row = self.db.watch_positions(source, entry_id).get(episode.id)
        if row is None or row["watched"] or row["position_ms"] < MIN_RESUME_MS:
            return 0
        return int(row["position_ms"])

    def record(self, source: str, entry_id: str, episode: Episode, position_ms: int, duration_ms: int) -> bool:
        """Remember where playback is. Returns True when this call is the one that completed the episode."""
        was = self.db.watch_positions(source, entry_id).get(episode.id)
        already = bool(was and was["watched"])
        done = already or is_watched(position_ms, duration_ms)
        self.db.watch_save(source, entry_id, episode.id, number=episode.number, position_ms=int(position_ms),
                           duration_ms=int(duration_ms), watched=done)
        if done and not already:
            self._sync_list(source, entry_id, episode)
            return True
        return False

    def mark(self, source: str, entry_id: str, episode: Episode, watched: bool) -> None:
        self.db.watch_save(source, entry_id, episode.id, number=episode.number, watched=watched,
                           position_ms=0 if not watched else None)
        if watched:
            self._sync_list(source, entry_id, episode)

    def _sync_list(self, source: str, entry_id: str, episode: Episode) -> None:
        """Watched episode N -> the linked show's progress becomes at least N (and goes to AniList when signed in)."""
        media = self.linked_media(source, entry_id)
        if media is None:
            return
        number = int(episode.number)
        row = self.db.anime_get(media["id"])
        if row is None:
            self.anilist.track(media, "CURRENT", progress=number)
        elif number > row["progress"]:
            self.anilist.set_progress(media["id"], number)

    # --- what to watch next -----------------------------------------------------------------------------

    def next_episode(self, source: str, entry_id: str, episodes: list[Episode]) -> Episode | None:
        """The first episode not watched yet (the last one when everything is watched)."""
        seen = {ep for ep, p in self.positions(source, entry_id).items() if p["watched"]}
        for episode in episodes:
            if episode.id not in seen:
                return episode
        return episodes[-1] if episodes else None
