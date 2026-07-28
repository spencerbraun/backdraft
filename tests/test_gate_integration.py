"""The gate over the real registry and the real workbook extractor.

Every other gate test hands the reader an in-memory fake, which is the right unit
boundary — and is also how a windowing bug survived. The fake built a sheet page
as a bare markdown table, while `extract/xlsx.py` writes a `## Sheet: …` title
and a blank line above the table; the reader treated that title as the repeated
header and windowed the real column header away, so every continuation window
rendered a headerless table.

So this walks one workbook the whole way: real ingest, real anchors, real page
text, real `gate.reader.read`. What it pins is SPEC § Gate's sheet rule —
"sheets paginate by rows, never mid-row, header row repeated".
"""

from __future__ import annotations

from pathlib import Path

from backdraft.gate.reader import read
from backdraft.registry import Registry


def _table(text: str) -> tuple[str, str, str, list[str]]:
    """A sheet page's title, column header, rule and data rows, as written."""
    lines = text.split("\n")
    rows = [line for line in lines if line.lstrip().startswith("|")]
    title = next(line for line in lines if line.startswith("## Sheet:"))
    return title, rows[0], rows[1], rows[2:]


def _windows(registry: Registry, slug: str, selector: str, limit: int) -> list[str]:
    """Every window of a read, walked the way the continuation hint says to."""
    out: list[str] = []
    offset = 0
    for _ in range(50):
        window = read(registry, slug, selector, session="s", offset=offset, limit=limit)
        out.append(window)
        hint = window.split("\n")[-1]
        if "Continue with:" not in hint:
            return out
        offset = int(hint.rsplit("--offset ", 1)[1].rstrip("]"))
    raise AssertionError("the continuation hint never terminated")


def test_every_sheet_window_repeats_the_real_header_block(
    registry: Registry, workbook: Path
) -> None:
    document = registry.ingest(workbook)
    page = registry.page(document.slug, 1)
    assert page is not None and page.kind == "sheet"
    title, header, rule, rows = _table(page.text)
    assert len(rows) > 1, "a one-row sheet cannot show a continuation window"

    windows = _windows(registry, document.slug, "p1", limit=1)

    assert len(windows) == len(rows)
    for window in windows:
        assert title in window
        assert header in window
        assert rule in window
        # The blank line between the title and the table travels too: without it
        # the title reads as part of the table.
        assert f"{title}\n\n{header}\n{rule}\n" in window


def test_sheet_windows_show_every_row_whole_and_once(
    registry: Registry, workbook: Path
) -> None:
    document = registry.ingest(workbook)
    page = registry.page(document.slug, 1)
    assert page is not None
    title, header, rule, rows = _table(page.text)

    seen = [
        line
        for window in _windows(registry, document.slug, "p1", limit=1)
        for line in window.split("\n")
        if line.lstrip().startswith("|") and line not in (header, rule)
    ]
    assert seen == rows


def test_a_whole_sheet_read_is_the_extractor_s_page_text(
    registry: Registry, workbook: Path
) -> None:
    """An unwindowed read shows the snapshot verbatim — nothing dropped, nothing added."""
    document = registry.ingest(workbook)
    page = registry.page(document.slug, 1)
    assert page is not None
    output = read(registry, document.slug, "p1", session="s")
    assert output.endswith(page.text)
