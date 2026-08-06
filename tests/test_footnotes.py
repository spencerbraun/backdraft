"""The markdown projection: golden files, and the guarantee that nothing drops.

    BACKDRAFT_UPDATE_GOLDEN=1 uv run pytest tests/test_footnotes.py
"""

from __future__ import annotations

import dataclasses
import pathlib

import pytest

from backdraft.kernel.model import BindReport, Citation, CitationStatus
from backdraft.render import footnotes

from conftest_render import BACKFILL_DOC, DEMO_DOC, backfill_report, demo_report
from golden_util import assert_golden

GOLDEN = pathlib.Path(__file__).parent / "golden" / "render"


@pytest.mark.parametrize(
    ("name", "source", "build"),
    [("demo", DEMO_DOC, demo_report), ("backfill", BACKFILL_DOC, backfill_report)],
)
def test_golden_footnotes(name: str, source: str, build) -> None:  # noqa: ANN001
    assert_golden(GOLDEN / f"{name}.footnotes.md", footnotes.render(source, build()))


def test_every_claim_gets_a_reference(demo_doc: str, demo: BindReport) -> None:
    text = footnotes.render(demo_doc, demo)
    citations = sum(len(claim.citations) for claim in demo.claims)
    for number in range(1, citations + 1):
        assert f"[^bd{number}]:" in text, f"footnote bd{number} is missing"
        assert f"[^bd{number}]" in text.split("## Receipts")[0]


def test_tokens_are_replaced_by_refs(demo_doc: str, demo: BindReport) -> None:
    body = footnotes.render(demo_doc, demo).split("## Receipts")[0]
    assert "](bd:" not in body
    assert "DSCR of 1.42x[^bd1]" in body
    assert "NOI of $4.1M[^bd2][^bd3]" in body


def test_notes_carry_document_locator_quote_and_status(
    demo_doc: str, demo: BindReport
) -> None:
    text = footnotes.render(demo_doc, demo)
    assert "[^bd1]: **t12-audit** · `p8.c3` · resolved" in text
    assert "> Debt service coverage for the trailing twelve months is 1.42x" in text
    assert "sha256 `f3e4f7d7833bceb52f1591cae2b5f3530b3b53af3805b4f334f58394a9e805ce`" in text
    assert "value-trace pass — 1.42x occurs in the snippet" in text


def test_drift_carries_both_snippets(demo_doc: str, demo: BindReport) -> None:
    text = footnotes.render(demo_doc, demo)
    assert "As cited, before the source changed:" in text
    assert "is 1.31x," in text
    assert "is 1.42x," in text


def test_unresolved_section_lists_every_failure(demo_doc: str, demo: BindReport) -> None:
    section = footnotes.render(demo_doc, demo).split("## Unresolved")[1]
    for citation in demo.unresolved:
        assert citation.token in section
        assert str(citation.status) in section
    assert "resolved**" not in section.replace("unresolved**", "")


def test_unmatched_claims_are_listed(backfill_doc: str, backfill: BindReport) -> None:
    text = footnotes.render(backfill_doc, backfill)
    assert "**unmatched** — claim 2" in text.split("## Unresolved")[1]
    assert "bind could not anchor it" in text


def test_a_clean_report_says_so(demo_doc: str, demo: BindReport) -> None:
    clean = dataclasses.replace(
        demo,
        claims=tuple(
            dataclasses.replace(
                claim,
                unmatched=False,
                citations=tuple(
                    dataclasses.replace(citation, status=CitationStatus.RESOLVED)
                    for citation in claim.citations
                ),
            )
            for claim in demo.claims
        ),
    )
    assert "Every citation resolved." in footnotes.render(demo_doc, clean)


def test_a_claim_absent_from_the_document_is_still_reported() -> None:
    report = dataclasses.replace(
        backfill_report(),
        claims=(
            dataclasses.replace(
                backfill_report().claims[0],
                text="a phrase this document does not contain",
                citations=(Citation(token="bd:x:p1:0000", status=CitationStatus.UNRESOLVED),),
            ),
        ),
    )
    text = footnotes.render(BACKFILL_DOC, report)
    assert "This claim was not located in the document text above." in text
    assert "bd:x:p1:0000" in text


def test_provenance_line_names_the_sidecar(demo_doc: str, demo: BindReport) -> None:
    text = footnotes.render(demo_doc, demo)
    assert "`memo.backdraft.json` (`backdraft/artifact-v1`)" in text
    assert "frontwalk, session `s-bridgeview-01`" in text


# ---- a fetched source's origin travels into the markdown --------------------

URL = "https://example.com/reports/q4-2025"


def _with_origin(report: BindReport, **entry) -> BindReport:
    return dataclasses.replace(
        report,
        evidence={
            "documents": {
                "t12-audit": {"filename": "q4-2025.html", "media_type": "html", **entry}
            },
            "pages": {}, "pagetexts": {}, "windows": {}, "sheets": {},
        },
    )


def test_the_source_line_carries_the_origin_as_an_autolink(
    demo_doc: str, demo: BindReport
) -> None:
    """The projection gives up the click, not the pointer."""
    text = footnotes.render(
        demo_doc, _with_origin(demo, url=URL, fetched_at="2026-08-05T09:14:00Z")
    )
    assert f"**t12-audit** · `p8.c3` · resolved · <{URL}> as of 2026-08-05" in text


def test_a_source_without_an_origin_keeps_the_line_it_had(
    demo_doc: str, demo: BindReport
) -> None:
    text = footnotes.render(demo_doc, _with_origin(demo))
    assert "**t12-audit** · `p8.c3` · resolved\n" in text


def test_a_report_with_no_evidence_still_renders(demo_doc: str, demo: BindReport) -> None:
    """Evidence is optional; the projection may not require it to name a source."""
    text = footnotes.render(demo_doc, dataclasses.replace(demo, evidence=None))
    assert "**t12-audit** · `p8.c3` · resolved\n" in text


def test_an_unparseable_fetch_time_leaves_the_url_undated(
    demo_doc: str, demo: BindReport
) -> None:
    text = footnotes.render(demo_doc, _with_origin(demo, url=URL, fetched_at="whenever"))
    assert f"· <{URL}>\n" in text
    assert "as of" not in text
