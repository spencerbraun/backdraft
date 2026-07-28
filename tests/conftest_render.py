"""Bind reports built by hand, for the renderers.

W4's only inputs are an authored document and a sidecar, so its fixtures are
exactly that: a document, and a `BindReport` assembled from kernel dataclasses.
No registry, no bind. The claim offsets come from `kernel.claims.parse_claims`,
so the fixture agrees with the parser rather than with a hand count.

`demo_report` covers every citation status, every verdict status, and every
locator kind; `backfill_report` covers the backfill-only `unmatched` claim.
"""

from __future__ import annotations

import dataclasses

import pytest

from backdraft.kernel import hashing
from backdraft.kernel.claims import parse_claims
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

DSCR_CHUNK = (
    "Debt service coverage for the trailing twelve months is 1.42x, "
    "against a covenant floor of 1.20x."
)
NOI_CELL = "[B10] 4,100,000"
COVERAGE_PAGE = (
    "Page 8 — Coverage\n\n"
    "Debt service coverage for the trailing twelve months is 1.42x, "
    "against a covenant floor of 1.20x.\n\n"
    "The covenant floor is unchanged from the prior review."
)
COVERAGE_PAGE_AS_CITED = COVERAGE_PAGE.replace("1.42x", "1.31x")
OCCUPANCY_CHUNK = "Occupancy closed the year at 91.4%, down from 93.8%."
SCHEDULE_RANGE = "[B10] 4,100,000\n[B11] 260,000\n[C10] 3,980,000\n[C11] 240,000"

DEMO_DOC = """# Bridgeview — T-12 review

**Recommendation:** proceed to term sheet. The property clears its covenant at a
[DSCR of 1.42x](bd:t12-audit:p8.c3:f3e4), on
[NOI of $4.1M](bd:model:rent-roll!B10:27e9;bd:t12-audit:p8:8f04).

## What the file says

- Occupancy [has been stable through the year](bd:t12-audit:p4.c1:ad01).
- The [reserve balance](bd:t12-audit:p12.c2:0000) is unchanged, per the *prior* memo.
- Across both files, [the ratios tie](bd:calc(model:rent-roll!B10 / t12-audit:p4.c1)).

The underwriting rows come from [the reserve schedule](bd:model:rent-roll!B10:C12:3095):

| Line | 2025 | 2024 |
|---|---:|---:|
| Revenue | 6,410,000 | 6,120,000 |
| Expenses | 2,310,000 | 2,260,000 |

> Underwriting is `unchanged` from the prior review.

See the [appendix](appendix.md) for the rent roll as extracted.
"""

BACKFILL_DOC = """# Rent roll notes

Vacancy improved to 4.2% at year end.

Management believes the trend continues into 2026.
"""


def anchor(slug: str, locator: str, snippet: str, token: str) -> Anchor:
    """An anchor as the sidecar carries it: slug, locator, snippet, hash."""
    parsed = parse_locator(locator)
    return Anchor(
        slug=slug,
        locator=parsed,
        receipt=Receipt(snippet=snippet, snippet_sha256=hashing.snippet_hash(snippet)),
        token=token,
        page_number=getattr(parsed, "page", None),
    )


def demo_report() -> BindReport:
    """The document above, bound: every status, every verdict, every locator kind."""
    claims = parse_claims(DEMO_DOC)
    assert len(claims) == 6, "fixture drift: the demo document has six claims"
    citations: list[tuple[Citation, ...]] = [
        (
            Citation(
                token="bd:t12-audit:p8.c3:f3e4",
                status=CitationStatus.RESOLVED,
                anchor=anchor("t12-audit", "p8.c3", DSCR_CHUNK, "bd:t12-audit:p8.c3:f3e4"),
                verdicts=(
                    Verdict("value-trace", VerdictStatus.PASS, "1.42x occurs in the snippet"),
                    Verdict("overlap", VerdictStatus.PARTIAL, "0.62 of the claim's tokens"),
                ),
            ),
        ),
        (
            Citation(
                token="bd:model:rent-roll!B10:27e9",
                status=CitationStatus.RESOLVED,
                anchor=anchor("model", "rent-roll!B10", NOI_CELL, "bd:model:rent-roll!B10:27e9"),
                verdicts=(
                    Verdict("value-trace", VerdictStatus.PASS, "4,100,000 == $4.1M at scale 1e6"),
                ),
            ),
            Citation(
                token="bd:t12-audit:p8:8f04",
                status=CitationStatus.DRIFTED,
                anchor=anchor("t12-audit", "p8", COVERAGE_PAGE, "bd:t12-audit:p8:8f04"),
                drifted_from=COVERAGE_PAGE_AS_CITED,
                verdicts=(
                    Verdict("value-trace", VerdictStatus.FAIL, "$4.1M does not occur in the page"),
                ),
            ),
        ),
        (
            Citation(
                token="bd:t12-audit:p4.c1:ad01",
                status=CitationStatus.NOT_SHOWN,
                anchor=anchor("t12-audit", "p4.c1", OCCUPANCY_CHUNK, "bd:t12-audit:p4.c1:ad01"),
                verdicts=(
                    Verdict("entail", VerdictStatus.SKIP, "judge not enabled for this run"),
                ),
            ),
        ),
        (
            Citation(
                token="bd:t12-audit:p12.c2:0000",
                status=CitationStatus.UNRESOLVED,
            ),
        ),
        (
            Citation(
                token="bd:calc(model:rent-roll!B10 / t12-audit:p4.c1)",
                status=CitationStatus.MALFORMED,
                error=(
                    "reserved derivation form 'bd:calc(...)' is not supported in v0: "
                    "'bd:calc(model:rent-roll!B10 / t12-audit:p4.c1)'"
                ),
            ),
        ),
        (
            Citation(
                token="bd:model:rent-roll!B10:C12:3095",
                status=CitationStatus.RESOLVED,
                anchor=anchor(
                    "model", "rent-roll!B10:C12", SCHEDULE_RANGE, "bd:model:rent-roll!B10:C12:3095"
                ),
                verdicts=(
                    Verdict("overlap", VerdictStatus.PASS, "exact substring for the quoted rows"),
                    Verdict("entail", VerdictStatus.PARTIAL, "supports the rows, not the trend"),
                ),
            ),
        ),
    ]
    return BindReport(
        doc_path="memo.md",
        mode="frontwalk",
        bound_at="2026-07-27T14:32:05Z",
        session_id="s-bridgeview-01",
        claims=tuple(
            dataclasses.replace(claim, citations=found)
            for claim, found in zip(claims, citations, strict=True)
        ),
    )


def backfill_report() -> BindReport:
    """Backfill mode: one anchored claim, one claim bind could not anchor."""
    anchored_text = "4.2% at year end"
    unmatched_text = "Management believes the trend continues into 2026."
    anchored_start = BACKFILL_DOC.index(anchored_text)
    unmatched_start = BACKFILL_DOC.index(unmatched_text)
    return BindReport(
        doc_path="notes.md",
        mode="backfill",
        bound_at="2026-07-27T15:01:44Z",
        claims=(
            Claim(
                text=anchored_text,
                start=anchored_start,
                end=anchored_start + len(anchored_text),
                citations=(
                    Citation(
                        token="bd:model:rent-roll!B10:27e9",
                        status=CitationStatus.RESOLVED,
                        anchor=anchor(
                            "model", "rent-roll!B10", NOI_CELL, "bd:model:rent-roll!B10:27e9"
                        ),
                        verdicts=(Verdict("overlap", VerdictStatus.PARTIAL, "0.41"),),
                    ),
                ),
            ),
            Claim(
                text=unmatched_text,
                start=unmatched_start,
                end=unmatched_start + len(unmatched_text),
                unmatched=True,
            ),
        ),
    )


@pytest.fixture
def demo_doc() -> str:
    return DEMO_DOC


@pytest.fixture
def demo() -> BindReport:
    return demo_report()


@pytest.fixture
def backfill_doc() -> str:
    return BACKFILL_DOC


@pytest.fixture
def backfill() -> BindReport:
    return backfill_report()
