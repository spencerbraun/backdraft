"""value-trace: the equivalence table, and the verdict rule over it."""

from __future__ import annotations

import pytest

from backdraft.bind.verify.value_trace import ValueTrace, extract_values, matches
from backdraft.kernel.model import (
    Anchor,
    Citation,
    Claim,
    CitationStatus,
    Receipt,
    VerdictStatus,
)
from backdraft.kernel.tokens import parse_locator

VERIFIER = ValueTrace()


def anchor(snippet: str) -> Anchor:
    return Anchor(
        slug="t12-audit",
        locator=parse_locator("p8.c3"),
        receipt=Receipt(snippet=snippet, snippet_sha256="0" * 64),
        token="bd:t12-audit:p8.c3:a7f3",
    )


def claim(text: str) -> Claim:
    return Claim(text=text, start=0, end=len(text))


def citation() -> Citation:
    return Citation(token="bd:t12-audit:p8.c3:a7f3", status=CitationStatus.RESOLVED)


def match(claimed: str, found: str) -> str | None:
    claimed_values = extract_values(claimed)
    found_values = extract_values(found)
    assert claimed_values, f"no value extracted from {claimed!r}"
    assert found_values, f"no value extracted from {found!r}"
    return matches(claimed_values[0], found_values[0])


# --- the equivalence table -------------------------------------------------

EXACT = [
    # scale suffixes, attached and spelled
    ("$1.4M", "1,400,000"),
    ("1.4M", "1400000"),
    ("1.4 million", "1,400,000"),
    ("$1.4M", "1.4 million"),
    ("1.4MM", "1400000"),
    ("$2.5K", "2,500"),
    ("3 thousand", "3000"),
    ("1.2B", "1,200,000,000"),
    ("1.2bn", "1.2 billion"),
    ("0.5T", "500,000,000,000"),
    # thousands separators and currency symbols
    ("$4,120,000", "4120000"),
    ("€1,234.56", "1234.56"),
    ("£99", "99"),
    ("¥1,000", "1000"),
    # percent, both directions
    ("12%", "0.12"),
    ("0.12", "12%"),
    ("12%", "12"),
    ("41.2%", "0.412"),
    ("7 percent", "0.07"),
    # multipliers
    ("1.42x", "1.42"),
    ("1.42", "1.42x"),
    ("2.5X", "2.50"),
    ("1.42×", "1.42"),
    # trailing zeros and formatting
    ("4.10", "4.1"),
    ("4.1", "4.100"),
    (".5", "0.50"),
    # accounting negatives
    ("(1,234)", "-1234"),
    ("-1234", "(1,234)"),
    ("($1.4M)", "-1400000"),
    # dates
    ("2025-03-31", "March 31, 2025"),
    ("2025-03-31", "Mar. 31 2025"),
    ("2025-03-31", "31 March 2025"),
    ("2025-03-31", "3/31/2025"),
    ("March 31, 2025", "31 March 2025"),
    ("Sept 1, 2025", "2025-09-01"),
    ("2025-03", "March 2025"),
    ("2025-03", "Mar 2025"),
    # an ambiguous slash date reads either way, so it matches either way
    ("4/5/2025", "5 April 2025"),
    ("4/5/2025", "April 5, 2025"),
]

ROUNDED = [
    ("$1.4M", "1,412,000"),
    ("1.4 million", "1,449,999"),
    ("$4.1M", "4,120,000"),
    ("3.2%", "0.0317"),
    ("March 2025", "2025-03-31"),
    ("2025-03-31", "March 2025"),
]

NO_MATCH = [
    ("$1.4M", "2,000,000"),
    ("1.4M", "1,600,000"),
    ("12%", "0.13"),
    ("1.42x", "1.43"),
    ("(1,234)", "1234"),
    ("2025-03-31", "2025-04-30"),
    ("March 2025", "April 2025"),
    ("2025-03-31", "1400000"),  # a date is never a number
]


@pytest.mark.parametrize(("claimed", "found"), EXACT)
def test_exact_equivalences(claimed: str, found: str) -> None:
    assert match(claimed, found) == "exact"


@pytest.mark.parametrize(("claimed", "found"), ROUNDED)
def test_rounded_equivalences(claimed: str, found: str) -> None:
    assert match(claimed, found) == "rounded"


@pytest.mark.parametrize(("claimed", "found"), NO_MATCH)
def test_non_equivalences(claimed: str, found: str) -> None:
    assert match(claimed, found) is None


def test_exact_equivalence_is_symmetric() -> None:
    for claimed, found in EXACT:
        assert match(found, claimed) == "exact", f"{found!r} vs {claimed!r}"


# --- extraction ------------------------------------------------------------


def test_dates_are_not_decomposed_into_numbers() -> None:
    values = extract_values("Filed 2025-03-31 with the trustee.")
    assert [value.kind for value in values] == ["date"]


def test_sentence_punctuation_is_not_part_of_a_number() -> None:
    (value,) = extract_values("The total was 1,400,000.")
    assert value.text == "1,400,000"


def test_values_come_back_in_document_order() -> None:
    values = extract_values("NOI of $4.1M on 2025-03-31 against a 1.42x DSCR")
    assert [value.kind for value in values] == ["number", "date", "number"]


def test_prose_without_values_yields_none() -> None:
    assert extract_values("The property performed in line with expectations.") == []


def test_a_bare_word_is_not_a_scale_suffix() -> None:
    (value,) = extract_values("3 Bedrooms")
    assert value.readings[0].number == 3


# --- applies ---------------------------------------------------------------


def test_applies_only_when_the_claim_carries_a_value() -> None:
    assert VERIFIER.applies(claim("DSCR of 1.42x"), citation()) is True
    assert VERIFIER.applies(claim("The covenant was met"), citation()) is False


def test_applies_to_a_claim_carrying_only_a_date() -> None:
    assert VERIFIER.applies(claim("as of March 31, 2025"), citation()) is True


# --- the verdict rule ------------------------------------------------------


def test_all_values_found_exactly_is_a_pass() -> None:
    verdict = VERIFIER.verify(
        claim("NOI of $4.12M as of 2025-03-31"),
        citation(),
        anchor("Net operating income 4,120,000 for the period ended March 31, 2025."),
    )
    assert verdict.status is VerdictStatus.PASS
    assert verdict.method == "value-trace"


def test_a_rounded_value_is_a_partial() -> None:
    verdict = VERIFIER.verify(
        claim("NOI of $4.1M"), citation(), anchor("Net operating income 4,120,000.")
    )
    assert verdict.status is VerdictStatus.PARTIAL
    assert "rounded match" in verdict.detail


def test_an_unfound_value_is_a_fail_naming_it() -> None:
    verdict = VERIFIER.verify(
        claim("NOI of $4.12M against a 1.42x DSCR"),
        citation(),
        anchor("Net operating income 4,120,000 for the period."),
    )
    assert verdict.status is VerdictStatus.FAIL
    assert "1.42x" in verdict.detail


def test_no_values_found_at_all_is_a_fail() -> None:
    verdict = VERIFIER.verify(
        claim("NOI of $4.12M"), citation(), anchor("The property is fully occupied.")
    )
    assert verdict.status is VerdictStatus.FAIL


def test_whitespace_in_the_snippet_does_not_change_the_verdict() -> None:
    verdict = VERIFIER.verify(
        claim("NOI of $4.12M"),
        citation(),
        anchor("Net operating\n   income\t4,120,000\nfor the period."),
    )
    assert verdict.status is VerdictStatus.PASS


# --- the receipt has to carry the value ------------------------------------


def test_a_percent_claim_traces_to_its_own_unrounded_cell(registry, tmp_path) -> None:
    """End to end: the cell anchor's snippet is what "5.75%" is checked against.

    A rate rounded on the way into the snapshot cannot be traced back out of it,
    so this test is really about the extractor — but it belongs here, because
    value-trace is where the damage shows.
    """
    from openpyxl import Workbook

    book = Workbook()
    book.active.title = "Assumptions"
    book.active.append(["Going-in cap rate", 0.0575])
    path = tmp_path / "underwriting.xlsx"
    book.save(path)

    document = registry.ingest(path)
    cell = next(
        found
        for found in registry.anchors_for_page(document.slug, 1)
        if found.token.endswith("!B1:" + found.token.rsplit(":", 1)[1])
    )
    assert cell.receipt.snippet == "0.0575"

    verdict = VERIFIER.verify(
        claim("The model underwrites a going-in cap rate of 5.75%."),
        Citation(token=cell.token, status=CitationStatus.RESOLVED),
        cell,
    )
    assert verdict.status is VerdictStatus.PASS


# --- ordinal labels and the zero-rounding guard ------------------------------


def test_year_labels_are_not_claimed_values() -> None:
    values = extract_values("a Year 1 debt yield of 7.7% and a Year 3 debt yield of 8.4%")
    assert [value.text for value in values] == ["7.7%", "8.4%"]


def test_quarter_and_fy_labels_are_masked_too() -> None:
    values = extract_values("Q3 revenue grew 12% over FY 2 baseline")
    assert [value.text for value in values] == ["12%"]


def test_a_number_never_rounds_to_a_bare_zero() -> None:
    verdict = VERIFIER.verify(
        claim("a debt yield of 7.7%"),
        citation(),
        anchor("Loss to Concessions 0 and nothing else"),
    )
    assert verdict.status is VerdictStatus.FAIL
    assert "7.7%" in verdict.detail
