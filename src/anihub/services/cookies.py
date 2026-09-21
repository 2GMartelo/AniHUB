"""Logging in to every site at once from one text file: cookies exported from a browser (the Netscape `cookies.txt` that "Get cookies.txt" and
similar extensions write, or the JSON export of EditThisCookie / Cookie-Editor), plus optional `name.key = value` lines for the things that are
not cookies (an API key, a login): `danbooru.login = me`, `danbooru.api_key = ...`, `civitai.token = ...`.

The cookies go to a jar in the config (`cookie.jar`, domain -> `a=b; c=d`) that the HTTP client adds to every request to that site, and the
sources that read a credential of their own (Pixiv's PHPSESSID) get it filled in too."""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field

DOMAIN_SPLIT = re.compile(r"^[.\s]+")
SETTING_LINE = re.compile(r"^\s*([A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)+)\s*[=:]\s*(.+?)\s*$")


@dataclass
class Cookie:
    domain: str
    name: str
    value: str
    path: str = "/"
    expires: float = 0.0             # unix time, 0 = a session cookie
    secure: bool = False

    def expired(self, now: float | None = None) -> bool:
        return bool(self.expires) and self.expires < (now or time.time())


@dataclass
class Report:
    """What an import did, for the message shown to the user."""
    cookies: int = 0
    domains: list[str] = field(default_factory=list)
    filled: list[str] = field(default_factory=list)        # human lines: "Pixiv: PHPSESSID", "danbooru.login"...
    skipped: int = 0                                        # expired cookies and lines that were not understood

    @property
    def empty(self) -> bool:
        return not self.cookies and not self.filled


def _clean_domain(domain: str) -> str:
    return DOMAIN_SPLIT.sub("", domain.strip().lower())


def _number(value) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def parse_cookies(text: str) -> list[Cookie]:
    """Netscape cookies.txt (7 tab separated fields, `#HttpOnly_` prefix allowed) or a JSON export; anything else gives no cookies."""
    text = text.lstrip("﻿")
    stripped = text.strip()
    if stripped[:1] in "[{":
        try:
            data = json.loads(stripped)
        except ValueError:
            data = None
        rows = data.get("cookies") if isinstance(data, dict) else data
        if isinstance(rows, list):
            out = []
            for row in rows:
                if isinstance(row, dict) and row.get("name") and row.get("domain") is not None:
                    out.append(Cookie(_clean_domain(str(row["domain"])), str(row["name"]), str(row.get("value", "")), str(row.get("path") or "/"),
                                      _number(row.get("expirationDate") or row.get("expires")), bool(row.get("secure"))))
            return out
    out = []
    for line in text.splitlines():
        line = line.rstrip("\r\n")
        if not line.strip():
            continue
        if line.startswith("#HttpOnly_"):
            line = line[len("#HttpOnly_"):]
        elif line.lstrip().startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) < 7:
            parts = re.split(r"\s+", line.strip(), maxsplit=6)              # a copy that lost its tabs
        if len(parts) < 7 or parts[1].upper() not in ("TRUE", "FALSE") or parts[3].upper() not in ("TRUE", "FALSE"):
            continue
        domain, _sub, path, secure, expires, name, value = parts[:7]
        try:
            exp = float(expires)
        except ValueError:
            exp = 0.0
        out.append(Cookie(_clean_domain(domain), name, value, path, exp, secure.upper() == "TRUE"))
    return out


def parse_settings(text: str) -> dict[str, str]:
    """`danbooru.login = me` lines (not cookie rows) -> {"danbooru.login": "me"}."""
    out = {}
    for line in text.splitlines():
        if "\t" in line or line.lstrip().startswith("#"):
            continue
        m = SETTING_LINE.match(line)
        if m and not m.group(1).lower().endswith(("com", "net", "org", "red", "me", "ru", "io")):     # a domain, not a setting
            out[m.group(1)] = m.group(2).strip().strip("\"'")
    return out


def jar_header(cookies: list[Cookie]) -> dict[str, str]:
    """{domain: "a=b; c=d"} without the expired ones (a later cookie of the same name wins)."""
    by_domain: dict[str, dict[str, str]] = {}
    for c in cookies:
        if c.domain and not c.expired():
            by_domain.setdefault(c.domain, {})[c.name] = c.value
    return {d: "; ".join(f"{k}={v}" for k, v in items.items()) for d, items in by_domain.items()}


def header_for(jar: dict[str, str], host: str) -> str:
    """The Cookie header for a request to `host`: the cookies of the site and of its parent domains."""
    host = (host or "").lower()
    parts = [value for domain, value in sorted(jar.items(), key=lambda kv: len(kv[0])) if host == domain or host.endswith("." + domain)]
    return "; ".join(parts)


def cookie_value(cookies: list[Cookie], domain_suffix: str, name: str) -> str:
    for c in cookies:
        if (c.domain == domain_suffix or c.domain.endswith("." + domain_suffix)) and c.name == name and not c.expired():
            return c.value
    return ""


def import_text(cfg, text: str, known_settings: set[str] | None = None) -> Report:
    """Puts everything that is in the text into the config. `known_settings`: the dotted setting names a line may set (`danbooru.login` ->
    `sources.danbooru.login`); `civitai.token` is always known. The config is saved once at the end."""
    report = Report()
    cookies = parse_cookies(text)
    fresh = [c for c in cookies if not c.expired()]
    report.skipped += len(cookies) - len(fresh)
    if fresh:
        jar = dict(cfg.get("cookie.jar") or {})
        jar.update(jar_header(fresh))
        cfg.set("cookie.jar", jar, save=False)
        report.cookies = len(fresh)
        report.domains = sorted({c.domain for c in fresh})
        pixiv = cookie_value(fresh, "pixiv.net", "PHPSESSID")
        if pixiv:                                                        # Pixiv reads its session cookie from a field of its own
            cfg.set("sources.pixiv.cookie", f"PHPSESSID={pixiv}", save=False)
            report.filled.append("Pixiv: PHPSESSID")
    settings = parse_settings(text)
    allowed = (known_settings or set()) | {"civitai.token"}
    for key, value in settings.items():
        if key in allowed:
            cfg.set(key if key == "civitai.token" else f"sources.{key}", value, save=False)
            report.filled.append(key)
        else:
            report.skipped += 1
    if not report.empty:
        cfg.save()
    return report
