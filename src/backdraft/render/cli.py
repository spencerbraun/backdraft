"""`backdraft render` — the artifact, the markdown projection, or the sidecar.

Render's inputs are an authored document and the sidecar bind wrote beside it.
The registry is never opened here: an artifact must be reproducible from the two
files a reader was handed, on a machine that has never seen the sources.

Mounted by the top-level CLI as `app`, per SPEC Addendum B:

    from backdraft.render import cli as render_cli
    app.registered_commands.extend(render_cli.app.registered_commands)
    app.registered_groups.extend(render_cli.app.registered_groups)

which puts `render <doc.md>` and the `theme` group at the top level. Both lines
are load-bearing: commands and groups are separate registries on a typer app, so
mounting only the first would silently drop `theme list` / `theme show`.

NOTE: this module's `app` is not meant to be invoked on its own. The command
names only exist once it is mounted next to the top level's others — and typer
collapses a single-command app into a bare command, which is what `app` was
before the `theme` group joined `render` here.
"""

from __future__ import annotations

import sys
from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer

from ..cli_context import UsageError, find_root, guard
from ..kernel.artifact import (
    ARTIFACT_SUFFIX,
    FOOTNOTES_SUFFIX,
    SIDECAR_SUFFIX,
)
from . import footnotes, html, sidecar, theme as theming

__all__ = ["app", "theme_app", "Target"]

app = typer.Typer(help="Render a bound document as a self-contained artifact.")
theme_app = typer.Typer(help="Inspect the artifact's themes.")
app.add_typer(theme_app, name="theme")


class Target(StrEnum):
    """What to render. `html` is the artifact; the others are projections of it."""

    HTML = "html"
    FOOTNOTES = "footnotes"
    JSON = "json"


_SUFFIX = {
    Target.HTML: ARTIFACT_SUFFIX,
    Target.FOOTNOTES: FOOTNOTES_SUFFIX,
    Target.JSON: SIDECAR_SUFFIX,
}
"""The naming family is the format's, so it comes from `kernel/artifact.py`."""


@app.command()
def render(
    doc: Annotated[Path, typer.Argument(help="The authored markdown document.")],
    to: Annotated[Target, typer.Option("--to", help="Output form.")] = Target.HTML,
    out: Annotated[
        Path | None,
        typer.Option("-o", "--out", help="Output file; '-' writes to stdout."),
    ] = None,
    theme: Annotated[
        str | None,
        typer.Option(
            "--theme",
            metavar="NAME|FILE",
            help=(
                "Restyle the artifact: a bundled theme "
                f"({', '.join(theming.bundled_names())}) or a theme file. "
                "Without it, .backdraft/theme.toml then "
                "~/.config/backdraft/theme.toml decide."
            ),
        ),
    ] = None,
) -> None:
    """Render `doc` and its sidecar.

    The sidecar is found beside the document as `<doc>.backdraft.json` (see
    spec/artifact.md). Exit codes: 0 on success, 1 when the document or its
    sidecar is missing or unreadable, or the theme cannot be used.

    NOTE: the spec's exit code 2 belongs to `bind` — render reports unresolved
    citations in the artifact, which is the whole point, and does not fail on
    them.
    """
    with guard():
        if not doc.is_file():
            raise UsageError(f"no such document: {doc}")
        found = sidecar.find_sidecar(doc)
        if found is None:
            raise UsageError(
                f"no sidecar beside {doc.name}: expected {sidecar.sidecar_path(doc).name}. "
                "Run `backdraft bind` first."
            )
        try:
            report = sidecar.read(found)
        except (ValueError, KeyError, OSError) as error:
            raise UsageError(f"unreadable sidecar {found.name}: {error}") from error
        if theme is not None and to is not Target.HTML:
            raise UsageError(f"--theme styles the html artifact; --to {to.value} has no styling")
        # NOTE: resolved before anything is written, so a bad theme costs a
        # message and no file — never a half-styled artifact. Themes are the one
        # thing render reads out of `.backdraft/`, and it is a config file, not
        # the registry: the artifact stays reproducible from the two files a
        # reader was handed.
        chosen = (
            theming.resolve(theme, project_root=find_root(doc.parent))
            if to is Target.HTML
            else None
        )

    source = doc.read_text(encoding="utf-8")
    if to is Target.HTML:
        text = html.render(source, report, theme=chosen)
    elif to is Target.FOOTNOTES:
        text = footnotes.render(source, report)
    else:
        text = sidecar.dumps(report)

    # NOTE: `--to json` writes to stdout unless told otherwise — its default file
    # name is the sidecar it just read, and rewriting an input in place is not a
    # thing a render command should do quietly.
    if (out is not None and str(out) == "-") or (out is None and to is Target.JSON):
        sys.stdout.write(text)
        return
    target = out or doc.with_name(doc.stem + _SUFFIX[to])
    target.write_text(text, encoding="utf-8")
    typer.secho(str(target), fg=typer.colors.GREEN)


@theme_app.command("list")
def theme_list() -> None:
    """List the bundled themes and name the one a render here would use.

    The second half is the point: precedence has four rungs, so "which theme am
    I getting?" is a real question, and the answer is a file path or the
    built-in look — never a guess.
    """
    with guard():
        for name in theming.bundled_names():
            typer.echo(name)
        found = theming.active(find_root())
        typer.echo("")
        typer.echo(f"in effect here: {found if found is not None else 'the built-in look'}")
        # NOTE: the hint has to know whether a theme is already in effect —
        # telling someone to redirect `show default` at a path that is currently
        # theirs is telling them to overwrite it.
        typer.echo(
            f"[Read it: backdraft theme show {found}]"
            if found is not None
            else (
                "[Start your own: backdraft theme show default > "
                f"{theming.user_config_dir() / theming.FILENAME}]"
            )
        )


@theme_app.command("show")
def theme_show(
    name: Annotated[
        str,
        typer.Argument(metavar="NAME|FILE", help="A bundled theme, or a theme file."),
    ],
) -> None:
    """Print a theme file, validated, to stdout.

    Redirecting `show default` writes a fully commented starting point, since
    the bundled default states every key with what it paints. Pointing it at a
    file of your own checks that file: it prints only what `render` would
    accept, so it doubles as the way to test a theme without rendering anything.
    """
    with guard():
        path = theming.locate(name)
        theming.load(path)
        sys.stdout.write(path.read_text(encoding="utf-8"))
