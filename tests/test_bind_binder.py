"""bind: the pipeline, the closed status set, the artifacts it writes.

The rewritten documents in `tests/golden/bind/` are the contract for what a
reader is handed. Regenerate deliberately, never reflexively:

    BACKDRAFT_UPDATE_GOLDEN=1 uv run pytest tests/test_bind_binder.py
"""

from __future__ import annotations

import json
import pathlib

import pytest
from fakes import FakeAnchorRegistry

from backdraft.bind.binder import (
    bind,
    bound_path,
    propose_anchors,
    search_query,
    sidecar_path,
)
from backdraft.kernel.model import CitationStatus, VerdictStatus

from golden_util import assert_golden

GOLDEN = pathlib.Path(__file__).parent / "golden" / "bind"

RESOLVED_SNIPPET = "Net operating income was 4,120,000 for the trailing twelve months."
DRIFTED_SNIPPET = "Net operating income was 3,980,000 for the trailing twelve months."
CELL_SNIPPET = "41,200"
FETCHED_URL = "https://en.wikipedia.org/w/index.php?title=Franklin_County,_Ohio"


@pytest.fixture
def fake_bind_registry() -> FakeAnchorRegistry:
    fake = FakeAnchorRegistry()
    fake.add_anchor("t12-audit", "p8.c3", RESOLVED_SNIPPET, page_number=8)
    fake.add_anchor("t12-audit", "p9.c1", DRIFTED_SNIPPET, current=False, page_number=9)
    fake.add_anchor("model", "rent-roll!B10", CELL_SNIPPET, page_number=1)
    fake.add_document("t12-audit", "T12 Audit.pdf")
    fake.add_document("model", "Underwriting Model.xlsx")
    return fake


def token(fake_bind_registry: FakeAnchorRegistry, slug: str, locator: str) -> str:
    for resolution in fake_bind_registry._anchors.values():
        anchor = resolution.anchor
        if anchor.slug == slug and str(anchor.locator) == locator:
            return anchor.token
    raise AssertionError(f"no anchor {slug}:{locator}")


def write(tmp_path: pathlib.Path, source: str) -> pathlib.Path:
    doc = tmp_path / "notes.md"
    doc.write_text(source, encoding="utf-8")
    return doc


# --- statuses --------------------------------------------------------------


def test_a_shown_current_anchor_resolves(tmp_path, fake_bind_registry) -> None:
    resolved = token(fake_bind_registry, "t12-audit", "p8.c3")
    fake_bind_registry.show("s1", resolved)
    doc = write(tmp_path, f"NOI was [$4.12M]({resolved}) last year.\n")
    report = bind(doc, fake_bind_registry, session_id="s1", bound=True)
    (citation,) = report.claims[0].citations
    assert citation.status is CitationStatus.RESOLVED
    assert citation.anchor is not None
    assert citation.anchor.receipt.snippet == RESOLVED_SNIPPET
    assert report.unresolved == ()


def test_an_older_generation_hit_is_drifted_and_carries_the_snippet(tmp_path, fake_bind_registry) -> None:
    drifted = token(fake_bind_registry, "t12-audit", "p9.c1")
    doc = write(tmp_path, f"NOI was [$3.98M]({drifted}).\n")
    report = bind(doc, fake_bind_registry, session_id="s1", bound=True)
    (citation,) = report.claims[0].citations
    assert citation.status is CitationStatus.DRIFTED
    assert citation.anchor is not None
    assert citation.drifted_from == DRIFTED_SNIPPET
    assert citation in report.unresolved


def test_drift_swaps_in_the_current_generations_snippet(tmp_path, fake_bind_registry) -> None:
    """The drift contract: `drifted_from` is as-cited, `anchor` is what stands now."""
    cited = token(fake_bind_registry, "t12-audit", "p9.c1")
    restated = "Net operating income was 4,050,000 for the trailing twelve months, restated."
    current = fake_bind_registry.add_anchor("t12-audit", "p9.c1", restated, page_number=9)
    doc = write(tmp_path, f"NOI was [$3.98M]({cited}).\n")
    report = bind(doc, fake_bind_registry, bound=True)
    (citation,) = report.claims[0].citations
    assert citation.status is CitationStatus.DRIFTED
    assert citation.drifted_from == DRIFTED_SNIPPET
    assert citation.anchor is not None
    assert citation.anchor.receipt.snippet == current.receipt.snippet


def test_a_valid_anchor_absent_from_the_ledger_is_not_shown(tmp_path, fake_bind_registry) -> None:
    resolved = token(fake_bind_registry, "t12-audit", "p8.c3")
    doc = write(tmp_path, f"NOI was [$4.12M]({resolved}).\n")
    report = bind(doc, fake_bind_registry, session_id="s1", bound=True)
    (citation,) = report.claims[0].citations
    assert citation.status is CitationStatus.NOT_SHOWN
    assert citation.anchor is not None  # the receipt still travels with the claim


def test_not_shown_is_frontwalk_only(tmp_path, fake_bind_registry) -> None:
    resolved = token(fake_bind_registry, "t12-audit", "p8.c3")
    doc = write(tmp_path, f"NOI was [$4.12M]({resolved}).\n")
    report = bind(doc, fake_bind_registry, mode="backfill", session_id="s1", bound=True)
    (citation,) = report.claims[0].citations
    assert citation.status is CitationStatus.RESOLVED


def test_without_a_session_frontwalk_does_not_claim_not_shown(tmp_path, fake_bind_registry) -> None:
    resolved = token(fake_bind_registry, "t12-audit", "p8.c3")
    doc = write(tmp_path, f"NOI was [$4.12M]({resolved}).\n")
    report = bind(doc, fake_bind_registry, session_id=None, bound=True)
    assert report.claims[0].citations[0].status is CitationStatus.RESOLVED


def test_a_token_with_no_anchor_anywhere_is_unresolved(tmp_path, fake_bind_registry) -> None:
    doc = write(tmp_path, "NOI was [$9.9M](bd:ghost:p1.c1:0000).\n")
    report = bind(doc, fake_bind_registry, session_id="s1", bound=True)
    (citation,) = report.claims[0].citations
    assert citation.status is CitationStatus.UNRESOLVED
    assert citation.anchor is None


def test_a_malformed_token_keeps_the_kernels_verdict_and_reason(tmp_path, fake_bind_registry) -> None:
    doc = write(tmp_path, "NOI was [$9.9M](bd:NOPE).\n")
    report = bind(doc, fake_bind_registry, session_id="s1", bound=True)
    (citation,) = report.claims[0].citations
    assert citation.status is CitationStatus.MALFORMED
    assert citation.error
    assert citation.token == "bd:NOPE"


def test_the_reserved_derivation_form_binds_as_malformed(tmp_path, fake_bind_registry) -> None:
    doc = write(tmp_path, "[NOI margin](bd:calc(model:rent-roll!B10 / t12-audit:p4.c1)).\n")
    report = bind(doc, fake_bind_registry, session_id="s1", bound=True)
    (citation,) = report.claims[0].citations
    assert citation.status is CitationStatus.MALFORMED
    assert "bd:calc" in (citation.error or "")


def test_every_status_appears_in_one_report(tmp_path, fake_bind_registry) -> None:
    resolved = token(fake_bind_registry, "t12-audit", "p8.c3")
    cell = token(fake_bind_registry, "model", "rent-roll!B10")
    drifted = token(fake_bind_registry, "t12-audit", "p9.c1")
    fake_bind_registry.show("s1", resolved)
    doc = write(
        tmp_path,
        f"A [one]({resolved}). B [two]({drifted}). C [three]({cell}). "
        "D [four](bd:ghost:p1.c1:0000). E [five](bd:nope).\n",
    )
    report = bind(doc, fake_bind_registry, session_id="s1", bound=True)
    statuses = [c.status for claim in report.claims for c in claim.citations]
    assert set(statuses) == {
        CitationStatus.RESOLVED,
        CitationStatus.DRIFTED,
        CitationStatus.NOT_SHOWN,
        CitationStatus.UNRESOLVED,
        CitationStatus.MALFORMED,
    }
    assert len(report.unresolved) == 4


def test_a_claim_may_carry_several_citations(tmp_path, fake_bind_registry) -> None:
    resolved = token(fake_bind_registry, "t12-audit", "p8.c3")
    cell = token(fake_bind_registry, "model", "rent-roll!B10")
    doc = write(tmp_path, f"[NOI ties]({resolved};{cell}).\n")
    report = bind(doc, fake_bind_registry, session_id=None, bound=True)
    assert len(report.claims[0].citations) == 2


def test_bind_never_edits_a_claims_text(tmp_path, fake_bind_registry) -> None:
    resolved = token(fake_bind_registry, "t12-audit", "p8.c3")
    doc = write(tmp_path, f"NOI was [$4.12M *as reported*]({resolved}).\n")
    report = bind(doc, fake_bind_registry, session_id=None, bound=True)
    assert report.claims[0].text == "$4.12M *as reported*"
    assert "$4.12M *as reported*" in bound_path(doc).read_text(encoding="utf-8")


# --- the artifacts ---------------------------------------------------------


def test_the_sidecar_is_the_self_describing_artifact_payload(tmp_path, fake_bind_registry) -> None:
    from backdraft.kernel.artifact import FORMAT, LEGEND

    resolved = token(fake_bind_registry, "t12-audit", "p8.c3")
    fake_bind_registry.show("s1", resolved)
    doc = write(tmp_path, f"NOI was [$4.12M]({resolved}).\n")
    report = bind(doc, fake_bind_registry, session_id="s1", bound=True)
    payload = json.loads(sidecar_path(doc).read_text(encoding="utf-8"))
    assert payload.pop("$format") == FORMAT
    assert payload.pop("$legend") == LEGEND
    assert payload == report.to_dict()
    assert payload["summary"]["by_status"] == {"resolved": 1}
    assert payload["mode"] == "frontwalk"
    assert payload["session_id"] == "s1"


def test_the_binding_row_carries_the_same_payload(tmp_path, fake_bind_registry) -> None:
    resolved = token(fake_bind_registry, "t12-audit", "p8.c3")
    doc = write(tmp_path, f"NOI was [$4.12M]({resolved}).\n")
    report = bind(doc, fake_bind_registry, mode="backfill", session_id="s1", bound=True)
    (row,) = fake_bind_registry.bindings
    assert row["doc_path"] == str(doc)
    assert row["mode"] == "backfill"
    assert row["session_id"] == "s1"
    assert json.loads(row["report_json"]) == report.to_dict()


def test_write_false_touches_nothing(tmp_path, fake_bind_registry) -> None:
    resolved = token(fake_bind_registry, "t12-audit", "p8.c3")
    doc = write(tmp_path, f"NOI was [$4.12M]({resolved}).\n")
    bind(doc, fake_bind_registry, session_id="s1", write=False)
    assert not bound_path(doc).exists()
    assert not sidecar_path(doc).exists()
    assert fake_bind_registry.bindings == []


def test_the_authored_document_is_left_alone(tmp_path, fake_bind_registry) -> None:
    resolved = token(fake_bind_registry, "t12-audit", "p8.c3")
    source = f"NOI was [$4.12M]({resolved}).\n"
    doc = write(tmp_path, source)
    bind(doc, fake_bind_registry, session_id="s1")
    assert doc.read_text(encoding="utf-8") == source


def test_artifact_paths_follow_the_documented_suffixes(tmp_path) -> None:
    doc = tmp_path / "notes.md"
    assert bound_path(doc).name == "notes.bound.md"
    assert sidecar_path(doc).name == "notes.backdraft.json"


# --- the rewritten document ------------------------------------------------


def test_the_rewritten_document_matches_its_golden_file(tmp_path, fake_bind_registry) -> None:
    resolved = token(fake_bind_registry, "t12-audit", "p8.c3")
    cell = token(fake_bind_registry, "model", "rent-roll!B10")
    drifted = token(fake_bind_registry, "t12-audit", "p9.c1")
    fake_bind_registry.show("s1", resolved)
    source = (
        "# Memo\n\n"
        f"NOI was [$4.12M]({resolved}) for the trailing twelve months, and the rent "
        f"roll [ties to the model]({cell};{drifted}).\n\n"
        "Prior-year NOI was [$3.98M](bd:ghost:p1.c1:0000), per a note we cannot "
        "place, and [one figure](bd:nope) never parsed.\n"
    )
    doc = write(tmp_path, source)
    bind(doc, fake_bind_registry, session_id="s1", bound=True)
    assert_golden(
        GOLDEN / "frontwalk.bound.md", bound_path(doc).read_text(encoding="utf-8")
    )


def test_every_citation_gets_a_number_and_a_reference(tmp_path, fake_bind_registry) -> None:
    resolved = token(fake_bind_registry, "t12-audit", "p8.c3")
    cell = token(fake_bind_registry, "model", "rent-roll!B10")
    doc = write(tmp_path, f"[a]({resolved}) and [b]({cell};bd:nope).\n")
    bind(doc, fake_bind_registry, session_id=None, bound=True)
    bound = bound_path(doc).read_text(encoding="utf-8")
    assert "[a](#cite-1)" in bound
    assert "[b](#cite-2)[3](#cite-3)" in bound
    for number in (1, 2, 3):
        assert f'<a id="cite-{number}"></a>' in bound


def test_a_reference_carries_doc_name_locator_and_verbatim_quote(tmp_path, fake_bind_registry) -> None:
    resolved = token(fake_bind_registry, "t12-audit", "p8.c3")
    doc = write(tmp_path, f"[a]({resolved}).\n")
    bind(doc, fake_bind_registry, session_id=None, bound=True)
    bound = bound_path(doc).read_text(encoding="utf-8")
    assert "T12 Audit.pdf" in bound
    assert "`p8.c3`" in bound
    assert f"> {RESOLVED_SNIPPET}" in bound


def test_a_multiline_snippet_is_quoted_line_for_line(tmp_path) -> None:
    fake_bind_registry = FakeAnchorRegistry()
    anchor = fake_bind_registry.add_anchor("t12-audit", "p1.c1", "First line.\nSecond line.")
    doc = write(tmp_path, f"[a]({anchor.token}).\n")
    bind(doc, fake_bind_registry, session_id=None, bound=True)
    bound = bound_path(doc).read_text(encoding="utf-8")
    assert "> First line.\n> Second line." in bound


def test_a_reference_for_an_unresolvable_citation_names_the_token(tmp_path, fake_bind_registry) -> None:
    doc = write(tmp_path, "[a](bd:ghost:p1.c1:0000).\n")
    bind(doc, fake_bind_registry, session_id=None, bound=True)
    bound = bound_path(doc).read_text(encoding="utf-8")
    assert "`bd:ghost:p1.c1:0000`" in bound
    assert "unresolved" in bound


def test_an_unknown_slug_falls_back_to_the_slug_as_the_doc_name(tmp_path) -> None:
    fake_bind_registry = FakeAnchorRegistry()
    anchor = fake_bind_registry.add_anchor("orphan", "p1.c1", "text")
    fake_bind_registry._documents.clear()
    doc = write(tmp_path, f"[a]({anchor.token}).\n")
    bind(doc, fake_bind_registry, session_id=None, bound=True)
    assert "orphan — `p1.c1`" in bound_path(doc).read_text(encoding="utf-8")


# --- what the markdown projection calls a source ---------------------------
#
# The bound markdown is the form that travels into a pull request or an email,
# where the HTML artifact cannot follow, so it is the surface that can least
# afford a name nobody has. It asks `kernel.model.source_name`, the same owner
# `ingest`, `ls` and the gate's document list ask.


@pytest.fixture
def fetched_registry() -> FakeAnchorRegistry:
    """A registry holding one fetched page beside one file, which is the case
    the two naming rules disagree on: the page's `filename` is the staging file
    `fetch.filename_for` invented, and its `meta["url"]` is the real address."""
    fake = FakeAnchorRegistry()
    fake.add_anchor("franklin", "p1.c11", "Franklin County had 1,326,063 residents.")
    fake.add_anchor("t12-audit", "p8.c3", RESOLVED_SNIPPET, page_number=8)
    fake.add_document("franklin", "index.html", url=FETCHED_URL)
    fake.add_document("t12-audit", "T12 Audit.pdf")
    return fake


def test_a_reference_for_a_fetched_source_names_its_origin(tmp_path, fetched_registry) -> None:
    """`index.html` is the temporary file the bytes were staged in — a name on
    nobody's disk. The URL stands in its place, never beside it."""
    resolved = token(fetched_registry, "franklin", "p1.c11")
    doc = write(tmp_path, f"[a]({resolved}).\n")
    bind(doc, fetched_registry, session_id=None, bound=True)
    bound = bound_path(doc).read_text(encoding="utf-8")
    assert f"**[1]** {FETCHED_URL} — `p1.c11` — resolved" in bound
    assert "index.html" not in bound


def test_a_reference_for_a_file_source_prints_the_line_it_always_did(
    tmp_path, fetched_registry
) -> None:
    """The byte-identity half. A registry that is mostly files must read exactly
    as it read before fetched sources existed — pinned as a whole line, the way
    `ls`'s file rows are."""
    resolved = token(fetched_registry, "t12-audit", "p8.c3")
    doc = write(tmp_path, f"[a]({resolved}).\n")
    bind(doc, fetched_registry, session_id=None, bound=True)
    bound = bound_path(doc).read_text(encoding="utf-8")
    assert '<a id="cite-1"></a>**[1]** T12 Audit.pdf — `p8.c3` — resolved' in bound


def test_a_backfill_proposal_names_a_fetched_source_by_its_origin(
    tmp_path, fetched_registry
) -> None:
    """The other half of the markdown that names a document: backfill's open
    list. One owner means one fix, not two."""
    doc = write(tmp_path, "Franklin County had 1,326,063 residents.\n")
    bind(doc, fetched_registry, mode="backfill", session_id=None, bound=True)
    bound = bound_path(doc).read_text(encoding="utf-8")
    assert "proposed: `bd:franklin:p1.c11:" in bound
    assert f"` — {FETCHED_URL}" in bound
    assert "index.html" not in bound


def test_a_document_with_no_claims_still_binds(tmp_path, fake_bind_registry) -> None:
    doc = write(tmp_path, "Just prose, no citations.\n")
    report = bind(doc, fake_bind_registry, session_id="s1", bound=True)
    assert report.claims == ()
    assert report.summary["citations"] == 0
    assert "## References" in bound_path(doc).read_text(encoding="utf-8")


# --- verification is off unless asked --------------------------------------


def test_no_checks_means_no_verdict_rows(tmp_path, fake_bind_registry) -> None:
    resolved = token(fake_bind_registry, "t12-audit", "p8.c3")
    doc = write(tmp_path, f"NOI was [$4.12M]({resolved}).\n")
    report = bind(doc, fake_bind_registry, session_id=None, bound=True)
    assert report.claims[0].citations[0].verdicts == ()
    assert report.summary["by_method"] == {}


def test_checks_record_verdicts_beside_the_status(tmp_path, fake_bind_registry) -> None:
    resolved = token(fake_bind_registry, "t12-audit", "p8.c3")
    doc = write(tmp_path, f"NOI was [$4.12M]({resolved}).\n")
    report = bind(doc, fake_bind_registry, session_id=None, checks=["value-trace", "overlap"], bound=True)
    (citation,) = report.claims[0].citations
    assert [verdict.method for verdict in citation.verdicts] == ["value-trace", "overlap"]
    assert citation.verdicts[0].status is VerdictStatus.PASS
    assert report.summary["by_method"]["value-trace"] == {"pass": 1}


def test_a_verdict_never_changes_a_citations_status(tmp_path, fake_bind_registry) -> None:
    resolved = token(fake_bind_registry, "t12-audit", "p8.c3")
    doc = write(tmp_path, f"NOI was [$9.99M]({resolved}).\n")
    report = bind(doc, fake_bind_registry, session_id=None, checks=["value-trace"], bound=True)
    (citation,) = report.claims[0].citations
    assert citation.verdicts[0].status is VerdictStatus.FAIL
    assert citation.status is CitationStatus.RESOLVED
    assert report.unresolved == ()


def test_a_method_that_does_not_apply_writes_no_row(tmp_path, fake_bind_registry) -> None:
    resolved = token(fake_bind_registry, "t12-audit", "p8.c3")
    doc = write(tmp_path, f"[occupancy held]({resolved}).\n")
    report = bind(doc, fake_bind_registry, session_id=None, checks=["value-trace", "recompute"], bound=True)
    assert report.claims[0].citations[0].verdicts == ()


def test_citations_without_an_anchor_carry_no_verdicts(tmp_path, fake_bind_registry) -> None:
    doc = write(tmp_path, "[NOI of $4.12M](bd:ghost:p1.c1:0000).\n")
    report = bind(doc, fake_bind_registry, session_id=None, checks=["value-trace", "overlap"], bound=True)
    assert report.claims[0].citations[0].verdicts == ()


def test_an_unknown_check_name_raises(tmp_path, fake_bind_registry) -> None:
    doc = write(tmp_path, "[a](bd:ghost:p1.c1:0000).\n")
    with pytest.raises(ValueError, match="unknown verification method"):
        bind(doc, fake_bind_registry, session_id=None, checks=["value_trace"])


def test_a_batching_verifier_is_prepared_once_before_verifying(tmp_path, fake_bind_registry, monkeypatch) -> None:
    from backdraft.bind.verify import VERIFIERS

    calls: list[int] = []
    monkeypatch.setattr(
        VERIFIERS["entail"], "prepare", lambda pairs: calls.append(len(pairs))
    )
    monkeypatch.setattr(
        VERIFIERS["entail"],
        "verify",
        lambda claim, citation, anchor: __import__(
            "backdraft.kernel.model", fromlist=["Verdict"]
        ).Verdict(method="entail", status=VerdictStatus.PASS),
    )
    resolved = token(fake_bind_registry, "t12-audit", "p8.c3")
    cell = token(fake_bind_registry, "model", "rent-roll!B10")
    doc = write(tmp_path, f"[a]({resolved}) and [b]({cell}).\n")
    report = bind(doc, fake_bind_registry, session_id=None, checks=["entail"], bound=True)
    assert calls == [2]
    assert report.summary["by_method"]["entail"] == {"pass": 2}


# --- backfill --------------------------------------------------------------


def test_backfill_marks_a_claim_it_could_not_anchor(tmp_path, fake_bind_registry) -> None:
    doc = write(tmp_path, "[NOI was $4.12M](bd:ghost:p1.c1:0000).\n")
    report = bind(doc, fake_bind_registry, mode="backfill", session_id=None, bound=True)
    assert report.claims[0].unmatched is True


def test_backfill_does_not_mark_a_claim_that_anchored(tmp_path, fake_bind_registry) -> None:
    resolved = token(fake_bind_registry, "t12-audit", "p8.c3")
    doc = write(tmp_path, f"[NOI was $4.12M]({resolved}).\n")
    report = bind(doc, fake_bind_registry, mode="backfill", session_id=None, bound=True)
    assert report.claims[0].unmatched is False


def test_backfill_finds_uncited_factual_sentences(tmp_path, fake_bind_registry) -> None:
    doc = write(
        tmp_path,
        "Net operating income was 4,120,000 last year. The property is well located.\n",
    )
    report = bind(doc, fake_bind_registry, mode="backfill", session_id=None, bound=True)
    assert [claim.text for claim in report.claims] == [
        "Net operating income was 4,120,000 last year."
    ]
    assert report.claims[0].unmatched is True
    assert report.claims[0].citations == ()


def test_frontwalk_does_not_scan_for_uncited_claims(tmp_path, fake_bind_registry) -> None:
    doc = write(tmp_path, "Net operating income was 4,120,000 last year.\n")
    report = bind(doc, fake_bind_registry, session_id=None, bound=True)
    assert report.claims == ()


def test_backfill_proposes_but_never_attaches(tmp_path, fake_bind_registry) -> None:
    doc = write(tmp_path, "Net operating income was 4,120,000 last year.\n")
    bind(doc, fake_bind_registry, mode="backfill", session_id=None, bound=True)
    bound = bound_path(doc).read_text(encoding="utf-8")
    assert "## Unmatched claims" in bound
    assert "proposed: `bd:t12-audit:p8.c3:" in bound
    report_json = json.loads(sidecar_path(doc).read_text(encoding="utf-8"))
    assert report_json["claims"][0]["citations"] == []
    assert report_json["claims"][0]["unmatched"] is True


def test_proposals_are_the_top_search_hits(fake_bind_registry) -> None:
    proposed = propose_anchors(fake_bind_registry, "net operating income 4,120,000")
    assert proposed and proposed[0].receipt.snippet == RESOLVED_SNIPPET


def test_a_claim_with_no_search_hits_proposes_nothing(fake_bind_registry) -> None:
    assert propose_anchors(fake_bind_registry, "zzz-unmatchable-zzz") == ()
    assert propose_anchors(fake_bind_registry, "   ") == ()


# --- References, deduplicated ------------------------------------------------
#
# One entry per distinct token. Repeating a 1200-char snippet once per citing
# claim is how a References section stops being readable.


def test_claims_citing_one_anchor_share_a_number(tmp_path, fake_bind_registry) -> None:
    resolved = token(fake_bind_registry, "t12-audit", "p8.c3")
    doc = write(
        tmp_path,
        f"NOI was [$4.12M]({resolved}) last year.\n\n"
        f"The same figure appears in [the summary]({resolved}).\n",
    )
    bind(doc, fake_bind_registry, mode="frontwalk", session_id=None, bound=True)
    bound = bound_path(doc).read_text(encoding="utf-8")
    assert bound.count("(#cite-1)") == 2
    assert "(#cite-2)" not in bound


def test_a_shared_anchor_is_quoted_once(tmp_path, fake_bind_registry) -> None:
    resolved = token(fake_bind_registry, "t12-audit", "p8.c3")
    doc = write(
        tmp_path,
        f"NOI was [$4.12M]({resolved}).\n\nAlso [see this]({resolved}).\n\n"
        f"And [again]({resolved}).\n",
    )
    bind(doc, fake_bind_registry, mode="frontwalk", session_id=None, bound=True)
    bound = bound_path(doc).read_text(encoding="utf-8")
    assert bound.count(f"> {RESOLVED_SNIPPET}") == 1
    assert bound.count('<a id="cite-') == 1


def test_every_citation_still_reaches_the_report(tmp_path, fake_bind_registry) -> None:
    """Deduplication is a rendering rule; the sidecar still carries all three."""
    resolved = token(fake_bind_registry, "t12-audit", "p8.c3")
    doc = write(tmp_path, f"A [one]({resolved}).\n\nB [two]({resolved}).\n")
    report = bind(doc, fake_bind_registry, mode="frontwalk", session_id=None, bound=True)
    assert [len(claim.citations) for claim in report.claims] == [1, 1]
    assert report.summary["citations"] == 2


def test_distinct_anchors_still_get_distinct_numbers(tmp_path, fake_bind_registry) -> None:
    first = token(fake_bind_registry, "t12-audit", "p8.c3")
    second = token(fake_bind_registry, "model", "rent-roll!B10")
    doc = write(tmp_path, f"A [one]({first}) and B [two]({second}).\n")
    bind(doc, fake_bind_registry, mode="frontwalk", session_id=None, bound=True)
    bound = bound_path(doc).read_text(encoding="utf-8")
    assert '<a id="cite-1">' in bound
    assert '<a id="cite-2">' in bound


def test_numbers_follow_first_appearance(tmp_path, fake_bind_registry) -> None:
    first = token(fake_bind_registry, "t12-audit", "p8.c3")
    second = token(fake_bind_registry, "model", "rent-roll!B10")
    doc = write(
        tmp_path,
        f"A [one]({second}).\n\nB [two]({first}).\n\nC [three]({second}).\n",
    )
    bind(doc, fake_bind_registry, mode="frontwalk", session_id=None, bound=True)
    bound = bound_path(doc).read_text(encoding="utf-8")
    body, _, references = bound.partition("## References")
    assert body.count("(#cite-1)") == 2
    assert body.count("(#cite-2)") == 1
    assert references.index("cite-1") < references.index("cite-2")


# --- the query a claim makes ------------------------------------------------
#
# A claim sentence handed to FTS5 verbatim does not parse, retries as a phrase,
# and matches nothing. These are about the reduction that fixes that.


def test_a_claim_becomes_its_distinctive_terms() -> None:
    query = search_query("Real estate taxes of $412,300 are the largest single expense line.")
    assert query == '"largest" OR "expense" OR "estate" OR "single" OR "taxes" OR "412,300"'


def test_stopwords_and_fragments_are_dropped() -> None:
    query = search_query("It is one of the items that we have to look at.")
    assert "the" not in query
    assert '"it"' not in query


def test_an_acronym_outranks_a_longer_word() -> None:
    """`NOI` is rarer in a corpus of prose than `underwritten` is."""
    query = search_query("NOI was underwritten conservatively.")
    assert query.startswith('"noi"')


def test_the_query_carries_the_claim_s_numbers() -> None:
    assert '"412,300"' in search_query("Taxes of $412,300 were assessed.")
    assert '"1.42"' in search_query("The DSCR finished at 1.42x.")


def test_every_term_is_quoted_so_no_word_becomes_an_operator() -> None:
    """A claim containing "or" must not turn into FTS5 syntax."""
    query = search_query("Repairs or replacements exceeded budget.")
    assert query.count('"') == query.count(" OR ") * 2 + 2
    assert " or " not in query.replace(" OR ", " ")


def test_the_query_is_a_pure_function_of_the_claim() -> None:
    claim = "Real estate taxes of $412,300 are the largest single expense line."
    assert search_query(claim) == search_query(claim)


def test_a_claim_with_nothing_distinctive_makes_no_query() -> None:
    assert search_query("It is so.") == ""
    assert search_query("   ") == ""
    assert propose_anchors(FakeAnchorRegistry(), "It is so.") == ()


def test_a_claim_sentence_proposes_its_anchor_against_real_fts5(tmp_path) -> None:
    """The bug, end to end: this claim used to propose nothing at all.

    The fake fake_bind_registry cannot show this — the failure was FTS5's parser rejecting
    `$`, `,` and `.`, so the test needs the real index.
    """
    from backdraft.registry import Registry

    source = tmp_path / "t12.md"
    source.write_text(
        "Total operating expenses were $1,254,800, or $9,803 per unit per year, "
        "driven principally by real estate taxes.\n\n"
        "Real estate taxes of $412,300 represent 32.9% of total operating expenses "
        "and are the single largest line item. The 2025 reassessment raised the "
        "taxable value from $18.4 million to $24.1 million.\n\n"
        "Insurance of $122,700 reflects the renewal completed in July 2025 at a "
        "premium 19% above the expiring policy, and utilities net of reimbursement "
        "were $70,100 for the period.\n",
        encoding="utf-8",
    )
    with Registry.open(tmp_path) as fake_bind_registry:
        fake_bind_registry.ingest(source)
        proposed = propose_anchors(
            fake_bind_registry, "Real estate taxes of $412,300 are the largest single expense line."
        )
    assert proposed, "the claim proposed nothing"
    assert "real estate taxes" in proposed[0].receipt.snippet.lower()
    assert "412,300" in proposed[0].receipt.snippet


def test_backfill_skips_code_fences_and_headings(tmp_path, fake_bind_registry) -> None:
    doc = write(
        tmp_path,
        "# Heading with 2025 in it\n\n```\nvalue = 4120000\n```\n\nCash flow was 900,000.\n",
    )
    report = bind(doc, fake_bind_registry, mode="backfill", session_id=None, bound=True)
    assert [claim.text for claim in report.claims] == ["Cash flow was 900,000."]


def test_backfill_does_not_rescan_a_cited_span(tmp_path, fake_bind_registry) -> None:
    resolved = token(fake_bind_registry, "t12-audit", "p8.c3")
    doc = write(tmp_path, f"NOI was [$4.12M]({resolved}) last year.\n")
    report = bind(doc, fake_bind_registry, mode="backfill", session_id=None, bound=True)
    assert len(report.claims) == 1
    assert report.claims[0].text == "$4.12M"


def test_backfill_claims_come_back_in_document_order(tmp_path, fake_bind_registry) -> None:
    doc = write(tmp_path, "First was 100. Second was 200. Third was 300.\n")
    report = bind(doc, fake_bind_registry, mode="backfill", session_id=None, bound=True)
    assert [claim.start for claim in report.claims] == sorted(
        claim.start for claim in report.claims
    )
    assert len(report.claims) == 3


def test_a_backfill_run_matches_its_golden_file(tmp_path, fake_bind_registry) -> None:
    source = (
        "# Backfill memo\n\n"
        "Net operating income was 4,120,000 last year. The rent roll ties.\n\n"
        "Prior-year NOI was $3.98M, per a note we cannot place.\n"
    )
    doc = write(tmp_path, source)
    bind(doc, fake_bind_registry, mode="backfill", session_id=None, bound=True)
    assert_golden(
        GOLDEN / "backfill.bound.md", bound_path(doc).read_text(encoding="utf-8")
    )


def test_bound_projection_is_opt_in(tmp_path, fake_bind_registry) -> None:
    """Default bind writes the record only; `bound=True` adds the projection.

    The standard working set is three files: the authored document, the
    sidecar record, the artifact.
    """
    resolved = token(fake_bind_registry, "t12-audit", "p8.c3")
    doc = write(tmp_path, f"NOI was [$4.12M]({resolved}).\n")
    bind(doc, fake_bind_registry, session_id="s1")
    assert not bound_path(doc).exists()
    assert sidecar_path(doc).exists()
