"""`backdraft render` — the artifact, the markdown projection, or the sidecar.

Render's inputs are an authored document and the sidecar bind wrote beside it.
The registry is never opened here: an artifact must be reproducible from the two
files a reader was handed, on a machine that has never seen the sources.

`verify` lives here too: it is the reader half of the same format, and this
module already holds the door onto it (`render.sidecar`). It is the one command
in this file that may open the registry — and it opens it from *cwd*, never from
the artifact's own directory, because an artifact is a file people forward and
where it landed says nothing about which registry produced it.

Mounted by the top-level CLI as `app`, per SPEC Addendum B:

    from backdraft.render import cli as render_cli
    app.registered_commands.extend(render_cli.app.registered_commands)
    app.registered_groups.extend(render_cli.app.registered_groups)

which puts `render <doc.md>`, `verify <artifact>` and the `theme` group at the
top level. Both lines are load-bearing: commands and groups are separate
registries on a typer app, so mounting only the first would silently drop
`theme list` / `theme show`.

NOTE: this module's `app` is not meant to be invoked on its own. The command
names only exist once it is mounted next to the top level's others — and typer
collapses a single-command app into a bare command, which is what `app` was
before `verify` and the `theme` group joined `render` here.
"""

from __future__ import annotations

import sys
from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer

from ..cli_context import (
    EXIT_UNRESOLVED,
    UsageError,
    claim_words,
    find_root,
    guard,
)
from ..kernel.artifact import (
    ARTIFACT_SUFFIX,
    FOOTNOTES_SUFFIX,
    SIDECAR_SUFFIX,
)
from ..kernel.errors import TokenError
from ..kernel.hashing import snippet_hash
from ..kernel.model import BindReport, Citation, CitationStatus, Claim
from ..kernel.tokens import format_locator, parse as parse_token
from ..registry import Registry, citation_for
from . import footnotes, html, math as math_module, sidecar, theme as theming

__all__ = ["app", "theme_app", "Target", "verify"]

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
    if to is Target.HTML and (note := _unrendered_math_note(source)) is not None:
        typer.echo(note)


VERBATIM_MATH_NOTE = (
    "note: {count} formula(s) rendered verbatim rather than as math — the "
    "`[math]` extra is not installed. Nothing was corrupted and no citation is "
    "affected; the artifact just shows the LaTeX as written. Install it with "
    "`pip install 'backdraft[math]'` (or `uv tool install 'backdraft[math]'`) "
    "and render again."
)
"""Said at exit 0, in the shape `ingest`'s poppler note uses: what happened,
what it did not cost, and the one command that fixes it.

Not printed when the artifact goes to stdout (`-o -`): the note would land in
the middle of the file it is about.
"""


def _unrendered_math_note(source: str) -> str | None:
    """The advisory for a document whose math could not become math, or None.

    The gap this closes is an agent's: the writing skill tells it to write LaTeX
    freely because a formula is never corrupted either way, which is true — and
    leaves it no way to find out which way happened. `render` printed the target
    path and nothing else, so an artifact full of raw TeX looked exactly like an
    artifact full of MathML.

    Only asked when the converter is missing, which is why the second scan it
    costs is affordable: the common render does not run it, and an installed
    extra prints nothing new. `math.protect` is the same call the renderer makes,
    so what counts as a formula is decided in one place — the count can differ by
    one from the render's own only where a claim span splits a formula in half,
    and being off by one in a sentence of advice is not a cost worth a second
    owner of the rule.
    """
    if math_module.available():
        return None
    found: list[math_module.Math] = []
    math_module.protect(source, found)
    return VERBATIM_MATH_NOTE.format(count=len(found)) if found else None


# ---- verify -----------------------------------------------------------------
#
# Two tiers, and the report always says which one ran. Tier one is the check a
# recipient can make with the file alone — the record against itself — and it is
# the one that matters, because it is the one that travels. Tier two only exists
# where the sources do, and it answers a different question: not "is this record
# intact" but "do the sources still say this today".


@app.command()
def verify(
    artifact: Annotated[
        Path,
        typer.Argument(help="A .backdraft.html artifact or a .backdraft.json sidecar."),
    ],
) -> None:
    """Check an artifact against itself, and against the sources when they are here.

    Two tiers, and the output names which ran. The record against itself needs
    nothing but the file: every `snippet_sha256` is recomputed from the snippet
    the file carries, every token is checked against the anchor it names, and
    `summary` is recounted from `claims`. That is `spec/artifact.md` § Checking
    an artifact, and it catches an edited artifact. Against the sources runs
    only when a `.backdraft/` is found from the current directory — not from the
    artifact's, because an artifact is a file people forward and the folder it
    landed in says nothing about which registry it came from. It re-resolves
    every token and reports the statuses as `bind` would.

    Read-only. It opens no session and mints nothing, which is what separates it
    from `backdraft show`: showing is minting, and an audit must not make its
    subject citable.

    Exit codes: 0 everything checked passed · 1 the file is missing, or is not
    an artifact · 2 something did not verify, so a hook can gate on it. A record
    that faithfully carries an `unresolved` citation still exits 0 on tier one —
    a kept failure is the record working, not the record broken.
    """
    with guard():
        if not artifact.is_file():
            raise UsageError(f"no such file: {artifact}")
        try:
            payload = sidecar.read_payload(artifact)
            report = sidecar.to_report(payload)
        except (ValueError, KeyError, TypeError, OSError, UnicodeDecodeError) as error:
            raise UsageError(_not_an_artifact(artifact, error)) from error

    receipts = [
        (claim, citation)
        for claim in report.claims
        for citation in claim.citations
        if citation.anchor is not None
    ]
    broken = [
        (claim, citation, reason)
        for claim, citation in receipts
        if (reason := _receipt_problem(citation)) is not None
    ]
    summary = report.summary
    # The finding is the boolean; the sentence is how it is said. Keeping the
    # two apart matters because the exit code below is one of the checks, and a
    # check that re-reads its own prose to decide would change meaning the next
    # time someone improves the wording.
    recounts = payload.get("summary") == summary
    recount = (
        "the summary recount agrees"
        if recounts
        else "the summary does NOT agree with a recount of claims — trust claims"
    )

    typer.echo(f"checked {artifact} [{payload['$format']}]")
    typer.echo(f"  receipts: {len(receipts) - len(broken)} of {len(receipts)} hold")
    typer.echo(
        f"  record: {summary['claims']} claim(s), {summary['citations']} citation(s); "
        f"{recount}"
    )
    typer.echo(f"  recorded: {_counts(summary['by_status'])}{_unmatched(report)}")

    root = find_root()
    against: list[tuple[Claim, Citation, Citation]] = []
    if root is None:
        typer.echo("  sources: no .backdraft/ found from here — not re-checked")
    else:
        against = _against_sources(report, root)
        typer.echo(
            f"  sources: re-resolved against {root} — "
            f"{_counts(_tally(fresh for _, _, fresh in against))}"
        )

    for claim, citation, reason in broken:
        typer.echo(f"  ! receipt: {citation.token} — {reason} — {_where(claim)}")
    for claim, recorded, fresh in against:
        if fresh.status is CitationStatus.RESOLVED:
            continue
        moved = (
            "" if fresh.status is recorded.status
            else f" — the record says {recorded.status}"
        )
        typer.echo(f"  ! {fresh.status}: {fresh.token}{moved} — {_where(claim)}")

    if root is None:
        typer.echo(
            "[Re-check against the sources: run this inside the project it was bound in.]"
        )
    if broken or not recounts or any(
        fresh.status is not CitationStatus.RESOLVED for _, _, fresh in against
    ):
        raise typer.Exit(EXIT_UNRESOLVED)


def _receipt_problem(citation: Citation) -> str | None:
    """Why this citation's receipt does not hold up, or None when it does.

    `spec/artifact.md` § Checking an artifact, steps 2 and 3, in order: the
    snippet must hash to the sha256 recorded beside it, the token's `hash`
    segment must be a prefix of the hash of the snippet that token was *minted
    from*, and the token's `slug` and `locator` must be the anchor's. Ordered
    because a snippet that does not hash to its own sha256 makes every
    comparison downstream meaningless — reporting one tampered snippet three
    times would bury which byte moved.

    The middle check is the one with a subtlety, and getting it wrong would flag
    every drifted artifact as forged. A `drifted` citation's token names what
    the author cited — `drifted_from` — while `anchor` carries what stands at
    that locator *now*, so the two hashes are supposed to differ. `slug` and
    `locator` are still the anchor's on both sides: drift is defined as the same
    locator holding different text.
    """
    anchor = citation.anchor
    assert anchor is not None  # callers filter; kept so the type is not a lie
    digest = snippet_hash(anchor.receipt.snippet)
    if digest != anchor.receipt.snippet_sha256:
        return (
            f"the snippet hashes to {digest[:16]}, "
            f"the record says {anchor.receipt.snippet_sha256[:16]}"
        )
    try:
        token = parse_token(citation.token)
    except TokenError as error:
        return f"the token does not parse: {error}"
    cited = digest if citation.drifted_from is None else snippet_hash(citation.drifted_from)
    if not cited.startswith(token.hash):
        named = "the snippet" if citation.drifted_from is None else "drifted_from"
        return f"the token's hash {token.hash} is not a prefix of {named}'s {cited[:16]}"
    if token.slug != anchor.slug:
        return f"the token names {token.slug}, the anchor is in {anchor.slug}"
    located = format_locator(anchor.locator)
    if format_locator(token.locator) != located:
        return f"the token points at {format_locator(token.locator)}, the anchor at {located}"
    return None


def _against_sources(
    report: BindReport, root: Path
) -> list[tuple[Claim, Citation, Citation]]:
    """Every citation re-resolved: the claim, what the record says, what the registry says.

    `registry.citation_for` is the walk `bind` runs, so a status printed here is
    the status a re-bind would print — with one gap, named rather than papered
    over: `not_shown` cannot appear, because it is a fact about a ledger session
    and verify opens none. A citation the record calls `not_shown` therefore
    comes back `resolved` here, which is not a contradiction; it is the other
    question being answered.
    """
    registry = Registry.open(root)
    try:
        return [
            (claim, citation, citation_for(registry, citation.token))
            for claim in report.claims
            for citation in claim.citations
        ]
    finally:
        registry.close()


def _not_an_artifact(artifact: Path, error: Exception) -> str:
    """Why this file could not be read as a record, and where the record may be.

    A person or an agent reaching for `verify` usually has the document in hand,
    not the record, so the common miss is `backdraft verify memo.md`. Naming the
    file that *is* the record turns the refusal into the next command.
    """
    message = f"{artifact.name} is not a backdraft artifact: {error}"
    beside = sidecar.find_sidecar(artifact)
    rendered = artifact.with_name(artifact.stem + ARTIFACT_SUFFIX)
    if beside is not None:
        return f"{message}. Its record is {beside}"
    if rendered.is_file():
        return f"{message}. Its artifact is {rendered}"
    return message


def _where(claim: Claim) -> str:
    """A line item's tail: the claim's own words and where they sit.

    `bind`'s shape exactly (`cli_context.claim_words`) — the two commands report
    on the same claims, and a reader who has read one report should not have to
    learn a second layout.
    """
    return f"{claim_words(claim.text)} @{claim.start}"


def _counts(by_status: dict[str, int]) -> str:
    """`{status: n}` as one line: `resolved 17, unresolved 1`."""
    pairs = sorted(by_status.items())
    return ", ".join(f"{status} {count}" for status, count in pairs) or "none"


def _tally(citations) -> dict[str, int]:  # noqa: ANN001 - an iterable of Citation
    counts: dict[str, int] = {}
    for citation in citations:
        counts[str(citation.status)] = counts.get(str(citation.status), 0) + 1
    return counts


def _unmatched(report: BindReport) -> str:
    """The backfill claims the record carries with no anchor at all.

    Counted rather than listed, and never a line item: an unmatched claim is
    something the record honestly says was never anchored, not something that
    failed a check here.
    """
    count = sum(1 for claim in report.claims if claim.unmatched)
    return f"; {count} unmatched claim(s)" if count else ""


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
