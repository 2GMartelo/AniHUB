"""Shared HTTP layer: proxy, per-host request throttling, retries, parallel-download cap.

Everything that talks to the internet goes through here so proxy / rate limits (ТЗ 3.12, 3.13)
apply uniformly to all sources.
"""
from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Callable
from urllib.parse import urlsplit

import httpx

from anihub.core.config import Config

log = logging.getLogger(__name__)


class HttpError(Exception):
    def __init__(self, status: int, body: str = ""):
        super().__init__(f"HTTP {status}: {body[:200]}")
        self.status = status
        self.body = body


class OfflineError(HttpError):
    """Raised instead of touching the internet while offline mode is on (ТЗ 5.10)."""

    def __init__(self, url: str = ""):
        super().__init__(0, f"offline mode: {url}")


LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1", "[::1]"}


def is_local(url: str) -> bool:
    return (urlsplit(url).hostname or "") in LOCAL_HOSTS


class RateLimiter:
    """Enforces a minimum interval between requests to the same host."""

    def __init__(self):
        self._lock = threading.Lock()
        self._next: dict[str, float] = {}

    def wait(self, host: str, min_interval: float) -> None:
        with self._lock:
            now = time.monotonic()
            slot = max(now, self._next.get(host, 0.0))
            self._next[host] = slot + min_interval
        delay = slot - now
        if delay > 0:
            time.sleep(delay)


class BandwidthLimiter:
    """Shared download speed limit (ТЗ 3.13/14): every chunk written reserves its share of the bandwidth, so the total over
    all parallel downloads stays at the limit. The clock and sleep are injectable for tests."""

    def __init__(self, clock: Callable[[], float] = time.monotonic, sleep: Callable[[float], None] = time.sleep):
        self._lock = threading.Lock()
        self._next = 0.0
        self._clock, self._sleep = clock, sleep

    def consume(self, nbytes: int, bytes_per_second: float) -> float:
        """Blocks as long as needed; returns how long it waited."""
        if bytes_per_second <= 0 or nbytes <= 0:
            return 0.0
        with self._lock:
            now = self._clock()
            start = max(now, self._next)
            self._next = start + nbytes / bytes_per_second
            wait = start - now
        if wait > 0:
            self._sleep(wait)
        return max(wait, 0.0)


class HttpClient:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self._limiter = RateLimiter()
        self._lock = threading.Lock()
        self._client: httpx.Client | None = None
        self._sem = threading.BoundedSemaphore(int(cfg.get("network.max_parallel", 6)))
        self._bandwidth = BandwidthLimiter()
        self._abort_generation = 0
        self._host_headers: dict[str, Callable[[], dict[str, str]]] = {}

    def add_host_headers(self, suffix: str, headers: Callable[[], dict[str, str]]) -> None:
        """Headers sent with every request to *suffix (e.g. a Referer that an image CDN insists on, or a login cookie).
        `headers` is called per request, so a setting changed in the UI applies at once."""
        self._host_headers[suffix.lower()] = headers

    def _merged_headers(self, url: str, headers: dict | None) -> dict | None:
        if not self._host_headers:
            return headers
        host = urlsplit(url).hostname or ""
        extra: dict[str, str] = {}
        for suffix, make in self._host_headers.items():
            if host == suffix or host.endswith("." + suffix):
                extra.update(make())
        return {**extra, **(headers or {})} if extra else headers

    def abort_downloads(self) -> None:
        """Stops every download that is running right now (they raise HttpError 'cancelled'); later ones are unaffected."""
        self._abort_generation += 1

    @property
    def speed_limit(self) -> float:
        """Bytes per second, 0 = unlimited (setting: network.speed_limit_mb, MB/s)."""
        try:
            return max(float(self.cfg.get("network.speed_limit_mb", 0) or 0), 0.0) * 1_048_576
        except (TypeError, ValueError):
            return 0.0

    @property
    def offline(self) -> bool:
        return bool(self.cfg.get("network.offline", False))

    def _check_online(self, url: str) -> None:
        if self.offline and not is_local(url):
            raise OfflineError(url)

    def reconfigure(self) -> None:
        """Apply changed proxy / limits from config."""
        with self._lock:
            if self._client is not None:
                self._client.close()
                self._client = None
            self._sem = threading.BoundedSemaphore(max(1, int(self.cfg.get("network.max_parallel", 6))))

    @property
    def client(self) -> httpx.Client:
        with self._lock:
            if self._client is None:
                proxy = self.cfg.get("network.proxy") or None
                self._client = httpx.Client(
                    proxy=proxy,
                    headers={"User-Agent": self.cfg.get("network.user_agent", "AniHUB/0.1")},
                    timeout=httpx.Timeout(30.0, connect=15.0),
                    follow_redirects=True,
                )
            return self._client

    def _request(self, url: str, params=None, auth=None, throttle: bool = False, headers=None,
                 interval_ms: float | None = None) -> httpx.Response:
        self._check_online(url)
        host = urlsplit(url).netloc
        if interval_ms is None:
            interval_ms = float(self.cfg.get("network.min_interval_ms", 250))
        # A source may need to be slower than the global setting, never faster.
        interval = max(interval_ms, float(self.cfg.get("network.min_interval_ms", 250))) / 1000
        last: Exception | None = None
        for attempt in range(3):
            if throttle:
                self._limiter.wait(host, interval)
            try:
                resp = self.client.get(url, params=params, auth=auth, headers=self._merged_headers(url, headers))
            except httpx.TransportError as exc:
                last = exc
                time.sleep(1 + attempt)
                continue
            if resp.status_code == 429 or resp.status_code >= 500:
                retry_after = resp.headers.get("Retry-After", "")
                time.sleep(float(retry_after) if retry_after.isdigit() else 2 * (attempt + 1))
                last = HttpError(resp.status_code, resp.text)
                continue
            if resp.status_code >= 400:
                raise HttpError(resp.status_code, resp.text)
            return resp
        if isinstance(last, HttpError):
            raise last
        raise HttpError(0, str(last))

    def get_json(self, url: str, params=None, auth=None, headers=None, interval_ms: float | None = None):
        """API call: throttled per host."""
        resp = self._request(url, params=params, auth=auth, throttle=True, headers=headers,
                             interval_ms=interval_ms)
        if not resp.content.strip():
            return []
        return resp.json()

    def get_text(self, url: str, params=None, headers=None, interval_ms: float | None = None) -> str:
        """HTML/text page (scraping sources): throttled per host."""
        return self._request(url, params=params, throttle=True, headers=headers, interval_ms=interval_ms).text

    def post_json(self, url: str, payload: dict, headers: dict | None = None, interval_ms: float | None = None):
        """JSON POST (GraphQL APIs): throttled per host, no automatic retries on 4xx (a bad query stays bad)."""
        self._check_online(url)
        interval = max(interval_ms or 0, float(self.cfg.get("network.min_interval_ms", 250))) / 1000
        last: Exception | None = None
        for attempt in range(3):
            self._limiter.wait(urlsplit(url).netloc, interval)
            try:
                resp = self.client.post(url, json=payload, headers=self._merged_headers(url, headers))
            except httpx.TransportError as exc:
                last = exc
                time.sleep(1 + attempt)
                continue
            if resp.status_code == 429 or resp.status_code >= 500:
                retry_after = resp.headers.get("Retry-After", "")
                time.sleep(min(float(retry_after), 65) if retry_after.isdigit() else 2 * (attempt + 1))
                last = HttpError(resp.status_code, resp.text)
                continue
            if resp.status_code >= 400:
                raise HttpError(resp.status_code, resp.text)
            return resp.json()
        if isinstance(last, HttpError):
            raise last
        raise HttpError(0, str(last))

    def get_bytes(self, url: str) -> bytes:
        with self._sem:
            return self._request(url).content

    def download(self, url: str, dest: Path, progress: Callable[[int, int], None] | None = None,
                 cancelled: Callable[[], bool] | None = None, headers: dict | None = None) -> None:
        """Stream to dest via a .part file. progress(done, total) (total 0 if unknown); cancelled() aborts."""
        self._check_online(url)
        dest.parent.mkdir(parents=True, exist_ok=True)
        part = dest.with_name(dest.name + ".part")
        generation = self._abort_generation
        with self._sem:
            try:
                with self.client.stream("GET", url, headers=self._merged_headers(url, headers)) as resp:
                    if resp.status_code >= 400:
                        raise HttpError(resp.status_code)
                    total = int(resp.headers.get("Content-Length") or 0)
                    done = 0
                    with part.open("wb") as fh:
                        for chunk in resp.iter_bytes(65536):
                            if (cancelled and cancelled()) or generation != self._abort_generation:
                                raise HttpError(0, "cancelled")
                            self._bandwidth.consume(len(chunk), self.speed_limit)
                            fh.write(chunk)
                            done += len(chunk)
                            if progress:
                                progress(done, total)
                part.replace(dest)
            finally:
                part.unlink(missing_ok=True)
