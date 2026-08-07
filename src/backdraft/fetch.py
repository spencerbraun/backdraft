"""Fetching a URL into bytes an extractor can read.

Diligence folders contain links, not just files, so `ingest` accepts a URL.
This module is the whole network surface of backdraft: one GET, bounded, over
http or https only. It deliberately sits outside `extract/` — an extractor is a
pure function of a file's bytes, and staying that way is what keeps
`deterministic` honest. The CLI fetches, stages the bytes in a temporary file,
and hands that file to the ordinary ingest path; the registry never touches a
socket.

Stdlib only, on purpose: `urllib.request` already follows redirects, and the
alternative is a dependency that would ship with every install to serve one
command. What that costs is named in the DESIGN row — no JavaScript rendering,
no authentication.

The bytes are what get hashed, so the file name matters only for picking an
extractor: `filename_for` gives the staged file the suffix the server's content
type implies, and `registry.media_type_for` takes it from there. A page served
as `text/html` therefore lands on the `html` extractor exactly as a saved
`.html` file would.
"""

from __future__ import annotations

import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from email.message import Message
from pathlib import PurePosixPath
from urllib.parse import unquote, urlsplit

from .kernel.errors import BackdraftError

__all__ = [
    "MAX_BYTES",
    "SCHEMES",
    "TIMEOUT",
    "USER_AGENT",
    "FetchError",
    "Fetched",
    "fetch",
    "filename_for",
    "is_url",
]

SCHEMES = ("http", "https")
"""The only schemes `ingest` will fetch. `file://` is a path — pass the path."""

TIMEOUT = 30.0
"""Seconds to wait for the connection and for each read."""

MAX_BYTES = 32 * 1024 * 1024
"""Refuse a response larger than this rather than filling the registry with it."""

USER_AGENT = "backdraft (+https://backdraft.dev)"
"""Named honestly: a server that wants to refuse an ingest can."""

# Content type -> the suffix the staged file takes, so extractor selection is
# the ordinary suffix rule and not a second table of its own.
_SUFFIX_FOR_TYPE = {
    "text/html": ".html",
    "application/xhtml+xml": ".html",
    "text/plain": ".txt",
    "text/markdown": ".md",
    "text/csv": ".csv",
    "text/tab-separated-values": ".tsv",
    "application/pdf": ".pdf",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/vnd.ms-excel": ".xls",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
    "image/tiff": ".tif",
}

_KNOWN_SUFFIXES = frozenset(_SUFFIX_FOR_TYPE.values()) | {".htm", ".jpeg", ".tiff", ".xlsm"}
"""Suffixes a URL may carry that we trust when the content type says nothing."""

_DEFAULT_SUFFIX = ".html"
"""What an unlabelled thing at the end of an http URL is, absent evidence."""


class FetchError(BackdraftError):
    """A URL could not be fetched."""


@dataclass(frozen=True, slots=True)
class Fetched:
    """One response: where it finally came from, what it said, and when.

    `url` is the URL *after* redirects — the page actually snapshotted, and the
    one the document records, so a shortener does not become the provenance.
    """

    url: str
    data: bytes
    content_type: str
    fetched_at: str


def is_url(source: str) -> bool:
    """True if `ingest` should fetch this argument rather than open it.

    Any scheme of two or more characters counts, not just http(s): a
    `file://` or `ftp://` argument is a URL the user meant, and `fetch`
    refusing it by name beats a "no such file" about a string with a scheme in
    it. The two-character floor is what keeps a Windows `C:\\...` a path.
    """
    scheme = urlsplit(source).scheme
    return len(scheme) > 1 and scheme.isascii() and scheme.isalnum()


def fetch(url: str, *, timeout: float = TIMEOUT, max_bytes: int = MAX_BYTES) -> Fetched:
    """GET `url` and return its bytes, its content type, and the fetch time.

    Redirects are followed; the final URL is what comes back. Raises
    `FetchError` for a non-http(s) scheme, a transport failure, an error
    status, or a response over `max_bytes`.
    """
    scheme = urlsplit(url).scheme
    if scheme not in SCHEMES:
        raise FetchError(
            f"cannot fetch {scheme!r} URLs; ingest reads {' and '.join(SCHEMES)}. "
            "For a local file, pass its path rather than a URL."
        )
    request = urllib.request.Request(  # noqa: S310 - scheme checked above
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "*/*",
            # No compression: the body is stored and hashed, and an encoded
            # response would have to be decoded before either.
            "Accept-Encoding": "identity",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            final = response.geturl()
            if urlsplit(final).scheme not in SCHEMES:  # pragma: no cover - urllib guards
                raise FetchError(f"{url} redirected to a non-web URL: {final}")
            data = response.read(max_bytes + 1)
            content_type = _content_type(response.headers)
    except urllib.error.HTTPError as error:
        raise FetchError(f"{url} returned HTTP {error.code} {error.reason}") from error
    except urllib.error.URLError as error:
        raise FetchError(f"could not reach {url}: {error.reason}") from error
    except OSError as error:  # timeouts, resets, TLS failures
        raise FetchError(f"could not read {url}: {error}") from error
    if len(data) > max_bytes:
        raise FetchError(
            f"{url} is larger than the {max_bytes // (1024 * 1024)} MiB ingest limit; "
            "download it and ingest the file if you want it anyway"
        )
    return Fetched(
        url=final,
        data=data,
        content_type=content_type,
        fetched_at=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    )


def filename_for(url: str, content_type: str = "") -> str:
    """The name the staged snapshot takes: a stem from the URL, a suffix from the type.

    The stem is the URL's last path segment without its extension, or the host
    when the path is empty — so `https://example.com/reports/q4-2025` becomes
    `q4-2025.html` and its slug reads `q4-2025`. The suffix comes from the
    content type, because that is what says which extractor should run; the
    URL's own suffix is the fallback when the server labelled nothing.
    """
    parts = urlsplit(url)
    segments = [segment for segment in PurePosixPath(unquote(parts.path)).parts if segment != "/"]
    tail = segments[-1] if segments else ""
    stem = PurePosixPath(tail).stem or parts.netloc or "page"
    own = PurePosixPath(tail).suffix.lower()
    suffix = _SUFFIX_FOR_TYPE.get(content_type) or (
        own if own in _KNOWN_SUFFIXES else _DEFAULT_SUFFIX
    )
    return f"{stem}{suffix}"


def _content_type(headers: Message) -> str:
    """The response's media type, lowercased, parameters (charset, boundary) dropped."""
    value = headers.get("Content-Type", "")
    return value.split(";", 1)[0].strip().lower()
