import json
import time

from anihub.core.config import Config
from anihub.net.http import HttpClient
from anihub.services import cookies as ck

NETSCAPE = (
    "# Netscape HTTP Cookie File\n"
    ".pixiv.net\tTRUE\t/\tTRUE\t2000000000\tPHPSESSID\t123_abc\n"
    "#HttpOnly_.civitai.red\tTRUE\t/\tTRUE\t0\t__Secure-civitai-token\ttok\n"
    ".smotret-anime.org\tTRUE\t/\tFALSE\t2000000000\tPHPSESSID\tanime\n"
    ".smotret-anime.org\tTRUE\t/\tFALSE\t2000000000\t_csrf\tc1\n"
    ".old.example\tTRUE\t/\tFALSE\t1000\told\tgone\n"
    "not a cookie line\n"
)


def test_netscape_parsing_httponly_expiry_and_junk():
    cookies = ck.parse_cookies(NETSCAPE)
    assert [(c.domain, c.name) for c in cookies] == [("pixiv.net", "PHPSESSID"), ("civitai.red", "__Secure-civitai-token"),
                                                     ("smotret-anime.org", "PHPSESSID"), ("smotret-anime.org", "_csrf"), ("old.example", "old")]
    assert cookies[4].expired() and not cookies[0].expired() and cookies[1].expires == 0 and not cookies[1].expired()   # 0 = a session cookie
    jar = ck.jar_header(cookies)
    assert jar["smotret-anime.org"] == "PHPSESSID=anime; _csrf=c1" and "old.example" not in jar
    assert ck.parse_cookies("just some text") == [] and ck.parse_cookies("") == []


def test_json_export_and_space_separated_copies():
    data = [{"domain": ".danbooru.donmai.us", "name": "_danbooru2_session", "value": "s", "path": "/", "expirationDate": 2e9, "secure": True}]
    assert ck.jar_header(ck.parse_cookies(json.dumps(data))) == {"danbooru.donmai.us": "_danbooru2_session=s"}
    assert ck.parse_cookies(json.dumps({"cookies": data}))[0].name == "_danbooru2_session"
    spaces = ".pixiv.net TRUE / TRUE 2000000000 PHPSESSID 42_x"                                                         # tabs lost in a copy
    assert ck.parse_cookies(spaces)[0].value == "42_x"


def test_header_for_matches_the_site_and_its_subdomains_only():
    jar = {"pixiv.net": "a=1", "www.pixiv.net": "b=2", "example.com": "c=3"}
    assert ck.header_for(jar, "www.pixiv.net") == "a=1; b=2" and ck.header_for(jar, "pixiv.net") == "a=1"
    assert ck.header_for(jar, "notpixiv.net") == "" and ck.header_for(jar, "i.pximg.net") == ""


def test_import_fills_the_jar_the_pixiv_field_and_known_settings(tmp_path):
    cfg = Config({}, tmp_path / "c.json")
    text = NETSCAPE + "danbooru.login = alice\ndanbooru.api_key: \"K3Y\"\ncivitai.token = ctok\nunknown.thing = 1\n# comment.key = 2\n"
    report = ck.import_text(cfg, text, {"danbooru.login", "danbooru.api_key"})
    assert report.cookies == 4 and report.skipped == 2 and set(report.domains) == {"pixiv.net", "civitai.red", "smotret-anime.org"}
    assert "Pixiv: PHPSESSID" in report.filled and {"danbooru.login", "danbooru.api_key", "civitai.token"} <= set(report.filled)
    assert cfg.get("sources.pixiv.cookie") == "PHPSESSID=123_abc" and cfg.get("sources.danbooru.login") == "alice"
    assert cfg.get("sources.danbooru.api_key") == "K3Y" and cfg.get("civitai.token") == "ctok"
    assert cfg.get("cookie.jar")["civitai.red"] == "__Secure-civitai-token=tok"
    saved = json.loads((tmp_path / "c.json").read_text(encoding="utf-8"))
    assert saved["cookie"]["jar"]["pixiv.net"] == "PHPSESSID=123_abc"                                                # written to disk
    again = ck.import_text(cfg, "nothing useful here")
    assert again.empty


def test_the_http_client_sends_the_jar_to_the_matching_site_only(tmp_path):
    cfg = Config({"cookie": {"jar": {"smotret-anime.org": "PHPSESSID=anime"}}}, tmp_path / "c.json")
    http = HttpClient(cfg)
    assert http._merged_headers("https://smotret-anime.org/api/x", None) == {"Cookie": "PHPSESSID=anime"}
    assert http._merged_headers("https://www.smotret-anime.org/x", {"Accept": "x"}) == {"Cookie": "PHPSESSID=anime", "Accept": "x"}
    assert http._merged_headers("https://other.org/", None) is None
    assert http._merged_headers("https://smotret-anime.org/", {"Cookie": "mine=1"}) == {"Cookie": "mine=1"}           # a source's own header wins
    http.add_host_headers("smotret-anime.org", lambda: {"Cookie": "own=1"})
    assert http._merged_headers("https://smotret-anime.org/", None) == {"Cookie": "own=1"}
