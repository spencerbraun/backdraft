"""Presentation helpers the renderers share: status prose, elision, quoting.

Both renderers project the same report, so both have to say the same things about
it. When the artifact and the markdown projection each carried their own copy of
these, they drifted — the same `not_shown` citation was "a valid anchor the
writer was never shown" in one and "A valid anchor, but the writer was never
shown it." in the other, which is two answers to one question.

The wording here is checked against `kernel/artifact.py`'s `LEGEND`
("citation_status"), which is the normative statement of what each status means;
these are its one-line renderings, not a second definition.

Private to `render/`: the dependency rule forbids sideways imports, so bind keeps
its own quoting even where the code looks alike.
"""

from __future__ import annotations

import re
from typing import Any

from ..kernel.model import CitationStatus

__all__ = ["STATUS_NOTE", "fetched_on", "quote_lines", "sentence", "short", "status_note"]

_ISO_DATE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})")

STATUS_NOTE: dict[CitationStatus, str] = {
    CitationStatus.DRIFTED: "the source changed after this claim was written",
    CitationStatus.NOT_SHOWN: "a valid anchor, but the writer was never shown it",
    CitationStatus.UNRESOLVED: "no anchor for this token in any generation",
    CitationStatus.MALFORMED: "the citation text is not a token",
}
"""Why a citation did not resolve, as a lowercase fragment.

`resolved` is deliberately absent: a resolved citation needs no explanation, and
`status_note` returning "" is what the callers test for.
"""


def status_note(status: CitationStatus) -> str:
    """The one-line reason for a status, or "" when there is nothing to say."""
    return STATUS_NOTE.get(status, "")


def fetched_on(value: Any) -> str:
    """The date out of a stored ISO fetch timestamp, or "" if it is not one.

    Both renderers date a fetched source's origin, and both want the day rather
    than the second: "as of" is what makes a frozen quote from a live page
    defensible, and no reader needs the milliseconds. A `fetched_at` that does
    not parse shows as nothing rather than as a broken date.
    """
    match = _ISO_DATE_RE.match(str(value or ""))
    return match.group(1) if match else ""


def sentence(text: str) -> str:
    """A fragment as a standalone sentence: capitalized, terminally punctuated.

    The markdown projection puts these after a colon, where a fragment reads
    correctly; the artifact shows them on their own, where it does not.
    """
    if not text:
        return ""
    return text[0].upper() + text[1:] + ("" if text.endswith((".", "!", "?")) else ".")


def short(text: str, *, limit: int) -> str:
    """A claim's text, collapsed to one line and elided at `limit` characters.

    `limit` is the caller's, because the two renderers have different room: an
    artifact's failure list is a styled block, a markdown list item is a line.
    """
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else flat[: limit - 1].rstrip() + "…"


def quote_lines(snippet: str) -> list[str]:
    """A verbatim snippet as markdown blockquote lines, line for line.

    NOTE: `bind.binder` has its own, on purpose — `bind` may not import `render`,
    and its References section quotes with slightly different blank-line handling
    besides.
    """
    return [f"> {line}" if line.strip() else ">" for line in snippet.splitlines() or [""]]
