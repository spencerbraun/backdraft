"""The vocabulary: closed status sets, immutability, and the BindReport shape."""

from __future__ import annotations

import dataclasses
import json

import pytest

from backdraft.kernel import hashing, tokens
from backdraft.kernel.model import (
    Anchor,
    BindReport,
    CellValue,
    Chunk,
    Citation,
    CitationStatus,
    Claim,
    Document,
    Extraction,
    Page,
    Receipt,
    Verdict,
    VerdictStatus,
    source_name,
    source_origin,
)

SNIPPET = "The DSCR is 1.42x."


def _anchor(locator: str = "p8.c3") -> Anchor:
    parsed = tokens.parse_locator(locator)
    digest = hashing.snippet_hash(SNIPPET)
    return Anchor(
        slug="t12-audit",
        locator=parsed,
        receipt=Receipt(snippet=SNIPPET, snippet_sha256=digest),
        token=tokens.format_token("t12-audit", parsed, hashing.hash_prefix(digest)),
        extraction_id=1,
        page_number=8,
        start=100,
        end=118,
    )


def test_citation_statuses_are_the_closed_set() -> None:
    assert {str(status) for status in CitationStatus} == {
        "resolved",
        "drifted",
        "not_shown",
        "unresolved",
        "malformed",
    }


def test_verdict_statuses_are_the_closed_set() -> None:
    assert {str(status) for status in VerdictStatus} == {"pass", "fail", "partial", "skip"}


def test_statuses_are_strings_on_the_wire() -> None:
    assert json.dumps({"s": CitationStatus.RESOLVED, "v": VerdictStatus.PASS}) == (
        '{"s": "resolved", "v": "pass"}'
    )


def test_values_are_frozen() -> None:
    anchor = _anchor()
    with pytest.raises(dataclasses.FrozenInstanceError):
        anchor.slug = "other"  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        Chunk(1, "x", 0, 1).text = "y"  # type: ignore[misc]


def test_anchor_kind_is_derived_from_the_locator() -> None:
    assert _anchor("p8").kind == "page"
    assert _anchor("p8.c3").kind == "chunk"
    assert _anchor("rent-roll!B10").kind == "cell"
    assert _anchor("rent-roll!B10:C12").kind == "range"


def test_anchor_dict_is_the_receipt() -> None:
    assert _anchor().to_dict() == {
        "slug": "t12-audit",
        "locator": "p8.c3",
        "snippet": SNIPPET,
        "snippet_sha256": hashing.snippet_hash(SNIPPET),
    }


def _report() -> BindReport:
    resolved = Citation(
        token=_anchor().token,
        status=CitationStatus.RESOLVED,
        anchor=_anchor(),
        verdicts=(
            Verdict("value-trace", VerdictStatus.PASS, "1.42 found in snippet"),
            Verdict("overlap", VerdictStatus.PARTIAL, "0.62"),
        ),
    )
    drifted = Citation(
        token="bd:t12-audit:p9.c1:0000",
        status=CitationStatus.DRIFTED,
        anchor=_anchor("p9.c1"),
        drifted_from="The DSCR was 1.31x.",
        verdicts=(Verdict("value-trace", VerdictStatus.FAIL, "1.42 not found"),),
    )
    not_shown = Citation(token="bd:model:rent-roll!B10:9e2f", status=CitationStatus.NOT_SHOWN)
    malformed = Citation(
        token="bd:calc(a / b)", status=CitationStatus.MALFORMED, error="not supported in v0"
    )
    return BindReport(
        doc_path="memo.md",
        mode="frontwalk",
        bound_at="2026-07-27T12:00:00Z",
        session_id="s-1",
        claims=(
            Claim(text="DSCR of 1.42x", start=4, end=40, citations=(resolved, drifted)),
            Claim(text="NOI of $4.1M", start=60, end=100, citations=(not_shown, malformed)),
            Claim(text="occupancy is stable", start=120, end=140, unmatched=True),
        ),
    )


def test_report_shape() -> None:
    payload = _report().to_dict()
    assert set(payload) == {
        "doc_path",
        "mode",
        "session_id",
        "bound_at",
        "claims",
        "summary",
    }
    assert set(payload["claims"][0]) == {"text", "start", "end", "unmatched", "citations"}
    citation = payload["claims"][0]["citations"][0]
    assert set(citation) == {"token", "status", "anchor", "verdicts"}
    assert set(citation["verdicts"][0]) == {"method", "status", "detail"}
    assert set(payload["claims"][0]["citations"][1]) == {
        "token",
        "status",
        "anchor",
        "drifted_from",
        "verdicts",
    }
    assert set(payload["claims"][1]["citations"][1]) == {
        "token",
        "status",
        "error",
        "verdicts",
    }


def test_report_summary() -> None:
    assert _report().summary == {
        "claims": 3,
        "citations": 4,
        "by_status": {"resolved": 1, "drifted": 1, "not_shown": 1, "malformed": 1},
        "by_method": {
            "value-trace": {"pass": 1, "fail": 1},
            "overlap": {"partial": 1},
        },
    }


def test_empty_report_summary() -> None:
    report = BindReport(doc_path="memo.md", mode="backfill", bound_at="2026-07-27T12:00:00Z")
    assert report.summary == {"claims": 0, "citations": 0, "by_status": {}, "by_method": {}}
    assert report.unresolved == ()


def test_unresolved_lists_every_non_resolved_citation_in_order() -> None:
    statuses = [citation.status for citation in _report().unresolved]
    assert statuses == [
        CitationStatus.DRIFTED,
        CitationStatus.NOT_SHOWN,
        CitationStatus.MALFORMED,
    ]


def test_report_is_json_serializable() -> None:
    payload = _report().to_dict()
    assert json.loads(json.dumps(payload)) == payload


def test_document_extraction_and_page_carry_the_ddl_columns() -> None:
    document = Document(
        slug="t12-audit",
        sha256="ab" * 32,
        path="./t12.pdf",
        filename="t12.pdf",
        media_type="pdf",
        created_at="2026-07-27T12:00:00Z",
        id=1,
    )
    extraction = Extraction(
        document_id=document.id or 0,
        extractor="pdf-text",
        extractor_version="1",
        config_hash=hashing.config_hash({}),
        deterministic=True,
        created_at="2026-07-27T12:00:00Z",
    )
    page = Page(
        number=1,
        kind="sheet",
        text="| Row | A |",
        name="rent-roll",
        cells=(CellValue(ref="B10", value="4,100,000"),),
        extraction_id=1,
    )
    assert extraction.is_current is True
    assert page.cells[0].ref == "B10"
    assert page.summary is None
    assert document.media_type == "pdf"


# --- what to call a source -------------------------------------------------
#
# A pure function of a `Document`, so it lives beside the type rather than in
# the first package that needed it: the gate, bind and the CLI all import this
# module downward, which is how one owner reaches all three without the sideways
# import SPEC forbids (2026-09-03).


def _document(**overrides) -> Document:
    fields = {
        "slug": "franklin-county",
        "sha256": "0" * 64,
        "path": "/corpus/index.html",
        "filename": "index.html",
        "media_type": "html",
        "created_at": "2026-07-27T00:00:00Z",
    }
    return Document(**(fields | overrides))


def test_a_file_source_is_called_by_its_filename() -> None:
    document = _document(filename="T12 Audit.pdf", media_type="pdf")
    assert source_name(document) == "T12 Audit.pdf"
    assert source_origin(document) == ""


def test_a_fetched_source_is_called_by_its_origin_not_its_staging_file() -> None:
    """`fetch.filename_for` invents `index.html` from a permanent link's last
    path segment — a name that exists on nobody's disk. The URL stands in its
    place rather than beside it (2026-08-06)."""
    url = "https://en.wikipedia.org/w/index.php?title=Franklin_County,_Ohio"
    document = _document(meta={"url": url, "fetched_at": "2026-08-17T00:00:00Z"})
    assert source_name(document) == url
    assert source_origin(document) == url


def test_meta_without_a_url_leaves_the_filename_standing() -> None:
    """`meta` is provenance in general, not a URL in particular, and a document
    carrying some other key is still a file with a filename."""
    document = _document(meta={"fetched_at": "2026-08-17T00:00:00Z"})
    assert source_name(document) == "index.html"
    assert source_origin(document) == ""


def test_an_empty_url_is_not_a_url() -> None:
    assert source_name(_document(meta={"url": ""})) == "index.html"
