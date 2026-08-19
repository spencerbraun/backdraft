"""`fetch`: the whole network surface, exercised against a local server.

Network-free by construction — `serve` binds 127.0.0.1 and answers from a
dict — but the transport is real, so redirects, status codes, content types and
the size cap are tested through `urllib` rather than around it.
"""

from __future__ import annotations

import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Iterator

import pytest

from backdraft.fetch import FetchError, fetch, filename_for, is_url

HTML = b"<html><head><title>Local</title></head><body><p>A page.</p></body></html>"


class _Routes(BaseHTTPRequestHandler):
    """Answers from `self.server.routes`: path -> (status, content type, body)."""

    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler's spelling
        status, content_type, body = self.server.routes.get(  # type: ignore[attr-defined]
            self.path, (404, "text/plain", b"no such page")
        )
        self.send_response(status)
        if status in (301, 302, 307, 308):
            self.send_header("Location", body.decode())
            body = b""
        elif content_type:
            self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_: object) -> None:  # keep the test output clean
        pass


@pytest.fixture
def serve() -> Iterator:
    """Start a server on a free loopback port; returns `routes -> base url`."""
    servers: list[ThreadingHTTPServer] = []

    def start(routes: dict[str, tuple[int, str, bytes]]) -> str:
        server = ThreadingHTTPServer(("127.0.0.1", 0), _Routes)
        server.routes = routes  # type: ignore[attr-defined]
        servers.append(server)
        # A short poll interval: the default 0.5s is all `shutdown()` time, and
        # this fixture is torn down once per test.
        threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01},
                         daemon=True).start()
        return f"http://127.0.0.1:{server.server_port}"

    yield start
    for server in servers:
        server.shutdown()
        server.server_close()


# ---- is_url -----------------------------------------------------------------


@pytest.mark.parametrize(
    "source", ["http://example.com", "https://example.com/a/b?c=1", "ftp://host/f"]
)
def test_a_scheme_makes_it_a_url(source: str) -> None:
    assert is_url(source)


@pytest.mark.parametrize(
    "source", ["notes.md", "./docs/a.pdf", "/abs/path.html", "C:\\docs\\a.pdf", ""]
)
def test_a_path_is_not_a_url(source: str) -> None:
    """A one-letter 'scheme' is a Windows drive, which is why the floor is two."""
    assert not is_url(source)


# ---- filename_for -----------------------------------------------------------


@pytest.mark.parametrize(
    ("url", "content_type", "expected"),
    [
        ("https://example.com/reports/q4-2025", "text/html", "q4-2025.html"),
        ("https://example.com/", "text/html", "example.com.html"),
        ("https://example.com", "", "example.com.html"),
        ("https://example.com/docs/report.pdf", "application/pdf", "report.pdf"),
        ("https://example.com/data.csv", "text/csv", "data.csv"),
        # The server's label wins: an .aspx that serves a PDF is a PDF.
        ("https://example.com/get.aspx", "application/pdf", "get.pdf"),
        # No label: the URL's own suffix, when it is one we know.
        ("https://example.com/a/notes.md", "", "notes.md"),
        ("https://example.com/a/thing.aspx", "", "thing.html"),
        ("https://example.com/reports/q4%202025", "text/html", "q4 2025.html"),
        ("https://example.com/a/b/?x=1#frag", "text/html", "b.html"),
    ],
)
def test_the_staged_name_carries_the_stem_and_the_type(
    url: str, content_type: str, expected: str
) -> None:
    assert filename_for(url, content_type) == expected


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        # The failure this rule exists for: two sites, one segment, one slug.
        ("https://a.example/reports/2025/index.html", "a.example-index.html"),
        ("https://b.example/docs/index.html", "b.example-index.html"),
        # Generic handlers are the same word everywhere they appear.
        ("https://example.com/w/index.php?title=Franklin&oldid=7", "example.com-index.html"),
        ("https://example.com/pages/view", "example.com-view.html"),
        # A bare id is the same problem wearing a number.
        ("https://example.com/articles/12345", "example.com-12345.html"),
        # `www.` is on every host or none, so it names nothing.
        ("https://www.example.com/index.html", "example.com-index.html"),
        # A port is not part of the site's name; two ports dedupe instead.
        ("http://127.0.0.1:8931/a/index.html", "127.0.0.1-index.html"),
    ],
)
def test_a_segment_that_names_no_page_gets_its_host_in_front(url: str, expected: str) -> None:
    """`index` and `index-2` say which is which to nobody; the host does."""
    assert filename_for(url, "text/html") == expected


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://example.com/reports/q4-2025", "q4-2025.html"),
        ("https://example.com/2025-outlook", "2025-outlook.html"),
        ("https://en.wikipedia.org/wiki/Franklin_County,_Ohio", "Franklin_County,_Ohio.html"),
    ],
)
def test_a_segment_that_names_its_page_is_left_alone(url: str, expected: str) -> None:
    """The common case must not get uglier to fix the collision case."""
    assert filename_for(url, "text/html") == expected


def test_an_empty_path_is_still_the_host_alone() -> None:
    """No segment to prefix: the host is the whole name, as it always was."""
    assert filename_for("https://example.com", "text/html") == "example.com.html"
    assert filename_for("https://example.com/", "text/html") == "example.com.html"


# ---- fetch ------------------------------------------------------------------


def test_a_page_comes_back_with_its_type_and_a_timestamp(serve) -> None:
    base = serve({"/page": (200, "text/html; charset=utf-8", HTML)})
    fetched = fetch(f"{base}/page")
    assert fetched.data == HTML
    assert fetched.content_type == "text/html"  # parameters dropped
    assert fetched.url == f"{base}/page"
    assert fetched.fetched_at.endswith("Z")


def test_redirects_are_followed_and_the_final_url_is_what_is_recorded(serve) -> None:
    """A shortener must not become the provenance."""
    base = serve(
        {
            "/short": (302, "", b"/page"),
            "/page": (200, "text/html", HTML),
        }
    )
    fetched = fetch(f"{base}/short")
    assert fetched.url == f"{base}/page"
    assert fetched.data == HTML


def test_an_error_status_names_the_status(serve) -> None:
    base = serve({})
    with pytest.raises(FetchError, match="HTTP 404"):
        fetch(f"{base}/missing")


def test_an_unreachable_host_says_so() -> None:
    """A port on loopback with nothing behind it: refused without leaving the machine.

    A hostname would be a DNS query, which is a network call even when it fails.
    """
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        dead = probe.getsockname()[1]
    with pytest.raises(FetchError, match="could not reach"):
        fetch(f"http://127.0.0.1:{dead}/page", timeout=5)


def test_a_server_that_accepts_and_never_answers_times_out() -> None:
    """A listener that completes the handshake and then says nothing.

    The likeliest real failure of the network path, and its own arm: a read
    timeout surfaces as `TimeoutError`, which `urllib` does *not* wrap in
    `URLError` the way it wraps a connect failure, so it reaches `fetch` as a
    bare `OSError`. Without that arm it would leave the CLI as a traceback
    rather than as a message.
    """
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    port = listener.getsockname()[1]
    try:
        with pytest.raises(FetchError, match="could not read"):
            fetch(f"http://127.0.0.1:{port}/hangs", timeout=0.25)
    finally:
        listener.close()


def test_a_response_over_the_cap_is_refused_by_name(serve) -> None:
    base = serve({"/big": (200, "text/html", b"x" * 5000)})
    with pytest.raises(FetchError, match="larger than"):
        fetch(f"{base}/big", max_bytes=1000)


def test_a_response_exactly_at_the_cap_is_kept(serve) -> None:
    base = serve({"/edge": (200, "text/html", b"x" * 1000)})
    assert len(fetch(f"{base}/edge", max_bytes=1000).data) == 1000


@pytest.mark.parametrize("url", ["file:///etc/passwd", "ftp://host/f", "data:text/html,x"])
def test_only_http_and_https_are_fetched(url: str) -> None:
    """`file://` in particular: `urllib` would happily read the disk."""
    with pytest.raises(FetchError, match="ingest reads http and https"):
        fetch(url)
