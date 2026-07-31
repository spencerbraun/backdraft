"""`backdraft bind`: the exit-code contract and the printed report."""

from __future__ import annotations

import json

import pytest
from fakes import FakeAnchorRegistry
from typer.testing import CliRunner

from backdraft.bind import cli as bind_cli
from backdraft.bind.binder import bound_path, sidecar_path
from backdraft.registry import DIRECTORY

RUNNER = CliRunner()
SNIPPET = "Net operating income was 4,120,000 for the trailing twelve months."


@pytest.fixture
def fake_bind_registry(monkeypatch) -> FakeAnchorRegistry:
    """A fake_bind_registry the CLI opens instead of W1's, with discovery stubbed out."""
    fake = FakeAnchorRegistry()
    fake.add_anchor("t12-audit", "p8.c3", SNIPPET, page_number=8)
    fake.add_document("t12-audit", "T12 Audit.pdf")
    monkeypatch.setattr(bind_cli, "open_registry", lambda start=None: fake)
    return fake


def token(fake_bind_registry: FakeAnchorRegistry) -> str:
    return next(iter(fake_bind_registry._anchors))


def write(tmp_path, source: str):
    doc = tmp_path / "notes.md"
    doc.write_text(source, encoding="utf-8")
    return doc


def run(*args):
    return RUNNER.invoke(bind_cli.app, list(args))


# --- exit codes ------------------------------------------------------------


def test_a_clean_bind_exits_zero(tmp_path, fake_bind_registry) -> None:
    resolved = token(fake_bind_registry)
    fake_bind_registry.show("s1", resolved)
    doc = write(tmp_path, f"NOI was [$4.12M]({resolved}).\n")
    result = run(str(doc), "--session", "s1")
    assert result.exit_code == 0, result.output


def test_a_non_resolved_citation_exits_two(tmp_path, fake_bind_registry) -> None:
    doc = write(tmp_path, "NOI was [$4.12M](bd:ghost:p1.c1:0000).\n")
    result = run(str(doc), "--session", "s1")
    assert result.exit_code == bind_cli.EXIT_UNRESOLVED
    assert "unresolved" in result.output


def test_not_shown_also_exits_two(tmp_path, fake_bind_registry) -> None:
    doc = write(tmp_path, f"NOI was [$4.12M]({token(fake_bind_registry)}).\n")
    result = run(str(doc), "--session", "s1")
    assert result.exit_code == bind_cli.EXIT_UNRESOLVED
    assert "not_shown" in result.output


def test_a_failing_verdict_does_not_change_the_exit_code(tmp_path, fake_bind_registry) -> None:
    resolved = token(fake_bind_registry)
    fake_bind_registry.show("s1", resolved)
    doc = write(tmp_path, f"NOI was [$9.99M]({resolved}).\n")
    result = run(str(doc), "--session", "s1", "--check", "value-trace")
    assert result.exit_code == 0
    assert "value-trace: fail 1" in result.output


def test_an_unmatched_backfill_claim_exits_two(tmp_path, fake_bind_registry) -> None:
    doc = write(tmp_path, "Net operating income was 4,120,000 last year.\n")
    result = run(str(doc), "--mode", "backfill")
    assert result.exit_code == bind_cli.EXIT_UNRESOLVED
    assert "unmatched" in result.output


def test_a_missing_document_is_a_usage_error(tmp_path, fake_bind_registry) -> None:
    result = run(str(tmp_path / "absent.md"))
    assert result.exit_code == bind_cli.EXIT_USAGE
    assert "no such document" in result.output


def test_an_unknown_mode_is_a_usage_error(tmp_path, fake_bind_registry) -> None:
    doc = write(tmp_path, "prose\n")
    result = run(str(doc), "--mode", "sideways")
    assert result.exit_code == bind_cli.EXIT_USAGE
    assert "unknown mode" in result.output


def test_an_unknown_check_name_is_a_usage_error(tmp_path, fake_bind_registry) -> None:
    doc = write(tmp_path, f"[a]({token(fake_bind_registry)}).\n")
    result = run(str(doc), "--check", "value_trace")
    assert result.exit_code == bind_cli.EXIT_USAGE
    assert "unknown verification method" in result.output


def test_no_registry_is_a_usage_error(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("BACKDRAFT_HOME", raising=False)
    import backdraft.cli as top_cli
    monkeypatch.setattr(top_cli, "find_root", lambda start=None: None)
    monkeypatch.delenv("BACKDRAFT_HOME", raising=False)
    doc = write(tmp_path, "prose\n")
    result = run(str(doc))
    assert result.exit_code == bind_cli.EXIT_USAGE
    assert ".backdraft" in result.output


# --- behavior --------------------------------------------------------------


def test_the_cli_writes_the_record_and_bound_is_opt_in(tmp_path, fake_bind_registry) -> None:
    resolved = token(fake_bind_registry)
    fake_bind_registry.show("s1", resolved)
    doc = write(tmp_path, f"NOI was [$4.12M]({resolved}).\n")
    result = run(str(doc), "--session", "s1")
    assert not bound_path(doc).exists()
    assert str(bound_path(doc)) not in result.output
    assert json.loads(sidecar_path(doc).read_text(encoding="utf-8"))["mode"] == "frontwalk"

    result = run(str(doc), "--session", "s1", "--bound")
    assert bound_path(doc).exists()
    assert str(bound_path(doc)) in result.output


def test_the_written_record_is_printed_as_the_user_would_type_it(
    tmp_path, fake_bind_registry, monkeypatch
) -> None:
    """A path relative to cwd, matching `render`, so the line docs and skills
    quote is the line the command prints — and no home directory in output
    anyone pastes."""
    fake_bind_registry.root = tmp_path
    monkeypatch.chdir(tmp_path)
    write(tmp_path, "prose only\n")
    result = run("notes.md")
    assert f"wrote {DIRECTORY}/records/notes.backdraft.json" in result.output


def test_a_record_outside_cwd_stays_absolute(
    tmp_path, fake_bind_registry, monkeypatch
) -> None:
    """Relativizing is a convenience, never a lie about where the file landed."""
    fake_bind_registry.root = tmp_path
    elsewhere = tmp_path / "work"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    doc = write(tmp_path, "prose only\n")
    result = run(str(doc))
    assert f"wrote {tmp_path.resolve()}/{DIRECTORY}/records/notes.backdraft.json" in result.output


def test_verification_is_off_unless_check_is_given(tmp_path, fake_bind_registry) -> None:
    resolved = token(fake_bind_registry)
    fake_bind_registry.show("s1", resolved)
    doc = write(tmp_path, f"NOI was [$4.12M]({resolved}).\n")
    run(str(doc), "--session", "s1")
    payload = json.loads(sidecar_path(doc).read_text(encoding="utf-8"))
    assert payload["summary"]["by_method"] == {}
    assert payload["claims"][0]["citations"][0]["verdicts"] == []


def test_check_takes_a_comma_separated_list(tmp_path, fake_bind_registry) -> None:
    resolved = token(fake_bind_registry)
    fake_bind_registry.show("s1", resolved)
    doc = write(tmp_path, f"NOI was [$4.12M]({resolved}).\n")
    result = run(str(doc), "--session", "s1", "--check", "value-trace,overlap")
    assert result.exit_code == 0
    payload = json.loads(sidecar_path(doc).read_text(encoding="utf-8"))
    assert set(payload["summary"]["by_method"]) == {"value-trace", "overlap"}


def test_the_session_flag_reaches_the_report(tmp_path, fake_bind_registry) -> None:
    doc = write(tmp_path, "prose only\n")
    run(str(doc), "--session", "s9")
    assert json.loads(sidecar_path(doc).read_text(encoding="utf-8"))["session_id"] == "s9"


def test_the_session_env_var_is_the_fallback(tmp_path, fake_bind_registry, monkeypatch) -> None:
    monkeypatch.setenv("BACKDRAFT_SESSION", "from-env")
    doc = write(tmp_path, "prose only\n")
    run(str(doc))
    assert json.loads(sidecar_path(doc).read_text(encoding="utf-8"))["session_id"] == "from-env"


def test_the_registry_is_closed_after_a_run(tmp_path, fake_bind_registry) -> None:
    doc = write(tmp_path, "prose only\n")
    run(str(doc))
    assert fake_bind_registry.closed is True


def test_the_summary_line_reports_counts(tmp_path, fake_bind_registry) -> None:
    resolved = token(fake_bind_registry)
    fake_bind_registry.show("s1", resolved)
    doc = write(tmp_path, f"[a]({resolved}) and [b]({resolved}).\n")
    result = run(str(doc), "--session", "s1")
    assert "bound 2 claim(s), 2 citation(s) [frontwalk]" in result.output


def test_discovery_walks_up_to_the_registry_directory(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("BACKDRAFT_HOME", raising=False)
    (tmp_path / DIRECTORY).mkdir()
    nested = tmp_path / "notes" / "deep"
    nested.mkdir(parents=True)
    doc = nested / "notes.md"
    doc.write_text("prose\n", encoding="utf-8")
    from backdraft.cli import find_root

    assert find_root(doc) == tmp_path.resolve()


def test_backdraft_home_overrides_discovery(tmp_path, monkeypatch) -> None:
    from backdraft.cli import find_root

    monkeypatch.setenv("BACKDRAFT_HOME", str(tmp_path))
    assert find_root(tmp_path / "notes.md") == tmp_path.resolve()


def test_the_sub_app_mounts_as_backdraft_bind() -> None:
    """Addendum B: the top level adopts this sub-app's commands, flat.

    Mounted the way `cli.py` actually mounts it — `registered_commands.extend`,
    not `add_typer` — so the command lands as `backdraft bind` with no group name
    in between.
    """
    import typer

    top = typer.Typer()

    @top.command("init")
    def init() -> None:  # pragma: no cover - stands in for the top level's own command
        pass

    top.registered_commands.extend(bind_cli.app.registered_commands)
    result = RUNNER.invoke(top, ["--help"])
    assert result.exit_code == 0
    assert "bind" in result.output
