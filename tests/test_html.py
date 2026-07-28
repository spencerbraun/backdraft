"""The artifact: structure, the islands, self-containment, and kept failures.

These assertions are the HTML half of `spec/artifact.md`. They check structure
and guarantees, never layout: the artifact may be restyled freely, but it may
never fetch anything, hide a failure, or lose a claim.

The v2 doctrine they pin (DESIGN.md, 2026-07-28): success is silent — a clean
artifact says nothing about citations on its face; failure speaks in one plain
masthead line and in the notes. The load-bearing constraint is no *network*,
enforced by CSP — inline behavior script is allowed as progressive enhancement.
"""

from __future__ import annotations

import dataclasses
import json
import re

import pytest

from backdraft.kernel.model import (
    Anchor,
    BindReport,
    Citation,
    CitationStatus,
    Claim,
    Receipt,
    Verdict,
    VerdictStatus,
)
from backdraft.kernel.tokens import parse_locator
from backdraft.render import html, sidecar

ISLAND_RE = re.compile(
    r'<script type="application/json" id="backdraft-artifact">\n(?P<payload>.*?)\n</script>',
    re.DOTALL,
)


def island(page: str) -> dict:
    match = ISLAND_RE.search(page)
    assert match is not None, "the artifact has no JSON island"
    return json.loads(match["payload"])


# ---- the islands ------------------------------------------------------------


def test_island_parses_and_is_the_sidecar(demo_doc: str, demo: BindReport) -> None:
    payload = island(html.render(demo_doc, demo))
    assert payload == sidecar.sidecar(demo)


def test_island_format_string_is_exact(demo_doc: str, demo: BindReport) -> None:
    assert island(html.render(demo_doc, demo))["$format"] == "backdraft/artifact-v1"


def test_island_carries_the_legend(demo_doc: str, demo: BindReport) -> None:
    assert island(html.render(demo_doc, demo))["$legend"] == sidecar.LEGEND


def test_island_round_trips_back_into_a_report(demo_doc: str, demo: BindReport) -> None:
    payload = island(html.render(demo_doc, demo))
    assert sidecar.dumps(sidecar.to_report(payload)) == sidecar.dumps(demo)


def test_island_omits_page_image_bytes_but_keeps_their_shape(demo_doc: str, demo: BindReport) -> None:
    """`evidence.pages[*].data` stays out of the island; the sidecar keeps it."""
    report = dataclasses.replace(
        demo,
        evidence={
            "documents": {"t12": {"filename": "t12.pdf", "media_type": "pdf"}},
            "pages": {"t12:p1": {"format": "webp", "width": 2, "height": 2, "data": "AAAA"}},
            "pagetexts": {},
            "windows": {},
            "sheets": {},
        },
    )
    payload = island(html.render(demo_doc, report))
    entry = payload["evidence"]["pages"]["t12:p1"]
    assert "data" not in entry
    assert entry["format"] == "webp" and entry["width"] == 2
    # the full sidecar still carries the bytes
    assert "data" in sidecar.sidecar(report)["evidence"]["pages"]["t12:p1"]


def test_island_cannot_be_closed_by_a_snippet(demo_doc: str) -> None:
    """A snippet containing `</script>` must not terminate the island."""
    locator = parse_locator("p1.c1")
    hostile = "</script><script>alert(1)</script> & <b>bold</b>"
    report = BindReport(
        doc_path="memo.md",
        mode="frontwalk",
        bound_at="2026-07-27T00:00:00Z",
        claims=(
            Claim(
                text="DSCR of 1.42x",
                start=0,
                end=0,
                citations=(
                    Citation(
                        token="bd:x:p1.c1:0000",
                        status=CitationStatus.RESOLVED,
                        anchor=Anchor(
                            slug="x",
                            locator=locator,
                            receipt=Receipt(snippet=hostile, snippet_sha256="0" * 64),
                            token="bd:x:p1.c1:0000",
                        ),
                    ),
                ),
            ),
        ),
    )
    page = html.render(demo_doc, report)
    assert island(page)["claims"][0]["citations"][0]["anchor"]["snippet"] == hostile
    assert "<script>alert(1)</script>" not in page


# ---- claims, receipts, verdicts ---------------------------------------------


def test_every_claim_is_addressable(demo_doc: str, demo: BindReport) -> None:
    page = html.render(demo_doc, demo)
    for number in range(1, len(demo.claims) + 1):
        assert f'id="claim-{number}"' in page
        assert f'id="card-{number}"' in page
        assert f'id="note-{number}"' in page


def test_every_receipt_carries_its_evidence(demo_doc: str, demo: BindReport) -> None:
    page = html.render(demo_doc, demo)
    for claim in demo.claims:
        for citation in claim.citations:
            assert citation.token.replace("&", "&amp;") in page
            if citation.anchor is None:
                continue
            assert citation.anchor.receipt.snippet_sha256 in page
            assert citation.anchor.slug in page


def test_every_verdict_is_recorded_with_its_status(demo_doc: str, demo: BindReport) -> None:
    page = html.render(demo_doc, demo)
    seen = {
        str(verdict.status)
        for claim in demo.claims
        for citation in claim.citations
        for verdict in citation.verdicts
    }
    assert seen == {str(status) for status in VerdictStatus}
    for status in seen:
        assert f"v-{status}" in page


def test_verdict_language_is_humanized() -> None:
    label, sentence = html.humanize_verdict(
        Verdict("value-trace", VerdictStatus.PASS, "3 value(s) found in snippet")
    )
    assert (label, sentence) == ("Figures", "All 3 figures in this claim appear in this source.")
    label, sentence = html.humanize_verdict(
        Verdict("value-trace", VerdictStatus.FAIL, "not found in snippet: 7.7%")
    )
    assert sentence == "Not found in this source: 7.7%."
    label, sentence = html.humanize_verdict(
        Verdict("overlap", VerdictStatus.PASS, "9/13 claim tokens in snippet (ratio 0.69)")
    )
    assert (label, sentence) == ("Wording", "9 of the claim's 13 words appear in this source.")


def test_drift_renders_both_snippets_as_a_diff(demo_doc: str, demo: BindReport) -> None:
    page = html.render(demo_doc, demo)
    assert '<div class="drift">' in page
    assert "<del>1.31x,</del>" in page
    assert "<ins>1.42x,</ins>" in page


# ---- failures speak; success is silent --------------------------------------


def test_failures_are_announced_on_the_masthead(demo_doc: str, demo: BindReport) -> None:
    page = html.render(demo_doc, demo)
    assert 'class="alarmline"' in page
    assert "could not be traced to a source" in page


def test_every_failure_is_in_the_notes(demo_doc: str, demo: BindReport) -> None:
    page = html.render(demo_doc, demo)
    notes = page.split('<ol class="notes">')[1].split("</ol>")[0]
    for citation in demo.unresolved:
        assert citation.token.replace("&", "&amp;") in notes


def test_success_is_silent(demo_doc: str) -> None:
    """A fully-resolved artifact says nothing about citations on its face."""
    locator = parse_locator("p1.c1")
    report = BindReport(
        doc_path="memo.md",
        mode="frontwalk",
        bound_at="2026-07-27T00:00:00Z",
        claims=(
            Claim(
                text="DSCR of 1.42x",
                start=0,
                end=0,
                citations=(
                    Citation(
                        token="bd:x:p1.c1:0000",
                        status=CitationStatus.RESOLVED,
                        anchor=Anchor(
                            slug="x",
                            locator=locator,
                            receipt=Receipt(snippet="DSCR was 1.42x", snippet_sha256="0" * 64),
                            token="bd:x:p1.c1:0000",
                        ),
                    ),
                ),
            ),
        ),
    )
    page = html.render(demo_doc, report)
    assert 'class="alarmline"' not in page
    masthead = page.split('class="masthead"')[1].split("</header>")[0]
    assert "citation" not in masthead.lower()


def test_unmatched_claims_are_visible(backfill_doc: str, backfill: BindReport) -> None:
    page = html.render(backfill_doc, backfill)
    assert "carry no citation" in page or "carries no citation" in page


def test_a_claim_absent_from_the_document_is_kept_in_the_notes(backfill: BindReport) -> None:
    report = dataclasses.replace(
        backfill,
        claims=(
            dataclasses.replace(backfill.claims[0], text="words that are not in the document"),
        ),
    )
    page = html.render("# Notes\n\nNothing to see.\n", report)
    assert "not in the document as rendered" in page
    assert "words that are not in the document" in page


# ---- self-containment -------------------------------------------------------


@pytest.mark.parametrize(
    "needle",
    ["http://", "https://", "@import", "url(", "srcset", "<iframe", "fetch(", "XMLHttpRequest"],
)
def test_the_artifact_reaches_for_nothing(demo_doc: str, demo: BindReport, needle: str) -> None:
    assert needle not in html.render(demo_doc, demo)


def test_every_src_is_data_or_deferred(demo_doc: str, demo: BindReport) -> None:
    """Image sources are data: URIs or empty (hydrated from the in-page store)."""
    page = html.render(demo_doc, demo)
    for match in re.finditer(r'\bsrc="([^"]*)"', page):
        assert match.group(1) == "" or match.group(1).startswith("data:")
    for match in re.finditer(r'<link[^>]*href="([^"]*)"', page):
        assert match.group(1).startswith("data:")


def test_no_network_is_enforced_by_csp(demo_doc: str, demo: BindReport) -> None:
    page = html.render(demo_doc, demo)
    assert "Content-Security-Policy" in page
    assert "default-src 'none'" in page


def test_scripts_are_two_islands_and_one_inline_behavior(demo_doc: str, demo: BindReport) -> None:
    page = html.render(demo_doc, demo)
    tags = re.findall(r"<script[^>]*>", page)
    assert len(tags) == 3
    assert sum(1 for tag in tags if 'type="application/json"' in tag) == 2
    assert not any("src=" in tag for tag in tags)
    for attribute in ("onclick=", "onload=", "javascript:"):
        assert attribute not in page


def test_styles_are_inline_and_print_aware(demo_doc: str, demo: BindReport) -> None:
    page = html.render(demo_doc, demo)
    assert "<style>" in page
    assert "color-scheme:light" in page
    assert "@media print" in page


# ---- the document face ------------------------------------------------------


def test_document_body_is_rendered(demo_doc: str, demo: BindReport) -> None:
    page = html.render(demo_doc, demo)
    assert "<h2>What the file says</h2>" in page
    assert "<strong>Recommendation:</strong>" in page
    assert '<div class="table-wrap"><table>' in page
    assert "<blockquote>" in page


def test_title_comes_from_the_document(demo_doc: str, demo: BindReport) -> None:
    assert "<title>Bridgeview — T-12 review</title>" in html.render(demo_doc, demo)


def test_title_falls_back_to_the_document_name(demo: BindReport) -> None:
    page = html.render("No heading here.\n", demo)
    assert "<title>memo.md</title>" in page


def test_title_can_be_overridden(demo_doc: str, demo: BindReport) -> None:
    assert "<title>Q3 file review</title>" in html.render(demo_doc, demo, title="Q3 file review")


def test_subtitle_is_the_italic_line_under_the_title(demo: BindReport) -> None:
    source = "# The Memo\n\n*Prepared from the Q3 files*\n\nBody text.\n"
    page = html.render(source, demo)
    assert '<p class="subtitle">Prepared from the Q3 files</p>' in page
    assert "*Prepared from the Q3 files*" not in page


def test_masthead_carries_no_machinery(demo_doc: str, demo: BindReport) -> None:
    """Session ids, modes and timestamps live in the record, not on the face."""
    masthead = html.render(demo_doc, demo).split('class="masthead"')[1].split("</header>")[0]
    assert "s-bridgeview-01" not in masthead
    assert "frontwalk" not in masthead


def test_snippets_are_escaped_not_executed(demo_doc: str) -> None:
    locator = parse_locator("p1.c1")
    report = BindReport(
        doc_path="memo.md",
        mode="frontwalk",
        bound_at="2026-07-27T00:00:00Z",
        claims=(
            Claim(
                text="DSCR of 1.42x",
                start=0,
                end=0,
                citations=(
                    Citation(
                        token="bd:x:p1.c1:0000",
                        status=CitationStatus.RESOLVED,
                        anchor=Anchor(
                            slug="x",
                            locator=locator,
                            receipt=Receipt(
                                snippet="a < b && c > d", snippet_sha256="0" * 64
                            ),
                            token="bd:x:p1.c1:0000",
                        ),
                        verdicts=(Verdict("overlap", VerdictStatus.PASS, "<ok>"),),
                    ),
                ),
            ),
        ),
    )
    page = html.render(demo_doc, report)
    assert "a &lt; b &amp;&amp; c &gt; d" in page
    assert "&lt;ok&gt;" in page


def test_colophon_is_the_signoff(demo_doc: str, demo: BindReport) -> None:
    page = html.render(demo_doc, demo)
    assert "Generated by Backdraft" in page
    assert 'class="bd-mark"' in page


def test_rendering_is_deterministic(demo_doc: str, demo: BindReport) -> None:
    assert html.render(demo_doc, demo) == html.render(demo_doc, demo)


# ---- evidence rendering -----------------------------------------------------


def _cell_report() -> BindReport:
    locator = parse_locator("model!D24")
    return BindReport(
        doc_path="memo.md",
        mode="frontwalk",
        bound_at="2026-07-27T00:00:00Z",
        claims=(
            Claim(
                text="a debt yield of 7.6%",
                start=0,
                end=0,
                citations=(
                    Citation(
                        token="bd:uw:model!D24:0000",
                        status=CitationStatus.RESOLVED,
                        anchor=Anchor(
                            slug="uw",
                            locator=locator,
                            receipt=Receipt(snippet="0.0765", snippet_sha256="0" * 64),
                            token="bd:uw:model!D24:0000",
                        ),
                    ),
                ),
            ),
        ),
        evidence={
            "documents": {"uw": {"filename": "model.xlsx", "media_type": "xlsx"}},
            "pages": {},
            "pagetexts": {},
            "windows": {
                "uw:model!D24": {
                    "sheet": "model",
                    "cited": "D24",
                    "cols": ["C", "D"],
                    "rows": [
                        {"n": 23, "cells": {"C": "NOI", "D": "3105877"}},
                        {"n": 24, "cells": {"C": "Debt Yield", "D": "0.0765"}},
                    ],
                }
            },
            "sheets": {
                "uw:model": {"name": "model", "nrows": 2, "ncols": 2,
                             "rows": [["NOI", "3105877"], ["Debt Yield", "0.0765"]]}
            },
        },
    )


def test_cell_evidence_renders_a_window_with_the_cited_cell() -> None:
    page = html.render("a debt yield of 7.6%\n", _cell_report())
    assert 'class="cited num"' in page or 'class="cited"' in page
    assert 'data-sheet="uw:model"' in page
    assert 'data-cited="D24"' in page
    assert "3,105,877" in page  # display-formatted, verbatim kept in title/record


def test_full_sheets_travel_in_their_own_island() -> None:
    page = html.render("a debt yield of 7.6%\n", _cell_report())
    match = re.search(
        r'<script type="application/json" id="bd-sheets">\n(.*?)\n</script>',
        page,
        re.DOTALL,
    )
    assert match is not None
    sheets = json.loads(match.group(1))
    assert sheets["uw:model"]["nrows"] == 2


def test_page_image_evidence_is_stored_once_and_referenced(demo_doc: str, demo: BindReport) -> None:
    report = dataclasses.replace(
        demo,
        evidence={
            "documents": {"t12-audit": {"filename": "t12.pdf", "media_type": "pdf"}},
            "pages": {
                "t12-audit:p8": {"format": "webp", "width": 4, "height": 4, "data": "QUJDRA=="}
            },
            "pagetexts": {"t12-audit:p8": "# Page eight\n\nText."},
            "windows": {},
            "sheets": {},
        },
    )
    page = html.render(demo_doc, report)
    assert page.count("data:image/webp;base64,QUJDRA==") == 1
    assert 'data-ev="ev-t12-audit-p8"' in page
