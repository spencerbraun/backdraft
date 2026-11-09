"""`bind`'s `cleared:` line: a `not_shown` cleared by `show` does not read as read-first.

Showing is minting, so the status clears by being shown. The report is the one
place that can still say the claim was written before its evidence was read, by
comparing against the record this run is about to overwrite. Display only.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from backdraft import cli
from backdraft.bind import cli as bind_cli
from backdraft.kernel.artifact import record_path
from backdraft.registry import Registry

runner = CliRunner()
PARAGRAPH = "Net operating income rose eleven percent over the trailing twelve months."
CLAIM = "Income rose eleven percent"
ROUTE = "backdraft show"


@pytest.fixture(autouse=True)
def no_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(cli.HOME_ENV, raising=False)
    monkeypatch.delenv(cli.SESSION_ENV, raising=False)


def invoke(*args: str):
    return runner.invoke(cli.app, list(args))


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    assert invoke("init").exit_code == 0
    (tmp_path / "notes.md").write_text(PARAGRAPH + "\n", encoding="utf-8")
    assert invoke("ingest", "notes.md").exit_code == 0
    return tmp_path


@pytest.fixture
def token(project: Path) -> str:
    with Registry.open(project) as registry:
        return next(a.token for a in registry.anchors_for_page("notes", 1) if a.kind == "chunk")


@pytest.fixture
def memo(project: Path, token: str) -> Path:
    path = project / "memo.md"
    path.write_text(f"[{CLAIM}]({token}).\n", encoding="utf-8")
    return path


def bind(*extra: str):
    return invoke("bind", "memo.md", "--session", "s1", *extra)


def show(token: str, session: str = "s1") -> None:
    assert invoke("show", token, "--session", session).exit_code == 0


def cleared_lines(output: str) -> list[str]:
    return [line for line in output.splitlines() if line.startswith("  cleared: ")]


def record(project: Path) -> Path:
    return record_path(project.resolve(), (project / "memo.md").resolve())


def test_a_flagged_citation_shown_and_rebound_prints_one_cleared_line(
    project: Path, memo: Path, token: str
) -> None:
    first = bind()
    assert first.exit_code == 2 and "not_shown" in first.output
    show(token)
    second = bind()
    assert second.exit_code == 0, second.output
    (line,) = cleared_lines(second.output)
    assert line == (
        f"  cleared: {token} — {CLAIM} @0 — shown under a minute after the bind that flagged it"
    )
    closing = [text for text in second.output.splitlines() if text.startswith("next: cleared — ")]
    assert len(closing) == 1
    assert f"`{ROUTE} <token> --session s1`" in closing[0]
    assert "  ! " not in second.output


def test_the_third_bind_prints_no_cleared_line(project: Path, memo: Path, token: str) -> None:
    bind()
    show(token)
    bind()
    third = bind()
    assert third.exit_code == 0
    assert "cleared" not in third.output


def test_status_record_and_json_do_not_carry_it(project: Path, memo: Path, token: str) -> None:
    bind()
    show(token)
    result = bind("--json")
    assert result.exit_code == 0
    assert "cleared" not in result.stdout
    payload = json.loads(result.stdout)
    assert payload["claims"][0]["citations"][0]["status"] == "resolved"
    assert "cleared" not in record(project).read_text(encoding="utf-8")


def test_a_citation_read_before_writing_binds_with_no_new_lines(
    project: Path, memo: Path, token: str
) -> None:
    show(token)
    first = bind()
    assert first.exit_code == 0
    assert first.output == (
        "bound 1 claim(s), 1 citation(s) [frontwalk] against session s1\n"
        "  resolved: 1\n"
        "wrote .backdraft/records/memo.backdraft.json\n"
    )
    assert bind().output == first.output


def test_a_still_flagged_citation_is_not_cleared(project: Path, memo: Path) -> None:
    bind()
    assert cleared_lines(bind().output) == []


@pytest.mark.parametrize(
    "broken",
    [
        b"{ not json",
        b"\xff\xfe not text",
        b"[]",
        b'{"$format": "backdraft/artifact-v1"}',
        b'{"$format": "something-else", "mode": "frontwalk", "session_id": "s1"}',
    ],
    ids=["invalid-json", "not-utf8", "not-an-object", "no-keys", "other-format"],
)
def test_a_previous_record_it_cannot_read_compares_nothing(
    project: Path, memo: Path, token: str, broken: bytes
) -> None:
    bind()
    show(token)
    record(project).write_bytes(broken)
    result = bind()
    assert result.exit_code == 0, result.output
    assert cleared_lines(result.output) == []


def rewrite_record(project: Path, **changes: object) -> None:
    path = record(project)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload.update(changes)
    path.write_text(json.dumps(payload), encoding="utf-8")


@pytest.mark.parametrize("value", ["yesterday", "2026-11-09T10:00:00"], ids=["junk", "naive"])
def test_a_previous_bound_at_with_no_usable_time_compares_nothing(
    project: Path, memo: Path, token: str, value: str
) -> None:
    bind()
    show(token)
    rewrite_record(project, bound_at=value)
    result = bind()
    assert result.exit_code == 0
    assert cleared_lines(result.output) == []


def test_a_previous_backfill_record_compares_nothing(
    project: Path, memo: Path, token: str
) -> None:
    bind()
    show(token)
    rewrite_record(project, mode="backfill")
    assert cleared_lines(bind().output) == []


def test_a_backfill_run_clears_nothing(project: Path, memo: Path, token: str) -> None:
    bind()
    show(token)
    assert cleared_lines(bind("--mode", "backfill").output) == []


def test_another_sessions_flag_says_nothing_about_this_ledger(
    project: Path, memo: Path, token: str
) -> None:
    bind()  # flagged under s1
    show(token, session="s2")
    result = invoke("bind", "memo.md", "--session", "s2")
    assert result.exit_code == 0
    assert cleared_lines(result.output) == []


def test_a_claim_keeps_its_own_line_when_a_token_is_cited_twice(
    project: Path, memo: Path, token: str
) -> None:
    memo.write_text(f"[First claim]({token}) and [second claim]({token}).\n", encoding="utf-8")
    bind()
    show(token)
    lines = cleared_lines(bind().output)
    assert [line.split(" — ")[1] for line in lines] == ["First claim @0", "second claim @39"]


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [
        (5, "under a minute"),
        (60, "1 minute"),
        (3599, "59 minutes"),
        (3600, "1 hour"),
        (86400, "1 day"),
        (172800, "2 days"),
    ],
)
def test_elapsed_reads_in_the_largest_whole_unit(seconds: int, expected: str) -> None:
    from datetime import UTC, datetime, timedelta

    since = datetime(2026, 11, 9, tzinfo=UTC)
    shown = (since + timedelta(seconds=seconds)).isoformat()
    assert bind_cli._elapsed(since, shown) == expected


def test_shown_at_is_none_for_a_token_never_shown(project: Path, token: str) -> None:
    with Registry.open(project) as registry:
        registry.ensure_session("s1")
        assert registry.shown_at("s1", token) is None
