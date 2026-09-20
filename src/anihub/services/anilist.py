"""AniList (ТЗ 10.3/10.4): season calendar, search, and a watch list that lives in the local DB and is mirrored to
the user's AniList account when they are signed in.

Public queries need no key. Writing to a list needs an access token: the user creates an API client at
anilist.co/settings/developer (redirect URL https://anilist.co/api/v2/oauth/pin), opens the authorize page from the app
and pastes the token shown there.
"""
from __future__ import annotations

import logging
import time
from datetime import date

from anihub.core.config import Config
from anihub.core.db import Database
from anihub.net.http import HttpClient, HttpError

log = logging.getLogger(__name__)

API = "https://graphql.anilist.co"
AUTH_URL = "https://anilist.co/api/v2/oauth/authorize?client_id={client_id}&response_type=token"
DEVELOPER_URL = "https://anilist.co/settings/developer"
PIN_REDIRECT = "https://anilist.co/api/v2/oauth/pin"

STATUSES = ("CURRENT", "PLANNING", "COMPLETED", "PAUSED", "DROPPED", "REPEATING")
SEASONS = ("WINTER", "SPRING", "SUMMER", "FALL")

MEDIA_FIELDS = """id title { romaji english native } coverImage { large } format episodes status season seasonYear
  averageScore genres description(asHtml: false) siteUrl isAdult
  nextAiringEpisode { episode airingAt } studios(isMain: true) { nodes { name } }"""

SEASON_QUERY = ("query($page:Int,$season:MediaSeason,$year:Int,$adult:Boolean){ Page(page:$page,perPage:50){ "
                "pageInfo{hasNextPage} media(season:$season,seasonYear:$year,type:ANIME,isAdult:$adult,"
                "sort:[POPULARITY_DESC]){ %s } } }" % MEDIA_FIELDS)
SEARCH_QUERY = ("query($page:Int,$q:String,$adult:Boolean){ Page(page:$page,perPage:30){ pageInfo{hasNextPage} "
                "media(search:$q,type:ANIME,isAdult:$adult,sort:[SEARCH_MATCH]){ %s } } }" % MEDIA_FIELDS)
VIEWER_QUERY = "query { Viewer { id name avatar { medium } } }"
LIST_QUERY = ("query($user:Int){ MediaListCollection(userId:$user,type:ANIME){ lists{ entries{ id mediaId status "
              "progress score(format:POINT_100) updatedAt media{ %s } } } } }" % MEDIA_FIELDS)
SAVE_MUTATION = ("mutation($mediaId:Int,$status:MediaListStatus,$progress:Int,$score:Int){ SaveMediaListEntry("
                 "mediaId:$mediaId,status:$status,progress:$progress,scoreRaw:$score){ id status progress score(format:POINT_100) } }")
DELETE_MUTATION = "mutation($id:Int){ DeleteMediaListEntry(id:$id){ deleted } }"


class AniListError(Exception):
    pass


def current_season(today: date | None = None) -> tuple[str, int]:
    """AniList seasons: winter = Dec-Feb (December already counts for the next year), spring = Mar-May,
    summer = Jun-Aug, fall = Sep-Nov."""
    today = today or date.today()
    if today.month == 12:
        return "WINTER", today.year + 1
    return SEASONS[today.month // 3 if today.month < 12 else 0], today.year


def shift_season(season: str, year: int, delta: int) -> tuple[str, int]:
    index = SEASONS.index(season) + delta
    return SEASONS[index % 4], year + index // 4


def normalize_media(m: dict) -> dict:
    """AniList media node -> the flat dict the UI works with."""
    title = m.get("title") or {}
    nxt = m.get("nextAiringEpisode") or {}
    studios = ((m.get("studios") or {}).get("nodes")) or []
    return {
        "id": m["id"], "title": title.get("english") or title.get("romaji") or title.get("native") or str(m["id"]),
        "romaji": title.get("romaji") or "", "native": title.get("native") or "",
        "cover": (m.get("coverImage") or {}).get("large") or "", "format": m.get("format") or "",
        "episodes": m.get("episodes"), "status": m.get("status") or "", "season": m.get("season") or "",
        "year": m.get("seasonYear"), "score": m.get("averageScore"), "genres": m.get("genres") or [],
        "description": _plain(m.get("description") or ""), "url": m.get("siteUrl") or "",
        "adult": bool(m.get("isAdult")), "studio": studios[0]["name"] if studios else "",
        "next_episode": nxt.get("episode"), "next_airing": nxt.get("airingAt"),
    }


def _plain(text: str) -> str:
    import re

    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    return re.sub(r"<[^>]+>", "", text).strip()


def format_airing(next_episode: int | None, airing_at: float | None, now: float | None = None) -> tuple[int, float] | None:
    """(next episode number, seconds until it airs) or None when nothing is scheduled."""
    if not next_episode or not airing_at:
        return None
    return int(next_episode), float(airing_at) - (time.time() if now is None else now)


def clamp_progress(progress: int, episodes: int | None) -> int:
    progress = max(int(progress), 0)
    return min(progress, episodes) if episodes else progress


def next_status(status: str, progress: int, episodes: int | None) -> str:
    """Watching the last episode completes the show; watching one of a planned show starts it."""
    if episodes and progress >= episodes:
        return "COMPLETED"
    if status in ("PLANNING", "PAUSED", "DROPPED") and progress > 0:
        return "CURRENT"
    return status


class AniList:
    def __init__(self, http: HttpClient, cfg: Config, db: Database):
        self.http, self.cfg, self.db = http, cfg, db

    # --- transport ------------------------------------------------------------------------------

    @property
    def token(self) -> str:
        return str(self.cfg.get("tracker.anilist.token", "") or "")

    @property
    def logged_in(self) -> bool:
        return bool(self.token)

    def _call(self, query: str, variables: dict | None = None, auth: bool = False) -> dict:
        headers = {"Accept": "application/json"}
        if auth:
            if not self.token:
                raise AniListError("not signed in")
            headers["Authorization"] = f"Bearer {self.token}"
        try:
            data = self.http.post_json(API, {"query": query, "variables": {k: v for k, v in (variables or {}).items() if v is not None}},
                                       headers=headers, interval_ms=700)
        except HttpError as exc:
            raise AniListError(str(exc)) from exc
        if data.get("errors"):
            raise AniListError("; ".join(e.get("message", "?") for e in data["errors"]))
        return data["data"]

    # --- public queries -------------------------------------------------------------------------

    def _adult_filter(self, allow_adult: bool) -> bool | None:
        return None if allow_adult else False          # None = no filter at all

    def season(self, season: str, year: int, page: int = 1, allow_adult: bool = False) -> tuple[list[dict], bool]:
        data = self._call(SEASON_QUERY, {"page": page, "season": season, "year": year, "adult": self._adult_filter(allow_adult)})
        block = data["Page"]
        return [normalize_media(m) for m in block["media"]], bool(block["pageInfo"]["hasNextPage"])

    def search(self, text: str, page: int = 1, allow_adult: bool = False) -> tuple[list[dict], bool]:
        data = self._call(SEARCH_QUERY, {"page": page, "q": text, "adult": self._adult_filter(allow_adult)})
        block = data["Page"]
        return [normalize_media(m) for m in block["media"]], bool(block["pageInfo"]["hasNextPage"])

    # --- account --------------------------------------------------------------------------------

    def authorize_url(self, client_id: str) -> str:
        return AUTH_URL.format(client_id=client_id.strip())

    def sign_in(self, token: str) -> dict:
        """Checks the pasted token; stores it only if AniList accepts it. Returns the viewer {id, name}."""
        token = token.strip()
        if not token:
            raise AniListError("empty token")
        old = self.cfg.get("tracker.anilist.token", "")
        self.cfg.set("tracker.anilist.token", token, save=False)
        try:
            viewer = self._call(VIEWER_QUERY, auth=True)["Viewer"]
        except AniListError:
            self.cfg.set("tracker.anilist.token", old, save=False)
            raise
        self.cfg.set("tracker.anilist.user_id", viewer["id"], save=False)
        self.cfg.set("tracker.anilist.user", viewer["name"], save=False)
        self.cfg.save()
        return viewer

    def sign_out(self) -> None:
        for key in ("token", "user_id", "user"):
            self.cfg.set(f"tracker.anilist.{key}", "" if key != "user_id" else 0, save=False)
        self.cfg.save()

    # --- the local list -------------------------------------------------------------------------

    def track(self, media: dict, status: str, progress: int | None = None, score: int | None = None) -> None:
        """Put the show on the list (or change it). Stored locally first; mirrored to AniList when possible."""
        existing = self.db.anime_get(media["id"])
        episodes = media.get("episodes") or (existing["episodes"] if existing else None)
        progress = existing["progress"] if progress is None and existing else (progress or 0)
        progress = clamp_progress(progress, episodes)
        score = existing["score"] if score is None and existing else (score or 0)
        if status == "COMPLETED" and episodes:
            progress = episodes
        self.db.anime_upsert(
            media_id=media["id"], title=media["title"], title_native=media.get("native"), cover_url=media.get("cover"),
            format=media.get("format"), episodes=episodes, airing_status=media.get("status"),
            next_episode=media.get("next_episode"), next_airing=media.get("next_airing"),
            status=status, progress=progress, score=int(score), synced=0, updated_at=time.time())

    def set_progress(self, media_id: int, progress: int) -> None:
        row = self.db.anime_get(media_id)
        if row is None:
            return
        progress = clamp_progress(progress, row["episodes"])
        self.db.anime_upsert(media_id=media_id, progress=progress, status=next_status(row["status"], progress, row["episodes"]),
                             synced=0, updated_at=time.time())

    def set_score(self, media_id: int, score: int) -> None:
        self.db.anime_upsert(media_id=media_id, score=max(0, min(int(score), 100)), synced=0, updated_at=time.time())

    def remove(self, media_id: int) -> None:
        row = self.db.anime_get(media_id)
        self.db.anime_delete(media_id)
        if row is not None and row["entry_id"] and self.logged_in:
            try:
                self._call(DELETE_MUTATION, {"id": row["entry_id"]}, auth=True)
            except AniListError as exc:
                log.info("could not delete the AniList entry: %s", exc)

    # --- sync -----------------------------------------------------------------------------------

    def push(self) -> int:
        """Send every locally changed entry to AniList. Returns how many were sent."""
        if not self.logged_in:
            return 0
        sent = 0
        for row in self.db.anime_unsynced():
            data = self._call(SAVE_MUTATION, {"mediaId": row["media_id"], "status": row["status"], "progress": row["progress"],
                                              "score": row["score"]}, auth=True)
            saved = data["SaveMediaListEntry"]
            self.db.anime_upsert(media_id=row["media_id"], entry_id=saved["id"], synced=1, updated_at=row["updated_at"])
            sent += 1
        return sent

    def pull(self) -> int:
        """Merge the account's list into the local one. A local change that was not sent yet wins (it will be pushed).
        Returns how many entries were added or updated."""
        if not self.logged_in:
            return 0
        user = int(self.cfg.get("tracker.anilist.user_id", 0) or 0)
        data = self._call(LIST_QUERY, {"user": user}, auth=True)
        changed = 0
        for lst in data["MediaListCollection"]["lists"]:
            for entry in lst["entries"]:
                media = normalize_media(entry["media"])
                local = self.db.anime_get(media["id"])
                if local is not None and not local["synced"]:
                    continue
                self.db.anime_upsert(
                    media_id=media["id"], title=media["title"], title_native=media["native"], cover_url=media["cover"],
                    format=media["format"], episodes=media["episodes"], airing_status=media["status"],
                    next_episode=media["next_episode"], next_airing=media["next_airing"], status=entry["status"],
                    progress=entry["progress"] or 0, score=entry["score"] or 0, entry_id=entry["id"], synced=1,
                    updated_at=float(entry.get("updatedAt") or time.time()))
                changed += 1
        return changed

    def sync(self) -> tuple[int, int]:
        """Push local changes, then pull the account. Returns (sent, received)."""
        return self.push(), self.pull()
