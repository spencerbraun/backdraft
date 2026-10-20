"""`session show --in <slug>`: what one document's reading covers, by locator.

The count `session show` prints is coverage for a report. A writer that lost its
context halfway down a long page needs the other kind — which chunks it was
shown, which it was not, and the read that picks up where it stopped — and the
ledger holds exactly that. Everything here runs over the real registry, because
the claim is about the ledger's join to the current generation, which a fake has
only one of.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from typer.testing import CliRunner

from backdraft import cli
from backdraft.gate.reader import EARLIER_GENERATION_NOTE, read, render_coverage
from backdraft.gate.searcher import search
from backdraft.registry import Registry

runner = CliRunner()


@pytest.fixture(autouse=True)
def no_home_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(cli.HOME_ENV, raising=False)
    monkeypatch.delenv(cli.SESSION_ENV, raising=False)


@pytest.fixture
def project(tmp_path: Path, note: Path, workbook: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """An initialized project holding the three-chunk note and the workbook."""
    monkeypatch.chdir(tmp_path)
    runner.invoke(cli.app, ["init"])
    result = runner.invoke(cli.app, ["ingest", str(note), str(workbook)])
    assert result.exit_code == 0, result.output
    return tmp_path


def _run(*args: str):
    return runner.invoke(cli.app, list(args))


def _ledger_rows(root: Path) -> int:
    connection = sqlite3.connect(root / ".backdraft" / "registry.db")
    try:
        return connection.execute("SELECT COUNT(*) FROM ledger").fetchone()[0]
    finally:
        connection.close()


def _hint(output: str) -> list[str]:
    """The command the closing hint names, as argv."""
    line = next(line for line in output.splitlines() if line.startswith("[Read what is not shown: "))
    command = line.removeprefix("[Read what is not shown: backdraft ").removesuffix("]")
    return command.split()


# ---- the acceptance shape --------------------------------------------------


def test_a_chunk_read_lists_what_was_shown_and_names_the_rest(project: Path) -> None:
    _run("read", "quarterly-notes", "p1.c1", "--session", "s-w")
    result = _run("session", "show", "--in", "quarterly-notes", "--session", "s-w")

    assert result.exit_code == 0, result.output
    assert "  p1  shown c1  not shown c2-c3" in result.stdout
    assert _hint(result.stdout) == ["read", "quarterly-notes", "p1.c2-c3", "--session", "s-w"]


def test_the_hint_runs_and_starts_where_the_reading_stopped(project: Path) -> None:
    _run("read", "quarterly-notes", "p1.c1", "--session", "s-w")
    hint = _hint(_run("session", "show", "--in", "quarterly-notes", "--session", "s-w").stdout)

    followed = _run(*hint)

    assert followed.exit_code == 0, followed.output
    tokens = [line for line in followed.stdout.splitlines() if line.startswith("[bd:")]
    assert tokens[0].startswith("[bd:quarterly-notes:p1.c2:")
    assert not any(":p1.c1:" in token for token in tokens)
    after = _run("session", "show", "--in", "quarterly-notes", "--session", "s-w").stdout
    assert "  p1  shown c1-c3" in after
    assert "Read what is not shown" not in after
    assert "everything quarterly-notes holds now has been shown" in after


def test_asking_mints_nothing(project: Path) -> None:
    """A coverage check that minted would answer its own question."""
    _run("read", "quarterly-notes", "p1.c1", "--session", "s-w")
    before = _ledger_rows(project)
    _run("session", "show", "--in", "quarterly-notes", "--session", "s-w")
    _run("session", "show", "--in", "model", "--session", "s-w")
    assert _ledger_rows(project) == before


def test_a_document_nothing_was_read_from_points_at_its_first_page(project: Path) -> None:
    result = _run("session", "show", "--in", "quarterly-notes", "--session", "s-w")
    assert "quarterly-notes  0 anchors shown" in result.stdout
    assert "  p1  not shown c1-c3" in result.stdout
    assert _hint(result.stdout) == ["read", "quarterly-notes", "p1", "--session", "s-w"]


def test_an_exported_session_carries_no_flag_into_the_hint(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(cli.SESSION_ENV, "s-env")
    _run("read", "quarterly-notes", "p1.c1")
    result = _run("session", "show", "--in", "quarterly-notes")
    assert "(from BACKDRAFT_SESSION)" in result.stdout
    assert _hint(result.stdout) == ["read", "quarterly-notes", "p1.c2-c3"]


def test_the_default_session_still_says_what_it_costs(project: Path) -> None:
    result = _run("session", "show", "--in", "quarterly-notes")
    assert "note: this is the default session" in result.stdout


# ---- sheets ----------------------------------------------------------------


def test_a_sheet_counts_cells_and_enumerates_none(project: Path) -> None:
    _run("search", "Acme", "--session", "s-w")
    result = _run("session", "show", "--in", "model", "--session", "s-w")

    assert result.exit_code == 0, result.output
    rows = [line for line in result.stdout.splitlines() if line.startswith("  p")]
    assert rows[0].startswith("  p1  rent-roll-2025  page not shown  1 of 9 cells shown")
    assert "cells shown" in rows[0]
    assert "B2" not in result.stdout
    assert _hint(result.stdout) == ["read", "model", "p1", "--session", "s-w"]


def test_a_sheet_read_whole_is_shown(project: Path) -> None:
    _run("read", "model", "p1-2", "--session", "s-w")
    result = _run("session", "show", "--in", "model", "--session", "s-w")
    rows = [line for line in result.stdout.splitlines() if line.startswith("  p")]
    assert all("  page shown  " in row for row in rows), rows
    assert "Read what is not shown" not in result.stdout


# ---- refusals --------------------------------------------------------------


def test_an_unknown_slug_is_refused_as_search_in_refuses_it(project: Path) -> None:
    coverage = _run("session", "show", "--in", "nope")
    searched = _run("search", "Acme", "--in", "nope")
    assert coverage.exit_code == searched.exit_code == 1
    assert "no such document: 'nope'" in coverage.output
    assert coverage.output == searched.output


def test_a_withdrawn_slug_is_refused_in_require_document_s_words(project: Path) -> None:
    _run("read", "quarterly-notes", "p1", "--session", "s-w")
    assert _run("forget", "quarterly-notes", "--yes").exit_code == 0
    result = _run("session", "show", "--in", "quarterly-notes", "--session", "s-w")
    assert result.exit_code == 1
    assert "no longer serves it" in result.output
    # The count is still listed, and marked, without `--in`.
    assert "withdrawn" in _run("session", "show", "--session", "s-w").stdout


def test_without_in_the_block_is_unchanged(project: Path) -> None:
    """The flag adds a view; it does not change the one that exists."""
    _run("read", "quarterly-notes", "p1.c1", "--session", "s-w")
    shown = _run("session", "show", "--session", "s-w").stdout
    assert shown == (
        "session s-w  (from --session)\n"
        "\n"
        "1 anchor shown across 1 document\n"
        "\n"
        "  quarterly-notes  1\n"
        "\n"
        "[Read more: backdraft read <slug> <page> --session s-w]\n"
    )


# ---- across a re-ingest ----------------------------------------------------


def test_a_re_ingest_keeps_what_survived_and_says_what_did_not(
    registry: Registry, note: Path
) -> None:
    """Matched by token, as `shown_by_document` counts: a chunk whose text
    survived is still shown at its new row, and one whose text changed is not —
    and the difference from the count is said rather than left to subtract."""
    registry.ingest(note)
    read(registry, "quarterly-notes", "p1", session="s")
    text = note.read_text(encoding="utf-8")
    note.write_text(text.replace("$4.1 million", "$4.2 million"), encoding="utf-8")
    registry.ingest(note)

    rendered = render_coverage(registry, "s", "quarterly-notes", source="--session")

    assert "  p1  shown c1, c3  not shown c2" in rendered
    assert EARLIER_GENERATION_NOTE.format(count=1) in rendered
    assert "[Read what is not shown: backdraft read quarterly-notes p1.c2]" in rendered
    assert dict(registry.shown_by_document("s"))["quarterly-notes"] == 3


def test_a_session_with_no_reading_lost_says_no_earlier_extraction(
    registry: Registry, note: Path
) -> None:
    registry.ingest(note)
    search(registry, "covenant", session="s")
    rendered = render_coverage(registry, "s", "quarterly-notes", source="--session")
    assert "earlier extraction" not in rendered
    assert "  p1  shown c1  not shown c2-c3" in rendered
