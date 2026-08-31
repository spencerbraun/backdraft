"""An in-memory stand-in for `Registry`, implementing SPEC Addendum A.

W1 owns `registry/`; W2 and W3 consume it. This is the lightweight fake Addendum
A calls for: the read surface, the ledger, and the two small result types, with
anchors built the way the real store builds them eagerly at ingest — real tokens,
real snippet hashes, one anchor row per chunk and per cell.

Anchors are supplied explicitly rather than chunked here on purpose: the gate
must recompute nothing, so a fake that hands it anchors is exactly the contract
under test.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from backdraft.kernel.hashing import snippet_hash, token_hash
from backdraft.kernel.model import Anchor, CellValue, Document, Page, Receipt
from backdraft.kernel.tokens import (
    Cell,
    CellLocator,
    ChunkLocator,
    PageLocator,
    format_token,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = [
    "FakeDocumentRegistry",
    "Ids",
    "Resolution",
    "SearchHit",
    "SearchResults",
    "pdf_document",
    "sheet_document",
    "sheet_text",
    "sheetref",
]


@dataclass(frozen=True, slots=True)
class Resolution:
    anchor: Anchor
    current: bool


@dataclass(frozen=True, slots=True)
class SearchHit:
    anchor: Anchor
    slug: str
    page_number: int


class SearchResults(list):
    """`list[SearchHit]` remembering the phrase retry and the pre-limit total."""

    def __init__(self, hits=(), *, phrase_fallback: bool = False, total: int | None = None):
        super().__init__(hits)
        self.phrase_fallback = phrase_fallback
        self.total = len(self) if total is None else total


_UNPARSEABLE = re.compile(r"[^\w\s\"]")
"""What sends the real store's FTS5 query down the phrase-retry path."""


def sheetref(name: str) -> str:
    """The sheetref a sheet name is sanitized into at ingest."""
    return re.sub(r"[\s_]+", "-", name.strip()).lower()


@dataclass(slots=True)
class _Loaded:
    document: Document
    pages: list[Page]
    anchors: dict[int, list[Anchor]]


@dataclass(slots=True)
class FakeDocumentRegistry:
    """Addendum A's read + ledger surface over dicts."""

    _docs: dict[str, _Loaded] = field(default_factory=dict)
    _sessions: dict[str, str | None] = field(default_factory=dict)
    _ledger: dict[str, set[int]] = field(default_factory=dict)
    _generated: int = 0
    closed: bool = False

    def add(self, loaded: _Loaded) -> FakeDocumentRegistry:
        self._docs[loaded.document.slug] = loaded
        return self

    # -- read side ---------------------------------------------------------

    def documents(self) -> list[Document]:
        return [loaded.document for loaded in self._docs.values()]

    def document(self, slug: str) -> Document | None:
        loaded = self._docs.get(slug)
        return loaded.document if loaded else None

    def pages(self, slug: str) -> list[Page]:
        loaded = self._docs.get(slug)
        return list(loaded.pages) if loaded else []

    def page(self, slug: str, number: int) -> Page | None:
        return next((page for page in self.pages(slug) if page.number == number), None)

    def anchors_for_page(self, slug: str, number: int) -> list[Anchor]:
        loaded = self._docs.get(slug)
        return list(loaded.anchors.get(number, [])) if loaded else []

    def resolve(self, token: str) -> Resolution | None:
        for loaded in self._docs.values():
            for anchors in loaded.anchors.values():
                for anchor in anchors:
                    if anchor.token == token:
                        return Resolution(anchor=anchor, current=True)
        return None

    def search(self, query: str, *, slug: str | None = None, limit: int = 20) -> SearchResults:
        """Naive substring match — enough to exercise rendering and minting.

        The `phrase_fallback` flag mirrors the real store's: a query carrying
        punctuation FTS5 would choke on comes back marked as retried.
        """
        needle = query.strip('"').lower()
        hits: list[SearchHit] = []
        for loaded in self._docs.values():
            if slug is not None and loaded.document.slug != slug:
                continue
            for number in sorted(loaded.anchors):
                for anchor in loaded.anchors[number]:
                    if needle in anchor.receipt.snippet.lower():
                        hits.append(
                            SearchHit(
                                anchor=anchor, slug=loaded.document.slug, page_number=number
                            )
                        )
        return SearchResults(
            hits[:limit],
            phrase_fallback=bool(_UNPARSEABLE.search(query)),
            total=len(hits),
        )

    # -- ledger ------------------------------------------------------------

    def ensure_session(self, session_id: str | None, label: str | None = None) -> str:
        if session_id is None:
            self._generated += 1
            session_id = f"generated-{self._generated}"
        self._sessions.setdefault(session_id, label)
        self._ledger.setdefault(session_id, set())
        return session_id

    def record_shown(self, session_id: str, anchor_ids: Sequence[int]) -> None:
        self._ledger.setdefault(session_id, set()).update(anchor_ids)

    def was_shown(self, session_id: str, token: str) -> bool:
        shown = self._ledger.get(session_id, set())
        return any(
            anchor.id in shown
            for loaded in self._docs.values()
            for anchors in loaded.anchors.values()
            for anchor in anchors
            if anchor.token == token
        )

    def shown_by_document(self, session_id: str) -> list[tuple[str, int]]:
        """`(slug, distinct tokens shown)`, in ingest order, empty docs omitted.

        Distinct tokens rather than anchor ids, the way the real store counts:
        one anchor per token here, so the two agree, and a fake that counted
        rows would hide the re-ingest case the real query exists to handle.
        """
        shown = self._ledger.get(session_id, set())
        rows = []
        for slug, loaded in self._docs.items():
            tokens = {
                anchor.token
                for anchors in loaded.anchors.values()
                for anchor in anchors
                if anchor.id in shown
            }
            if tokens:
                rows.append((slug, len(tokens)))
        return rows

    def close(self) -> None:
        self.closed = True

    # -- test conveniences -------------------------------------------------

    def shown_tokens(self, session_id: str) -> set[str]:
        shown = self._ledger.get(session_id, set())
        return {
            anchor.token
            for loaded in self._docs.values()
            for anchors in loaded.anchors.values()
            for anchor in anchors
            if anchor.id in shown
        }

    def sessions(self) -> dict[str, str | None]:
        return dict(self._sessions)


# ---------------------------------------------------------------------------
# builders
# ---------------------------------------------------------------------------


class Ids:
    """Anchor ids. Share one across a fixture's documents: they are primary keys."""

    def __init__(self) -> None:
        self.next = 0

    def take(self) -> int:
        self.next += 1
        return self.next


def pdf_document(
    slug: str,
    filename: str,
    pages: Sequence[Sequence[str]],
    *,
    summaries: Sequence[str | None] = (),
    ids: Ids | None = None,
    media_type: str = "pdf",
    url: str | None = None,
) -> _Loaded:
    """A `page`-kind document from explicit per-page chunk texts.

    `url` makes it a fetched source: `meta` carries the origin and the fetch
    time exactly as `Registry.ingest` stores them for a URL, which is what the
    gate reads to name the source by its page instead of its staging filename.
    """
    ids = ids or Ids()
    document = Document(
        slug=slug,
        sha256="0" * 64,
        path=f"/corpus/{filename}",
        filename=filename,
        media_type=media_type,  # type: ignore[arg-type]
        created_at="2026-07-27T00:00:00Z",
        meta=(
            {"url": url, "fetched_at": "2026-07-27T00:00:00Z"} if url is not None else None
        ),
    )
    built: list[Page] = []
    anchors: dict[int, list[Anchor]] = {}
    for index, chunks in enumerate(pages, start=1):
        summary = summaries[index - 1] if index - 1 < len(summaries) else None
        built.append(
            Page(number=index, kind="page", text="\n\n".join(chunks), summary=summary)
        )
        anchors[index] = [
            _anchor(slug, ChunkLocator(page=index, ordinal=ordinal), text, index, ids)
            for ordinal, text in enumerate(chunks, start=1)
        ]
    return _Loaded(document=document, pages=built, anchors=anchors)


def sheet_text(name: str, rows: Sequence[str]) -> str:
    """A sheet page's text, in the shape `extract/xlsx.py` produces.

    A real sheet snapshot is a `## Sheet: …` title, a blank line, then the
    markdown table — see `_title` and `_render` there. The gate windows sheets by
    row and repeats the header block above every window, so a fake that handed it
    a bare table would hide the bug where the title is mistaken for the header.
    `tests/test_gate_integration.py` drives the same path over the real extractor
    and the real registry; this keeps the unit-level fake honest to that shape.
    """
    return "\n".join([f"## Sheet: {name} - Values View with cell references", "", *rows])


def sheet_document(
    slug: str,
    filename: str,
    sheets: Sequence[tuple[str, Sequence[str]]],
    *,
    ids: Ids | None = None,
) -> _Loaded:
    """A `sheet`-kind document from (name, table rows) pairs.

    The rows are the markdown table exactly as the extractor renders it — column
    header, `|---|` rule, data rows — and `sheet_text` puts the sheet title above
    them, so the page text a test reads through the gate has the real shape.
    Cell anchors are derived from the in-band `[B10] value` references in the
    table rows, matching what the xlsx extractor puts in the text.
    """
    ids = ids or Ids()
    document = Document(
        slug=slug,
        sha256="1" * 64,
        path=f"/corpus/{filename}",
        filename=filename,
        media_type="xlsx",
        created_at="2026-07-27T00:00:00Z",
    )
    built: list[Page] = []
    anchors: dict[int, list[Anchor]] = {}
    for index, (name, rows) in enumerate(sheets, start=1):
        text = sheet_text(name, rows)
        cells = tuple(
            CellValue(ref=ref, value=value.strip())
            for ref, value in re.findall(r"\[([A-Z]+[0-9]+)\]([^|\n]*)", text)
        )
        built.append(Page(number=index, kind="sheet", text=text, name=name, cells=cells))
        page_anchor = _anchor(slug, PageLocator(page=index), text, index, ids)
        cell_anchors = [
            _anchor(
                slug,
                CellLocator(
                    sheet=sheetref(name),
                    cell=Cell(
                        column=re.match(r"([A-Z]+)([0-9]+)", cell.ref)[1],  # type: ignore[index]
                        row=int(re.match(r"([A-Z]+)([0-9]+)", cell.ref)[2]),  # type: ignore[index]
                    ),
                ),
                cell.value,
                index,
                ids,
            )
            for cell in cells
        ]
        anchors[index] = [page_anchor, *cell_anchors]
    return _Loaded(document=document, pages=built, anchors=anchors)


def _anchor(slug: str, locator: object, snippet: str, page_number: int, ids: Ids) -> Anchor:
    return Anchor(
        slug=slug,
        locator=locator,  # type: ignore[arg-type]
        receipt=Receipt(snippet=snippet, snippet_sha256=snippet_hash(snippet)),
        token=format_token(slug, locator, token_hash(snippet)),  # type: ignore[arg-type]
        page_number=page_number,
        id=ids.take(),
    )
