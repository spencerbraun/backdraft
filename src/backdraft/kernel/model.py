"""The whole vocabulary, as frozen dataclasses.

Every concept in the spec's concept table lives here and nothing else does. New
nouns require a spec change.

These types are pure values: they carry no database rows, no file handles, no
connections. The registry reads and writes them; the gate mints them; bind
reports on them; the renderers project them.

Timestamps are ISO-8601 UTC strings, matching the DDL, which stores them as TEXT
everywhere. NOTE: kept as `str` rather than `datetime` so that a value read from
SQLite and a value about to be written are the same thing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Literal

from .tokens import Locator, format_locator

__all__ = [
    "MediaType",
    "PageKind",
    "AnchorKind",
    "BindMode",
    "CitationStatus",
    "VerdictStatus",
    "Document",
    "Extraction",
    "Page",
    "CellValue",
    "Chunk",
    "Receipt",
    "Anchor",
    "Citation",
    "Claim",
    "Verdict",
    "BindReport",
]

type MediaType = Literal["pdf", "xlsx", "text"]
type PageKind = Literal["page", "sheet"]
type AnchorKind = Literal["page", "chunk", "cell", "range"]
type BindMode = Literal["frontwalk", "backfill"]


class CitationStatus(StrEnum):
    """Closed set. Every non-`RESOLVED` status is a report line item."""

    RESOLVED = "resolved"
    """Anchor found in the current extraction; snippet hash matches."""

    DRIFTED = "drifted"
    """Anchor found only in a superseded extraction; the source moved under it."""

    NOT_SHOWN = "not_shown"
    """Valid anchor, absent from the session ledger. Front-walk mode only."""

    UNRESOLVED = "unresolved"
    """Well-formed token, no anchor in any generation. Also the pre-bind state."""

    MALFORMED = "malformed"
    """The token text does not parse — including the reserved `bd:calc(...)` form."""


class VerdictStatus(StrEnum):
    """Closed set. Verdicts are recorded evidence, never gates."""

    PASS = "pass"
    FAIL = "fail"
    PARTIAL = "partial"
    SKIP = "skip"


@dataclass(frozen=True, slots=True)
class Document:
    """An ingested file. Identity is the sha256 of its bytes; `slug` is the handle."""

    slug: str
    sha256: str
    path: str
    filename: str
    media_type: MediaType
    created_at: str
    id: int | None = None


@dataclass(frozen=True, slots=True)
class Extraction:
    """A snapshot of a document's content produced by one extractor run.

    Generations are kept; exactly one per document is `is_current`.
    """

    document_id: int
    extractor: str
    extractor_version: str
    config_hash: str
    deterministic: bool
    created_at: str
    is_current: bool = True
    id: int | None = None


@dataclass(frozen=True, slots=True)
class CellValue:
    """One spreadsheet cell: its A1 reference and its rendered value.

    Carried out of an extraction for cell anchors and for value-trace.
    """

    ref: str
    value: str


@dataclass(frozen=True, slots=True)
class Page:
    """An ordered unit within an extraction — a PDF page or a sheet.

    `text` is the snapshot. Receipts quote *this*, not the file.
    """

    number: int
    kind: PageKind
    text: str
    name: str | None = None
    summary: str | None = None
    cells: tuple[CellValue, ...] = ()
    extraction_id: int | None = None
    id: int | None = None


@dataclass(frozen=True, slots=True)
class Chunk:
    """A deterministic subdivision of a page's text.

    `ordinal` is 1-based within the page (the `cN` in a chunk locator).
    `start`/`end` are char offsets into the page text, and are exact:
    `page_text[start:end] == text`.
    """

    ordinal: int
    text: str
    start: int
    end: int


@dataclass(frozen=True, slots=True)
class Receipt:
    """The evidence an anchor carries: the verbatim snippet and its hash.

    An anchor is not a pointer; it is a pointer plus this.
    """

    snippet: str
    snippet_sha256: str


@dataclass(frozen=True, slots=True)
class Anchor:
    """An addressable location in an extraction, carrying its receipt.

    Named by its token: `bd:<slug>:<locator>:<hash>`.
    """

    slug: str
    locator: Locator
    receipt: Receipt
    token: str
    extraction_id: int | None = None
    page_number: int | None = None
    start: int | None = None
    end: int | None = None
    id: int | None = None

    @property
    def kind(self) -> AnchorKind:
        """`page` | `chunk` | `cell` | `range`, derived from the locator."""
        return self.locator.kind  # type: ignore[return-value]

    def to_dict(self) -> dict[str, Any]:
        """The anchor as it appears inside a BindReport citation."""
        return {
            "slug": self.slug,
            "locator": format_locator(self.locator),
            "snippet": self.receipt.snippet,
            "snippet_sha256": self.receipt.snippet_sha256,
        }


@dataclass(frozen=True, slots=True)
class Verdict:
    """One verification method's finding for one (claim, citation)."""

    method: str
    status: VerdictStatus
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"method": self.method, "status": str(self.status), "detail": self.detail}


@dataclass(frozen=True, slots=True)
class Citation:
    """One token on a claim, plus everything bind learned about it.

    `token` is the text exactly as authored, so a malformed citation can still be
    reported verbatim. `error` explains a `MALFORMED` status — including the
    reserved `bd:calc(...)` derivation form, which is recognized but unsupported.
    """

    token: str
    status: CitationStatus = CitationStatus.UNRESOLVED
    anchor: Anchor | None = None
    drifted_from: str | None = None
    verdicts: tuple[Verdict, ...] = ()
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"token": self.token, "status": str(self.status)}
        if self.anchor is not None:
            out["anchor"] = self.anchor.to_dict()
        if self.drifted_from is not None:
            out["drifted_from"] = self.drifted_from
        if self.error is not None:
            out["error"] = self.error
        out["verdicts"] = [verdict.to_dict() for verdict in self.verdicts]
        return out


@dataclass(frozen=True, slots=True)
class Claim:
    """A span of authored text and its citation tokens.

    `start`/`end` bound the whole markdown link in the authored document, so
    `source[start:end]` is the construct bind rewrites; `text` is the link text
    alone — the words the citations support.

    `unmatched` is a backfill-mode outcome: a claim bind could not anchor.
    """

    text: str
    start: int
    end: int
    citations: tuple[Citation, ...] = ()
    unmatched: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "start": self.start,
            "end": self.end,
            "unmatched": self.unmatched,
            "citations": [citation.to_dict() for citation in self.citations],
        }


@dataclass(frozen=True, slots=True)
class BindReport:
    """One bind run over one authored document.

    Serialized into the sidecar artifact and `bindings.report_json`.
    """

    doc_path: str
    mode: BindMode
    bound_at: str
    claims: tuple[Claim, ...] = field(default_factory=tuple)
    session_id: str | None = None
    evidence: dict[str, Any] | None = None
    """Evidence context for the cited sources, assembled at bind time.

    JSON-shaped, keyed exactly as the sidecar carries it (`documents`, `pages`,
    `pagetexts`, `windows`, `sheets` — see `LEGEND["evidence"]`). None when
    bind ran without a registry or evidence was skipped; the artifact then
    falls back to snippets alone. Optional by design: a sidecar without
    evidence is still a complete record — evidence is context, receipts are
    the proof.
    """

    @property
    def summary(self) -> dict[str, Any]:
        """Counts, derived — never stored, so it can never disagree with `claims`.

        NOTE: the spec fixes the keys but not the shape of `by_method`; it is
        `{method: {verdict status: count}}`, the shape a run-level pass-rate
        table needs.
        """
        by_status: dict[str, int] = {}
        by_method: dict[str, dict[str, int]] = {}
        citations = 0
        for claim in self.claims:
            for citation in claim.citations:
                citations += 1
                key = str(citation.status)
                by_status[key] = by_status.get(key, 0) + 1
                for verdict in citation.verdicts:
                    statuses = by_method.setdefault(verdict.method, {})
                    vkey = str(verdict.status)
                    statuses[vkey] = statuses.get(vkey, 0) + 1
        return {
            "claims": len(self.claims),
            "citations": citations,
            "by_status": by_status,
            "by_method": by_method,
        }

    @property
    def unresolved(self) -> tuple[Citation, ...]:
        """Every citation that did not resolve, in document order.

        The list the report and the artifact must show; nothing drops silently.
        """
        return tuple(
            citation
            for claim in self.claims
            for citation in claim.citations
            if citation.status is not CitationStatus.RESOLVED
        )

    def to_dict(self, *, include_evidence: bool = True) -> dict[str, Any]:
        """Serialize. `include_evidence=False` drops the (heavy) evidence block
        — the shape the registry's bindings row stores."""
        payload: dict[str, Any] = {
            "doc_path": self.doc_path,
            "mode": self.mode,
            "session_id": self.session_id,
            "bound_at": self.bound_at,
            "claims": [claim.to_dict() for claim in self.claims],
            "summary": self.summary,
        }
        if include_evidence and self.evidence is not None:
            payload["evidence"] = self.evidence
        return payload
