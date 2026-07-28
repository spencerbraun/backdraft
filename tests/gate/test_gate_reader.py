"""The reader's rendered output, pinned.

These are golden strings rather than golden files because the format *is* the
deliverable: it is what an agent reads and what the skill quotes. A diff here
should be read as a change to a published surface.
"""

from __future__ import annotations

import pytest
from fake_registry import FakeDocumentRegistry, pdf_document, sheet_document

from backdraft.gate.reader import GateError, read, select_pages

DOCUMENTS = """\
2 documents

t12-audit   t12-audit-report.pdf  pdf   3 pages
rent-model  rent-model.xlsx       xlsx  2 sheets

[Table of contents: backdraft read <slug>]"""

TOC_PDF = """\
t12-audit  (t12-audit-report.pdf, pdf, 3 pages)

p1  Cover page.
p2  The portfolio comprises 14 assets across three markets. Trailing twelve month \
net operating income was $4,102,880.
p3  Occupancy averaged 93.4% over the period.

[Read one: backdraft read t12-audit p1]
[Read a range: backdraft read t12-audit p1-3]"""

TOC_SHEETS = """\
rent-model  (rent-model.xlsx, xlsx, 2 sheets)

p1  Rent Roll    ## Sheet: Rent Roll - Values View with cell references | Row | A | B \
| |---|---|---| | 1 | [A1] Property | [B1] NOI | | ...
p2  Assumptions  ## Sheet: Assumptions - Values View with cell references | Row | A | \
B | |---|---|---| | 1 | [A1] Vacancy | [B1] 6.6% |

[Read one: backdraft read rent-model p1]
[Read by name: backdraft read rent-model "Rent Roll"]"""

PAGE = """\
# t12-audit p2  (page 2 of 3)

[bd:t12-audit:p2.c1:50bd]
The portfolio comprises 14 assets across three markets.

[bd:t12-audit:p2.c2:1e7a]
Trailing twelve month net operating income was $4,102,880."""

RANGE = """\
# t12-audit p1  (page 1 of 3)

[bd:t12-audit:p1.c1:5ff8]
Cover. T12 Audit prepared for Acme Capital, March 2026.

# t12-audit p2  (page 2 of 3)

[bd:t12-audit:p2.c1:50bd]
The portfolio comprises 14 assets across three markets.

[bd:t12-audit:p2.c2:1e7a]
Trailing twelve month net operating income was $4,102,880."""

SHEET = """\
# rent-model p1  (sheet 1 of 2: Rent Roll)  [bd:rent-model:p1:feef]

## Sheet: Rent Roll - Values View with cell references

| Row | A | B |
|---|---|---|
| 1 | [A1] Property | [B1] NOI |
| 2 | [A2] Elm St | [B2] 1,204,000 |
| 3 | [A3] Oak Ave | [B3] 986,500 |"""

SHEET_FIRST_WINDOW = """\
# rent-model p1  (sheet 1 of 2: Rent Roll)  [bd:rent-model:p1:feef]

## Sheet: Rent Roll - Values View with cell references

| Row | A | B |
|---|---|---|
| 1 | [A1] Property | [B1] NOI |
| 2 | [A2] Elm St | [B2] 1,204,000 |

[Showing 0-2 of 3 rows. Continue with: backdraft read rent-model p1 --offset 2]"""

SHEET_LAST_WINDOW = """\
# rent-model p1  (sheet 1 of 2: Rent Roll)  [bd:rent-model:p1:feef]

## Sheet: Rent Roll - Values View with cell references

| Row | A | B |
|---|---|---|
| 3 | [A3] Oak Ave | [B3] 986,500 |

[Showing 2-3 of 3 rows.]"""

PAGE_FIRST_WINDOW = """\
# t12-audit p2  (page 2 of 3)

[bd:t12-audit:p2.c1:50bd]
The portfolio comprises 14 assets across three markets.

[Showing 0-55 of 113 chars. Continue with: backdraft read t12-audit p2 --offset 55]"""

PAGE_LAST_WINDOW = """\
# t12-audit p2  (page 2 of 3)

[bd:t12-audit:p2.c2:1e7a]
Trailing twelve month net operating income was $4,102,880.

[Showing 55-113 of 113 chars.]"""


# ---------------------------------------------------------------------------
# dispatch
# ---------------------------------------------------------------------------


def test_documents(fake_gate_registry: FakeDocumentRegistry) -> None:
    assert read(fake_gate_registry) == DOCUMENTS


def test_documents_empty() -> None:
    assert read(FakeDocumentRegistry()) == (
        "No documents.\n\n[Ingest one with: backdraft ingest <file>]"
    )


def test_toc_pages(fake_gate_registry: FakeDocumentRegistry) -> None:
    assert read(fake_gate_registry, "t12-audit") == TOC_PDF


def test_toc_sheets(fake_gate_registry: FakeDocumentRegistry) -> None:
    assert read(fake_gate_registry, "rent-model") == TOC_SHEETS


def test_toc_prefers_summary_over_text(fake_gate_registry: FakeDocumentRegistry) -> None:
    """Page 1 carries a summary; pages 2 and 3 fall back to their opening text."""
    assert "p1  Cover page." in read(fake_gate_registry, "t12-audit")


def test_toc_truncates_at_120_chars(fake_gate_registry: FakeDocumentRegistry) -> None:
    line = next(
        line for line in read(fake_gate_registry, "rent-model").split("\n") if line.startswith("p1")
    )
    assert line.endswith("...")


# ---------------------------------------------------------------------------
# page read
# ---------------------------------------------------------------------------


def test_page_read(fake_gate_registry: FakeDocumentRegistry) -> None:
    assert read(fake_gate_registry, "t12-audit", "p2", session="s") == PAGE


def test_page_range(fake_gate_registry: FakeDocumentRegistry) -> None:
    assert read(fake_gate_registry, "t12-audit", "p1-2", session="s") == RANGE


def test_page_read_uses_registry_tokens(fake_gate_registry: FakeDocumentRegistry) -> None:
    """Recompute nothing: every token printed is an anchor's own token."""
    tokens = {anchor.token for anchor in fake_gate_registry.anchors_for_page("t12-audit", 2)}
    output = read(fake_gate_registry, "t12-audit", "p2", session="s")
    assert tokens
    assert all(f"[{token}]\n" in output for token in tokens)


def test_page_with_no_anchors_says_so() -> None:
    fake_gate_registry = FakeDocumentRegistry().add(pdf_document("blank", "blank.pdf", [[]]))
    assert read(fake_gate_registry, "blank", "p1", session="s") == (
        "# blank p1  (page 1 of 1)\n\n(no text on this page)"
    )


def test_sheet_read(fake_gate_registry: FakeDocumentRegistry) -> None:
    assert read(fake_gate_registry, "rent-model", "p1", session="s") == SHEET


def test_sheet_read_by_name(fake_gate_registry: FakeDocumentRegistry) -> None:
    assert read(fake_gate_registry, "rent-model", "Rent Roll", session="s") == SHEET


def test_sheet_read_by_sheetref(fake_gate_registry: FakeDocumentRegistry) -> None:
    """The sanitized form a token carries also selects the sheet."""
    assert read(fake_gate_registry, "rent-model", "rent-roll", session="s") == SHEET


def test_sheet_header_carries_the_page_token(fake_gate_registry: FakeDocumentRegistry) -> None:
    page_anchor = fake_gate_registry.anchors_for_page("rent-model", 1)[0]
    header = read(fake_gate_registry, "rent-model", "p1", session="s").split("\n")[0]
    assert header.endswith(f"[{page_anchor.token}]")


def test_sheet_does_not_inline_cell_tokens(fake_gate_registry: FakeDocumentRegistry) -> None:
    output = read(fake_gate_registry, "rent-model", "p1", session="s")
    assert "rent-roll!B2" not in output
    assert "[B2] 1,204,000" in output


# ---------------------------------------------------------------------------
# windowing
# ---------------------------------------------------------------------------


def test_sheet_rows_first_window(fake_gate_registry: FakeDocumentRegistry) -> None:
    assert read(fake_gate_registry, "rent-model", "p1", session="s", limit=2) == SHEET_FIRST_WINDOW


def test_sheet_rows_last_window(fake_gate_registry: FakeDocumentRegistry) -> None:
    assert read(fake_gate_registry, "rent-model", "p1", session="s", offset=2) == SHEET_LAST_WINDOW


def test_sheet_repeats_the_header_row_on_every_window(fake_gate_registry: FakeDocumentRegistry) -> None:
    """SPEC § Gate: the header row travels with every window — title and rule too.

    The sheet title sits above the table in the extractor's output, so a window
    that repeated only the first line would repeat the title and window the
    column header away.
    """
    for offset in (0, 1, 2):
        window = read(fake_gate_registry, "rent-model", "p1", session="s", offset=offset, limit=1)
        assert "## Sheet: Rent Roll - Values View with cell references" in window
        assert "| Row | A | B |" in window
        assert "|---|---|---|" in window


def test_sheet_windows_never_cut_a_row(fake_gate_registry: FakeDocumentRegistry) -> None:
    rows = [
        line
        for offset in (0, 1, 2)
        for line in read(
            fake_gate_registry, "rent-model", "p1", session="s", offset=offset, limit=1
        ).split("\n")
        if line.startswith(("| 1 |", "| 2 |", "| 3 |"))
    ]
    assert rows == [
        "| 1 | [A1] Property | [B1] NOI |",
        "| 2 | [A2] Elm St | [B2] 1,204,000 |",
        "| 3 | [A3] Oak Ave | [B3] 986,500 |",
    ]


def test_page_chars_first_window(fake_gate_registry: FakeDocumentRegistry) -> None:
    assert read(fake_gate_registry, "t12-audit", "p2", session="s", limit=60) == PAGE_FIRST_WINDOW


def test_page_chars_last_window(fake_gate_registry: FakeDocumentRegistry) -> None:
    assert read(fake_gate_registry, "t12-audit", "p2", session="s", offset=55) == PAGE_LAST_WINDOW


def test_continuation_offset_walks_the_page_exactly_once(fake_gate_registry: FakeDocumentRegistry) -> None:
    """Following the hint shows every chunk once and never repeats one."""
    seen: list[str] = []
    offset = 0
    for _ in range(10):
        output = read(fake_gate_registry, "t12-audit", "p2", session="s", offset=offset, limit=60)
        seen += [line for line in output.split("\n") if line.startswith("[bd:")]
        hint = output.split("\n")[-1]
        if "Continue with:" not in hint:
            break
        offset = int(hint.rsplit("--offset ", 1)[1].rstrip("]"))
    assert seen == ["[bd:t12-audit:p2.c1:50bd]", "[bd:t12-audit:p2.c2:1e7a]"]


def test_a_window_is_one_contiguous_run(fake_gate_registry: FakeDocumentRegistry) -> None:
    """A chunk that will not fit closes the window; it does not skip to a smaller one."""
    output = read(fake_gate_registry, "t12-audit", "p1-3", session="s", limit=100)
    assert [line for line in output.split("\n") if line.startswith("[bd:")] == [
        "[bd:t12-audit:p1.c1:5ff8]"
    ]
    assert output.endswith(
        "[Showing 0-55 of 209 chars. Continue with: backdraft read t12-audit p1-3 --offset 55]"
    )


def test_continuation_walks_a_range_exactly_once(fake_gate_registry: FakeDocumentRegistry) -> None:
    seen: list[str] = []
    offset = 0
    for _ in range(10):
        output = read(fake_gate_registry, "t12-audit", "p1-3", session="s", offset=offset, limit=100)
        seen += [line for line in output.split("\n") if line.startswith("[bd:")]
        hint = output.split("\n")[-1]
        if "Continue with:" not in hint:
            break
        offset = int(hint.rsplit("--offset ", 1)[1].rstrip("]"))
    assert seen == [
        "[bd:t12-audit:p1.c1:5ff8]",
        "[bd:t12-audit:p2.c1:50bd]",
        "[bd:t12-audit:p2.c2:1e7a]",
        "[bd:t12-audit:p3.c1:028c]",
    ]


def test_window_larger_than_content_has_no_hint(fake_gate_registry: FakeDocumentRegistry) -> None:
    assert read(fake_gate_registry, "t12-audit", "p2", session="s", limit=10_000) == PAGE


def test_a_chunk_longer_than_the_limit_is_still_shown_whole(
    fake_gate_registry: FakeDocumentRegistry,
) -> None:
    """A token is never printed above partial text, so limit yields to the chunk."""
    output = read(fake_gate_registry, "t12-audit", "p2", session="s", limit=1)
    assert "The portfolio comprises 14 assets across three markets." in output


def test_offset_past_the_end(fake_gate_registry: FakeDocumentRegistry) -> None:
    output = read(fake_gate_registry, "t12-audit", "p2", session="s", offset=500)
    assert output.startswith("(nothing to show at this offset)")


def test_negative_offset_and_limit_are_refused(fake_gate_registry: FakeDocumentRegistry) -> None:
    with pytest.raises(GateError):
        read(fake_gate_registry, "t12-audit", "p2", offset=-1)
    with pytest.raises(GateError):
        read(fake_gate_registry, "t12-audit", "p2", limit=-1)


# ---------------------------------------------------------------------------
# selection
# ---------------------------------------------------------------------------


def test_select_forms(fake_gate_registry: FakeDocumentRegistry) -> None:
    pages = fake_gate_registry.pages("t12-audit")
    assert select_pages(pages, "p2").numbers == (2,)
    assert select_pages(pages, "p1-3").numbers == (1, 2, 3)
    assert select_pages(pages, "2").numbers == (2,)
    assert select_pages(pages, "2").text == "p2"


def test_select_range_clips_to_existing_pages(fake_gate_registry: FakeDocumentRegistry) -> None:
    assert select_pages(fake_gate_registry.pages("t12-audit"), "p2-9").numbers == (2, 3)


def test_select_name_wins_over_number() -> None:
    """A sheet named `3` is reachable by its name, not shadowed by page 3."""
    fake_gate_registry = FakeDocumentRegistry().add(
        sheet_document("book", "book.xlsx", [("A", ["h", "r"]), ("3", ["h", "r"])])
    )
    assert select_pages(fake_gate_registry.pages("book"), "3").numbers == (2,)


@pytest.mark.parametrize("selector", ["p9", "p3-1", "nope", "0"])
def test_bad_selectors(fake_gate_registry: FakeDocumentRegistry, selector: str) -> None:
    with pytest.raises(GateError):
        read(fake_gate_registry, "t12-audit", selector)


def test_unknown_slug(fake_gate_registry: FakeDocumentRegistry) -> None:
    with pytest.raises(GateError):
        read(fake_gate_registry, "nope")
    with pytest.raises(GateError):
        read(fake_gate_registry, "nope", "p1")
