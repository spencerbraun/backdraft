"""The artifact: structure, the islands, self-containment, and kept failures.

These assertions are the HTML half of `spec/artifact.md`. They check structure
and guarantees, never layout: the artifact may be restyled freely, but it may
never fetch anything, hide a failure, or lose a claim.

The v2 doctrine they pin (DESIGN.md, 2026-07-28): success is silent — a clean
artifact says nothing about citations on its face; failure speaks in one plain
mark on the claim itself and in the notes. The load-bearing constraint is no *network*,
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
from backdraft.render.html.text import worst_status
from backdraft.render.placement import locate

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


def test_a_failed_claim_is_marked_where_it_stands(demo_doc: str, demo: BindReport) -> None:
    """Failure speaks at the claim, not above the document. The mark is the
    whole of its showing in the body, so it has to be on every failed claim."""
    page = html.render(demo_doc, demo)
    flagged = {
        number
        for number, placement in enumerate(locate(demo_doc, demo.claims), start=1)
        if placement.placed
        and worst_status(placement.claim) is not CitationStatus.RESOLVED
    }
    assert flagged, "the demo report is supposed to carry failures"
    for number in flagged:
        assert f'<a class="claim flagged" id="claim-{number}"' in page


def test_the_masthead_never_summarises_failures(demo_doc: str, demo: BindReport) -> None:
    """The removed line, pinned shut: a count above the first sentence is the
    one thing about a failed citation a reader cannot act on (DESIGN 2026-08-04).
    `demo` carries failures, so a summary would appear here if one existed."""
    masthead = html.render(demo_doc, demo).split('class="masthead"')[1].split("</header>")[0]
    assert "citation" not in masthead.lower()
    assert "could not be traced" not in masthead
    assert "alarmline" not in html.render(demo_doc, demo)


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
    masthead = page.split('class="masthead"')[1].split("</header>")[0]
    assert "citation" not in masthead.lower()
    assert 'class="claim flagged"' not in page


def test_unmatched_claims_are_visible(backfill_doc: str, backfill: BindReport) -> None:
    """An unmatched claim has no citation to rank, so it could quietly have
    ranked `resolved` and lost its only mark when the masthead line went."""
    page = html.render(backfill_doc, backfill)
    placements = [p for p in locate(backfill_doc, backfill.claims) if p.placed]
    unmatched = [p for p in placements if p.claim.unmatched or not p.claim.citations]
    assert unmatched, "the backfill report is supposed to carry an unmatched claim"
    for placement in unmatched:
        assert f'<a class="claim flagged" id="claim-{placement.number}"' in page


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


# ---- a fetched source points back at the page it came from -------------------

URL = "https://example.com/reports/q4-2025"


def _with_origin(report: BindReport, **entry) -> BindReport:
    """The demo report, with `t12-audit` recorded as a fetched page."""
    return dataclasses.replace(
        report,
        evidence={
            "documents": {
                "t12-audit": {"filename": "q4-2025.html", "media_type": "html", **entry}
            },
            "pages": {}, "pagetexts": {}, "windows": {}, "sheets": {},
        },
    )


def test_a_fetched_sources_receipt_links_to_the_live_page(
    demo_doc: str, demo: BindReport
) -> None:
    page = html.render(
        demo_doc, _with_origin(demo, url=URL, fetched_at="2026-08-05T09:14:00Z")
    )
    assert f'<a class="origin" href="{URL}">{URL}</a>' in page
    assert '<span class="asof">fetched 2026-08-05</span>' in page


def test_the_source_list_shows_the_origin_in_place_of_the_staged_filename(
    demo_doc: str, demo: BindReport
) -> None:
    """`q4-2025.html` names nothing on anyone's disk; the URL does. The record
    island keeps the filename — this is what the reader is shown, not what is
    stored."""
    page = html.render(
        demo_doc, _with_origin(demo, url=URL, fetched_at="2026-08-05T09:14:00Z")
    )
    listing = page.split('<ul class="srclist">', 1)[1].split("</ul>", 1)[0]
    assert re.search(
        r'<li><span class="doc">T12 Audit</span>'
        rf'<span class="filemeta"><a class="origin" href="{re.escape(URL)}">{re.escape(URL)}'
        r"</a> &middot; fetched 2026-08-05 &middot; \d+ citations?</span></li>",
        listing,
    )
    assert "q4-2025.html" not in listing


def test_a_fetched_source_is_titled_by_its_slug_not_its_staging_filename(
    demo_doc: str, demo: BindReport
) -> None:
    """`fetch.filename_for` invents the staging name — a Wikipedia article stages
    as `index.html` and would title itself "Index". The slug is the handle
    somebody chose, so it is the name."""
    page = html.render(demo_doc, _with_origin(demo, url=URL, filename="index.html"))
    assert '<span class="doc">T12 Audit</span>' in page
    assert "Index" not in page.split('<ul class="srclist">', 1)[1].split("</ul>", 1)[0]


def test_a_file_source_still_shows_its_filename(demo_doc: str, demo: BindReport) -> None:
    page = html.render(demo_doc, _with_origin(demo))
    assert "q4-2025.html &middot;" in page
    assert '<span class="doc">Q4 2025</span>' in page
    assert 'class="origin"' not in page


def test_the_origin_survives_in_the_script_free_notes(
    demo_doc: str, demo: BindReport
) -> None:
    """Artifact rule 2: the reader without JavaScript loses the card, not the
    provenance. The Notes section carries the same link."""
    page = html.render(demo_doc, _with_origin(demo, url=URL))
    notes = page.split('<ol class="notes">', 1)[1].split("</ol>", 1)[0]
    assert f'href="{URL}"' in notes


def test_a_url_under_an_unknown_scheme_is_shown_but_never_linked(
    demo_doc: str, demo: BindReport
) -> None:
    """Artifact rule 3 forbids `javascript:` URLs, and the guard is an
    allowlist — the pointer is still shown, as text a reader can read."""
    page = html.render(demo_doc, _with_origin(demo, url="javascript:alert(1)"))
    assert '<span class="origin">javascript:alert(1)</span>' in page
    assert "<a class=\"origin\"" not in page


def test_the_origin_href_is_escaped(demo_doc: str, demo: BindReport) -> None:
    page = html.render(demo_doc, _with_origin(demo, url='https://x.test/a"><b>'))
    assert '<b>' not in page.split('<ol class="notes">', 1)[1]
    assert "https://x.test/a&quot;&gt;&lt;b&gt;" in page


def test_an_unparseable_fetch_time_shows_no_date(demo_doc: str, demo: BindReport) -> None:
    page = html.render(demo_doc, _with_origin(demo, url=URL, fetched_at="whenever"))
    assert f'href="{URL}"' in page
    assert "fetched whenever" not in page
    assert 'class="asof"' not in page


def test_an_artifact_with_a_link_still_fetches_nothing(
    demo_doc: str, demo: BindReport
) -> None:
    """The CSP forbids fetching, not linking: `img-src data:` and nothing else
    stays true with an `<a href>` to the open web in the page."""
    page = html.render(demo_doc, _with_origin(demo, url=URL))
    assert "default-src 'none'" in page
    assert "connect-src" not in page
