"""The gate's CLI: wiring, session resolution, exit codes.

The commands hold no logic — these tests check that flags reach the reader and
the searcher, that the session the ledger sees is the one the precedence rules
pick, and that a `GateError` leaves as exit code 1 rather than a traceback.
"""

from __future__ import annotations

import pytest
from fake_registry import FakeDocumentRegistry
from typer.testing import CliRunner

from backdraft import cli as top_cli
from backdraft.gate import cli


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def wired(monkeypatch: pytest.MonkeyPatch, fake_gate_registry) -> object:
    """Point gate.cli at the fake fake_gate_registry through its cli_context seams.

    `opened_registry` and `resolve_session` are imported names in gate.cli's
    namespace, so patching them there wires the fake in without touching
    `backdraft.cli_context` itself.
    """
    from contextlib import contextmanager

    fake_gate_registry = fake_gate_registry

    @contextmanager
    def fake_opened(start=None):
        from backdraft.cli_context import guard

        with guard():
            try:
                yield fake_gate_registry
            finally:
                fake_gate_registry.close()

    monkeypatch.setattr(cli, "opened_registry", fake_opened)
    monkeypatch.delenv(cli.SESSION_ENV, raising=False)
    return fake_gate_registry


# ---------------------------------------------------------------------------
# read
# ---------------------------------------------------------------------------


def test_read_lists_documents(runner: CliRunner, wired: FakeDocumentRegistry) -> None:
    result = runner.invoke(cli.app, ["read"])
    assert result.exit_code == 0
    assert "2 documents" in result.output


def test_read_shows_a_table_of_contents(runner: CliRunner, wired: FakeDocumentRegistry) -> None:
    result = runner.invoke(cli.app, ["read", "t12-audit"])
    assert result.exit_code == 0
    assert "p2  The portfolio comprises" in result.output


def test_read_mints_into_the_named_session(runner: CliRunner, wired: FakeDocumentRegistry) -> None:
    result = runner.invoke(cli.app, ["read", "t12-audit", "p2", "--session", "run-a"])
    assert result.exit_code == 0
    assert wired.shown_tokens("run-a") == {
        "bd:t12-audit:p2.c1:50bd",
        "bd:t12-audit:p2.c2:1e7a",
    }


def test_read_passes_offset_and_limit(runner: CliRunner, wired: FakeDocumentRegistry) -> None:
    result = runner.invoke(cli.app, ["read", "t12-audit", "p2", "--limit", "60"])
    assert "[Showing 0-55 of 113 chars." in result.output


def test_read_closes_the_registry(runner: CliRunner, wired: FakeDocumentRegistry) -> None:
    runner.invoke(cli.app, ["read"])
    assert wired.closed


def test_unknown_slug_is_exit_1(runner: CliRunner, wired: FakeDocumentRegistry) -> None:
    """Naming the listing command matters: an agent that guessed a slug cannot
    recover the real one from the error otherwise."""
    result = runner.invoke(cli.app, ["read", "nope", "p1"])
    assert result.exit_code == 1
    assert result.stderr.strip() == (
        "backdraft: no such document: 'nope'; "
        "run `backdraft read` to list what is ingested"
    )


def test_unknown_page_is_exit_1(runner: CliRunner, wired: FakeDocumentRegistry) -> None:
    result = runner.invoke(cli.app, ["read", "t12-audit", "p9"])
    assert result.exit_code == 1
    assert result.stderr.strip() == (
        "backdraft: no such page: 'p9'; this document has p1-3"
    )


def test_the_registry_is_closed_even_after_an_error(
    runner: CliRunner, wired: FakeDocumentRegistry
) -> None:
    runner.invoke(cli.app, ["read", "nope"])
    assert wired.closed


# ---------------------------------------------------------------------------
# search
# ---------------------------------------------------------------------------


def test_search(runner: CliRunner, wired: FakeDocumentRegistry) -> None:
    result = runner.invoke(cli.app, ["search", "net operating income"])
    assert result.exit_code == 0
    assert "[bd:t12-audit:p2.c2:1e7a]  t12-audit p2" in result.output


def test_search_scoped_and_minted(runner: CliRunner, wired: FakeDocumentRegistry) -> None:
    result = runner.invoke(
        cli.app, ["search", "NOI", "--in", "rent-model", "--session", "run-b"]
    )
    assert result.exit_code == 0
    assert "in rent-model" in result.output
    assert wired.shown_tokens("run-b")


def test_search_in_unknown_document_is_exit_1(
    runner: CliRunner, wired: FakeDocumentRegistry
) -> None:
    result = runner.invoke(cli.app, ["search", "NOI", "--in", "nope"])
    assert result.exit_code == 1
    assert result.stderr.strip() == (
        "backdraft: no such document: 'nope'; "
        "run `backdraft read` to list what is ingested"
    )


# ---------------------------------------------------------------------------
# show
# ---------------------------------------------------------------------------


def test_show_prints_the_snippet_and_mints_it(
    runner: CliRunner, wired: FakeDocumentRegistry
) -> None:
    result = runner.invoke(
        cli.app, ["show", "bd:t12-audit:p2.c1:50bd", "--session", "run-c"]
    )
    assert result.exit_code == 0
    assert "The portfolio comprises 14 assets across three markets." in result.output
    assert wired.shown_tokens("run-c") == {"bd:t12-audit:p2.c1:50bd"}


def test_show_of_a_token_naming_nothing_is_exit_1(
    runner: CliRunner, wired: FakeDocumentRegistry
) -> None:
    """The reason is on stdout, not stderr: a status is a result, not a crash."""
    result = runner.invoke(cli.app, ["show", "bd:t12-audit:p9.c1:1a2b"])
    assert result.exit_code == 1
    assert "unresolved" in result.output
    assert result.stderr == ""


def test_show_of_a_malformed_token_is_exit_1(
    runner: CliRunner, wired: FakeDocumentRegistry
) -> None:
    result = runner.invoke(cli.app, ["show", "bd:t12-audit:p2c1:50bd"])
    assert result.exit_code == 1
    assert "malformed" in result.output
    assert "bd:<slug>:<locator>:<hash>" in result.output


def test_show_closes_the_registry_on_the_failing_path(
    runner: CliRunner, wired: FakeDocumentRegistry
) -> None:
    runner.invoke(cli.app, ["show", "bd:nope:p1.c1:1a2b"])
    assert wired.closed


# ---------------------------------------------------------------------------
# session
# ---------------------------------------------------------------------------


def test_session_start(runner: CliRunner, wired: FakeDocumentRegistry) -> None:
    result = runner.invoke(cli.app, ["session", "start", "--id", "run-x", "--label", "note"])
    assert result.exit_code == 0
    assert "session run-x  started" in result.output
    assert f"export {cli.SESSION_ENV}=run-x" in result.output
    assert wired.sessions() == {"run-x": "note"}


def test_session_start_generates_an_id(runner: CliRunner, wired: FakeDocumentRegistry) -> None:
    result = runner.invoke(cli.app, ["session", "start"])
    assert "session generated-1  started" in result.output


def test_session_show_default(runner: CliRunner, wired: FakeDocumentRegistry) -> None:
    result = runner.invoke(cli.app, ["session", "show"])
    assert result.exit_code == 0
    assert result.output.startswith("session default  (from default)")


def test_session_show_env(
    runner: CliRunner, wired: FakeDocumentRegistry, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(cli.SESSION_ENV, "from-env")
    result = runner.invoke(cli.app, ["session", "show"])
    assert result.output.startswith(f"session from-env  (from {cli.SESSION_ENV})")


def test_session_show_flag_wins(
    runner: CliRunner, wired: FakeDocumentRegistry, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(cli.SESSION_ENV, "from-env")
    result = runner.invoke(cli.app, ["session", "show", "--session", "from-flag"])
    assert result.output.startswith("session from-flag  (from --session)")


def test_session_show_reports_what_the_ledger_holds(
    runner: CliRunner, wired: FakeDocumentRegistry
) -> None:
    """The acceptance question: read one document, search another, then ask."""
    runner.invoke(cli.app, ["read", "t12-audit", "p2", "--session", "s-deal"])
    runner.invoke(cli.app, ["search", "Vacancy", "--session", "s-deal"])

    result = runner.invoke(cli.app, ["session", "show", "--session", "s-deal"])
    assert result.exit_code == 0
    assert "4 anchors shown across 2 documents" in result.output
    assert "t12-audit   2" in result.output
    assert "rent-model  2" in result.output


def test_session_show_on_an_empty_session_names_read(
    runner: CliRunner, wired: FakeDocumentRegistry
) -> None:
    result = runner.invoke(cli.app, ["session", "show", "--session", "s-fresh"])
    assert result.exit_code == 0
    assert "nothing shown yet" in result.output
    assert "backdraft read" in result.output


def test_the_default_session_says_it_accumulates(
    runner: CliRunner, wired: FakeDocumentRegistry
) -> None:
    """The cost of never exporting a session, said where a caller meets it."""
    result = runner.invoke(cli.app, ["session", "show"])
    assert "note: this is the default session" in result.output
    assert f"exported `{cli.SESSION_ENV}`" in result.output


def test_a_named_session_carries_no_accumulation_note(
    runner: CliRunner, wired: FakeDocumentRegistry, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(cli.SESSION_ENV, "s-x")
    result = runner.invoke(cli.app, ["session", "show"])
    assert result.output.startswith(f"session s-x  (from {cli.SESSION_ENV})")
    assert "note:" not in result.output


def test_naming_the_default_session_explicitly_still_notes(
    runner: CliRunner, wired: FakeDocumentRegistry
) -> None:
    """The note is about the shared ledger, not about which rule chose it."""
    result = runner.invoke(cli.app, ["session", "show", "--session", "default"])
    assert result.output.startswith("session default  (from --session)")
    assert "note: this is the default session" in result.output


# ---------------------------------------------------------------------------
# session precedence, on its own
# ---------------------------------------------------------------------------


def test_precedence_flag_over_env_over_default(monkeypatch: pytest.MonkeyPatch) -> None:
    _resolve_session = top_cli.resolve_session

    monkeypatch.delenv(cli.SESSION_ENV, raising=False)
    assert _resolve_session(None) == top_cli.DEFAULT_SESSION
    monkeypatch.setenv(cli.SESSION_ENV, "from-env")
    assert _resolve_session(None) == "from-env"
    assert _resolve_session("from-flag") == "from-flag"


def test_reads_without_a_session_flag_use_the_default(
    runner: CliRunner, wired: FakeDocumentRegistry
) -> None:
    runner.invoke(cli.app, ["read", "t12-audit", "p1"])
    assert wired.shown_tokens(top_cli.DEFAULT_SESSION) == {"bd:t12-audit:p1.c1:5ff8"}
