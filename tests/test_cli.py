"""The CLI surface W1 owns: discovery, session resolution, init/ingest/ls/export."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from backdraft import cli
from backdraft.registry import DIRECTORY, Registry

runner = CliRunner()


@pytest.fixture(autouse=True)
def no_home_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """Neither env var leaks in from the developer's shell."""
    monkeypatch.delenv(cli.HOME_ENV, raising=False)
    monkeypatch.delenv(cli.SESSION_ENV, raising=False)


@pytest.fixture
def project(tmp_path: Path, note: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """An initialized project, with cwd inside it."""
    monkeypatch.chdir(tmp_path)
    runner.invoke(cli.app, ["init"])
    return tmp_path


# ---- discovery --------------------------------------------------------------


def test_find_root_walks_up(tmp_path: Path) -> None:
    (tmp_path / DIRECTORY).mkdir()
    deep = tmp_path / "a" / "b"
    deep.mkdir(parents=True)
    assert cli.find_root(deep) == tmp_path.resolve()


def test_find_root_is_none_without_a_registry(tmp_path: Path) -> None:
    assert cli.find_root(tmp_path) is None


def test_backdraft_home_overrides_the_walk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(cli.HOME_ENV, str(tmp_path))
    assert cli.find_root(Path("/")) == tmp_path


def test_backdraft_home_accepts_the_registry_directory_itself(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(cli.HOME_ENV, str(tmp_path / DIRECTORY))
    assert cli.find_root(Path("/")) == tmp_path


# ---- sessions ---------------------------------------------------------------


def test_the_default_session_is_used_when_nothing_is_given(root: Path) -> None:
    with Registry.open(root) as registry:
        assert cli.resolve_session(registry=registry) == "default"


def test_the_env_var_beats_the_default(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(cli.SESSION_ENV, "from-env")
    with Registry.open(root) as registry:
        assert cli.resolve_session(registry=registry) == "from-env"


def test_the_flag_beats_the_env_var(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(cli.SESSION_ENV, "from-env")
    with Registry.open(root) as registry:
        assert cli.resolve_session("from-flag", registry) == "from-flag"


# ---- commands ---------------------------------------------------------------


def test_init_creates_the_registry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(cli.app, ["init"])
    assert result.exit_code == 0
    assert (tmp_path / DIRECTORY / "registry.db").is_file()
    assert "documents: 0" in result.stdout


def test_commands_without_a_registry_exit_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(cli.app, ["ls"])
    assert result.exit_code == cli.EXIT_USAGE
    assert "backdraft init" in result.stderr


def test_ingest_then_ls(project: Path, note: Path) -> None:
    result = runner.invoke(cli.app, ["ingest", str(note)])
    assert result.exit_code == 0
    assert "quarterly-notes" in result.stdout

    listed = runner.invoke(cli.app, ["ls"])
    assert listed.exit_code == 0
    assert "quarterly-notes\tquarterly-notes.md\ttext\t1 pages" in listed.stdout


def test_ls_says_so_when_empty(project: Path) -> None:
    assert "no documents ingested" in runner.invoke(cli.app, ["ls"]).stdout


def test_ingest_accepts_an_explicit_slug(project: Path, note: Path) -> None:
    result = runner.invoke(cli.app, ["ingest", str(note), "--slug", "t12-audit"])
    assert result.exit_code == 0
    assert "t12-audit" in result.stdout


def test_a_slug_with_several_files_is_a_usage_error(project: Path, note: Path) -> None:
    result = runner.invoke(cli.app, ["ingest", str(note), str(note), "--slug", "x"])
    assert result.exit_code == cli.EXIT_USAGE


def test_ingest_reports_an_extractor_failure(project: Path, tmp_path: Path) -> None:
    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"%PDF-1.4 nonsense")
    result = runner.invoke(cli.app, ["ingest", str(broken)])
    assert result.exit_code == cli.EXIT_USAGE
    assert "broken.pdf" in result.stderr


def test_ingest_rejects_a_malformed_config_pair(project: Path, note: Path) -> None:
    result = runner.invoke(cli.app, ["ingest", str(note), "--config", "nonsense"])
    assert result.exit_code == cli.EXIT_USAGE
    assert "key=value" in result.stderr


def test_ingest_passes_config_through(project: Path, note: Path) -> None:
    first = runner.invoke(cli.app, ["ingest", str(note)])
    second = runner.invoke(cli.app, ["ingest", str(note), "--config", "mode=loud"])
    assert (first.exit_code, second.exit_code) == (0, 0)
    with Registry.open(project) as registry:
        generations = registry.export_json()["documents"][0]["extractions"]
    assert len(generations) == 2


def test_export_to_stdout(project: Path, note: Path) -> None:
    runner.invoke(cli.app, ["ingest", str(note)])
    result = runner.invoke(cli.app, ["export"])
    assert result.exit_code == 0
    assert json.loads(result.stdout)["$format"] == "backdraft/registry-v1"


def test_export_to_a_file(project: Path, note: Path, tmp_path: Path) -> None:
    runner.invoke(cli.app, ["ingest", str(note)])
    out = tmp_path / "registry.json"
    result = runner.invoke(cli.app, ["export", "--out", str(out)])
    assert result.exit_code == 0
    assert json.loads(out.read_text())["documents"][0]["slug"] == "quarterly-notes"


def test_ingesting_a_workbook_through_the_cli(project: Path, workbook: Path) -> None:
    result = runner.invoke(cli.app, ["ingest", str(workbook)])
    assert result.exit_code == 0
    assert "model" in result.stdout and "2 pages" in result.stdout


def test_help_lists_the_commands_w1_owns() -> None:
    result = runner.invoke(cli.app, ["--help"])
    for command in ("init", "ingest", "ls", "export"):
        assert command in result.stdout


def test_a_missing_sub_app_degrades_silently() -> None:
    """A workstream that has not landed yet must not break the whole CLI."""
    assert cli._mount("backdraft.nothing.here.cli") is False
    assert runner.invoke(cli.app, ["--help"]).exit_code == 0


def test_skill_install_copies_the_bundled_skill(tmp_path, monkeypatch) -> None:
    from typer.testing import CliRunner

    from backdraft.cli import app

    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    result = CliRunner().invoke(app, ["skill", "install"])
    assert result.exit_code == 0, result.output
    installed = tmp_path / ".claude" / "skills" / "backdraft" / "SKILL.md"
    assert installed.is_file()
    assert "backdraft read" in installed.read_text(encoding="utf-8")

    result = CliRunner().invoke(app, ["skill", "install", "--all"])
    assert result.exit_code == 0, result.output
    assert (tmp_path / ".claude" / "skills" / "backdraft-backfill" / "SKILL.md").is_file()
