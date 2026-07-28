"""`backdraft render`: sidecar discovery, the three targets, and the exit codes.

The load-bearing test here is `test_renders_with_the_registry_deleted`: a bare
directory holding a document and a sidecar, nothing else, no `.backdraft/`
anywhere above it. That is the integration invariant the artifact exists for.
"""

from __future__ import annotations

import json
import pathlib

import pytest
import typer
from typer.testing import CliRunner

from backdraft.kernel.model import BindReport
from backdraft.render import sidecar
from backdraft.render.cli import app as render_app

from conftest_render import DEMO_DOC

runner = CliRunner()


def _mounted() -> typer.Typer:
    """The top level, as SPEC Addendum B assembles it.

    W1 owns `cli.py` and mounts render's commands into it. Testing through a
    stand-in top level rather than through `render_app` alone keeps the tested
    surface the one users type: `backdraft render <doc>`.
    """
    root = typer.Typer()

    @root.command()
    def init() -> None:
        """Stand-in for W1's own commands."""

    root.registered_commands.extend(render_app.registered_commands)
    return root


app = _mounted()


@pytest.fixture
def bound(tmp_path: pathlib.Path, demo: BindReport) -> pathlib.Path:
    """A document and its sidecar, alone in a directory."""
    doc = tmp_path / "memo.md"
    doc.write_text(DEMO_DOC, encoding="utf-8")
    sidecar.write(demo, sidecar.sidecar_path(doc))
    return doc


def test_renders_html_next_to_the_document(bound: pathlib.Path) -> None:
    result = runner.invoke(app, ["render", str(bound)])
    assert result.exit_code == 0, result.output
    artifact = bound.with_name("memo.backdraft.html")
    assert artifact.is_file()
    assert str(artifact) in result.output
    assert "backdraft/artifact-v1" in artifact.read_text(encoding="utf-8")


def test_renders_footnotes(bound: pathlib.Path) -> None:
    result = runner.invoke(app, ["render", str(bound), "--to", "footnotes"])
    assert result.exit_code == 0, result.output
    projection = bound.with_name("memo.footnotes.md")
    assert "[^bd1]:" in projection.read_text(encoding="utf-8")


def test_renders_the_sidecar_to_stdout(bound: pathlib.Path) -> None:
    result = runner.invoke(app, ["render", str(bound), "--to", "json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["$format"] == "backdraft/artifact-v1"


def test_output_path_is_honoured(bound: pathlib.Path, tmp_path: pathlib.Path) -> None:
    out = tmp_path / "elsewhere" / "artifact.html"
    out.parent.mkdir()
    result = runner.invoke(app, ["render", str(bound), "-o", str(out)])
    assert result.exit_code == 0, result.output
    assert out.is_file()


def test_dash_writes_to_stdout(bound: pathlib.Path) -> None:
    result = runner.invoke(app, ["render", str(bound), "--to", "footnotes", "-o", "-"])
    assert result.exit_code == 0, result.output
    assert result.stdout.startswith("# Bridgeview")
    assert not bound.with_name("memo.footnotes.md").exists()


def test_the_full_filename_sidecar_form_is_accepted(
    tmp_path: pathlib.Path, demo: BindReport
) -> None:
    doc = tmp_path / "memo.md"
    doc.write_text(DEMO_DOC, encoding="utf-8")
    sidecar.write(demo, tmp_path / "memo.md.backdraft.json")
    result = runner.invoke(app, ["render", str(doc), "--to", "json"])
    assert result.exit_code == 0, result.output


def test_a_missing_document_is_a_usage_error(tmp_path: pathlib.Path) -> None:
    result = runner.invoke(app, ["render", str(tmp_path / "nope.md")])
    assert result.exit_code == 1
    assert "no such document" in result.output


def test_a_missing_sidecar_is_a_usage_error(tmp_path: pathlib.Path) -> None:
    doc = tmp_path / "memo.md"
    doc.write_text(DEMO_DOC, encoding="utf-8")
    result = runner.invoke(app, ["render", str(doc)])
    assert result.exit_code == 1
    assert "memo.backdraft.json" in result.output
    assert "bind" in result.output


def test_an_unknown_format_is_a_usage_error(bound: pathlib.Path) -> None:
    path = sidecar.sidecar_path(bound)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["$format"] = "someone-elses/format-v9"
    path.write_text(json.dumps(payload), encoding="utf-8")
    result = runner.invoke(app, ["render", str(bound)])
    assert result.exit_code == 1
    assert "unreadable sidecar" in result.output


def test_unresolved_citations_do_not_fail_the_render(bound: pathlib.Path) -> None:
    """Exit code 2 is bind's contract; render reports failures, it does not gate."""
    result = runner.invoke(app, ["render", str(bound)])
    assert result.exit_code == 0


def test_renders_with_the_registry_deleted(
    tmp_path: pathlib.Path, demo: BindReport, monkeypatch: pytest.MonkeyPatch
) -> None:
    bare = tmp_path / "handed-over"
    bare.mkdir()
    doc = bare / "memo.md"
    doc.write_text(DEMO_DOC, encoding="utf-8")
    sidecar.write(demo, sidecar.sidecar_path(doc))
    monkeypatch.chdir(bare)
    monkeypatch.setenv("BACKDRAFT_HOME", str(bare / "does-not-exist"))

    result = runner.invoke(app, ["render", "memo.md"])
    assert result.exit_code == 0, result.output

    artifact = (bare / "memo.backdraft.html").read_text(encoding="utf-8")
    assert sorted(path.name for path in bare.iterdir()) == [
        "memo.backdraft.html",
        "memo.backdraft.json",
        "memo.md",
    ]
    assert "Debt service coverage for the trailing twelve months is 1.42x" in artifact
    assert "backdraft/artifact-v1" in artifact
    for citation in demo.unresolved:
        assert citation.token.replace("&", "&amp;") in artifact
    # NOTE: the favicon data URI carries the SVG xml namespace (an identifier,
    # never fetched, and percent-encoded); the reach-for-nothing check is on
    # actual URL forms.
    assert "http://" not in artifact
    assert "https://" not in artifact
