"""A claim that straddles two chunks: the gate names the second token.

The chunker cuts a paragraph longer than its limit into pieces, and chunks every
page alone, so a sentence the writer is about to cite can end in a chunk the
query never matched. One token then resolves, the receipt is real, and the half
of the claim living next door is uncited while looking cited. `reader.adjoining`
names that chunk wherever the text may run on into it, decided by the chunks'
own edges: no blank line between two chunks of a page, or a page break.

The fakes carry offsets the way the real store does, and `splits` joins two
chunks of one page with a space instead of a blank line — the one shape the
chunker produces only by cutting a paragraph for length.
"""

from __future__ import annotations

import dataclasses

from fake_registry import FakeDocumentRegistry, pdf_document, sheet_document

from backdraft.gate.reader import (
    ADJOINING_NOTE,
    EXCERPT_CHARS,
    Adjoining,
    adjoining,
    adjoining_lines,
    read,
)
from backdraft.gate.searcher import search

_OPENING = "The borrower's reserve covenant runs to the end of the term."
_MIDDLE = "Debt service coverage was 1.42x for the trailing twelve months."
_CLOSING = "The lender waived the cash sweep for the quarter."


def _one_page(*, splits: tuple[int, ...] = ()) -> FakeDocumentRegistry:
    """Three chunks on one page; `splits` names ordinals joined to the next by a space."""
    return FakeDocumentRegistry().add(
        pdf_document("memo", "memo.pdf", [[_OPENING, _MIDDLE, _CLOSING]], splits=[splits])
    )


def _token(registry: FakeDocumentRegistry, locator: str) -> str:
    return next(
        anchor.token
        for page in registry.pages("memo")
        for anchor in registry.anchors_for_page("memo", page.number)
        if str(anchor.locator) == locator
    )


# ---- a hit wholly inside a paragraph ------------------------------------------


def test_a_hit_wholly_inside_a_paragraph_prints_what_it_always_did() -> None:
    """The acceptance's negative branch, byte for byte: blank lines on both sides
    of a chunk on a one-page source mean nothing adjoins it and nothing is added."""
    registry = _one_page()
    assert search(registry, "coverage", session="s") == """\
1 result for "coverage"

[bd:memo:p1.c2:925e]  memo p1
  Debt service coverage was 1.42x for the trailing twelve months.

[Read the page: backdraft read memo p1]"""
    assert registry.shown_tokens("s") == {"bd:memo:p1.c2:925e"}


def test_a_one_page_read_names_nothing_beyond_it() -> None:
    output = read(_one_page(), "memo", "p1", session="s")
    assert "next page begins" not in output
    assert ADJOINING_NOTE not in output


# ---- a paragraph the chunker split ---------------------------------------------


def test_a_hit_in_a_split_paragraph_names_the_chunk_it_runs_on_into() -> None:
    registry = _one_page(splits=(2,))
    output = search(registry, "coverage", session="s")
    after = _token(registry, "p1.c3")
    assert output == f"""\
1 result for "coverage"

[bd:memo:p1.c2:925e]  memo p1
  Debt service coverage was 1.42x for the trailing twelve months.
  same paragraph, after: [{after}]
    The lender waived the cash sweep for the quarter.

[Read the page: backdraft read memo p1]

{ADJOINING_NOTE}"""


def test_both_tokens_are_recorded_as_shown() -> None:
    """Emitting is minting, for the adjoining chunk exactly as for the hit."""
    registry = _one_page(splits=(1, 2))
    search(registry, "coverage", session="s")
    assert registry.shown_tokens("s") == {
        _token(registry, "p1.c1"),
        _token(registry, "p1.c2"),
        _token(registry, "p1.c3"),
    }


def test_the_chunk_before_shows_the_end_that_touches_the_hit() -> None:
    """The edge that matters for a straddling claim is the one beside the hit."""
    long = "Opening words that scroll away. " + "filler " * 40 + "the last words before it."
    registry = FakeDocumentRegistry().add(
        pdf_document("memo", "memo.pdf", [[long, _MIDDLE]], splits=[(1,)])
    )
    lines = search(registry, "coverage", session="s").splitlines()
    label = lines.index(f"  same paragraph, before: [{_token(registry, 'p1.c1')}]")
    tail = lines[label + 1].strip()
    assert tail.startswith("...")
    assert tail.endswith("the last words before it.")
    assert len(tail) == EXCERPT_CHARS + len("...")


def test_a_blank_line_on_one_side_names_only_the_other() -> None:
    registry = _one_page(splits=(1,))
    output = search(registry, "coverage", session="s")
    assert f"same paragraph, before: [{_token(registry, 'p1.c1')}]" in output
    assert "after:" not in output


# ---- a page break ----------------------------------------------------------------


def _paged() -> FakeDocumentRegistry:
    return FakeDocumentRegistry().add(
        pdf_document("memo", "memo.pdf", [[_OPENING, _MIDDLE], [_CLOSING]])
    )


def test_a_hit_ending_a_page_names_the_first_chunk_of_the_next() -> None:
    registry = _paged()
    output = search(registry, "coverage", session="s")
    assert f"  next page begins: [{_token(registry, 'p2.c1')}]" in output.splitlines()
    assert _token(registry, "p2.c1") in registry.shown_tokens("s")


def test_a_hit_opening_a_page_names_the_last_chunk_of_the_one_before() -> None:
    """The last chunk, not the first: that is the one the break sits beside."""
    registry = _paged()
    output = search(registry, "cash sweep", session="s")
    assert f"  previous page ends: [{_token(registry, 'p1.c2')}]" in output.splitlines()
    assert _token(registry, "p1.c1") not in output


def test_the_note_is_printed_once_however_many_hits_adjoin() -> None:
    registry = FakeDocumentRegistry().add(
        pdf_document("memo", "memo.pdf", [["alpha one", "alpha two"], ["alpha three"]])
    )
    assert search(registry, "alpha", session="s").count(ADJOINING_NOTE) == 1


def test_an_empty_page_between_adjoins_nothing() -> None:
    """A page with no chunks has nothing to name, and what lies past it is not next."""
    registry = FakeDocumentRegistry().add(
        pdf_document("memo", "memo.pdf", [[_MIDDLE], [], [_CLOSING]])
    )
    assert search(registry, "coverage", session="s").endswith(
        "[Read the page: backdraft read memo p1]"
    )


# ---- what never adjoins ------------------------------------------------------------


def test_a_cell_hit_names_nothing() -> None:
    """A sheet's citable unit is the cell, and cells are not cut from paragraphs."""
    registry = FakeDocumentRegistry().add(
        sheet_document(
            "model",
            "model.xlsx",
            [("Rent", ["| Row | A |", "|---|---|", "| 1 | [A1] coverage |"])],
        )
    )
    assert ADJOINING_NOTE not in search(registry, "coverage", session="s")


def test_unknown_offsets_claim_no_paragraph() -> None:
    """Without offsets the whitespace between two chunks cannot be read, and a
    chunk is not said to run on into a neighbour nothing shows it touches."""
    registry = _one_page(splits=(1, 2))
    loaded = registry._docs["memo"]
    loaded.anchors[1] = [
        dataclasses.replace(anchor, start=None, end=None) for anchor in loaded.anchors[1]
    ]
    assert adjoining(registry, loaded.anchors[1]) == {}


def test_overlapping_offsets_claim_no_paragraph() -> None:
    """Chunks never overlap, so offsets that say they do are not read as a join."""
    registry = _one_page(splits=(1,))
    loaded = registry._docs["memo"]
    first, second = [a for a in loaded.anchors[1] if a.kind == "chunk"][:2]
    assert adjoining(registry, [first])[first.token].after == second
    overlapping = dataclasses.replace(second, start=first.end - 1)
    loaded.anchors[1] = [overlapping if a is second else a for a in loaded.anchors[1]]
    assert adjoining(registry, [first]) == {}


def test_a_chunk_off_its_pages_current_anchors_names_nothing() -> None:
    """A superseded generation's chunk is not on the page it names any more."""
    registry = _one_page(splits=(1,))
    stale = dataclasses.replace(
        registry.anchors_for_page("memo", 1)[0], token="bd:memo:p1.c1:0000"
    )
    assert adjoining(registry, [stale]) == {}


# ---- the page read's half ----------------------------------------------------------


def test_a_page_read_names_the_next_page_and_mints_it() -> None:
    registry = _paged()
    output = read(registry, "memo", "p1", session="s")
    first = _token(registry, "p2.c1")
    assert output.endswith(
        f"{_MIDDLE}\n\nnext page begins: [{first}]\n  {_CLOSING}\n\n{ADJOINING_NOTE}"
    )
    assert first in registry.shown_tokens("s")


def test_a_read_of_the_last_page_names_nothing_after_it() -> None:
    output = read(_paged(), "memo", "p2", session="s")
    assert "next page begins" not in output
    assert ADJOINING_NOTE not in output


def test_a_read_that_stops_short_names_nothing_beyond_it() -> None:
    """Its closing line already says how to go on; the page break is not reached."""
    registry = _paged()
    output = read(registry, "memo", "p1", session="s", limit=10)
    assert "Continue with:" in output
    assert "next page begins" not in output
    assert _token(registry, "p2.c1") not in registry.shown_tokens("s")


def test_a_range_names_only_what_follows_its_last_page() -> None:
    """Inside a range the next page's first chunk is already printed under its token."""
    registry = FakeDocumentRegistry().add(
        pdf_document("memo", "memo.pdf", [[_OPENING], [_MIDDLE], [_CLOSING]])
    )
    output = read(registry, "memo", "p1-2", session="s")
    assert output.count("next page begins") == 1
    assert f"next page begins: [{_token(registry, 'p3.c1')}]" in output


def test_a_page_read_does_not_repeat_the_chunk_it_already_printed() -> None:
    """The read shows every chunk of its page, so only the break after it adjoins."""
    output = read(_one_page(splits=(1, 2)), "memo", "p1", session="s")
    assert "same paragraph" not in output


def test_search_and_the_page_read_print_one_shape() -> None:
    """One owner for the lines: the page read's are `adjoining_lines`', unindented."""
    registry = _paged()
    last = registry.anchors_for_page("memo", 1)[-1]
    first = registry.anchors_for_page("memo", 2)[0]
    lines = adjoining_lines(last, Adjoining(after=first))
    assert "\n".join(lines) in read(registry, "memo", "p1", session="s")
    indented = "\n".join(adjoining_lines(last, Adjoining(after=first), indent="  "))
    assert indented in search(registry, "coverage", session="s")
