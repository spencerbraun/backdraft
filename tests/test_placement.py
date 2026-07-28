"""Placing claims in the document render was handed, whichever one that is."""

from __future__ import annotations

from backdraft.kernel.model import BindReport, Claim
from backdraft.render.placement import locate

from conftest_render import DEMO_DOC


def test_recorded_offsets_are_used_when_they_still_hold(demo: BindReport) -> None:
    placements = locate(DEMO_DOC, demo.claims)
    assert [placement.number for placement in placements] == [1, 2, 3, 4, 5, 6]
    for placement, claim in zip(placements, demo.claims, strict=True):
        assert (placement.start, placement.end) == (claim.start, claim.end)
        assert DEMO_DOC[placement.start : placement.end].startswith(f"[{claim.text}](")


def test_a_rewritten_document_is_found_by_its_link_text(demo: BindReport) -> None:
    """Bind rewrites tokens into readable citations; the offsets move with them."""
    rewritten = DEMO_DOC.replace(
        "[DSCR of 1.42x](bd:t12-audit:p8.c3:f3e4)", "prefix [DSCR of 1.42x](#cite-1)"
    )
    placement = locate(rewritten, demo.claims)[0]
    assert placement.placed
    assert rewritten[placement.start : placement.end] == "[DSCR of 1.42x](#cite-1)"


def test_a_projected_document_is_found_by_its_text() -> None:
    source = "The DSCR of 1.42x clears the covenant.\n"
    claim = Claim(text="DSCR of 1.42x", start=900, end=930)
    placement = locate(source, [claim])[0]
    assert placement.placed
    assert source[placement.start : placement.end] == "DSCR of 1.42x"


def test_repeated_claim_text_places_in_order() -> None:
    source = "one two. one two.\n"
    claims = [Claim(text="one two", start=0, end=0), Claim(text="one two", start=0, end=0)]
    first, second = locate(source, claims)
    assert (first.start, second.start) == (0, 9)


def test_a_claim_that_is_not_there_is_unplaced() -> None:
    claim = Claim(text="a phrase from another document", start=0, end=0)
    placement = locate("nothing here\n", [claim])[0]
    assert not placement.placed
    assert placement.start is None
    assert placement.number == 1


def test_offsets_past_the_end_of_the_document_do_not_crash() -> None:
    claim = Claim(text="DSCR", start=10_000, end=10_004)
    assert locate("DSCR\n", [claim])[0].start == 0
