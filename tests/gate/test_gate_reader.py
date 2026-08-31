"""The reader's rendered output, pinned.

These are golden strings rather than golden files because the format *is* the
deliverable: it is what an agent reads and what the skill quotes. A diff here
should be read as a change to a published surface.
"""

from __future__ import annotations

import pytest
from fake_registry import FakeDocumentRegistry, pdf_document, sheet_document

from backdraft.cli_context import SESSION_ENV
from backdraft.gate.reader import (
    DEFAULT_SESSION_NOTE,
    GateError,
    read,
    render_session,
    select_pages,
)
from backdraft.gate.searcher import search

COUNTY_URL = "https://en.wikipedia.org/w/index.php?title=Franklin_County&oldid=1367935775"


def _fetched() -> object:
    """A web page staged under the filename `fetch.filename_for` invented for it."""
    return pdf_document(
        "county",
        "index.html",
        [["Franklin County had 1,326,063 residents."]],
        media_type="html",
        url=COUNTY_URL,
    )


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


# ---------------------------------------------------------------------------
# a fetched source is named by its page
# ---------------------------------------------------------------------------


def test_a_fetched_source_is_listed_by_its_url(
    fake_gate_registry: FakeDocumentRegistry,
) -> None:
    """`fetch.filename_for` invents `index.html`; the URL stands in its place.

    Both names would be two names for one thing, and the invented one would be
    the one that looks authoritative — the 2026-08-06 rule, applied here.
    """
    fake_gate_registry.add(_fetched())
    listed = read(fake_gate_registry)
    assert f"county      {COUNTY_URL}  html  1 page" in listed
    assert "index.html" not in listed


def test_a_fetched_source_carries_its_url_in_the_toc_headline(
    fake_gate_registry: FakeDocumentRegistry,
) -> None:
    fake_gate_registry.add(_fetched())
    assert read(fake_gate_registry, "county").startswith(
        f"county  ({COUNTY_URL}, html, 1 page)"
    )


def test_a_long_url_does_not_widen_the_file_column(
    fake_gate_registry: FakeDocumentRegistry,
) -> None:
    """The origin overflows its column rather than sizing every row to itself.

    An 80-character URL joining the width computation pushes `pdf  3 pages`
    past column 100 on a registry that is otherwise files, so the file rows are
    byte-identical whether or not a fetched page sits beside them.
    """
    before = read(fake_gate_registry).splitlines()
    fake_gate_registry.add(_fetched())
    after = read(fake_gate_registry).splitlines()
    assert [line for line in after if "http" not in line] == [
        line.replace("2 documents", "3 documents") for line in before
    ]


def test_a_registry_of_files_prints_what_it_always_did(
    fake_gate_registry: FakeDocumentRegistry,
) -> None:
    """No document carries a URL, so nothing about this list may move."""
    assert read(fake_gate_registry) == DOCUMENTS


def test_a_registry_of_nothing_but_fetched_pages_still_lists_cleanly() -> None:
    """No filename sizes the name column, so it collapses instead of padding.

    The `default=0` branch of the width computation: with every name a URL
    there is nothing to align to, and padding to the longest URL would put two
    columns of blanks after the shortest one.
    """
    registry = FakeDocumentRegistry()
    registry.add(_fetched())
    registry.add(
        pdf_document(
            "notes",
            "index.html",
            [["Rents in the submarket rose."]],
            media_type="html",
            url="https://example.com/a",
        )
    )
    listed = read(registry).splitlines()
    assert listed[2] == f"county  {COUNTY_URL}  html  1 page"
    assert listed[3] == "notes   https://example.com/a  html  1 page"


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


def test_a_dead_selector_names_what_exists(fake_gate_registry: FakeDocumentRegistry) -> None:
    """The error carries the answer to the question the caller would ask next,
    so a wrong selector costs one command rather than two."""
    with pytest.raises(GateError, match=r"this document has p1-3"):
        read(fake_gate_registry, "t12-audit", "p9")
    with pytest.raises(GateError, match=r"this document has p1-3"):
        read(fake_gate_registry, "t12-audit", "nope")


def test_a_dead_selector_on_a_workbook_names_the_sheets() -> None:
    registry = FakeDocumentRegistry().add(
        sheet_document("book", "book.xlsx", [("Rent Roll", ["h", "r"]), ("Assumptions", ["h", "r"])])
    )
    with pytest.raises(GateError, match=r"sheets: Rent Roll, Assumptions"):
        read(registry, "book", "nope")


def test_unknown_slug(fake_gate_registry: FakeDocumentRegistry) -> None:
    with pytest.raises(GateError):
        read(fake_gate_registry, "nope")
    with pytest.raises(GateError):
        read(fake_gate_registry, "nope", "p1")


# ---------------------------------------------------------------------------
# session
# ---------------------------------------------------------------------------


SESSION_EMPTY = """\
session s-fresh  (from --session)

nothing shown yet — a citation bound against it reports `not_shown`

[Start reading: backdraft read]"""

SESSION_HELD = """\
session s-deal  (from BACKDRAFT_SESSION)

5 anchors shown across 2 documents

  t12-audit   3
  rent-model  2

[Read more: backdraft read <slug> <page>]"""


def test_a_session_holding_nothing_says_so_and_names_read(
    fake_gate_registry: FakeDocumentRegistry,
) -> None:
    """A bare zero would be the answer without the next command attached."""
    assert (
        render_session(fake_gate_registry, "s-fresh", source="--session") == SESSION_EMPTY
    )


def test_a_session_names_each_document_and_totals_them(
    fake_gate_registry: FakeDocumentRegistry,
) -> None:
    """Two page reads and a search that lands elsewhere: two rows and a total.

    The search matches the sheet's page anchor and the cell inside it, which is
    the point of counting anchors rather than commands — coverage is spans.
    """
    read(fake_gate_registry, "t12-audit", "p2", session="s-deal")
    read(fake_gate_registry, "t12-audit", "p3", session="s-deal")
    search(fake_gate_registry, "Vacancy", session="s-deal")

    assert (
        render_session(fake_gate_registry, "s-deal", source=SESSION_ENV) == SESSION_HELD
    )


def test_a_document_nothing_was_shown_from_is_absent_rather_than_zero(
    fake_gate_registry: FakeDocumentRegistry,
) -> None:
    read(fake_gate_registry, "t12-audit", "p1", session="s-one")
    rendered = render_session(fake_gate_registry, "s-one", source="--session")
    assert "t12-audit" in rendered
    assert "rent-model" not in rendered
    assert "1 anchor shown across 1 document" in rendered


def test_the_note_closes_the_block_when_it_is_handed_one(
    fake_gate_registry: FakeDocumentRegistry,
) -> None:
    """The default-session warning is the CLI's to decide and the reader's to place.

    Both shapes of block take it: the empty one, where there is nothing above it
    to qualify, and the populated one, where the counts are what it is about.
    """
    note = DEFAULT_SESSION_NOTE.format(env=SESSION_ENV)
    read(fake_gate_registry, "t12-audit", "p1", session="s-held")

    for session in ("s-empty", "s-held"):
        rendered = render_session(fake_gate_registry, session, source="default", note=note)
        assert rendered.endswith(note)
        assert SESSION_ENV in rendered

    # No note handed over, none printed: the reader decides nothing here.
    assert "note:" not in render_session(fake_gate_registry, "s-held", source="--session")


def test_the_session_summary_mints_nothing(fake_gate_registry: FakeDocumentRegistry) -> None:
    """Counting what was shown is not being shown it."""
    read(fake_gate_registry, "t12-audit", "p1", session="s-count")
    before = fake_gate_registry.shown_tokens("s-count")
    render_session(fake_gate_registry, "s-count", source="--session")
    assert fake_gate_registry.shown_tokens("s-count") == before
