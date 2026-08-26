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

`show` is here for the same reason twice over: drift is a property of holding two
extraction generations, which only the real registry has, and the integration
invariant it exists to satisfy — a token the gate emits binds `resolved` in the
same session — is only true end to end.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest_registry import PAGE_BREAK

from backdraft.bind.binder import bind
from backdraft.gate.reader import read, show
from backdraft.gate.searcher import search
from backdraft.kernel.model import CitationStatus
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


def test_the_widen_hint_really_produces_the_results_it_promised(
    registry: Registry, note: Path
) -> None:
    """The hint is a command, so the check is running it — as `_windows` does for `read`.

    A total counted differently from the fetch would name a number the caller
    can never reach, which is worse than the silence it replaced.
    """
    registry.ingest(note)
    capped = search(registry, "the", limit=1, session="s")
    hint = capped.split("\n")[-1]
    assert hint.startswith("[See all ")
    widened = search(registry, "the", limit=int(hint.rsplit("--limit ", 1)[1].rstrip("]")), session="s")
    total = int(hint.split("[See all ", 1)[1].split(":", 1)[0])
    assert widened.count("[bd:") == total
    assert widened.startswith(f"{total} results")
    assert "See all" not in widened


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


# ---------------------------------------------------------------------------
# show
# ---------------------------------------------------------------------------


PAGE_ONE = "Page one holds the covenant language and nothing else worth quoting."
PAGE_TWO = "Page two carries the debt service coverage ratio of 1.42x for the quarter."
PAGE_TWO_EDITED = "Page two now carries a debt service coverage ratio of 1.19x instead."


@pytest.fixture
def book(tmp_path: Path, paged: object) -> Path:
    """A two-page file the `paged` extractor splits, editable between ingests."""
    path = tmp_path / "quarterly-notes.md"
    _write(path, [PAGE_ONE, PAGE_TWO])
    return path


def _write(path: Path, pages: list[str]) -> None:
    path.write_text(PAGE_BREAK.join(pages), encoding="utf-8")


def _token(registry: Registry, slug: str, locator: str) -> str:
    return next(
        anchor.token
        for page in registry.pages(slug)
        for anchor in registry.anchors_for_page(slug, page.number)
        if str(anchor.locator) == locator
    )


def test_a_shown_token_binds_resolved_rather_than_not_shown(
    registry: Registry, tmp_path: Path, book: Path
) -> None:
    """The acceptance test for `show` minting, run the whole way.

    `not_shown` is the status a token gets when it resolves but the session never
    saw it, so a session that has only ever run `show` is the sharpest possible
    check that showing records.
    """
    registry.ingest(book, extractor="paged")
    token = _token(registry, "quarterly-notes", "p2.c1")
    memo = tmp_path / "memo.md"
    memo.write_text(f"The [coverage ratio is 1.42x]({token}).\n", encoding="utf-8")

    before = bind(memo, registry, session_id="s-unshown", write=False)
    assert before.claims[0].citations[0].status is CitationStatus.NOT_SHOWN

    show(registry, [token], session="s-shown")

    after = bind(memo, registry, session_id="s-shown", write=False)
    assert after.claims[0].citations[0].status is CitationStatus.RESOLVED


def test_show_reports_drift_with_both_snippets_and_mints_the_current_one(
    registry: Registry, book: Path
) -> None:
    registry.ingest(book, extractor="paged")
    cited = _token(registry, "quarterly-notes", "p2.c1")

    _write(book, [PAGE_ONE, PAGE_TWO_EDITED])
    registry.ingest(book, extractor="paged")
    current = _token(registry, "quarterly-notes", "p2.c1")

    shown = show(registry, [cited], session="s")

    assert shown.complete is True, "drift showed text; whether it still holds is bind's call"
    assert shown.text.splitlines()[:3] == [
        f"[{cited}]  drifted  quarterly-notes p2.c1",
        "cited:",
        PAGE_TWO,
    ]
    assert f"now [{current}]:" in shown.text
    assert PAGE_TWO_EDITED in shown.text
    # The anchor standing there now is the one worth citing, so it is minted.
    assert registry.was_shown("s", current) is True


def test_show_says_so_when_the_locator_itself_is_gone(
    registry: Registry, book: Path
) -> None:
    """The other drift branch: the token resolves, but nothing stands there now."""
    registry.ingest(book, extractor="paged")
    cited = _token(registry, "quarterly-notes", "p2.c1")

    _write(book, [PAGE_ONE])
    registry.ingest(book, extractor="paged")

    shown = show(registry, [cited])

    assert "drifted" in shown.text
    assert PAGE_TWO in shown.text
    assert "now: nothing stands at that locator in the current extraction" in shown.text


def test_show_resolves_a_cell_token_off_a_real_workbook(
    registry: Registry, workbook: Path
) -> None:
    """Every locator form goes through one path; the cell form is the one with a
    sheetref, and a sheet name is sanitized at ingest."""
    registry.ingest(workbook)
    token = _token(registry, "model", "rent-roll-2025!C2")

    shown = show(registry, [token], session="s")

    assert shown.complete is True
    assert shown.text.splitlines()[0] == f"[{token}]  resolved  model rent-roll-2025!C2"
    assert registry.was_shown("s", token) is True
