"""A tiny local HTTP proxy that lets the built-in player play streams which need request headers.

Most anime sites answer only when the request carries their Referer (and sometimes a cookie or User-Agent). The Qt player cannot
send headers, so a source's Stream(headers=...) is played through http://127.0.0.1:<port>/s/<token>: the proxy adds the headers,
forwards Range requests (seeking) and rewrites HLS playlists so that every segment and key goes through it as well. It listens on
the loopback interface only and every address carries a random token.
"""
from __future__ import annotations

import logging
import re
import secrets
import threading
from collections import OrderedDict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urljoin, urlsplit

log = logging.getLogger(__name__)

_URI_ATTR = re.compile(r'URI="([^"]+)"')
_PASS_HEADERS = ("Content-Type", "Content-Length", "Content-Range", "Accept-Ranges", "Last-Modified", "ETag")
_MAX_TOKENS = 4000


def is_playlist(url: str, content_type: str) -> bool:
    return "mpegurl" in content_type.lower() or urlsplit(url).path.lower().endswith((".m3u8", ".m3u"))


def rewrite_playlist(text: str, base: str, wrap) -> str:
    """Every URI in an HLS playlist (segments, keys, sub-playlists, maps) -> wrap(absolute_url)."""
    out = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            out.append(line)
        elif stripped.startswith("#"):
            out.append(_URI_ATTR.sub(lambda m: f'URI="{wrap(urljoin(base, m.group(1)))}"', line))
        else:
            out.append(wrap(urljoin(base, stripped)))
    return "\n".join(out) + "\n"


class StreamProxy:
    def __init__(self, http):
        self.http = http
        self._tokens: "OrderedDict[str, tuple[str, dict]]" = OrderedDict()
        self._lock = threading.Lock()
        self._server: ThreadingHTTPServer | None = None
        self.port = 0

    # --- registry ----------------------------------------------------------------------------------------------

    def url_for(self, url: str, headers: dict[str, str] | None = None) -> str:
        """The local address that plays `url` with `headers` (starts the server on first use)."""
        self.start()
        token = secrets.token_urlsafe(12)
        suffix = urlsplit(url).path.rsplit(".", 1)[-1].lower()
        with self._lock:
            self._tokens[token] = (url, dict(headers or {}))
            while len(self._tokens) > _MAX_TOKENS:
                self._tokens.popitem(last=False)
        ext = f".{suffix}" if 1 <= len(suffix) <= 5 and suffix.isalnum() else ""          # helps the demuxer recognise the format
        return f"http://127.0.0.1:{self.port}/s/{token}{ext}"

    def lookup(self, token: str) -> tuple[str, dict] | None:
        with self._lock:
            return self._tokens.get(token)

    # --- server ------------------------------------------------------------------------------------------------

    def start(self) -> None:
        if self._server is not None:
            return
        proxy = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args) -> None:               # noqa: D401 - silence the default stderr logging
                pass

            def do_GET(self) -> None:                           # noqa: N802
                proxy._serve(self, head=False)

            def do_HEAD(self) -> None:                          # noqa: N802
                proxy._serve(self, head=True)

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._server.daemon_threads = True
        self.port = self._server.server_address[1]
        threading.Thread(target=self._server.serve_forever, name="stream-proxy", daemon=True).start()

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None

    def _serve(self, handler: BaseHTTPRequestHandler, head: bool) -> None:
        match = re.match(r"^/s/([\w-]+)(?:\.\w+)?$", handler.path.split("?", 1)[0])
        entry = self.lookup(match.group(1)) if match else None
        if entry is None:
            handler.send_error(404)
            return
        url, headers = entry
        upstream = {**headers, "Accept-Encoding": "identity"}      # the length we relay must be the length we get
        if handler.headers.get("Range"):
            upstream["Range"] = handler.headers["Range"]
        try:
            self.http._check_online(url)
            merged = self.http._merged_headers(url, upstream) or upstream
            with self.http.client.stream("HEAD" if head else "GET", url, headers=merged) as resp:
                content_type = resp.headers.get("Content-Type", "")
                if not head and resp.status_code < 400 and is_playlist(str(resp.url), content_type):
                    body = rewrite_playlist(resp.read().decode("utf-8", "replace"), str(resp.url),
                                            lambda u: self.url_for(u, headers)).encode("utf-8")
                    handler.send_response(200)
                    handler.send_header("Content-Type", "application/vnd.apple.mpegurl")
                    handler.send_header("Content-Length", str(len(body)))
                    handler.end_headers()
                    handler.wfile.write(body)
                    return
                handler.send_response(resp.status_code)
                for name in _PASS_HEADERS:
                    if name in resp.headers:
                        handler.send_header(name, resp.headers[name])
                handler.end_headers()
                if not head:
                    for chunk in resp.iter_bytes(65536):
                        handler.wfile.write(chunk)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass                                                # the player closed the connection (seek, stop)
        except Exception as exc:  # noqa: BLE001 - the player just sees a failed request
            log.warning("stream proxy: %s: %s", url, exc)
            try:
                handler.send_error(502)
            except OSError:
                pass


def proxy_for(http) -> StreamProxy:
    """The one proxy of an HttpClient (created on first use)."""
    proxy = getattr(http, "_stream_proxy", None)
    if proxy is None:
        proxy = http._stream_proxy = StreamProxy(http)
    return proxy
