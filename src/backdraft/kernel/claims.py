"""Reading claims out of authored markdown.

The wire form is one markdown link per claim span — `[claim text](bd:...)` — and
nothing else: no doc names, no footnotes, no display text. Which words an anchor
supports can never be recovered later and can always be projected away, so it is
captured here, at write time.

`parse_claims` is total: it never raises. A token that does not parse becomes a
`Citation` with status `malformed` carrying the reason, because bind must report
every citation the author wrote — including the ones it cannot use.

Scope, deliberately small (NOTE: the spec is silent on each of these):

* Link text may contain balanced brackets, other inline formatting, and newlines.
* Images (`![alt](...)`) are not claims.
* An href is a citation href if any `;`-separated piece starts with `bd:`; the
  pieces that do not are reported as malformed rather than dropped.
* Code spans and fenced blocks are not special-cased — a token written inside one
  is still read as a claim. Recognizing fences would require a markdown parser,
  and a document that quotes tokens in prose is not the case worth optimizing.
"""

from __future__ import annotations

import re

from .errors import MalformedTokenError, UnsupportedTokenError
from .model import Citation, CitationStatus, Claim
from .tokens import is_token_href, parse, split_href

__all__ = ["parse_claims", "parse_citation"]

_LINK_TITLE = re.compile(r"""\s+(?:"[^"]*"|'[^']*')$""")


def parse_claims(source: str) -> list[Claim]:
    """Every claim in an authored document, in document order.

    A claim's `start`/`end` bound the whole markdown link, so
    `source[claim.start:claim.end]` is the construct bind rewrites; `claim.text`
    is the link text alone.
    """
    claims: list[Claim] = []
    index = 0
    length = len(source)
    while index < length:
        character = source[index]
        if character == "\\":
            index += 2
            continue
        if character != "[":
            index += 1
            continue
        if index > 0 and source[index - 1] == "!":
            index += 1
            continue
        link = _scan_link(source, index)
        if link is None:
            index += 1
            continue
        text_start, text_end, href, link_end = link
        if not is_token_href(href):
            index += 1
            continue
        claims.append(
            Claim(
                text=source[text_start:text_end],
                start=index,
                end=link_end,
                citations=tuple(parse_citation(piece) for piece in split_href(href)),
            )
        )
        index = link_end
    return claims


def parse_citation(token_text: str) -> Citation:
    """One citation from one token's text. Never raises.

    Unparseable tokens — including the reserved `bd:calc(...)` derivation form,
    which is recognized but unsupported in v0 — come back with status
    `malformed` and the reason in `error`.
    """
    try:
        parse(token_text)
    except (MalformedTokenError, UnsupportedTokenError) as error:
        return Citation(
            token=token_text, status=CitationStatus.MALFORMED, error=str(error)
        )
    return Citation(token=token_text, status=CitationStatus.UNRESOLVED)


def _scan_link(source: str, open_bracket: int) -> tuple[int, int, str, int] | None:
    """Scan `[text](href)` starting at `open_bracket`.

    Returns `(text_start, text_end, href, link_end)`, or None if this bracket does
    not open an inline link.
    """
    text_start = open_bracket + 1
    text_end = _scan_balanced(source, text_start, "[", "]")
    if text_end is None:
        return None
    if text_end + 1 >= len(source) or source[text_end + 1] != "(":
        return None
    href_start = text_end + 2
    href_end = _scan_balanced(source, href_start, "(", ")")
    if href_end is None:
        return None
    return (text_start, text_end, _clean_href(source[href_start:href_end]), href_end + 1)


def _scan_balanced(source: str, start: int, opener: str, closer: str) -> int | None:
    """Index of the `closer` matching an already-consumed `opener`, or None."""
    depth = 1
    index = start
    length = len(source)
    while index < length:
        character = source[index]
        if character == "\\":
            index += 2
            continue
        if character == opener:
            depth += 1
        elif character == closer:
            depth -= 1
            if depth == 0:
                return index
        index += 1
    return None


def _clean_href(raw: str) -> str:
    """The href as written, minus markdown's decorations.

    NOTE: only a trailing quoted link title (`[x](bd:... "why")`) and enclosing
    angle brackets are removed. Interior whitespace is kept, because the reserved
    `bd:calc(...)` form contains it and a citation must be reported verbatim.
    """
    href = raw.strip()
    if href.startswith("<") and href.endswith(">"):
        href = href[1:-1].strip()
    return _LINK_TITLE.sub("", href).strip()
