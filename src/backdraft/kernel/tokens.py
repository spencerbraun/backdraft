"""The citation token grammar: parse, format, validate.

A token is the textual name of an anchor — the thing a model transcribes into
authored text as a markdown link href: `[claim text](bd:t12-audit:p8.c3:a7f3)`.

EBNF (normative; prose copy in spec/tokens.md)::

    token       = "bd:" slug ":" locator ":" hash
    slug        = alnum-lower (alnum-lower | "-"){1,31}   ; unique per registry
    locator     = page-loc | chunk-loc | cell-loc
    page-loc    = "p" int                                 ; whole page
    chunk-loc   = "p" int "." "c" int                     ; chunk ordinal, 1-based
    cell-loc    = sheetref "!" cell [":" cell]            ; cell or rectangular range
    sheetref    = slug-sanitized sheet name (no ":" "!" whitespace)
    cell        = column-letters row-int                   ; A1 notation, uppercase
    hash        = lowercase-hex{4,8}                       ; prefix of snippet sha256

Examples: ``bd:t12-audit:p8.c3:a7f3`` · ``bd:model:rent-roll!B10:9e2f``
· ``bd:t12-audit:p8:c114`` · ``bd:model:rent-roll!B10:C12:9e2f``

Wire form: one markdown link per claim span; multiple citations are `;`-separated
inside one href (`[claim](bd:...;bd:...)`). One grammar, no alternates.

Reserved and not implemented in v0: the derivation form ``bd:calc(<expr>)``.
`parse` raises `UnsupportedTokenError` for it — recognized, not supported.

Parsing is strict: no surrounding whitespace is tolerated and no canonicalization
is performed, so `format(parse(t)) == t` for every token this module accepts.
Callers that read from documents strip first (see `kernel.claims`).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .errors import MalformedTokenError, UnsupportedTokenError

__all__ = [
    "PREFIX",
    "SEPARATOR",
    "Cell",
    "PageLocator",
    "ChunkLocator",
    "CellLocator",
    "Locator",
    "Token",
    "parse",
    "parse_locator",
    "format_token",
    "format_locator",
    "validate",
    "split_href",
    "is_token_href",
]

PREFIX = "bd:"
"""Every token starts with this."""

SEPARATOR = ";"
"""Separates multiple citations inside one markdown href."""

_RESERVED_DERIVATION = "calc("
"""Reserved derivation form: `bd:calc(<expr over tokens>)`. Grammar TBD."""

_SLUG_RE = re.compile(r"[a-z0-9][a-z0-9-]{1,31}")
_HASH_RE = re.compile(r"[0-9a-f]{4,8}")
# NOTE: the spec constrains sheetrefs to exclude ":" "!" and whitespace. We also
# exclude ";" "(" ")" because those terminate a citation or a markdown link — a
# sheet name containing them could not survive the wire form.
_SHEETREF_RE = re.compile(r"[^:!;()\s]+")
# NOTE: integers are canonical — no leading zeros — so parse/format round-trips.
_INT_RE = r"(?:0|[1-9][0-9]*)"
_PAGE_RE = re.compile(rf"p(?P<page>{_INT_RE})")
_CHUNK_RE = re.compile(rf"p(?P<page>{_INT_RE})\.c(?P<ordinal>{_INT_RE})")
_CELL_RE = re.compile(
    rf"(?P<sheet>[^:!;()\s]+)!"
    rf"(?P<col>[A-Z]+)(?P<row>{_INT_RE})"
    rf"(?::(?P<col2>[A-Z]+)(?P<row2>{_INT_RE}))?"
)


@dataclass(frozen=True, slots=True)
class Cell:
    """An A1-notation cell reference: uppercase column letters + 1-based row."""

    column: str
    row: int

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[A-Z]+", self.column):
            raise MalformedTokenError(f"cell column must be uppercase letters: {self.column!r}")
        if self.row < 1:
            raise MalformedTokenError(f"cell row must be 1-based: {self.row!r}")

    def format(self) -> str:
        return f"{self.column}{self.row}"

    def __str__(self) -> str:
        return self.format()


@dataclass(frozen=True, slots=True)
class PageLocator:
    """A whole page or sheet: `p8`."""

    page: int

    def __post_init__(self) -> None:
        if self.page < 1:
            raise MalformedTokenError(f"page numbers are 1-based: {self.page!r}")

    @property
    def kind(self) -> str:
        return "page"

    def format(self) -> str:
        return f"p{self.page}"

    def __str__(self) -> str:
        return self.format()


@dataclass(frozen=True, slots=True)
class ChunkLocator:
    """A chunk within a page: `p8.c3`. Both numbers are 1-based."""

    page: int
    ordinal: int

    def __post_init__(self) -> None:
        if self.page < 1:
            raise MalformedTokenError(f"page numbers are 1-based: {self.page!r}")
        if self.ordinal < 1:
            raise MalformedTokenError(f"chunk ordinals are 1-based: {self.ordinal!r}")

    @property
    def kind(self) -> str:
        return "chunk"

    def format(self) -> str:
        return f"p{self.page}.c{self.ordinal}"

    def __str__(self) -> str:
        return self.format()


@dataclass(frozen=True, slots=True)
class CellLocator:
    """A cell or rectangular range within a sheet: `rent-roll!B10`, `rent-roll!B10:C12`.

    `kind` is `"cell"` when `end` is absent and `"range"` when it is present,
    matching the `anchors.kind` column.
    """

    sheet: str
    cell: Cell
    end: Cell | None = None

    def __post_init__(self) -> None:
        if not _SHEETREF_RE.fullmatch(self.sheet):
            raise MalformedTokenError(f"invalid sheet reference: {self.sheet!r}")

    @property
    def kind(self) -> str:
        return "range" if self.end is not None else "cell"

    def format(self) -> str:
        span = self.cell.format()
        if self.end is not None:
            span = f"{span}:{self.end.format()}"
        return f"{self.sheet}!{span}"

    def __str__(self) -> str:
        return self.format()


type Locator = PageLocator | ChunkLocator | CellLocator


@dataclass(frozen=True, slots=True)
class Token:
    """A parsed citation token: `bd:<slug>:<locator>:<hash>`."""

    slug: str
    locator: Locator
    hash: str

    def __post_init__(self) -> None:
        if not _SLUG_RE.fullmatch(self.slug):
            raise MalformedTokenError(f"invalid slug: {self.slug!r}")
        if not _HASH_RE.fullmatch(self.hash):
            raise MalformedTokenError(f"invalid hash: {self.hash!r}")

    @property
    def kind(self) -> str:
        """The anchor kind this token names: `page` | `chunk` | `cell` | `range`."""
        return self.locator.kind

    def format(self) -> str:
        return f"{PREFIX}{self.slug}:{self.locator.format()}:{self.hash}"

    def __str__(self) -> str:
        return self.format()


def parse(text: str) -> Token:
    """Parse a token. Strict: no whitespace tolerance, no canonicalization.

    Raises `UnsupportedTokenError` for the reserved `bd:calc(...)` derivation
    form and `MalformedTokenError` for everything else that is not a token.
    """
    if not isinstance(text, str):
        raise MalformedTokenError(f"token must be a string: {text!r}")
    if not text.startswith(PREFIX):
        raise MalformedTokenError(f"token must start with {PREFIX!r}: {text!r}")
    body = text[len(PREFIX) :]
    if body.startswith(_RESERVED_DERIVATION):
        raise UnsupportedTokenError(
            f"reserved derivation form 'bd:calc(...)' is not supported in v0: {text!r}"
        )
    slug, sep, rest = body.partition(":")
    if not sep:
        raise MalformedTokenError(f"token needs slug, locator and hash segments: {text!r}")
    locator_text, sep, hash_text = rest.rpartition(":")
    if not sep:
        raise MalformedTokenError(f"token is missing its hash segment: {text!r}")
    if not _SLUG_RE.fullmatch(slug):
        raise MalformedTokenError(f"invalid slug {slug!r} in token: {text!r}")
    if not _HASH_RE.fullmatch(hash_text):
        raise MalformedTokenError(f"invalid hash {hash_text!r} in token: {text!r}")
    return Token(slug=slug, locator=parse_locator(locator_text), hash=hash_text)


def parse_locator(text: str) -> Locator:
    """Parse the locator segment of a token into a typed locator."""
    if match := _CHUNK_RE.fullmatch(text):
        return ChunkLocator(page=int(match["page"]), ordinal=int(match["ordinal"]))
    if match := _PAGE_RE.fullmatch(text):
        return PageLocator(page=int(match["page"]))
    if match := _CELL_RE.fullmatch(text):
        end = None
        if match["col2"] is not None:
            end = Cell(column=match["col2"], row=int(match["row2"]))
        return CellLocator(
            sheet=match["sheet"],
            cell=Cell(column=match["col"], row=int(match["row"])),
            end=end,
        )
    raise MalformedTokenError(f"invalid locator: {text!r}")


def format_token(slug: str, locator: Locator, hash: str) -> str:  # noqa: A002 - spec vocabulary
    """Format a token from its parts, validating them."""
    return Token(slug=slug, locator=locator, hash=hash).format()


def format_locator(locator: Locator) -> str:
    """Format a locator exactly as it appears in a token."""
    return locator.format()


def validate(text: str) -> bool:
    """True iff `text` is a token this version can parse.

    The reserved `bd:calc(...)` form is *not* valid: it is recognized but
    unsupported, and callers that must distinguish should catch the errors.
    """
    try:
        parse(text)
    except (MalformedTokenError, UnsupportedTokenError):
        return False
    return True


def split_href(href: str) -> list[str]:
    """Split a markdown href into its citation candidates.

    Multiple citations are `;`-separated. Each piece is stripped; empty pieces
    (a stray or trailing `;`) carry no token and are dropped.
    """
    return [piece for piece in (raw.strip() for raw in href.split(SEPARATOR)) if piece]


def is_token_href(href: str) -> bool:
    """True if any `;`-separated piece of `href` claims to be a backdraft token.

    Deliberately shallow: an href with a `bd:` piece is a citation href even if
    that piece is malformed, so bind reports it instead of ignoring it.
    """
    return any(piece.startswith(PREFIX) for piece in split_href(href))
