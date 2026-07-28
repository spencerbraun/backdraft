"""overlap, recompute, entail, and the verifier fake_bind_registry."""

from __future__ import annotations

import pytest

from backdraft.bind.verify import VERIFIERS, selected
from backdraft.bind.verify.entail import Entail
from backdraft.bind.verify.overlap import PASS_RATIO, Overlap, quoted_spans, word_tokens
from backdraft.bind.verify.recompute import Recompute
from backdraft.kernel.model import (
    Anchor,
    Citation,
    CitationStatus,
    Claim,
    Receipt,
    VerdictStatus,
)
from backdraft.kernel.tokens import parse_locator

OVERLAP = Overlap()


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


# --- the fake_bind_registry ----------------------------------------------------------


def test_every_spec_method_is_registered() -> None:
    assert set(VERIFIERS) == {"value-trace", "overlap", "recompute", "entail"}


def test_selected_returns_the_named_methods_in_order() -> None:
    chosen = selected(["overlap", "value-trace"])
    assert [verifier.method for verifier in chosen] == ["overlap", "value-trace"]


def test_selected_of_nothing_is_nothing() -> None:
    assert selected([]) == []


def test_selected_deduplicates() -> None:
    assert len(selected(["overlap", "overlap"])) == 1


def test_an_unknown_method_is_a_usage_error() -> None:
    with pytest.raises(ValueError, match="unknown verification method"):
        selected(["value_trace"])


# --- overlap ---------------------------------------------------------------


def test_overlap_applies_to_any_claim_with_words() -> None:
    assert OVERLAP.applies(claim("occupancy held steady"), citation()) is True
    assert OVERLAP.applies(claim("   "), citation()) is False


def test_a_verbatim_quoted_span_passes() -> None:
    verdict = OVERLAP.verify(
        claim('the auditor called it "materially consistent" with prior years'),
        citation(),
        anchor("Results are materially consistent with the prior two fiscal years."),
    )
    assert verdict.status is VerdictStatus.PASS
    assert "verbatim" in verdict.detail


def test_a_quoted_span_differing_only_in_case_is_partial() -> None:
    verdict = OVERLAP.verify(
        claim('described as "Materially Consistent"'),
        citation(),
        anchor("Results are materially consistent with prior years."),
    )
    assert verdict.status is VerdictStatus.PARTIAL
    assert "case" in verdict.detail


def test_a_missing_quoted_span_is_partial_never_fail() -> None:
    verdict = OVERLAP.verify(
        claim('the auditor called it "wholly unsupported"'),
        citation(),
        anchor("Results are materially consistent with prior years."),
    )
    assert verdict.status is VerdictStatus.PARTIAL
    assert "not in snippet" in verdict.detail


def test_smart_quotes_are_quoted_spans_too() -> None:
    assert quoted_spans("he said “fully occupied” today") == ["fully occupied"]


def test_a_quoted_span_matches_across_reflowed_whitespace() -> None:
    verdict = OVERLAP.verify(
        claim('the report says "materially consistent"'),
        citation(),
        anchor("Results are materially\n   consistent with prior years."),
    )
    assert verdict.status is VerdictStatus.PASS


def test_high_token_overlap_passes() -> None:
    verdict = OVERLAP.verify(
        claim("occupancy held steady at 94 percent"),
        citation(),
        anchor("Occupancy held steady at 94 percent across the trailing twelve months."),
    )
    assert verdict.status is VerdictStatus.PASS
    assert "ratio" in verdict.detail


def test_low_token_overlap_is_partial_never_fail() -> None:
    verdict = OVERLAP.verify(
        claim("the sponsor refinanced the mezzanine tranche"),
        citation(),
        anchor("Occupancy held steady across the trailing twelve months."),
    )
    assert verdict.status is VerdictStatus.PARTIAL


def test_overlap_never_returns_fail() -> None:
    for snippet in ("", "unrelated text entirely", "occupancy held steady"):
        verdict = OVERLAP.verify(claim("occupancy held steady"), citation(), anchor(snippet))
        assert verdict.status is not VerdictStatus.FAIL


def test_the_pass_threshold_is_the_documented_ratio() -> None:
    assert 0 < PASS_RATIO <= 1


def test_word_tokens_keep_numerals_whole() -> None:
    assert word_tokens("NOI of $4,120,000 rose") == ["noi", "of", "4,120,000", "rose"]


# --- recompute -------------------------------------------------------------


def test_recompute_applies_to_nothing() -> None:
    assert Recompute().applies(claim("NOI of $4.1M"), citation()) is False


def test_recompute_is_registered_under_its_spec_name() -> None:
    assert VERIFIERS["recompute"].method == "recompute"


def test_recompute_mentions_the_reserved_derivation_form() -> None:
    assert "bd:calc" in (Recompute.__doc__ or "") + (Recompute.verify.__doc__ or "")


def test_recompute_skips_rather_than_raising_if_ever_called() -> None:
    verdict = Recompute().verify(claim("x"), citation(), anchor("y"))
    assert verdict.status is VerdictStatus.SKIP


# --- entail ----------------------------------------------------------------


def test_entail_module_loads_without_the_extra() -> None:
    assert VERIFIERS["entail"].method == "entail"


def test_entail_applies_to_any_claim_with_text() -> None:
    verifier = Entail()
    assert verifier.applies(claim("occupancy improved"), citation()) is True
    assert verifier.applies(claim("  "), citation()) is False


def test_entail_skips_with_a_reason_when_it_cannot_run(monkeypatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    verdict = Entail().verify(claim("occupancy improved"), citation(), anchor("text"))
    assert verdict.status is VerdictStatus.SKIP
    assert verdict.detail


def test_entail_records_a_judged_batch(monkeypatch) -> None:
    verifier = Entail()
    asked: list[list[tuple[str, str]]] = []

    def fake_ask(batch):
        asked.append(list(batch))
        for index, key in enumerate(batch):
            answer = ("yes", "partial", "no")[index % 3]
            verifier._answers[key] = (
                {"yes": VerdictStatus.PASS, "partial": VerdictStatus.PARTIAL, "no": VerdictStatus.FAIL}[
                    answer
                ],
                f"judge: {answer}",
            )

    monkeypatch.setattr(verifier, "_ask", fake_ask)
    pairs = [
        (claim("first"), citation(), anchor("one")),
        (claim("second"), citation(), anchor("two")),
        (claim("third"), citation(), anchor("three")),
    ]
    verifier.prepare(pairs)
    assert len(asked) == 1 and len(asked[0]) == 3
    statuses = [verifier.verify(*pair).status for pair in pairs]
    assert statuses == [VerdictStatus.PASS, VerdictStatus.PARTIAL, VerdictStatus.FAIL]
    assert len(asked) == 1  # prepared answers are not re-asked


# --- overlap on cell anchors -------------------------------------------------


def test_overlap_skips_cell_anchors_with_a_reason() -> None:
    cell = Anchor(
        slug="model",
        locator=parse_locator("rent-roll!B10"),
        receipt=Receipt(snippet="24850000", snippet_sha256="0" * 64),
        token="bd:model:rent-roll!B10:27e9",
    )
    verdict = OVERLAP.verify(claim("gross rent of $24,850,000"), citation(), cell)
    assert verdict.status is VerdictStatus.SKIP
    assert "single cell" in verdict.detail
