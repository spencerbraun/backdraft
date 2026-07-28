"""The chunker: golden files, determinism, and exact offsets.

The golden files in `tests/golden/chunking/` are the contract. A chunk's ordinal
is half of an anchor's identity, so a change that moves a boundary invalidates
citations — these files exist to make that change loud.

Regenerate deliberately, never reflexively:

    BACKDRAFT_UPDATE_GOLDEN=1 uv run pytest tests/test_chunking.py
"""

from __future__ import annotations

import json
import pathlib

import pytest

from backdraft.kernel.chunking import MAX_CHARS, MIN_CHARS, chunk

from golden_util import assert_golden

GOLDEN = pathlib.Path(__file__).parent / "golden" / "chunking"
FIXTURES = sorted(path.stem for path in GOLDEN.glob("*.txt"))


def _as_json(page_text: str) -> list[dict[str, object]]:
    return [
        {"ordinal": c.ordinal, "start": c.start, "end": c.end, "text": c.text}
        for c in chunk(page_text)
    ]


@pytest.mark.parametrize("fixture", FIXTURES)
def test_golden(fixture: str) -> None:
    page_text = (GOLDEN / f"{fixture}.txt").read_text(encoding="utf-8")
    actual = json.dumps(_as_json(page_text), indent=2, ensure_ascii=False) + "\n"
    assert_golden(GOLDEN / f"{fixture}.json", actual)


@pytest.mark.parametrize("fixture", FIXTURES)
def test_offsets_are_exact(fixture: str) -> None:
    page_text = (GOLDEN / f"{fixture}.txt").read_text(encoding="utf-8")
    for piece in chunk(page_text):
        assert page_text[piece.start : piece.end] == piece.text


@pytest.mark.parametrize("fixture", FIXTURES)
def test_chunks_are_ordered_edge_trimmed_and_disjoint(fixture: str) -> None:
    page_text = (GOLDEN / f"{fixture}.txt").read_text(encoding="utf-8")
    chunks = chunk(page_text)
    assert [piece.ordinal for piece in chunks] == list(range(1, len(chunks) + 1))
    previous_end = 0
    for piece in chunks:
        assert piece.text == piece.text.strip()
        assert piece.start >= previous_end
        assert piece.start < piece.end
        previous_end = piece.end
    assert previous_end <= len(page_text)


@pytest.mark.parametrize("fixture", FIXTURES)
def test_determinism(fixture: str) -> None:
    page_text = (GOLDEN / f"{fixture}.txt").read_text(encoding="utf-8")
    assert chunk(page_text) == chunk(page_text)


def test_specific_shapes() -> None:
    """Each golden fixture stands for one shape; assert the shape, not just bytes."""
    counts = {
        fixture: len(chunk((GOLDEN / f"{fixture}.txt").read_text(encoding="utf-8")))
        for fixture in FIXTURES
    }
    # one short page merges into a single chunk
    assert counts["short_page"] == 1
    # twelve tiny paragraphs merge forward into groups of four
    assert counts["many_small"] == 3
    # a 4680-char paragraph splits near 1200, 2400 and 3600
    assert counts["one_giant"] == 4
    # a 2495-char paragraph splits near 1200; the 77-char tail merges backward
    assert counts["long_tail"] == 2
    # a long paragraph with no sentence boundary is left whole, oversize
    assert counts["unsplittable"] == 1


# --- rules, in isolation -----------------------------------------------------


def test_empty_page() -> None:
    assert chunk("") == []


def test_whitespace_only_page() -> None:
    assert chunk("   \n\n \t \n") == []


def test_single_paragraph_is_one_chunk() -> None:
    text = "A single sentence about the reserve account."
    chunks = chunk(text)
    assert len(chunks) == 1
    assert chunks[0].ordinal == 1
    assert chunks[0].text == text
    assert (chunks[0].start, chunks[0].end) == (0, len(text))


def test_leading_and_trailing_whitespace_is_outside_the_offsets() -> None:
    body = "A single sentence about the reserve account."
    text = f"\n\n  {body}  \n\n"
    piece = chunk(text)[0]
    assert piece.text == body
    assert text[piece.start : piece.end] == body


def test_long_paragraph_stands_alone_when_it_clears_the_minimum() -> None:
    first = "A. " * 70  # 210 chars
    second = "B. " * 70
    chunks = chunk(f"{first.strip()}\n\n{second.strip()}")
    assert len(chunks) == 2


def test_short_paragraph_merges_forward() -> None:
    short = "Too short."
    long = "C" * (MIN_CHARS + 10)
    chunks = chunk(f"{short}\n\n{long}")
    assert len(chunks) == 1
    assert chunks[0].text.startswith(short)
    assert chunks[0].text.endswith(long)


def test_trailing_short_paragraph_merges_backward() -> None:
    long = "D" * (MIN_CHARS + 10)
    chunks = chunk(f"{long}\n\nToo short.")
    assert len(chunks) == 1
    assert chunks[0].text.endswith("Too short.")


def test_a_lone_short_paragraph_survives_alone() -> None:
    chunks = chunk("Only this.")
    assert len(chunks) == 1
    assert chunks[0].text == "Only this."


def test_blank_line_variants_all_split() -> None:
    body = "E" * (MIN_CHARS + 10)
    for separator in ("\n\n", "\n\n\n", "\n   \n", "\n\t\n", "\r\n\r\n", "\n \n \n"):
        assert len(chunk(f"{body}{separator}{body}")) == 2, separator


def test_single_newline_does_not_split() -> None:
    body = "F" * (MIN_CHARS + 10)
    assert len(chunk(f"{body}\n{body}")) == 1


def test_split_happens_at_sentence_starts() -> None:
    sentence = "The reserve account was funded at closing and remains untouched. "
    chunks = chunk(sentence * 60)
    assert len(chunks) > 1
    for piece in chunks:
        assert piece.text.startswith("The reserve")


def test_split_only_above_the_maximum() -> None:
    sentence = "The account was funded. "
    text = (sentence * (MAX_CHARS // len(sentence)))[: MAX_CHARS - 1].strip()
    assert len(text) <= MAX_CHARS
    assert len(chunk(text)) == 1


def test_uppercase_or_digit_required_after_the_terminator() -> None:
    # "1.42x. the" is not a sentence boundary: lowercase follows.
    text = ("value of 1.42x. the same value repeats verbatim in this line. " * 60).strip()
    for piece in chunk(text):
        assert not piece.text.startswith("the ")


def test_a_split_never_leaves_an_undersized_tail() -> None:
    """Merging runs before splitting, so rule 3 has to clean up after itself."""
    sentence = "The reserve account was funded at closing and remains untouched. "
    text = (sentence * 39).strip()  # ~2535 chars: one cut, then a short remainder
    assert len(text) > MAX_CHARS
    chunks = chunk(text)
    assert len(chunks) > 1
    assert all(len(piece.text) >= MIN_CHARS for piece in chunks)


def test_the_absorbed_tail_stays_inside_its_predecessor() -> None:
    """Absorbing a tail must not drop text or break the offset identity."""
    text = (GOLDEN / "long_tail.txt").read_text(encoding="utf-8")
    chunks = chunk(text)
    assert len(chunks) == 2
    assert chunks[-1].text.endswith("Sentence 032 restates the covenant and adds a clause of moderate length here.")
    assert text[chunks[-1].start : chunks[-1].end] == chunks[-1].text


def test_only_a_lone_chunk_may_be_undersized() -> None:
    """Across every fixture: a short chunk is only ever a whole short page."""
    for fixture in FIXTURES:
        chunks = chunk((GOLDEN / f"{fixture}.txt").read_text(encoding="utf-8"))
        for piece in chunks:
            assert len(piece.text) >= MIN_CHARS or len(chunks) == 1, fixture


def test_chunking_a_chunk_is_stable() -> None:
    """A chunk fed back in is already a chunk (no drift on re-extraction)."""
    text = (GOLDEN / "mixed.txt").read_text(encoding="utf-8")
    for piece in chunk(text):
        if len(piece.text) <= MAX_CHARS and "\n\n" not in piece.text:
            assert [c.text for c in chunk(piece.text)] == [piece.text]
