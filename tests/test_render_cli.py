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
from backdraft.render import math as render_math, sidecar
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
    # groups are a separate registry: without this line `theme list` is missing
    root.registered_groups.extend(render_app.registered_groups)
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


# ---- themes -----------------------------------------------------------------
#
# Precedence: --theme > .backdraft/theme.toml > ~/.config/backdraft/theme.toml >
# built-in. The suite's autouse fixture points XDG at an empty directory, so a
# test that wants the user-wide rung sets it itself.


def _configure(root: pathlib.Path, body: str) -> None:
    (root / ".backdraft").mkdir(parents=True, exist_ok=True)
    (root / ".backdraft" / "theme.toml").write_text(body, encoding="utf-8")


def test_the_flag_takes_a_bundled_theme(bound: pathlib.Path) -> None:
    result = runner.invoke(app, ["render", str(bound), "--theme", "slate"])
    assert result.exit_code == 0, result.output
    artifact = bound.with_name("memo.backdraft.html").read_text(encoding="utf-8")
    assert "--ink:#1C2126" in artifact
    assert "text-transform:uppercase" in artifact


def test_a_project_theme_applies_with_no_flag(bound: pathlib.Path) -> None:
    _configure(bound.parent, '[colors]\nink = "#BBBBBB"\n')
    result = runner.invoke(app, ["render", str(bound)])
    assert result.exit_code == 0, result.output
    assert "--ink:#BBBBBB" in bound.with_name("memo.backdraft.html").read_text()


def test_a_user_wide_theme_applies_in_any_project(
    bound: pathlib.Path, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The rung that makes a preference stick: no flag, no project config."""
    config = tmp_path / "xdg" / "backdraft"
    config.mkdir(parents=True)
    (config / "theme.toml").write_text('[colors]\nink = "#AAAAAA"\n', encoding="utf-8")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))

    result = runner.invoke(app, ["render", str(bound)])
    assert result.exit_code == 0, result.output
    assert "--ink:#AAAAAA" in bound.with_name("memo.backdraft.html").read_text()


def test_the_flag_overrides_a_configured_theme(bound: pathlib.Path) -> None:
    _configure(bound.parent, '[colors]\nink = "#BBBBBB"\n')
    result = runner.invoke(app, ["render", str(bound), "--theme", "press"])
    assert result.exit_code == 0, result.output
    artifact = bound.with_name("memo.backdraft.html").read_text()
    assert "--ink:#241F1A" in artifact
    assert "#BBBBBB" not in artifact


def test_the_flag_takes_a_theme_file(bound: pathlib.Path, tmp_path: pathlib.Path) -> None:
    mine = tmp_path / "mine.toml"
    mine.write_text('[colors]\nsel = "#123456"\n', encoding="utf-8")
    result = runner.invoke(app, ["render", str(bound), "--theme", str(mine)])
    assert result.exit_code == 0, result.output
    assert "--sel:#123456" in bound.with_name("memo.backdraft.html").read_text()


def test_no_theme_anywhere_leaves_the_artifact_untouched(bound: pathlib.Path) -> None:
    """Theming is inert by default: the built-in look, and no override block."""
    result = runner.invoke(app, ["render", str(bound)])
    assert result.exit_code == 0, result.output
    artifact = bound.with_name("memo.backdraft.html").read_text()
    assert artifact.count(":root{") == 1


def test_a_malformed_theme_writes_no_artifact(bound: pathlib.Path) -> None:
    """Never a half-styled artifact: resolution happens before anything is
    written, so a bad theme costs a message and no file."""
    _configure(bound.parent, '[colors]\nink = "#GG"\n')
    result = runner.invoke(app, ["render", str(bound)])
    assert result.exit_code == 1
    assert "is not a CSS color" in result.output
    assert "theme.toml" in result.output
    assert not bound.with_name("memo.backdraft.html").exists()


def test_an_unknown_theme_name_lists_the_bundled_ones(bound: pathlib.Path) -> None:
    result = runner.invoke(app, ["render", str(bound), "--theme", "dusk"])
    assert result.exit_code == 1
    assert "default, press, slate" in result.output
    assert not bound.with_name("memo.backdraft.html").exists()


def test_the_theme_flag_is_refused_on_the_unstyled_targets(bound: pathlib.Path) -> None:
    result = runner.invoke(app, ["render", str(bound), "--to", "json", "--theme", "slate"])
    assert result.exit_code == 1
    assert "--theme styles the html artifact" in result.output


def test_a_configured_theme_is_ignored_by_the_unstyled_targets(
    bound: pathlib.Path,
) -> None:
    """A theme is display; the record and the projection have none to change."""
    _configure(bound.parent, '[colors]\nink = "#BBBBBB"\n')
    result = runner.invoke(app, ["render", str(bound), "--to", "footnotes"])
    assert result.exit_code == 0, result.output
    assert "#BBBBBB" not in bound.with_name("memo.footnotes.md").read_text()


# ---- `backdraft theme` ------------------------------------------------------


def test_theme_list_names_the_bundled_themes() -> None:
    result = runner.invoke(app, ["theme", "list"])
    assert result.exit_code == 0, result.output
    assert result.output.splitlines()[:3] == ["default", "press", "slate"]


def test_theme_list_says_which_one_is_in_effect(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["theme", "list"])
    assert "in effect here: the built-in look" in result.output
    assert "Start your own" in result.output

    config = tmp_path / "xdg" / "backdraft"
    config.mkdir(parents=True)
    (config / "theme.toml").write_text('[colors]\nink = "#AAAAAA"\n', encoding="utf-8")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))

    result = runner.invoke(app, ["theme", "list"])
    assert f"in effect here: {config / 'theme.toml'}" in result.output
    # the bootstrap hint would name the file that is already theirs
    assert "Start your own" not in result.output
    assert "Read it:" in result.output


def test_theme_show_prints_the_file_verbatim() -> None:
    result = runner.invoke(app, ["theme", "show", "press"])
    assert result.exit_code == 0, result.output
    from backdraft.render import theme as theming

    assert result.stdout == (theming.BUNDLED / "press.toml").read_text(encoding="utf-8")


def test_theme_show_bootstraps_a_working_theme(
    bound: pathlib.Path, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The whole point of `show`: its output is a theme file that renders."""
    config = tmp_path / "xdg" / "backdraft"
    config.mkdir(parents=True)
    written = config / "theme.toml"
    written.write_text(runner.invoke(app, ["theme", "show", "default"]).stdout)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))

    result = runner.invoke(app, ["render", str(bound)])
    assert result.exit_code == 0, result.output
    assert "--ink:#282828" in bound.with_name("memo.backdraft.html").read_text()


def test_theme_show_validates_a_file_of_your_own(tmp_path: pathlib.Path) -> None:
    """`show <file>` is also the way to check a theme without rendering."""
    mine = tmp_path / "mine.toml"
    mine.write_text('[colors]\ninkk = "#111"\n', encoding="utf-8")
    result = runner.invoke(app, ["theme", "show", str(mine)])
    assert result.exit_code == 1
    assert "unknown color 'inkk'" in result.output


def test_theme_show_of_nothing_lists_the_bundled_ones() -> None:
    result = runner.invoke(app, ["theme", "show", "dusk"])
    assert result.exit_code == 1
    assert "default, press, slate" in result.output


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


# ---- math the artifact could not typeset ------------------------------------
#
# `render` prints its target path and nothing else, so an artifact full of raw
# TeX looks exactly like an artifact full of MathML. The writing skill tells an
# agent to write LaTeX freely — true, and it needs a way to learn which of the
# two happened.


MATH_DOC = DEMO_DOC.replace(
    "## What the file says",
    "Coverage is $\\frac{NOI}{D}$ today.\n\n## What the file says",
)


@pytest.fixture
def no_math_extra(monkeypatch: pytest.MonkeyPatch) -> None:
    """The `[math]` extra uninstalled, without uninstalling it."""
    monkeypatch.setattr(render_math, "_LOOKED", True)
    monkeypatch.setattr(render_math, "_CONVERTER", None)


def test_math_without_the_extra_says_so_and_names_the_install(
    bound: pathlib.Path, no_math_extra: None
) -> None:
    bound.write_text(MATH_DOC, encoding="utf-8")
    result = runner.invoke(app, ["render", str(bound)])
    assert result.exit_code == 0, result.output
    assert "1 formula(s) rendered verbatim" in result.output
    assert "pip install 'backdraft[math]'" in result.output
    assert "no citation is affected" in result.output


def test_the_note_is_silent_when_the_extra_is_installed(bound: pathlib.Path) -> None:
    pytest.importorskip("latex2mathml", reason="[math] extra not installed")
    bound.write_text(MATH_DOC, encoding="utf-8")
    result = runner.invoke(app, ["render", str(bound)])
    assert result.exit_code == 0, result.output
    assert "formula(s) rendered verbatim" not in result.output


def test_a_document_with_no_math_never_mentions_math(
    bound: pathlib.Path, no_math_extra: None
) -> None:
    """Byte-identical to what render printed before the note existed."""
    result = runner.invoke(app, ["render", str(bound)])
    assert result.exit_code == 0, result.output
    assert result.output == f"{bound.with_name('memo.backdraft.html')}\n"


def test_the_note_belongs_to_the_artifact_not_the_projections(
    bound: pathlib.Path, no_math_extra: None
) -> None:
    """`--to footnotes` never typesets math, so it has nothing to apologize for."""
    bound.write_text(MATH_DOC, encoding="utf-8")
    result = runner.invoke(app, ["render", str(bound), "--to", "footnotes"])
    assert result.exit_code == 0, result.output
    assert "formula(s) rendered verbatim" not in result.output
