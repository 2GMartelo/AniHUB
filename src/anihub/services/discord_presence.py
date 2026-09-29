"""Discord Rich Presence: the "what are you doing" status shown under a person's name on Discord, standard for many
desktop apps and games. Talks to a LOCALLY running Discord client over its own IPC socket via pypresence -- no
network call of AniHUB's own, no bot token, the same local mechanism games use. Needs a Discord "Application ID"
the user creates once, for free, at discord.com/developers/applications (mirrors how the AniList integration
already asks for the user's own client id + token). Every method here is best-effort and never raises: Discord not
installed, not running, or the id being empty/wrong should silently mean "no presence shown", never a crash."""
from __future__ import annotations

import time

try:
    from pypresence import Presence
except ImportError:  # pypresence itself, or one of its own dependencies, is missing
    Presence = None


class DiscordPresence:
    def __init__(self, client_id: str) -> None:
        self.client_id = client_id
        self._rpc = None
        self._connected = False
        self._start = int(time.time())

    @property
    def available(self) -> bool:
        return Presence is not None and bool(self.client_id)

    def _ensure_connected(self) -> bool:
        if not self.available:
            return False
        if self._connected:
            return True
        try:
            self._rpc = Presence(self.client_id)
            self._rpc.connect()
            self._connected = True
        except Exception:
            self._rpc = None
            self._connected = False
        return self._connected

    def update(self, state: str, details: str = "") -> None:
        if not self._ensure_connected():
            return
        try:
            self._rpc.update(state=state, details=details or None, start=self._start)
        except Exception:
            self._connected = False  # Discord likely closed meanwhile; retry the connection next time

    def close(self) -> None:
        if self._rpc is not None:
            try:
                self._rpc.close()
            except Exception:
                pass
        self._rpc = None
        self._connected = False
