import contextlib
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from autoclick_pro import updater
from autoclick_pro.updater import UpdateError, UpdateInfo, check_for_update, parse_release, parse_version
from autoclick_pro.winhttp import HttpError, http_get

windows_only = pytest.mark.skipif(sys.platform != "win32", reason="WinHTTP is Windows-only")
REPO = "someone/autoclick-pro"


def release(tag="v2.5.0", url=f"https://github.com/{REPO}/releases/tag/v2.5.0", body="Notes"):
    return json.dumps({"tag_name": tag, "html_url": url, "body": body}).encode()


@pytest.mark.parametrize(
    ("candidate", "current", "expected"),
    [
        ("2.5.0", "2.1.0", True),
        ("v2.1.1", "2.1.0", True),
        ("2.1.0", "2.1.0", False),
        ("2.0.9", "2.1.0", False),
        ("10.0.0", "9.9.9", True),  # Numeric, not text, comparison.
    ],
)
def test_is_newer(candidate, current, expected):
    assert updater.is_newer(candidate, current) is expected


@pytest.mark.parametrize("bad", ["", "latest", "2.1", "2.1.0-beta", "v2.1.0.1", "2.x.0", None, 5])
def test_parse_version_rejects(bad):
    with pytest.raises(ValueError):
        parse_version(bad)


def test_api_url_and_repo_validation():
    assert updater.api_url(REPO) == f"https://api.github.com/repos/{REPO}/releases/latest"
    for bad in ("", "no-slash", "a/b/c", "a/b?x=1", "../../x", "a b/c"):
        with pytest.raises(UpdateError):
            updater.api_url(bad)


def test_unconfigured_source_is_an_error():
    with pytest.raises(UpdateError, match="not configured"):
        check_for_update(repo="", current="2.1.0", fetch=lambda u: b"")


@pytest.mark.parametrize(
    ("url", "safe"),
    [
        (f"https://github.com/{REPO}/releases/tag/v2.5.0", True),
        (f"https://GitHub.com/{REPO.upper()}/releases", True),
        (f"http://github.com/{REPO}/releases", False),
        (f"https://github.com.evil.example/{REPO}/releases", False),
        (f"https://evil.example/{REPO}/releases", False),
        (f"https://user@github.com/{REPO}/releases", False),
        ("https://github.com/someone-else/repo/releases", False),
        (f"https://github.com:444/{REPO}/releases", False),
        ("javascript:alert(1)", False),
        ("file:///C:/Windows/System32/calc.exe", False),
        (None, False),
    ],
)
def test_release_url_safety(url, safe):
    assert updater.is_safe_release_url(url, REPO) is safe


def test_parse_release_falls_back_for_unsafe_url():
    info = parse_release(release(url="https://evil.example/download.exe"), REPO)
    assert info == UpdateInfo("2.5.0", f"https://github.com/{REPO}/releases/latest", "Notes")


@pytest.mark.parametrize(
    "document",
    [b"", b"not json", b"[]", b"{}", json.dumps({"tag_name": "nightly"}).encode(), b"\xff\xfe"],
)
def test_parse_release_rejects_garbage(document):
    with pytest.raises(UpdateError):
        parse_release(document, REPO)


def test_check_reports_newer_and_current():
    newer = check_for_update(REPO, "2.1.0", fetch=lambda u: release("v2.5.0"))
    assert newer is not None and newer.version == "2.5.0"
    assert check_for_update(REPO, "2.5.0", fetch=lambda u: release("v2.5.0")) is None
    assert check_for_update(REPO, "3.0.0", fetch=lambda u: release("v2.5.0")) is None


def test_network_failure_becomes_update_error():
    def boom(url):
        raise HttpError("Server answered HTTP 403.")

    with pytest.raises(UpdateError, match="HTTP 403"):
        check_for_update(REPO, "2.1.0", fetch=boom)


def test_notes_are_capped():
    info = parse_release(release(body="x" * 10_000), REPO)
    assert len(info.notes) == 2000


# ---------------------------------------------------------------- real WinHTTP


@pytest.fixture
def server():
    state = {"status": 200, "body": release(), "headers": {}, "hits": [], "delay": 0.0}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            import time

            state["hits"].append((self.path, self.headers.get("User-Agent"), self.headers.get("Accept")))
            time.sleep(state["delay"])
            if self.path == "/redirect":
                self.send_response(302)
                self.send_header("Location", "/latest")
                self.end_headers()
                return
            self.send_response(state["status"])
            for key, value in state["headers"].items():
                self.send_header(key, value)
            self.send_header("Content-Length", str(len(state["body"])))
            self.end_headers()
            with contextlib.suppress(OSError):
                self.wfile.write(state["body"])

        def log_message(self, *args):
            pass

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    state["base"] = f"http://127.0.0.1:{httpd.server_address[1]}"
    yield state
    httpd.shutdown()
    httpd.server_close()


@windows_only
def test_http_get_round_trip(server):
    body = http_get(server["base"] + "/latest?x=1", user_agent="AutoClickPro/9.9")
    assert json.loads(body)["tag_name"] == "v2.5.0"
    path, agent, accept = server["hits"][0]
    assert path == "/latest?x=1"
    assert agent == "AutoClickPro/9.9"
    assert accept == "application/json"


@windows_only
def test_http_get_follows_redirects(server):
    assert b"tag_name" in http_get(server["base"] + "/redirect")


@windows_only
def test_http_get_status_errors(server):
    server["status"] = 404
    with pytest.raises(HttpError, match="HTTP 404"):
        http_get(server["base"] + "/latest")


@windows_only
def test_http_get_size_cap(server):
    server["body"] = b"x" * 5000
    with pytest.raises(HttpError, match="larger than expected"):
        http_get(server["base"] + "/latest", max_bytes=1000)


@windows_only
def test_http_get_timeout(server):
    server["delay"] = 3.0
    with pytest.raises(HttpError):
        http_get(server["base"] + "/latest", timeout=0.5)


@windows_only
def test_http_get_connection_refused():
    with pytest.raises(HttpError):
        http_get("http://127.0.0.1:1/", timeout=2)


@windows_only
@pytest.mark.parametrize("url", ["ftp://example.com/x", "file:///C:/x", "//nohost", "https://"])
def test_http_get_rejects_unsupported_urls(url):
    with pytest.raises(HttpError):
        http_get(url)


@windows_only
def test_full_check_against_local_server(server):
    info = check_for_update(REPO, "2.1.0", url=server["base"] + "/latest")
    assert info is not None and info.version == "2.5.0"
    assert info.url == f"https://github.com/{REPO}/releases/tag/v2.5.0"
