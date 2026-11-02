"""The registry's schema stamp: a build refuses a registry newer than it knows.

The registry travels with the project folder, so it meets builds other than the
one that wrote it. What is under test is that a file stamped too high is refused
by everything that opens it with the bytes untouched, and that every other file
carries on as it did.
"""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

import pytest
from typer.testing import CliRunner

from backdraft import cli
from backdraft.registry import SCHEMA_VERSION, Registry, RegistryError
from backdraft.registry.store import DATABASE, DIRECTORY

runner = CliRunner()


def _database(root: Path) -> Path:
    return root / DIRECTORY / DATABASE


def _stamp(root: Path, version: int) -> None:
    connection = sqlite3.connect(_database(root))
    connection.execute(f"PRAGMA user_version = {version}")
    connection.close()


def _stamped(root: Path) -> int:
    connection = sqlite3.connect(_database(root))
    try:
        return connection.execute("PRAGMA user_version").fetchone()[0]
    finally:
        connection.close()


def _contents(root: Path) -> dict[str, bytes]:
    """Everything under `.backdraft/`, so a stray journal counts as a change too."""
    directory = root / DIRECTORY
    return {
        str(path.relative_to(directory)): path.read_bytes()
        for path in sorted(directory.rglob("*"))
        if path.is_file()
    }


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A project with a source, a bound memo and its record, as a real run leaves one."""
    for name in (cli.HOME_ENV, cli.SESSION_ENV):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "notes.txt").write_text(
        "Revenue was twelve million in the year under review, up from nine.\n",
        encoding="utf-8",
    )
    (tmp_path / "memo.md").write_text("Nothing cited yet.\n", encoding="utf-8")
    for arguments in (["init"], ["ingest", "notes.txt"], ["bind", "memo.md"]):
        result = runner.invoke(cli.app, arguments)
        assert result.exit_code == 0, result.output
    return tmp_path


def test_a_new_registry_carries_the_current_version(tmp_path: Path) -> None:
    Registry.open(tmp_path).close()
    assert _stamped(tmp_path) == SCHEMA_VERSION == 1


def test_a_registry_from_before_the_stamp_opens_and_is_stamped(project: Path) -> None:
    _stamp(project, 0)
    with Registry.open(project) as registry:
        assert [document.slug for document in registry.documents()] == ["notes"]
        assert registry.schema_version() == SCHEMA_VERSION
    assert _stamped(project) == SCHEMA_VERSION


def test_opening_a_current_registry_writes_nothing(project: Path) -> None:
    before = _contents(project)
    Registry.open(project).close()
    assert _contents(project) == before


def test_a_newer_registry_is_refused_naming_both_numbers_and_the_fix(project: Path) -> None:
    newer = SCHEMA_VERSION + 1
    _stamp(project, newer)
    with pytest.raises(RegistryError) as refused:
        Registry.open(project)
    message = str(refused.value)
    assert f"version {newer}" in message and f"version {SCHEMA_VERSION}" in message
    assert "upgrade backdraft" in message
    assert str(_database(project)) in message


def test_the_refusal_comes_before_the_ddl(project: Path) -> None:
    """A newer file without a table this build expects must not have it added."""
    connection = sqlite3.connect(_database(project))
    connection.execute("DROP TABLE withdrawals")
    connection.commit()
    connection.close()
    _stamp(project, SCHEMA_VERSION + 1)
    before = _contents(project)
    with pytest.raises(RegistryError):
        Registry.open(project)
    assert _contents(project) == before


@pytest.mark.parametrize(
    "arguments",
    [
        ["init"],
        ["ingest", "notes.txt"],
        ["ingest", "--dry-run", "notes.txt"],
        ["ls"],
        ["read"],
        ["read", "notes"],
        ["search", "revenue"],
        ["show", "bd:notes:p1.c1:aaaa"],
        ["session", "start"],
        ["session", "show"],
        ["bind", "memo.md"],
        ["locate", "memo.md"],
        ["forget", "notes", "--yes"],
        ["snapshot-pages", "notes"],
        ["export"],
        ["verify", f"{DIRECTORY}/records/memo.backdraft.json"],
    ],
    ids=" ".join,
)
def test_every_verb_that_opens_it_refuses_at_exit_1_and_changes_nothing(
    project: Path, arguments: list[str]
) -> None:
    _stamp(project, SCHEMA_VERSION + 1)
    before = _contents(project)
    result = runner.invoke(cli.app, arguments)
    assert result.exit_code == 1, result.output
    assert isinstance(result.exception, SystemExit), result.exception  # the guard, no traceback
    assert "written by a newer backdraft" in result.output.replace("\n", " ")
    assert _contents(project) == before


def test_verify_reports_a_damaged_registry_through_the_guard(project: Path) -> None:
    _database(project).write_bytes(b"not a database, " * 64)
    result = runner.invoke(cli.app, ["verify", f"{DIRECTORY}/records/memo.backdraft.json"])
    assert result.exit_code == 1, result.output
    assert isinstance(result.exception, SystemExit), result.exception
    assert "is not a registry backdraft can read" in result.output.replace("\n", " ")


def test_render_never_opens_the_registry_so_a_newer_one_does_not_stop_it(project: Path) -> None:
    """An artifact is reproducible from the draft and its record alone."""
    _stamp(project, SCHEMA_VERSION + 1)
    before = _contents(project)
    result = runner.invoke(cli.app, ["render", "memo.md", "--to", "html"])
    assert result.exit_code == 0, result.output
    assert _contents(project) == before


def test_doctor_reports_a_newer_registry_as_its_gap_at_exit_0(project: Path) -> None:
    newer = SCHEMA_VERSION + 1
    _stamp(project, newer)
    before = _contents(project)
    result = runner.invoke(cli.app, ["doctor"])
    assert result.exit_code == 0, result.output
    line = next(line for line in result.output.splitlines() if line.startswith("registry"))
    assert "missing" in line and f"version {newer}" in line
    assert _contents(project) == before


def test_doctor_names_the_schema_version(project: Path) -> None:
    result = runner.invoke(cli.app, ["doctor"])
    line = next(line for line in result.output.splitlines() if line.startswith("registry"))
    assert "ready" in line and f"schema {SCHEMA_VERSION}, 1 document(s)" in line


def test_export_carries_the_version_beside_the_format(project: Path) -> None:
    result = runner.invoke(cli.app, ["export"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert list(payload)[:2] == ["$format", "schema_version"]
    assert payload["schema_version"] == SCHEMA_VERSION


@pytest.mark.skipif(os.geteuid() == 0, reason="root writes through a read-only mode")
def test_a_registry_that_cannot_be_written_opens_and_stays_unstamped(project: Path) -> None:
    """A read-only mount answered every read before the stamp, and still does."""
    _stamp(project, 0)
    database, directory = _database(project), project / DIRECTORY
    database.chmod(0o444)
    directory.chmod(0o555)
    try:
        with Registry.open(project) as registry:
            assert [document.slug for document in registry.documents()] == ["notes"]
            assert registry.schema_version() == 0
    finally:
        directory.chmod(0o755)
        database.chmod(0o644)
