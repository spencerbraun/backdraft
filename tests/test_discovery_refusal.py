"""What `bind` and `locate` say when the walk from a document finds no registry.

Both walk up from the document's directory (SPEC § CLI). A draft kept beside its
project — `project/` and `elsewhere/memo.md` side by side, run from inside the
project — used to be told there was no registry "in this directory", which reads
as cwd, the one directory that visibly has one, and to run `backdraft init`,
which was the wrong fix from either place. The refusal now names where it
searched, the registry that does not cover the draft, and `BACKDRAFT_HOME`. Every
walk that started at cwd — every gate command, and `bind memo.md` in cwd — still
prints the old line byte for byte. None of these refusals may leave a
`.backdraft/` behind, because `Registry.open` creates what it does not find.
"""

from __future__ import annotations

import shlex
from pathlib import Path

import pytest
from typer.testing import CliRunner

from backdraft import cli
from backdraft.cli_context import HOME_ENV
from backdraft.registry import DIRECTORY

runner = CliRunner()

TODAY = "backdraft: no .backdraft/ found in this directory or any parent; run `backdraft init`\n"
"""The cwd refusal as it has always read — pinned, not paraphrased."""


def invoke(*args: str):
    return runner.invoke(cli.app, list(args))


def registries(under: Path) -> list[Path]:
    """Every `.backdraft/` beneath `under`, so a test can assert none appeared."""
    return sorted(path for path in under.rglob(DIRECTORY) if path.is_dir())


@pytest.fixture
def layout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """`project/` with a registry and `elsewhere/memo.md` beside it; cwd is the project."""
    monkeypatch.delenv(HOME_ENV, raising=False)
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.chdir(project)
    assert invoke("init").exit_code == 0
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "memo.md").write_text("Prose with no citations in it.\n", encoding="utf-8")
    return tmp_path


@pytest.mark.parametrize("command", ["bind", "locate"])
def test_a_draft_beside_the_project_names_the_registry_that_does_not_cover_it(
    layout: Path, command: str
) -> None:
    result = invoke(command, "../elsewhere/memo.md")

    assert result.exit_code == 1
    message = result.stderr
    assert f"found in {(layout / 'elsewhere').resolve()}, where ../elsewhere/memo.md is," in message
    assert f"the registry at {(layout / 'project').resolve()} does not cover it" in message
    assert f"{HOME_ENV}={shlex.quote(str((layout / 'project').resolve()))}" in message
    assert "backdraft init" not in message
    assert message.count("\n") == 1, "one line, like every other refusal"
    assert registries(layout) == [layout / "project" / DIRECTORY]


@pytest.mark.parametrize("command", ["bind", "locate"])
def test_naming_the_project_with_backdraft_home_lets_the_same_run_through(
    layout: Path, command: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(HOME_ENV, str(layout / "project"))

    result = invoke(command, "../elsewhere/memo.md")

    assert result.exit_code == 0, result.output
    assert registries(layout) == [layout / "project" / DIRECTORY]


def test_it_never_falls_back_to_the_registry_cwd_is_under(layout: Path) -> None:
    """Refused, not bound against cwd's registry: no session row, no record written."""
    assert invoke("bind", "../elsewhere/memo.md").exit_code == 1
    assert sorted(path.name for path in (layout / "elsewhere").iterdir()) == ["memo.md"]


@pytest.mark.parametrize("command", ["bind", "locate"])
def test_with_no_registry_anywhere_a_draft_elsewhere_is_named_and_init_is_still_the_advice(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, command: str
) -> None:
    monkeypatch.delenv(HOME_ENV, raising=False)
    monkeypatch.chdir(tmp_path)
    drafts = tmp_path / "drafts"
    drafts.mkdir()
    (drafts / "memo.md").write_text("Prose.\n", encoding="utf-8")

    result = invoke(command, "drafts/memo.md")

    assert result.exit_code == 1
    assert f"found in {drafts.resolve()}, where drafts/memo.md is," in result.stderr
    assert "`backdraft init <project root>`" in result.stderr
    assert HOME_ENV not in result.stderr
    assert registries(tmp_path) == []


@pytest.mark.parametrize(
    "args", [("read",), ("ls",), ("bind", "memo.md"), ("locate", "memo.md")]
)
def test_a_walk_from_cwd_prints_todays_refusal_byte_for_byte(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, args: tuple[str, ...]
) -> None:
    monkeypatch.delenv(HOME_ENV, raising=False)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "memo.md").write_text("Prose.\n", encoding="utf-8")

    result = invoke(*args)

    assert result.exit_code == 1
    assert result.stderr == TODAY
    assert registries(tmp_path) == []
