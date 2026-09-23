from pathlib import Path

import httpx
import pytest

from anihub.core.config import Config
from anihub.net.http import HttpClient, HttpError


def make_client(tmp_path, handler) -> HttpClient:
    http = HttpClient(Config({}, tmp_path / "c.json"))
    http._client = httpx.Client(transport=httpx.MockTransport(handler))
    return http


def full_handler(body: bytes):
    def handler(request: httpx.Request) -> httpx.Response:
        assert "Range" not in request.headers
        return httpx.Response(200, headers={"Content-Length": str(len(body))}, content=body)
    return handler


def test_download_writes_the_file_and_reports_progress(tmp_path):
    body = b"hello world" * 100
    http = make_client(tmp_path, full_handler(body))
    seen = []
    dest = tmp_path / "out.bin"
    http.download("https://example.com/f", dest, progress=lambda d, t: seen.append((d, t)))
    assert dest.read_bytes() == body
    assert seen[-1] == (len(body), len(body))
    assert not dest.with_name(dest.name + ".part").exists()


def test_pausing_mid_download_keeps_the_part_file_and_resume_continues_with_range(tmp_path):
    # MockTransport buffers a response as one piece, so "pause after the first chunk" lands after the whole body
    # is already on disk -- what this actually verifies is that pausing stops short of finalising into `dest` and
    # that resuming issues the right Range request and finishes correctly from wherever the .part file is.
    body = b"0123456789" * 50  # 500 bytes
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        rng = request.headers.get("Range")
        calls.append(rng)
        if rng:
            start = int(rng.removeprefix("bytes=").rstrip("-"))
            chunk = body[start:]
            return httpx.Response(206, headers={"Content-Length": str(len(chunk))}, content=chunk)
        return httpx.Response(200, headers={"Content-Length": str(len(body))}, content=body)

    http = make_client(tmp_path, handler)
    dest = tmp_path / "out.bin"
    part = dest.with_name(dest.name + ".part")

    http.download("https://example.com/f", dest, paused=lambda: True)      # stop before finalising
    assert calls == [None]
    assert part.exists() and part.stat().st_size == len(body) and not dest.exists()

    partial_size = part.stat().st_size
    http.download("https://example.com/f", dest)  # resume: no more pausing
    assert calls == [None, f"bytes={partial_size}-"]
    assert dest.read_bytes() == body
    assert not part.exists()


def test_resume_restarts_cleanly_when_the_server_ignores_range(tmp_path):
    body = b"x" * 300

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"Content-Length": str(len(body))}, content=body)  # always ignores Range

    http = make_client(tmp_path, handler)
    dest = tmp_path / "out.bin"
    part = dest.with_name(dest.name + ".part")
    part.write_bytes(b"stale partial data")

    http.download("https://example.com/f", dest)
    assert dest.read_bytes() == body                                        # started over, not appended to the stale bytes
    assert not part.exists()


def test_cancelling_discards_the_part_file(tmp_path):
    http = make_client(tmp_path, full_handler(b"y" * 200))
    dest = tmp_path / "out.bin"
    with pytest.raises(HttpError, match="cancelled"):
        http.download("https://example.com/f", dest, cancelled=lambda: True)
    assert not dest.exists() and not dest.with_name(dest.name + ".part").exists()


def test_autotag_download_model_pauses_before_the_next_file(tmp_path, monkeypatch):
    from anihub.services import autotag

    monkeypatch.setattr(autotag, "MODEL_FILES", {"a.bin": "https://example.com/a", "b.bin": "https://example.com/b"})
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, headers={"Content-Length": "4"}, content=b"data")

    http = make_client(tmp_path, handler)
    model_dir = tmp_path / "model"
    autotag.download_model(http, model_dir, paused=lambda: True)
    assert calls == ["https://example.com/a"]                          # stopped before b.bin ever started
    assert (model_dir / "a.bin.part").exists() and not (model_dir / "a.bin").exists()
    assert not (model_dir / "b.bin").exists() and not (model_dir / "b.bin.part").exists()

    autotag.download_model(http, model_dir)                            # resume, no more pausing
    assert calls == ["https://example.com/a", "https://example.com/a", "https://example.com/b"]
    assert (model_dir / "a.bin").exists() and (model_dir / "b.bin").exists()
