"""The read side of the gate: document list, table of contents, page read.

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

from ..kernel.errors import BackdraftError
from ..kernel.hashing import normalize
from ..kernel.tokens import CellLocator, ChunkLocator

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from ..kernel.model import Anchor, Document, Page
    from ..registry.store import Registry

__all__ = [
    "GateError",
    "cells",
    "LIST_HINT",
    "TOC_PREVIEW_CHARS",
    "Selection",
    "read",
    "render_documents",
    "render_toc",
    "render_page_read",
    "select_pages",
    "unit",
]


class GateError(BackdraftError):
    """The gate cannot serve this read: unknown slug, unusable selector."""


LIST_HINT = "run `backdraft read` to list what is ingested"
"""Appended wherever a slug names nothing. An agent that guessed a slug has no
way to discover the real one from the error alone, and would otherwise spend a
turn finding out. Shared with `searcher.py` so both spellings stay one."""

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
    """One line per document: slug, filename, media type, page count.

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
        rows.append((document.slug, document.filename, document.media_type, pages))

    slug_width = max(len(row[0]) for row in rows)
    file_width = max(len(row[1]) for row in rows)
    media_width = max(len(row[2]) for row in rows)
    count_width = max(len(str(len(row[3]))) for row in rows)

    lines = [_plural(len(documents), "document"), ""]
    lines += [
        "  ".join(
            (
                slug.ljust(slug_width),
                filename.ljust(file_width),
                media.ljust(media_width),
                f"{len(pages):>{count_width}} {unit(pages)}",
            )
        )
        for slug, filename, media, pages in rows
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
    document = _require_document(registry, slug)
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

    document = _require_document(registry, slug)
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
    _require_document(registry, slug)
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


def _require_document(registry: Registry, slug: str) -> Document:
    document = registry.document(slug)
    if document is None:
        raise GateError(f"no such document: {slug!r}; {LIST_HINT}")
    return document


def _document_headline(document: Document, pages: Sequence[Page]) -> str:
    return (
        f"{document.slug}  ({document.filename}, {document.media_type}, "
        f"{len(pages)} {unit(pages)})"
    )


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
