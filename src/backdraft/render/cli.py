"""`backdraft render` — the artifact, the markdown projection, or the sidecar.

Render's inputs are an authored document and the sidecar bind wrote beside it.
The registry is never opened here: an artifact must be reproducible from the two
files a reader was handed, on a machine that has never seen the sources.

`verify` lives here too: it is the reader half of the same format, and this
module already holds the door onto it (`render.sidecar`). It is the one command
in this file that may open the registry — and it finds it from *cwd*, never from
the artifact's own directory, because an artifact is a file people forward and
where it landed says nothing about which registry produced it. `--against` is
the recipient saying which one instead: a link the caller asserts, never one
the tool infers.

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

import json
import shlex
import sys
from dataclasses import dataclass
from enum import StrEnum
from itertools import zip_longest
from pathlib import Path
from typing import Annotated, Any, NamedTuple

import typer

from ..cli_context import (
    EXIT_UNRESOLVED,
    RECEIPT,
    RECOUNT,
    UsageError,
    as_typed,
    authored_text,
    claim_words,
    find_root,
    guard,
    named_root,
    next_moves,
)
from ..kernel.artifact import (
    ARTIFACT_SUFFIX,
    DEFAULT_SESSION,
    DEFAULT_SESSION_MEANING,
    FOOTNOTES_SUFFIX,
    SIDECAR_SUFFIX,
    VERIFY_FORMAT,
)
from ..kernel.claims import parse_claims
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
    """Render the artifact from `doc` and the record `bind` wrote for it.

    Reads two files and never the registry: the authored document, and its
    record — under `.backdraft/records/` in a project, which is where `bind`
    writes it, or beside the document as `<doc>.backdraft.json`, the form a
    reader is handed (see spec/artifact.md). So an artifact renders on a
    machine that has never seen the sources. The output lands beside the
    document — `<doc>.backdraft.html` for the artifact — unless `-o` names
    another path; `--to json` goes to stdout.

    Refuses a document edited since its bind: every cited claim must stand in
    the document with the text, tokens and offsets the record holds, or nothing
    is written and the fix is to bind again. Prose edits that move no claim
    render as before.

    Exit codes: 0 on success, 1 when the document or its record is missing or
    unreadable, the document was edited since bind, or the theme cannot be
    used. An unresolved citation is not a failure here: the artifact reports
    it, which is the point, and exit 2 belongs to `bind` and `verify`.
    """
    with guard():
        source = authored_text(doc)
        found = sidecar.find_sidecar(doc)
        if found is None:
            raise UsageError(_no_record(doc))
        try:
            report = sidecar.read(found)
        except (ValueError, KeyError, OSError) as error:
            raise UsageError(f"unreadable sidecar {found.name}: {error}") from error
        if (stale := _edited_since_bind(doc, source, report)) is not None:
            raise UsageError(stale)
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
    f"{math_module.INSTALL} and render again."
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


def _edited_since_bind(doc: Path, source: str, report: BindReport) -> str | None:
    """Why the record no longer describes `source`, or None when it still does.

    The artifact's claim is that every citation in it was checked, so a claim
    added or changed after `bind` must not ride out in it unjudged — and render
    places each claim by offset, so one that merely moved would misplace every
    highlight after it. A claim is compared on what bind recorded of it: its
    words, its tokens in order, and its span. The cited claims are the ones
    `parse_claims` finds again; backfill's uncited sentences carry no token, so
    each is held to its span still holding its words.

    No hash of the draft is stored for this: the record already carries the
    claims, so the check needs no format change, and an edit outside every claim
    that moves no offset — a typo fixed after the last claim — still renders.
    """
    cited = [claim for claim in report.claims if claim.citations]
    parsed = parse_claims(source)
    differing: list[tuple[Claim | None, Claim | None]] = [
        (recorded, current)
        for recorded, current in zip_longest(cited, parsed)
        if recorded is None or current is None or _signature(recorded) != _signature(current)
    ]
    differing.extend(
        (claim, None)
        for claim in report.claims
        if not claim.citations and source[claim.start : claim.end] != claim.text
    )
    if not differing:
        return None
    recorded, current = min(
        differing, key=lambda pair: min(c.start for c in pair if c is not None)
    )
    if current is None:
        first = (
            f'the claim "{claim_words(recorded.text)}" at offset {recorded.start} '
            "is no longer in the draft"
        )
    elif recorded is None:
        first = (
            f'the claim "{claim_words(current.text)}" at offset {current.start} '
            "is not in the record"
        )
    elif _signature(recorded)[:2] == _signature(current)[:2]:
        first = (
            f'the claim "{claim_words(current.text)}" moved from offset '
            f"{recorded.start} to {current.start}"
        )
    else:
        first = (
            f'the claim at offset {current.start}, "{claim_words(current.text)}", '
            "is not the one bind recorded"
        )
    count = len(differing)
    return (
        f"{doc.name} was edited since it was bound at {report.bound_at}: {count} "
        f"claim{'' if count == 1 else 's'} differ{'s' if count == 1 else ''} from the "
        f"record, first {first}. Nothing was rendered; run "
        f"`backdraft bind {shlex.quote(str(doc))}`, then render again."
    )


def _signature(claim: Claim) -> tuple[str, tuple[str, ...], int, int]:
    """What a claim is, for `_edited_since_bind`: words, tokens in order, span."""
    return (
        claim.text,
        tuple(citation.token for citation in claim.citations),
        claim.start,
        claim.end,
    )


def _no_record(doc: Path) -> str:
    """Why `render` has nothing to render, naming every place it looked.

    Naming only the beside-the-document form sent a caller in a project to look
    for a file `bind` never writes there: a rooted bind writes under
    `.backdraft/records/`, so that is named first when there is a project.
    """
    beside, _, *records = sidecar.sidecar_candidates(doc)
    places = [f"{as_typed(path)}, where bind writes in this project" for path in records]
    places.append(f"{beside.name} beside it")
    return (
        f"no record for {doc.name}: looked for {', or '.join(places)}. "
        f"Run `backdraft bind {shlex.quote(str(doc))}` first."
    )


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
    against: Annotated[
        Path | None,
        typer.Option(
            "--against",
            metavar="PROJECT",
            help=(
                "Check against the sources in this project's registry instead of one "
                "found from the current directory: the project root or its .backdraft "
                "directory. You are saying the artifact came from there; verify never "
                "infers it."
            ),
        ),
    ] = None,
    as_json: Annotated[
        bool,
        typer.Option(
            "--json",
            help=(
                "Print the check as one JSON object instead of the report: both tiers, "
                "and every finding with its kind (receipt, recount, source). Same exit code."
            ),
        ),
    ] = False,
) -> None:
    """Check an artifact against itself, and against the sources when they are here.

    Two tiers, and the output names which ran. The record against itself needs
    nothing but the file: every `snippet_sha256` is recomputed from the snippet
    the file carries, every token is checked against the anchor it names, and
    `summary` is recounted from `claims`. That is `spec/artifact.md` § Checking
    an artifact, and it catches an edited artifact. Against the sources runs
    only when a `.backdraft/` is found from the current directory — not from the
    artifact's, because an artifact is a file people forward and the folder it
    landed in says nothing about which registry it came from — or when
    `--against` names the project it came from, which is the one way to check a
    file you were sent against a registry you have. It re-resolves every token
    and reports the statuses as `bind` would, and names the registry it used.
    That includes `not_shown`: a front-walk record names the ledger session it
    was bound under, and a citation that session was never shown is reported as
    such, with the session named.

    Read-only. It opens no session and mints nothing, which is what separates it
    from `backdraft show`: showing is minting, and an audit must not make its
    subject citable. Reading the ledger the record names is not opening one — a
    session this registry does not have is reported absent, never created.

    Exit codes: 0 everything checked passed · 1 the file is missing, is not an
    artifact, or `--against` names no registry · 2 something did not verify, so
    a hook can gate on it. A record that faithfully carries an `unresolved`
    citation still exits 0 on tier one — a kept failure is the record working,
    not the record broken.

    `--json` prints the same check as one object instead of the report. Its
    `findings` carry a `kind` — `receipt` means the file was edited, `source`
    that the sources or the ledger do not stand behind a citation today — so
    the causes of an exit 2 are told apart without reading a sentence. The
    report says the same in words: it closes with one `next:` line per kind of
    finding, naming the command that addresses it.
    """
    with guard():
        if not artifact.is_file():
            raise UsageError(f"no such file: {artifact}")
        try:
            payload = sidecar.read_payload(artifact)
            report = sidecar.to_report(payload)
        except (ValueError, KeyError, TypeError, OSError, UnicodeDecodeError) as error:
            raise UsageError(_not_an_artifact(artifact, error)) from error
        # NOTE: the flag bypasses discovery rather than joining it, so it also
        # outranks `BACKDRAFT_HOME`: a name typed on this command is more
        # specific than one exported for the whole shell.
        root = named_root(against) if against is not None else find_root()

    checked = _check(payload, report, root)
    if as_json:
        document = _verification(artifact, checked)
        sys.stdout.write(json.dumps(document, indent=2, ensure_ascii=False) + "\n")
    else:
        _print_verification(artifact, checked)
    if not checked.clean:
        raise typer.Exit(EXIT_UNRESOLVED)


class _Ledger(StrEnum):
    """What the source tier could ask of the ledger session the record names.

    `--json`'s `sources.ledger`. Only `read` re-checks `not_shown`; each of the
    others says why it was not, so a `resolved` from this tier is never mistaken
    for one the ledger stands behind.
    """

    READ = "read"
    """The record's session is in this registry, and every citation resolving today was asked of it."""
    ABSENT = "absent"
    """The record names a session this registry does not have — it was bound against another registry."""
    NO_SESSION = "no_session"
    """The run that bound it had no session, so there was nothing to judge `not_shown` against."""
    BACKFILL = "backfill"
    """Backfill judges nothing against a ledger, so neither does its re-check."""


class _Problem(NamedTuple):
    """A receipt that did not hold: which check failed, and the sentence saying how."""

    check: str
    detail: str


@dataclass(frozen=True)
class _Checked:
    """One verify run's findings, before anything is said about them.

    The report and `--json` are two ways of saying this, and neither decides
    anything: the exit code reads `clean`, and `clean` reads the findings. The
    finding is the boolean; the sentence is how it is said. Keeping the two apart
    matters because a check that re-read its own prose to decide would change
    meaning the next time someone improves the wording — and so would a caller
    that scraped it, which is what `--json` exists to stop.
    """

    payload: dict[str, Any]
    report: BindReport
    receipts: int
    """Citations carrying an anchor, each of which was checked."""
    broken: list[tuple[Claim, Citation, _Problem]]
    recounts: bool
    """The file's `summary` equals a recount of its `claims`."""
    root: Path | None
    """The registry tier two ran against — discovered or named — or None when it did not run."""
    against: list[tuple[Claim, Citation, Citation]]
    """Every citation re-resolved: the claim, what the record says, what the registry says."""
    ledger: _Ledger | None
    """What the ledger could say about the record's session, or None when tier two did not run."""

    @property
    def moved(self) -> list[tuple[Claim, Citation, Citation]]:
        """Tier two's findings: every citation the sources and the ledger do not stand behind today."""
        return [row for row in self.against if row[2].status is not CitationStatus.RESOLVED]

    @property
    def clean(self) -> bool:
        return not self.broken and self.recounts and not self.moved


def _check(payload: dict[str, Any], report: BindReport, root: Path | None) -> _Checked:
    """Both tiers of spec/artifact.md § Checking an artifact, run once."""
    receipts = [
        (claim, citation)
        for claim in report.claims
        for citation in claim.citations
        if citation.anchor is not None
    ]
    against, ledger = ([], None) if root is None else _against_sources(report, root)
    return _Checked(
        payload=payload,
        report=report,
        receipts=len(receipts),
        broken=[
            (claim, citation, problem)
            for claim, citation in receipts
            if (problem := _receipt_problem(citation)) is not None
        ],
        recounts=payload.get("summary") == report.summary,
        root=root,
        against=against,
        ledger=ledger,
    )


def _print_verification(artifact: Path, checked: _Checked) -> None:
    """The human report: the two tiers' counts, then every finding as a line item."""
    summary = checked.report.summary
    recount = (
        "the summary recount agrees"
        if checked.recounts
        else "the summary does NOT agree with a recount of claims — trust claims"
    )
    typer.echo(f"checked {artifact} [{checked.payload['$format']}]")
    typer.echo(f"  receipts: {checked.receipts - len(checked.broken)} of {checked.receipts} hold")
    typer.echo(
        f"  record: {summary['claims']} claim(s), {summary['citations']} citation(s); "
        f"{recount}"
    )
    typer.echo(f"  recorded: {_counts(summary['by_status'])}{_unmatched(checked.report)}")
    if _in_default_session(checked.report):
        typer.echo(f"  session: {DEFAULT_SESSION} — {DEFAULT_SESSION_MEANING}")
    if checked.root is None:
        typer.echo("  sources: no .backdraft/ found from here — not re-checked")
    else:
        typer.echo(
            f"  sources: re-resolved against {checked.root} — "
            f"{_counts(_tally(fresh for _, _, fresh in checked.against))}"
        )
        ledger_line = _ledger_line(checked)
        if ledger_line is not None:
            typer.echo(f"  ledger: {ledger_line}")

    for claim, citation, problem in checked.broken:
        typer.echo(f"  ! receipt: {citation.token} — {problem.detail} — {_where(claim)}")
    for claim, recorded, fresh in checked.moved:
        # The reason first, where the registry has one — a token whose source was
        # withdrawn and one whose source was never there are both `unresolved`
        # against the sources, and only the reason tells a reader which happened.
        # Same position bind's line items give it, so the two read alike.
        reason = f" — {fresh.error}" if fresh.error else ""
        if fresh.status is CitationStatus.NOT_SHOWN:
            reason = f" — session {checked.report.session_id} was never shown it"
        moved = (
            "" if fresh.status is recorded.status
            else f" — the record says {recorded.status}"
        )
        typer.echo(f"  ! {fresh.status}: {fresh.token}{reason}{moved} — {_where(claim)}")

    if checked.root is None:
        typer.echo(
            "[Re-check against the sources: run this inside the project it was bound in.]"
        )
    for line in _next_moves(checked):
        typer.echo(line)


def _next_moves(checked: _Checked) -> list[str]:
    """The closing `next:` lines: one per kind of finding, bind's table.

    `receipt` and `recount` come first because they mean something categorically
    different — the file was edited, so what the sources say about it is moot
    until it is rebuilt. The source tier's statuses get the moves `bind` prints
    for them, against the document and session the record names, since the fix
    is a re-bind of that document. A record that only *carries* a failure is not
    a finding here (it exits 0), so it gets no line either.
    """
    present: set[str] = {str(fresh.status) for _, _, fresh in checked.moved}
    if checked.broken:
        present.add(RECEIPT)
    if not checked.recounts:
        present.add(RECOUNT)
    report = checked.report
    session = report.session_id if report.mode == "frontwalk" else None
    return next_moves(present, doc=report.doc_path, session=session)


def _ledger_line(checked: _Checked) -> str | None:
    """The `ledger:` line, or None where there is nothing the sources line has not said.

    Silent when the ledger was read and agreed with every citation, so a record
    the ledger stands behind reads exactly as it did before verify asked — and
    silent for backfill, which never judged `not_shown` to begin with. Every
    other outcome is said, because each one is a `resolved` that would otherwise
    read as stronger than it is.
    """
    session = checked.report.session_id
    if checked.ledger is _Ledger.READ:
        unseen = sum(
            1 for _, _, fresh in checked.against if fresh.status is CitationStatus.NOT_SHOWN
        )
        if not unseen:
            return None
        return f"read session {session} — {unseen} citation(s) it was never shown"
    if checked.ledger is _Ledger.ABSENT:
        return (
            f"no session {session} in this registry — not_shown not re-checked; "
            "it was bound against another registry"
        )
    if checked.ledger is _Ledger.NO_SESSION:
        return "the run that bound this had no session — not_shown not re-checked"
    return None


def _in_default_session(report: BindReport) -> bool:
    """A front-walk record whose statuses were judged against the shared ledger.

    Read off the record alone, so the first tier says it with no registry in
    reach: the recipient holding only the file is exactly who cannot otherwise
    learn that `default` weakens every `not_shown` and `resolved` in it. The
    sentence is the legend's (`DEFAULT_SESSION_MEANING`), not a second wording.
    Backfill judges nothing against a ledger, so it says nothing.
    """
    return report.mode == "frontwalk" and report.session_id == DEFAULT_SESSION


def _verification(artifact: Path, checked: _Checked) -> dict[str, Any]:
    """`verify --json`'s object — spec/artifact.md § Checking an artifact is its format.

    The same facts the report prints, keyed rather than worded. `findings` is
    empty exactly when the run exits 0, and is ordered as the checks run:
    receipts, the recount, then the sources. `kind` is the field a caller
    branches on, because the two causes of an exit 2 want opposite responses — a
    `receipt` finding means the file changed after it was written, a `source`
    finding that the file is intact and the sources do not stand behind the
    citation today — and `detail` and `error` stay sentences for a person, free
    to be reworded.

    Counts are sorted by status so the object is a pure function of the run; the
    claim is carried whole, as `claims[]` carries it, rather than cut to the
    report's line width, since a caller that parses has no line to fit.
    """
    report = checked.report
    summary = report.summary
    ran = checked.root is not None
    findings: list[dict[str, Any]] = [
        {
            "kind": "receipt",
            "check": problem.check,
            "token": citation.token,
            "detail": problem.detail,
            "claim": _claim_at(claim),
        }
        for claim, citation, problem in checked.broken
    ]
    if not checked.recounts:
        findings.append(
            {
                "kind": "recount",
                "recorded": checked.payload.get("summary"),
                "recounted": summary,
            }
        )
    findings.extend(
        {
            "kind": "source",
            "token": fresh.token,
            "status": str(fresh.status),
            "recorded": str(recorded.status),
            "error": fresh.error,
            "claim": _claim_at(claim),
        }
        for claim, recorded, fresh in checked.moved
    )
    return {
        "$format": VERIFY_FORMAT,
        "artifact": str(artifact),
        "record": {
            "ran": True,
            "receipts": checked.receipts,
            "receipts_held": checked.receipts - len(checked.broken),
            "summary_agrees": checked.recounts,
            "claims": summary["claims"],
            "citations": summary["citations"],
            "by_status": dict(sorted(summary["by_status"].items())),
            "unmatched": _unmatched_count(report),
        },
        "sources": {
            "ran": ran,
            "registry": str(checked.root) if ran else None,
            "by_status": (
                dict(sorted(_tally(fresh for _, _, fresh in checked.against).items()))
                if ran
                else None
            ),
            "ledger": None if checked.ledger is None else str(checked.ledger),
        },
        "findings": findings,
    }


def _claim_at(claim: Claim) -> dict[str, Any]:
    """A finding's claim, in the record's own keys: its words and its span."""
    return {"text": claim.text, "start": claim.start, "end": claim.end}


def _receipt_problem(citation: Citation) -> _Problem | None:
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

    Each problem names its check as well as saying it — `snippet_sha256`,
    `token_parses`, `token_hash`, `token_slug`, `token_locator`, the values
    spec/artifact.md fixes for `--json` — so a caller can tell a rehashed
    snippet from a re-pointed token without matching on the sentence.
    """
    anchor = citation.anchor
    assert anchor is not None  # callers filter; kept so the type is not a lie
    digest = snippet_hash(anchor.receipt.snippet)
    if digest != anchor.receipt.snippet_sha256:
        return _Problem(
            "snippet_sha256",
            f"the snippet hashes to {digest[:16]}, "
            f"the record says {anchor.receipt.snippet_sha256[:16]}",
        )
    try:
        token = parse_token(citation.token)
    except TokenError as error:
        return _Problem("token_parses", f"the token does not parse: {error}")
    cited = digest if citation.drifted_from is None else snippet_hash(citation.drifted_from)
    if not cited.startswith(token.hash):
        named = "the snippet" if citation.drifted_from is None else "drifted_from"
        return _Problem(
            "token_hash",
            f"the token's hash {token.hash} is not a prefix of {named}'s {cited[:16]}",
        )
    if token.slug != anchor.slug:
        return _Problem(
            "token_slug", f"the token names {token.slug}, the anchor is in {anchor.slug}"
        )
    located = format_locator(anchor.locator)
    if format_locator(token.locator) != located:
        return _Problem(
            "token_locator",
            f"the token points at {format_locator(token.locator)}, the anchor at {located}",
        )
    return None


def _against_sources(
    report: BindReport, root: Path
) -> tuple[list[tuple[Claim, Citation, Citation]], _Ledger]:
    """Every citation re-resolved — the claim, what the record says, what the registry
    says — and what the ledger could be asked.

    `registry.citation_for` is the walk `bind` runs, `not_shown` included, so a
    status printed here is the status a re-bind would print. The session it is
    judged against is the one the record names, never one verify picks, and it
    is looked up with `has_session` rather than `ensure_session`: reading a
    ledger is not opening one, and a session this registry never had is a fact
    about where the record came from. Without that session `not_shown` cannot
    appear, and `_Ledger` says which reason applies.
    """
    registry = Registry.open(root)
    try:
        ledger = _ledger(report, registry)
        session_id = report.session_id if ledger is _Ledger.READ else None
        rows = [
            (claim, citation, citation_for(registry, citation.token, session_id=session_id))
            for claim in report.claims
            for citation in claim.citations
        ]
        return rows, ledger
    finally:
        registry.close()


def _ledger(report: BindReport, registry: Registry) -> _Ledger:
    """Which ledger question this record lets the source tier ask, in bind's own terms."""
    if report.mode != "frontwalk":
        return _Ledger.BACKFILL
    if report.session_id is None:
        return _Ledger.NO_SESSION
    if not registry.has_session(report.session_id):
        return _Ledger.ABSENT
    return _Ledger.READ


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
    count = _unmatched_count(report)
    return f"; {count} unmatched claim(s)" if count else ""


def _unmatched_count(report: BindReport) -> int:
    return sum(1 for claim in report.claims if claim.unmatched)


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
