"""The read side of the gate: document list, table of contents, page read, show.

The gate is the mechanism the whole design rests on: *the set of citable tokens
is exactly the set the gate emitted*. Two consequences shape every function here.

1. **Recompute nothing.** Tokens are read off `Registry.anchors_for_page`, never
   re-derived from page text. A token printed here is a token that already
   exists as a row, so it resolves later by construction.
2. **Emitting is minting.** Every anchor whose token (or whose in-band `[B10]`
   reference) reaches the output is recorded in the session ledger before the
   text is returned. Bind's `not_shown` status is what catches a token the writer
   never saw; that status is only meaningful if this module never under-records.

The registry is consumed through the pinned surface in SPEC Addendum A and
nothing else. Nothing in this module writes to `registry/`.

Output is plain ASCII and line-oriented: it is read by an agent in a terminal, so
it is scannable, and it is a contract, so it is stable enough to diff.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..kernel.claims import parse_citation
from ..kernel.errors import BackdraftError
from ..kernel.hashing import normalize
from ..kernel.model import CitationStatus
from ..kernel.tokens import CellLocator, ChunkLocator, format_locator, parse as parse_token
from ..registry import current_at, withdrawn_reason

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from ..kernel.model import Anchor, Document, Page
    from ..registry.store import Registry

__all__ = [
    "GateError",
    "cells",
    "DEFAULT_SESSION_NOTE",
    "GRAMMAR_HINT",
    "LIST_HINT",
    "TOC_PREVIEW_CHARS",
    "WITHDRAWN_HINT",
    "WITHDRAWN_SESSION_NOTE",
    "Selection",
    "Shown",
    "read",
    "render_documents",
    "render_session",
    "render_toc",
    "render_page_read",
    "require_document",
    "select_pages",
    "show",
    "source_name",
    "unit",
]


class GateError(BackdraftError):
    """The gate cannot serve this read: unknown slug, unusable selector."""


LIST_HINT = "run `backdraft read` to list what is ingested"
"""Appended wherever a slug names nothing. An agent that guessed a slug has no
way to discover the real one from the error alone, and would otherwise spend a
turn finding out. Shared with `searcher.py` so both spellings stay one."""

GRAMMAR_HINT = (
    "[Token grammar: bd:<slug>:<locator>:<hash>, locators p8, p8.c3 and "
    "sheet!B10. Copy tokens from gate output rather than editing them by hand.]"
)
"""Closes a `show` that met a token which does not parse.

A malformed token is the one failure where the reason alone does not say what to
do — the kernel names the segment that broke, and this names the shape it broke
from."""

WITHDRAWN_HINT = "Re-ingest it to bring it back: backdraft ingest {path}"
"""The way back from a withdrawal, wherever one is reported.

`forget` is the one command that takes something away, so every surface that
meets its result says how to undo it — the gate's refusal, `show`'s block, and
`forget`'s own confirmation. `{path}` is the document's `path`, which is the
source as `ingest` was given it and is therefore literally re-runnable.
"""

TOC_PREVIEW_CHARS = 120
"""How much of a page's text stands in for a missing summary (SPEC § Gate)."""

_ELLIPSIS = "..."
_PAGE_SELECTOR = re.compile(r"p(?P<first>[1-9][0-9]*)(?:-(?P<last>[1-9][0-9]*))?")
_BARE_NUMBER = re.compile(r"[1-9][0-9]*")
_MARKDOWN_RULE = re.compile(r"[\s|:-]*-[\s|:-]*")


# ---------------------------------------------------------------------------
# selection
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Selection:
    """The pages one read targets, plus the selector text that targeted them.

    `text` is echoed back verbatim in continuation hints, so the command the
    reader is told to run next is the command it just ran.
    """

    numbers: tuple[int, ...]
    text: str


def select_pages(pages: Sequence[Page], selector: str) -> Selection:
    """Resolve `p3`, `p3-5`, a sheet name, or a bare page number to page numbers.

    Sheet names win over the numeric forms so that a sheet named `p3` or `3` is
    still reachable by name. Matching is on `Page.name`, insensitive to case and
    to the `-`/space/underscore difference between a sheet name and the sheetref
    it was sanitized into at ingest.

    Raises `GateError` if the selector names nothing.
    """
    wanted = _fold(selector)
    named = [page.number for page in pages if page.name and _fold(page.name) == wanted]
    if named:
        return Selection(numbers=tuple(sorted(named)), text=selector)

    known = {page.number for page in pages}
    if match := _PAGE_SELECTOR.fullmatch(selector):
        first = int(match["first"])
        last = int(match["last"]) if match["last"] else first
        if last < first:
            raise GateError(f"page range runs backwards: {selector!r}")
        numbers = tuple(number for number in range(first, last + 1) if number in known)
        if not numbers:
            raise GateError(f"no such page: {selector!r}; {_what_exists(pages)}")
        return Selection(numbers=numbers, text=selector)

    if _BARE_NUMBER.fullmatch(selector) and int(selector) in known:
        # NOTE: the spec shows `p3`; a bare `3` is accepted because it costs
        # nothing and is what a reader types by accident.
        return Selection(numbers=(int(selector),), text=f"p{selector}")

    raise GateError(f"no page or sheet named {selector!r}; {_what_exists(pages)}")


def _what_exists(pages: Sequence[Page]) -> str:
    """What the caller could have asked for. A selector that named nothing is
    the one moment the answer is worth spending a line on, because otherwise
    the next command is a second `read` just to find out."""
    if not pages:
        return "this document has no pages"
    names = [page.name for page in pages if page.name]
    if len(names) == len(pages):
        return "sheets: " + ", ".join(names)
    numbers = sorted(page.number for page in pages)
    span = f"p{numbers[0]}" if len(numbers) == 1 else f"p{numbers[0]}-{numbers[-1]}"
    return f"this document has {span}"


def _fold(name: str) -> str:
    """Compare sheet names the way a reader types them."""
    return re.sub(r"[\s_-]+", "-", name.strip().lower())


# ---------------------------------------------------------------------------
# dispatch
# ---------------------------------------------------------------------------


def read(
    registry: Registry,
    slug: str | None = None,
    selector: str | None = None,
    *,
    session: str | None = None,
    offset: int = 0,
    limit: int | None = None,
) -> str:
    """The unified `backdraft read` dispatch.

    No arguments lists documents; a slug alone prints its table of contents;
    a slug plus a selector prints token-marked content and mints it into
    `session`. Listing and the table of contents emit no tokens, so they mint
    nothing.
    """
    if slug is None:
        return render_documents(registry)
    if selector is None:
        return render_toc(registry, slug)
    return render_page_read(
        registry, slug, selector, session=session, offset=offset, limit=limit
    )


# ---------------------------------------------------------------------------
# document list
# ---------------------------------------------------------------------------


def render_documents(registry: Registry) -> str:
    """One line per document: slug, name, media type, page count.

    The name is `source_name`'s — a filename, or a fetched page's origin URL in
    its place. A URL is long enough to wreck the layout if it joins the name
    column's width, so it does not: the column is sized on filenames alone and
    an origin overflows it, pushing that one row's later columns right rather
    than pushing every row's. The alternative sizes the whole list to the
    longest URL, which is how one 80-character address moves `pdf  3 pages`
    past column 100 on a registry that is otherwise files.

    Emits no tokens: a document is not evidence, its pages are.
    """
    documents = registry.documents()
    if not documents:
        return _block(
            ["No documents.", "", "[Ingest one with: backdraft ingest <file>]"]
        )

    rows = []
    for document in documents:
        pages = registry.pages(document.slug)
        # NOTE: page count is derived rather than read off Document, which
        # Addendum A does not carry one on.
        rows.append((document.slug, source_name(document), document.media_type, pages))

    slug_width = max(len(row[0]) for row in rows)
    # Only filenames size the name column; an origin overflows it — see above.
    # `default=0` is the all-fetched registry: no filename sizes anything, so
    # every name is a URL and the column collapses rather than padding to one.
    file_width = max(
        (len(document.filename) for document in documents if not _origin(document)),
        default=0,
    )
    media_width = max(len(row[2]) for row in rows)
    count_width = max(len(str(len(row[3]))) for row in rows)

    lines = [_plural(len(documents), "document"), ""]
    lines += [
        "  ".join(
            (
                slug.ljust(slug_width),
                name.ljust(file_width),
                media.ljust(media_width),
                f"{len(pages):>{count_width}} {unit(pages)}",
            )
        )
        for slug, name, media, pages in rows
    ]
    lines += ["", "[Table of contents: backdraft read <slug>]"]
    return _block(lines)


# ---------------------------------------------------------------------------
# table of contents
# ---------------------------------------------------------------------------


def render_toc(registry: Registry, slug: str) -> str:
    """One line per page or sheet: number, name, summary or first 120 chars.

    Emits no tokens: a preview is not a receipt, and a reader that cites from a
    table of contents is citing text it was shown only in part.
    """
    document = require_document(registry, slug)
    pages = registry.pages(slug)
    if not pages:
        return _block([_document_headline(document, pages), "", "(no pages)"])

    labels = [f"p{page.number}" for page in pages]
    label_width = max(len(label) for label in labels)
    names = [page.name or "" for page in pages]
    name_width = max(len(name) for name in names)

    lines = [_document_headline(document, pages), ""]
    for page, label, name in zip(pages, labels, names, strict=True):
        cells = [label.ljust(label_width)]
        if name_width:
            cells.append(name.ljust(name_width))
        cells.append(_preview(page))
        lines.append("  ".join(cells).rstrip())

    first = pages[0]
    lines += ["", f"[Read one: backdraft read {slug} p{first.number}]"]
    if len(pages) > 1 and first.kind == "page":
        lines.append(
            f"[Read a range: backdraft read {slug} p{first.number}-{pages[-1].number}]"
        )
    if first.name:
        lines.append(f'[Read by name: backdraft read {slug} "{first.name}"]')
    return _block(lines)


def _preview(page: Page) -> str:
    """A page's summary, or its opening text collapsed onto one line."""
    if page.summary:
        return normalize(page.summary)
    text = normalize(page.text)
    if len(text) <= TOC_PREVIEW_CHARS:
        return text
    return text[:TOC_PREVIEW_CHARS] + _ELLIPSIS


# ---------------------------------------------------------------------------
# page read
# ---------------------------------------------------------------------------


def render_page_read(
    registry: Registry,
    slug: str,
    selector: str,
    *,
    session: str | None = None,
    offset: int = 0,
    limit: int | None = None,
) -> str:
    """Token-marked content for the selected pages, minted into `session`.

    PDF pages render one chunk per token: `[bd:slug:p3.c1:a7f3]` alone on a line
    above the chunk's verbatim snippet, chunks separated by a blank line. Sheets
    render `Page.text` unchanged — the `[B10]` references are already in band —
    under a header line carrying the page token.

    Windowing shares one budget across the whole request, counted in the unit
    each page kind is native to: characters for `page`, rows for `sheet`.
    `offset` skips that many units and `limit` caps how many are shown; a
    continuation hint reports the window and the command that reads the next one.
    NOTE: windows never cut a chunk or a row in half, so `offset` snaps outward
    to the enclosing unit. A token is never printed above partial text.

    Every anchor shown is recorded, including the cell anchors a sheet window
    exposes by their in-band references but does not print tokens for.
    """
    if offset < 0:
        raise GateError(f"offset must not be negative: {offset!r}")
    if limit is not None and limit < 0:
        raise GateError(f"limit must not be negative: {limit!r}")

    document = require_document(registry, slug)
    pages = registry.pages(slug)
    selection = select_pages(pages, selector)
    by_number = {page.number: page for page in pages}
    total_pages = len(pages)

    window = _Window(offset=offset, limit=limit)
    blocks: list[str] = []
    minted: list[int] = []
    # NOTE: one unit name for the whole request, taken from the first page. An
    # extraction is all pages or all sheets, so a mixed selection cannot arise.
    unit = "rows" if by_number[selection.numbers[0]].kind == "sheet" else "chars"
    for number in selection.numbers:
        page = by_number[number]
        anchors = registry.anchors_for_page(slug, number)
        if page.kind == "sheet":
            block, shown = _render_sheet(document, page, anchors, total_pages, window)
        else:
            block, shown = _render_page(document, page, anchors, total_pages, window)
        if block:
            blocks.append(block)
        minted.extend(shown)

    _mint(registry, session, minted)

    lines = "\n\n".join(blocks).split("\n") if blocks else ["(nothing to show at this offset)"]
    if (hint := window.hint(slug, selection.text, unit)) is not None:
        lines += ["", hint]
    return _block(lines)


@dataclass(slots=True)
class _Window:
    """The shared offset/limit budget for one read, in page-native units.

    `consumed` counts units skipped or shown so far; `total` counts every unit
    the request covers, whether shown or not, so the hint can say how much is
    left.
    """

    offset: int
    limit: int | None
    consumed: int = 0
    shown: int = 0
    start: int | None = None
    total: int = 0
    full: bool = False

    @property
    def open(self) -> bool:
        """True while the window is neither still skipping nor already closed."""
        return not self.full and self.consumed >= self.offset

    def take(self, size: int) -> bool:
        """Offer one indivisible group of `size` units. True if it is shown.

        A group is shown whole or not at all, so `offset` snaps outward to the
        enclosing group and a group larger than `limit` is still shown when it is
        the first one — a read never prints a token above partial text.

        The first group that will not fit closes the window for good: a window is
        one contiguous run, so `--offset` on the continuation hint resumes exactly
        where this one stopped rather than at a gap.
        """
        self.total += size
        if not self.open:
            self.consumed += size
            return False
        if self.limit is not None and self.shown and self.shown + size > self.limit:
            self.full = True
            self.consumed += size
            return False
        if self.start is None:
            self.start = self.consumed
        self.consumed += size
        self.shown += size
        return True

    def hint(self, slug: str, selector: str, unit: str) -> str | None:
        """The continuation line, or None when the window covered everything."""
        start = self.start if self.start is not None else min(self.offset, self.total)
        end = start + self.shown
        if start == 0 and end == self.total:
            return None
        line = f"[Showing {start}-{end} of {self.total} {unit}."
        if end < self.total:
            line += f" Continue with: backdraft read {slug} {selector} --offset {end}"
        return line + "]"


def _render_page(
    document: Document,
    page: Page,
    anchors: Sequence[Anchor],
    total_pages: int,
    window: _Window,
) -> tuple[str, list[int]]:
    """A PDF/text page as its chunks, each under its own token."""
    header = f"# {document.slug} p{page.number}  (page {page.number} of {total_pages})"
    chunks = sorted(
        (a for a in anchors if isinstance(a.locator, ChunkLocator)),
        key=lambda a: a.locator.ordinal,  # type: ignore[union-attr]
    )
    parts: list[str] = []
    minted: list[int] = []
    for anchor in chunks:
        if not window.take(len(anchor.receipt.snippet)):
            continue
        parts.append(f"[{anchor.token}]\n{anchor.receipt.snippet}")
        if anchor.id is not None:
            minted.append(anchor.id)
    if not parts:
        if not chunks and window.open:
            # NOTE: a page with no chunk anchors has no citable text; say so
            # rather than printing text no token covers.
            return f"{header}\n\n(no text on this page)", []
        return "", []
    return "\n\n".join([header, *parts]), minted


def _render_sheet(
    document: Document,
    page: Page,
    anchors: Sequence[Anchor],
    total_pages: int,
    window: _Window,
) -> tuple[str, list[int]]:
    """A sheet as its markdown table, header row repeated on every window."""
    name = page.name or f"p{page.number}"
    header = f"# {document.slug} p{page.number}  (sheet {page.number} of {total_pages}: {name})"
    page_anchor = next((a for a in anchors if a.locator.kind == "page"), None)
    if page_anchor is not None:
        header = f"{header}  [{page_anchor.token}]"

    table_header, rows = _split_table(page.text)
    shown = [row for row in rows if window.take(1)]
    if not shown:
        return "", []

    body = "\n".join([*table_header, *shown])
    minted = [page_anchor.id] if page_anchor is not None and page_anchor.id is not None else []
    minted += _cells_in(anchors, body)
    return f"{header}\n\n{body}", minted


def _split_table(text: str) -> tuple[list[str], list[str]]:
    """Separate a sheet page's header block from the table's data rows.

    The header block is *everything above the first data row*: the extractor puts
    a `## Sheet: … - Values View with cell references` title and a blank line
    above the table (`extract/xlsx.py`), then the `| Row | A | B |` column header
    and its `|---|` rule. Repeating only the first line would repeat the title and
    window the column header away, leaving continuation windows with a headerless
    table — SPEC § Gate requires the header row on every window, so the whole
    block travels with every one of them, blank line included.

    Rows are lines, so a window can never cut one in half.
    """
    lines = text.split("\n")
    header: list[str] = []
    index = 0
    while index < len(lines) and not _is_table_row(lines[index]):
        header.append(lines[index])
        index += 1
    if index < len(lines):
        header.append(lines[index])  # the column header row
        index += 1
        if index < len(lines) and _is_rule(lines[index]):
            header.append(lines[index])
            index += 1
    rows = [line for line in lines[index:] if line.strip()]
    # NOTE: a page whose text is a placeholder rather than a table (the
    # inflated-sheet case, or a sheet with no data) has no rows to repeat a header
    # above; show it whole.
    if not rows:
        return [], [line for line in lines if line.strip()]
    return _trimmed(header), rows


def _is_table_row(line: str) -> bool:
    """True for a markdown table line, which the extractor always leads with `|`."""
    return line.lstrip().startswith("|")


def _is_rule(line: str) -> bool:
    """True for a `|---|---|` separator under a table's column header."""
    return bool(_MARKDOWN_RULE.fullmatch(line))


def _trimmed(header: list[str]) -> list[str]:
    """The header block without leading or trailing blank lines.

    The blank line *between* the title and the table is content — it is what keeps
    the title from being read as part of the table — so only the edges go.
    """
    while header and not header[0].strip():
        header.pop(0)
    while header and not header[-1].strip():
        header.pop()
    return header


def _cells_in(anchors: Iterable[Anchor], text: str) -> list[int]:
    """Cell anchor ids whose in-band `[B10]` reference appears in `text`.

    Sheets do not print per-cell tokens — the spec puts the references in band
    and lets bind compose `bd:slug:sheet!B10:hash` from the registry. Those
    composed tokens must still bind `resolved`, so the cells a window exposes are
    minted exactly as if their tokens had been printed. Membership is decided on
    the rendered text itself, which needs no assumption about the table's shape.
    """
    ids: list[int] = []
    for anchor in anchors:
        locator = anchor.locator
        if not isinstance(locator, CellLocator) or locator.end is not None:
            continue
        if anchor.id is not None and f"[{locator.cell.format()}]" in text:
            ids.append(anchor.id)
    return ids


def cells(
    registry: Registry, slug: str, refs: Sequence[str], *, session: str | None = None
) -> str:
    """Mint cell tokens directly: `refs` are `sheet!REF` locators.

    The ergonomic path to citing a cell you are looking at in a windowed read —
    the alternative was searching for the cell's own value and copying the
    token off the hit. Each line mirrors a search hit: the token, then the
    verbatim value. Emitting a token records it as shown, exactly as a read
    would (the gate's whole contract).
    """
    require_document(registry, slug)
    # Folded like `read`'s sheet selector, so the name a reader types (or the
    # display name a registry stores) both land on the same sheet.
    sheet_pages = {
        _fold(page.name): (page.name, page.number)
        for page in registry.pages(slug)
        if page.kind == "sheet" and page.name
    }
    lines: list[str] = []
    minted: list[int] = []
    for ref in refs:
        sheet, separator, cell_ref = ref.partition("!")
        if not separator or not cell_ref:
            raise GateError(f"expected sheet!REF, got {ref!r} (for example rent-roll!B10)")
        found_sheet = sheet_pages.get(_fold(sheet))
        if found_sheet is None:
            known = ", ".join(sorted(name for name, _ in sheet_pages.values())) or "none"
            raise GateError(f"no sheet {sheet!r} in {slug!r}; sheets: {known}")
        _, number = found_sheet
        found = None
        for anchor in registry.anchors_for_page(slug, number):
            locator = anchor.locator
            if (
                isinstance(locator, CellLocator)
                and locator.end is None
                and locator.cell.format() == cell_ref
            ):
                found = anchor
                break
        if found is None:
            raise GateError(f"no cell {cell_ref!r} on sheet {sheet!r} (empty cells mint nothing)")
        lines.append(f"[{found.token}]  {found.receipt.snippet}")
        if found.id is not None:
            minted.append(found.id)
    _mint(registry, session, minted)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# show
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Shown:
    """One `show` run: the rendered block, and whether every token landed.

    `complete` is False when any token came back `unresolved` or `malformed` —
    the two statuses where there was nothing to show — and is what the CLI turns
    into exit 1. `drifted` leaves it True: drift showed text, and whether that
    text still supports a claim is bind's question, not a lookup's.
    """

    text: str
    complete: bool


def show(
    registry: Registry, tokens: Sequence[str], *, session: str | None = None
) -> Shown:
    """The inverse of minting: what does this token say?

    Resolution is the path bind takes, not a second reading of what a token
    means. `kernel.claims.parse_citation` decides `malformed` — the same call
    bind's kernel step makes, so the reserved `bd:calc(...)` form lands the same
    way here as there — and `Registry.resolve` decides the rest, so a status
    printed here is the status bind would print for the same token.

    Four of bind's five statuses can appear. `not_shown` cannot, by
    construction: this is the gate, so an anchor it prints is an anchor it mints,
    and a token shown here is a token the writer may cite. That is what makes
    `show` a citation surface rather than a debugging aid — the receipt an agent
    reads out of somebody's artifact becomes citable in its own document.

    Blocks print in argument order, one per token, in `read`'s shape: the token
    on its own line, the snippet verbatim underneath. A drifted token prints
    both sides of the diff and mints the anchor standing at the locator now,
    since that token is the one worth citing.

    A token whose document was *withdrawn* is the reason this command outlives
    `forget`: the anchor is found and the receipt prints, under the `unresolved`
    status `bind` gives it and the reason saying when it was withdrawn. It earns
    the way-back hint instead of the read hint, because the read the hint names
    is a read the gate would now refuse.
    """
    blocks: list[str] = []
    minted: list[int] = []
    read_hints: list[str] = []
    toc_hints: list[str] = []
    back_hints: list[str] = []
    malformed = False
    complete = True

    for text in tokens:
        citation = parse_citation(text)
        if citation.status is CitationStatus.MALFORMED:
            blocks.append(f"[{text}]  {CitationStatus.MALFORMED}\n{citation.error}")
            complete = False
            malformed = True
            continue
        resolution = registry.resolve(text)
        if resolution is None:
            slug = parse_token(text).slug  # parses by construction: not malformed
            known = registry.document(slug) is not None
            reason = _nothing_named(slug, known)
            blocks.append(f"[{text}]  {CitationStatus.UNRESOLVED}\n{reason}")
            complete = False
            # A known slug earns a hint the reason does not already carry; an
            # unknown one does not, because `_nothing_named` closed that reason
            # with `LIST_HINT` — and the same next step twice in one block is a
            # reader deciding which of two to trust.
            if known:
                _remember(toc_hints, f"[Table of contents: backdraft read {slug}]")
            continue
        anchor = resolution.anchor
        shown: tuple[Anchor | None, ...]
        document = registry.document(anchor.slug)
        if document is not None and document.withdrawn_at is not None:
            # Emitting is minting, unconditionally: this block shows the
            # receipt, so the anchor is recorded exactly as any other shown one
            # would be. What the withdrawal changes is the *status*, which is
            # `citation_for`'s to say and which bind will say again.
            blocks.append(_withdrawn_block(anchor, document))
            complete = False
            minted += [anchor.id] if anchor.id is not None else []
            _remember(back_hints, WITHDRAWN_HINT.format(path=document.path))
            continue
        if resolution.current:
            headline = _headline(anchor, CitationStatus.RESOLVED)
            blocks.append(f"{headline}\n{anchor.receipt.snippet}")
            shown = (anchor,)
        else:
            current = current_at(registry, anchor)
            blocks.append(_drift_block(anchor, current))
            shown = (anchor, current)
        # Emitting is minting: every anchor whose token reached the output.
        minted += [a.id for a in shown if a is not None and a.id is not None]
        if anchor.page_number is not None:
            _remember(
                read_hints,
                f"[Read the page: backdraft read {anchor.slug} p{anchor.page_number}]",
            )

    _mint(registry, session, minted)

    lines = "\n\n".join(blocks).split("\n") if blocks else ["(no tokens)"]
    hints = [*read_hints, *toc_hints, *(f"[{hint}]" for hint in back_hints)]
    if malformed:
        hints.append(GRAMMAR_HINT)
    return Shown(text=_block([*lines, "", *hints]), complete=complete)


def _headline(anchor: Anchor, status: CitationStatus) -> str:
    """A shown anchor's first line: the token, its status, where it lives."""
    return f"[{anchor.token}]  {status}  {anchor.slug} {format_locator(anchor.locator)}"


def _withdrawn_block(anchor: Anchor, document: Document) -> str:
    """A withdrawn source's token: the status, the reason, then the receipt.

    The receipt still prints, and that is the whole value of showing a withdrawn
    token — the person holding an artifact that cites one can still read what it
    said. The reason stands between the headline and the snippet so that nobody
    reads the evidence without meeting the fact that its source is gone from
    this registry.
    """
    return "\n".join(
        [
            _headline(anchor, CitationStatus.UNRESOLVED),
            f"{withdrawn_reason(document)}; the receipt below still reads, but "
            f"{document.slug} is no longer a source here",
            anchor.receipt.snippet,
        ]
    )


def _drift_block(anchor: Anchor, current: Anchor | None) -> str:
    """A drifted token as both sides of the diff, labelled.

    `anchor` is the superseded receipt the token names — what the writer saw —
    and `current` is what stands at that locator in the current extraction. The
    labels are the whole point: two snippets under one token, unlabelled, is a
    reader guessing which one is the evidence.
    """
    lines = [_headline(anchor, CitationStatus.DRIFTED), "cited:", anchor.receipt.snippet]
    if current is None:
        lines.append("now: nothing stands at that locator in the current extraction")
    else:
        lines += [f"now [{current.token}]:", current.receipt.snippet]
    return "\n".join(lines)


def _nothing_named(slug: str, known: bool) -> str:
    """Why a well-formed token resolved to nothing — the two cases differ.

    A slug that names no document and a slug that does are different mistakes
    with different next steps, and `unresolved` alone says neither.
    """
    if not known:
        return f"no document with slug {slug!r}; {LIST_HINT}"
    return (
        f"{slug} carries no anchor named by this token, in any extraction; "
        "the locator or the hash is wrong"
    )


def _remember(hints: list[str], hint: str) -> None:
    """Append a hint once, keeping first-seen order."""
    if hint not in hints:
        hints.append(hint)


# ---------------------------------------------------------------------------
# session
# ---------------------------------------------------------------------------


DEFAULT_SESSION_NOTE = (
    "note: this is the default session, which every run in this registry shares "
    "when nothing exported `{env}` — so what it holds is whatever anything has "
    "read here, not what this draft's author read, and `bind` judges `not_shown` "
    "against all of it. Give this draft its own with `backdraft session start "
    "--id s-<name>` and export the id it prints; that is what makes `not_shown` "
    "mean that the writer never saw it."
)
"""Said at exit 0 whenever the session is the shared default one.

Same shape as `ingest`'s poppler note and `render`'s math note: what happened,
what it costs, and the command that changes it. The default session is
documented as stable across invocations *so reads accumulate*, which is a
convenience for one agent working in one directory and a real weakening of the
system's strongest check for everybody else — and until this note it was stated
nowhere a caller would meet it. Never a failure: reading into the default
session is allowed and often right.

The wording lives here, with the rest of the block it closes; `{env}` is filled
in by the CLI, which is the layer that owns the environment variable's name (it
is `cli_context`'s, and this module may not import it — `cli_context` imports
typer and this is the gate's library half).
"""

WITHDRAWN_SESSION_NOTE = (
    "note: a row marked `withdrawn` is a source that has since been taken out of "
    "this registry with `backdraft forget`. What the session was shown from it is "
    "still what it was shown — the ledger is a record and this does not rewrite it "
    "— but that reading no longer counts as coverage: a claim citing it binds "
    "`unresolved` naming the withdrawal, so the fact needs a source still ingested."
)
"""Closes a session block holding anything from a withdrawn source.

The one place a withdrawn document is still *listed*, and it has to be: the
ledger records what a writer saw, and dropping the row would rewrite history and
leave the total disagreeing with the ledger the export carries. So it stays and
is marked — otherwise a coverage check counts anchors that can no longer be
cited, which is the "looks fine, is not" failure `forget` exists to end.
"""

EMPTY_SESSION_HINT = "[Start reading: backdraft read]"
"""Where an empty session sends the caller. `backdraft read` with no arguments
lists what is ingested, which is the first thing to know when nothing has been
shown — including the case where the registry itself is empty."""


def render_session(
    registry: Registry, session_id: str, *, source: str, note: str | None = None
) -> str:
    """What the session holds: the id, then a document and a count per document.

    The ledger is the mechanism the design rests on, and nothing read it back:
    an agent could only find out what it had been shown by binding a draft and
    counting `not_shown`, which is finding out after the draft exists. This is
    the same question asked before writing.

    Emits no tokens — counting what was shown is not being shown it, and a
    coverage check that minted would answer its own question.

    A row whose source has since been withdrawn is kept and marked rather than
    dropped — see `WITHDRAWN_SESSION_NOTE` for why the ledger is the one place a
    withdrawn document still appears.

    `source` names which rule chose the id — the `--session` flag, the
    environment variable, or the default — and `note`, when there is one, closes
    the block. Both come from the CLI: this module is the gate's library half and
    reads no environment, and the only note there is today is
    `DEFAULT_SESSION_NOTE`, whose text is here.
    """
    rows = registry.shown_by_document(session_id)
    total = sum(count for _, count in rows)
    lines = [f"session {session_id}  (from {source})", ""]
    if not rows:
        lines += [
            "nothing shown yet — a citation bound against it reports `not_shown`",
            "",
            EMPTY_SESSION_HINT,
        ]
    else:
        slug_width = max(len(slug) for slug, _ in rows)
        count_width = max(len(str(count)) for _, count in rows)
        lines.append(
            f"{_plural(total, 'anchor')} shown across {_plural(len(rows), 'document')}"
        )
        lines.append("")
        marks = {slug: _withdrawn_mark(registry, slug) for slug, _ in rows}
        lines += [
            f"  {slug.ljust(slug_width)}  {count:>{count_width}}{marks[slug]}"
            for slug, count in rows
        ]
        lines += ["", "[Read more: backdraft read <slug> <page>]"]
        if any(marks.values()):
            lines += ["", WITHDRAWN_SESSION_NOTE]
    if note:
        lines += ["", note]
    return _block(lines)


def _withdrawn_mark(registry: Registry, slug: str) -> str:
    """`  withdrawn` for a source that has been withdrawn, else nothing.

    A session that holds nothing from a withdrawn source prints exactly what it
    printed before this existed, which is the byte-identity rule every display
    change here follows.
    """
    document = registry.document(slug)
    return "  withdrawn" if document is not None and document.withdrawn_at else ""


# ---------------------------------------------------------------------------
# shared
# ---------------------------------------------------------------------------


def _mint(registry: Registry, session: str | None, anchor_ids: Sequence[int]) -> None:
    """Record every emitted anchor under the session. The gate's whole contract.

    Called once per read, on the anchors that reached the output — never on the
    anchors a window skipped.
    """
    if session is None or not anchor_ids:
        return
    session_id = registry.ensure_session(session)
    registry.record_shown(session_id, sorted(set(anchor_ids)))


def require_document(registry: Registry, slug: str) -> Document:
    """The document `slug` names, or a `GateError` saying why there is none.

    The gate's one check that a slug is servable, shared by every command that
    reads one — the table of contents, a page read, `cell`, and `search --in`,
    which used to carry its own copy of the missing-slug wording.

    Two ways to have nothing to serve, and they are different mistakes. An
    unknown slug is a typo or a guess, and `LIST_HINT` says where the real ones
    are. A *withdrawn* one is a source somebody deliberately took out of this
    registry, and the reasons differ enough to be worth separating: nothing is
    wrong with the caller, the tokens minted from it still resolve, and the way
    back is to ingest the file again. Saying "no such document" for that would
    be the one thing a withdrawal must never look like — a source that vanished.
    """
    document = registry.document(slug)
    if document is None:
        raise GateError(f"no such document: {slug!r}; {LIST_HINT}")
    if document.withdrawn_at is not None:
        raise GateError(
            f"{slug} was {withdrawn_reason(document)}, so the gate no longer "
            f"serves it. Its tokens still resolve — `backdraft show <token>` "
            f"prints their receipts. {WITHDRAWN_HINT.format(path=document.path)}"
        )
    return document


def _document_headline(document: Document, pages: Sequence[Page]) -> str:
    return (
        f"{document.slug}  ({source_name(document)}, {document.media_type}, "
        f"{len(pages)} {unit(pages)})"
    )


def _origin(document: Document) -> str:
    """The URL a fetched source came from; `""` for a file.

    The one place `meta["url"]` is read on this side: `source_name` answers
    what to call the document and `render_documents` asks whether the name is
    a URL, and two readings of one key drift apart the moment the key does.
    """
    return str((document.meta or {}).get("url") or "")


def source_name(document: Document) -> str:
    """What to call a source: its origin URL where it has one, else its filename.

    A fetched page's `filename` names the temporary file the bytes were staged
    in — `fetch.filename_for` invents it from the URL's last path segment, so a
    permanent link arrives as `index.html`, a name that exists on nobody's disk.
    The URL therefore stands *in its place* rather than beside it, which is the
    2026-08-06 rule the artifact's source list already follows: showing both
    would give a reader two names for one thing and let the fictional one look
    authoritative.

    Display only. The slug, the token and everything a citation resolves through
    are untouched — "provenance, never identity" (2026-08-05).

    Public for the reason `unit` is: `ingest` and `ls` name the same document
    the gate's list names, and one owner is the only way three surfaces keep
    giving one answer.
    """
    return _origin(document) or document.filename


def unit(pages: Sequence[Page]) -> str:
    """`sheets` when every page is one, else `pages`. Singular when there is one.

    Public because the top-level CLI's `ingest` and `ls` print the same count and
    must print the same noun: a workbook the gate calls `2 sheets` was `2 pages`
    in `ls`, which reads as two commands describing two different registries.
    One owner is the only way that stays true as page kinds are added.
    """
    word = "sheet" if pages and all(page.kind == "sheet" for page in pages) else "page"
    return word if len(pages) == 1 else f"{word}s"


def _plural(count: int, word: str) -> str:
    return f"{count} {word}" if count == 1 else f"{count} {word}s"


def _block(lines: Iterable[str]) -> str:
    """Join rendered lines into the final output: no trailing blank lines."""
    return "\n".join(line.rstrip() for line in lines).rstrip("\n")
