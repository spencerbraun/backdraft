"""The CLI — the system's first substrate (SPEC.md § Addendum B).

This module owns the typer app, the `init` / `ingest` / `ls` / `export`
commands, and the mounts. The context every command shares — registry discovery,
session resolution, the exit codes and the error guard — lives in
`cli_context.py`, which the sub-apps import directly; the names are re-exported
here because `cli.find_root`, `cli.open_registry` and `cli.resolve_session` are
what the spec and the tests call the CLI's surface.

The gate, bind and render workstreams each ship an `app = typer.Typer()` that is
mounted here; each mount is guarded, so a partial checkout still runs the
commands it does have.

Exit codes: 0 clean, 1 usage or environment error, 2 `bind` completing with
non-resolved citations (so a hook can gate on it).
"""

from __future__ import annotations

import json
import sys
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Annotated, Iterable, Iterator

import typer

from . import fetch
from .cli_context import (
    DEFAULT_SESSION,
    EXIT_UNRESOLVED,
    EXIT_USAGE,
    HOME_ENV,
    SESSION_ENV,
    UsageError,
    fail,
    find_root,
    guard,
    open_registry,
    opened_registry,
    resolve_session,
)
from .extract import snapshots, vlm_ready
# The words a document is described in have one owner each, and `ingest`/`ls`
# describe the same documents the gate's list does: the noun for a collection of
# pages is `gate.unit`; how much text came out of a source, and whether that is
# too little to cite, are `gate.extracted_chars` and `gate.thin_mark`; and what
# to call the source itself is `kernel.model.source_name` — a pure function of a
# `Document`, so it lives with the type rather than in the first package that
# needed it. All are downward imports, which SPEC § Dependency rule spells "`cli`
# imports everything"; the mount guard below is about sub-*apps*, and `gate`
# itself does not need typer.
from .gate import WITHDRAWN_HINT, extracted_chars, thin_mark, unit
from .kernel.errors import BackdraftError
from .kernel.model import Document, Page, source_name
from .registry import (
    DIRECTORY,
    GENERATION,
    UNCHANGED,
    Ingested,
    Naming,
    Registry,
    withdrawn_reason,
)

__all__ = [
    "app",
    "main",
    # re-exported from cli_context: this module is the CLI's front door
    "DEFAULT_SESSION",
    "EXIT_UNRESOLVED",
    "EXIT_USAGE",
    "HOME_ENV",
    "SESSION_ENV",
    "find_root",
    "open_registry",
    "resolve_session",
]

app = typer.Typer(
    name="backdraft",
    help="Drop-in provenance for factual claims.",
    no_args_is_help=True,
    add_completion=False,
)


_ENV_TEMPLATE = """\
# Backdraft reads credentials only from here, BACKDRAFT_* variables, or --config.
# Ambient provider keys (OPENAI_API_KEY, ...) are never read.
BACKDRAFT_VLM_API_KEY=
BACKDRAFT_ENTAIL_API_KEY=
# Page-snapshot budget, display only (defaults shown):
# BACKDRAFT_SNAPSHOT_QUALITY=85
# BACKDRAFT_SNAPSHOT_MAX_HEIGHT=1056
"""

_THIN_CAUSE = {
    "pdf": (
        "a PDF with no text layer is a scan, and the text layer is all `pdf-text` "
        "reads. The vision extractor reads the page image itself: set "
        "BACKDRAFT_VLM_API_KEY in .backdraft/env and re-ingest."
    ),
    "html": (
        "a page rendered by JavaScript, or one that answered with a login wall "
        "instead of its content, carries almost no text in its markup — and the "
        "markup is what was snapshotted. Opening the page in a signed-in browser, "
        "saving it once it has rendered, and ingesting that file gets the real text."
    ),
    "pptx": (
        "a deck whose slides are charts and images carries almost no slide text, "
        "and slide text is all this extractor reads — the note above has the fix."
    ),
}
_THIN_CAUSE_DEFAULT = (
    "the source may simply be short, or may keep its content somewhere this "
    "extractor does not read."
)
"""For a media type with nothing specific to say. Deliberately not a guess: an
unmapped cause reported plainly beats a wrong suggestion confidently made."""


def _thin_cause(media_type: str) -> str:
    """Why a source came back thin, as far as its media type can say."""
    return _THIN_CAUSE.get(media_type, _THIN_CAUSE_DEFAULT)


def _outcome_note(document: Ingested) -> str:
    """What `ingest` did, appended to the source's line. A fresh document says nothing.

    Three outcomes printed one line: an agent re-ingesting after a fix could not
    tell a no-op from a new generation, and the two mean opposite things about
    the work already written against the source.

    `restored` rides beside them rather than among them, because it is a
    different question with a different answer — a withdrawn source re-ingested
    unchanged is both `unchanged` and back, and a line that could only say one
    would have to drop the other.
    """
    marks = []
    if document.outcome == UNCHANGED:
        marks.append("unchanged")
    elif document.outcome == GENERATION:
        marks.append("new generation")
    if document.restored:
        marks.append("restored")
    return "".join(f"  {mark}" for mark in marks)


# ---- commands ---------------------------------------------------------------


@app.command()
def init(
    directory: Annotated[
        Path | None,
        typer.Argument(help="Project root to initialize. Defaults to the current directory."),
    ] = None,
) -> None:
    """Create `.backdraft/` here and print the registry's status."""
    root = (directory or Path.cwd()).resolve()
    with guard():
        registry = Registry.open(root)
        try:
            documents = registry.documents()
        finally:
            registry.close()
    env_path = root / DIRECTORY / "env"
    if not env_path.exists():
        env_path.write_text(_ENV_TEMPLATE, encoding="utf-8")
    typer.echo(f"registry: {root / DIRECTORY}")
    typer.echo(f"documents: {len(documents)}")
    typer.echo(f"settings:  {env_path}  (credentials go here, deliberately)")
    typer.echo(
        "next: ingest sources, then have an agent write against them — "
        "the backdraft skill (skills/backdraft) is the writing contract."
    )


@app.command()
def ingest(
    sources: Annotated[
        list[str], typer.Argument(help="Files, or http(s) URLs, to ingest.")
    ],
    extractor: Annotated[
        str,
        typer.Option(
            "--extractor",
            help=(
                "auto, or one of: vlm, pdf-text, xlsx, xls, csv, docx, pptx, "
                "image, html, text."
            ),
        ),
    ] = "auto",
    slug: Annotated[
        str | None, typer.Option("--slug", help="Slug for a new document. One source only.")
    ] = None,
    config: Annotated[
        list[str] | None,
        typer.Option(
            "--config",
            help=(
                "Extractor config as `key=value`. Repeatable. Keys are declared "
                "per extractor; an unknown one fails and names the valid ones."
            ),
        ),
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run",
            help=(
                "Print the slug and media type each source would take, then stop. "
                "Fetches nothing, writes nothing, mints nothing."
            ),
        ),
    ] = False,
) -> None:
    """Snapshot files or web pages into the registry, minting their anchors.

    A source is a path or an http(s) URL. A URL is fetched once and snapshotted
    like any other source — the bytes at fetch time are the document's identity,
    and the URL travels with it as provenance, so re-ingesting a page that has
    since changed makes a new generation and the citations on the old one report
    `drifted`. JavaScript-rendered pages and pages behind a login are out of
    reach: what is fetched is what the server sends unauthenticated.

    A source that cannot be read does not end the run: the rest of the list is
    ingested anyway, every failure is named at the end with its reason, and the
    command exits 1. Each reason says what to do next — a directory says to name
    the files inside it or pass a glob, a missing path says to check the
    spelling, an unreadable file says to fix its permissions or ingest a copy —
    and a source with no bytes in it is a failure rather than a document with
    nothing to cite. Re-running the same list after a fix re-ingests nothing that
    already landed unchanged.

    Each source that lands prints its slug, its name, its media type, its page
    count and how much text came out — plus `unchanged` when re-running produced
    a no-op, or `new generation` when the bytes moved, which is when citations
    into the previous snapshot can start reporting `drifted`. A source almost no
    text came out of gets a note naming the likely cause, at exit 0: a thin
    snapshot is still a real one.

    `--dry-run` answers what each source would be *called* and stops there: the
    slug and the media type, nothing fetched, nothing written, no anchor minted.
    A slug is permanent once a token carries it, so this is how to see the
    default before `--slug` has to overrule it. A source already in the registry
    says so and names the slug it already has; a name another document has taken
    says that too, with the numbered slug it would land on instead.

    `--config` keys are checked against the extractor that was chosen, which for
    `auto` is per file. Both PDF paths (`pdf-text`, `vlm`) take `dpi`; every path
    that stores a page image — those two and `image` — takes `snapshot_quality`
    and `snapshot_max_height`. The vision paths (`vlm`, `image`) also take
    `api_key`, `base_url`, `model`, `timeout` and `retries`, and `concurrency` is
    `vlm`'s alone. Every other format reads no config at all, so a key there is a
    typo and is reported as one.
    """
    nudge_vlm = False
    note_pptx = False
    unsnapshot: dict[str, list[str]] = {}  # why it failed -> which documents
    thin: dict[str, list[str]] = {}  # why it came back thin -> which documents
    regenerated: list[str] = []  # documents that gained a generation this run
    restored: list[str] = []  # documents that had been withdrawn and are back
    unread: list[tuple[str, str]] = []  # which source -> why it never landed
    with guard():
        if slug is not None and len(sources) > 1:
            raise UsageError("--slug names one document; pass one source")
        # Parsed before the dry run branches off, because `ingest` refuses a
        # malformed pair before it touches any source: a dry run that exited 0
        # on a command that cannot start would be a prediction worse than none.
        settings = _parse_config(config or [])
        if dry_run:
            _report_naming(sources, slug)
            return
        with opened_registry() as registry:
            for source in sources:
                # One unreadable source is data, not the end of the run: the rest
                # of the list is still ingested and every failure is named below,
                # so ingesting a folder never leaves an agent guessing which half
                # landed. `guard` stays the only place a BackdraftError becomes an
                # exit code — nothing caught here is re-raised.
                try:
                    with _staged(source) as (path, origin):
                        document = registry.ingest(
                            path, extractor=extractor, slug=slug, config=settings, **origin
                        )
                        pages = registry.pages(document.slug)
                        # How much text came out, in one number: the count a
                        # login wall and a scanned PDF both fail, and the only
                        # thing on this line that says whether the snapshot is
                        # worth citing. `chars` for sheets too — this is the
                        # extraction's volume, not a window into it.
                        chars = extracted_chars(pages)
                        typer.echo(
                            f"{document.slug}  {source_name(document)}  "
                            f"{document.media_type}  {len(pages)} {unit(pages)}  "
                            f"{chars} chars{_outcome_note(document)}"
                        )
                        if document.outcome == GENERATION:
                            regenerated.append(document.slug)
                        if document.restored:
                            restored.append(document.slug)
                        if thin_mark(pages):
                            thin.setdefault(
                                _thin_cause(document.media_type), []
                            ).append(document.slug)
                        nudge_vlm = nudge_vlm or (
                            extractor == "auto"
                            and document.media_type == "pdf"
                            and not vlm_ready(settings)
                        )
                        note_pptx = note_pptx or document.media_type == "pptx"
                        # Page images: the VLM extractor stores them itself, so this
                        # only ever fires for the text-layer path (and for a re-ingest
                        # that landed before this machine had poppler). Display only,
                        # hence best-effort — a failure notes itself and ingest stands.
                        if _wants_snapshots(registry, document, pages):
                            try:
                                for _ in snapshots.capture(
                                    registry, document.slug, path, config=settings
                                ):
                                    pass
                            except snapshots.SnapshotError as error:
                                unsnapshot.setdefault(str(error), []).append(document.slug)
                except BackdraftError as error:
                    unread.append((source, str(error)))
    # One line per distinct reason — which is one line, unless a machine
    # without poppler is somehow also holding an unrenderable PDF.
    for reason, slugs in unsnapshot.items():
        typer.echo(
            f"note: page images not captured — {reason}. Citations and quotes "
            "are unaffected; artifacts just carry no cited-page image. Backfill "
            f"later with `backdraft snapshot-pages <slug>` for: {', '.join(slugs)}."
        )
    if nudge_vlm:
        # One line, once per invocation: `auto` fell back to the text layer,
        # and the note names the condition that failed.
        typer.echo(f"note: extracted with pdf-text (the embedded text layer). {_vlm_gap()}")
    if note_pptx:
        # Same shape as the pdf-text note: the honest gap, and the path that
        # closes it — relayed by a calling agent when the deck is visual-heavy.
        typer.echo(
            "note: extracted slide text only. Charts and images on slides are "
            "not captured; exporting the deck to PDF and ingesting it through "
            "the vision extractor captures them."
        )
    # Grouped by cause, the way the snapshot note above is: one scanned PDF and
    # the next have the same story, and each document's own count is already on
    # its own line, so the note carries the cause and the names rather than
    # repeating numbers.
    for cause, slugs in thin.items():
        typer.echo(
            f"note: little text extracted — {cause} Read it with `backdraft read "
            "<slug>` before citing it, and tell the user the source came back "
            f"thin rather than citing the shell of it: {', '.join(slugs)}."
        )
    if restored:
        # Grouped like the rest, and said out loud because it undoes a command
        # somebody ran on purpose: an agent re-ingesting a folder should not
        # have to notice that a source it was told to forget is back.
        typer.echo(
            f"note: {', '.join(restored)} came back — withdrawn with `backdraft "
            "forget`, and ingesting the source again is the undo. Back in "
            "`backdraft read`, `search` and `ls`, with citations into them "
            "resolving again. Forget again if that was not the intent."
        )
    if regenerated:
        # The one line here that is about work already done: a new generation is
        # the moment older citations can start reporting `drifted`.
        typer.echo(
            "note: new generation of "
            f"{', '.join(regenerated)} — citations into the previous snapshot may "
            "now report `drifted`. A token whose locator and snippet both survived "
            "the change carries over untouched, so `backdraft bind` on a document "
            "citing it is what says which; `backdraft show <token>` then prints "
            "the cited snippet beside what stands there now."
        )
    if unread:
        # Last, and it carries the exit code: everything above is what landed.
        fail(
            _unread_report(
                unread,
                len(sources),
                verb="ingested",
                closing=(
                    "fix these and re-run the same command: a source already in "
                    "the registry re-ingests as a no-op when its bytes, extractor "
                    "and config are unchanged."
                ),
            )
        )


def _report_naming(sources: list[str], slug: str | None) -> None:
    """`ingest --dry-run`: what each source would be called, before that is permanent.

    Called from inside `ingest`'s own guard, so it opens the registry the long
    way rather than through `opened_registry` — one guard, one mapping from a
    `BackdraftError` to exit 1.

    Every source gets a line in `ingest`'s own shape, so the prediction and the
    thing predicted read alike. A source that cannot be read is a line in the
    failure report instead, the way it is under a real ingest: a dry run is
    most often somebody checking a name they are unsure of, and a confident
    slug for a path that does not exist is the worst answer available.
    """
    named: list[tuple[str, Naming]] = []
    unread: list[tuple[str, str]] = []
    registry = open_registry()
    try:
        for source in sources:
            try:
                named.append((source, _naming(registry, source, slug)))
            except BackdraftError as error:
                unread.append((source, str(error)))
    finally:
        registry.close()
    for source, naming in named:
        typer.echo(f"{naming.slug}  {source}  {naming.media_type}{_naming_note(naming, slug)}")
    for line in _naming_notes(named, slug):
        typer.echo(line)
    if unread:
        fail(
            _unread_report(
                unread,
                len(sources),
                verb="named",
                closing=(
                    "fix these and ask again. Nothing was ingested either way — "
                    "`--dry-run` reads the addresses and the registry, and stops."
                ),
            )
        )


def _naming(registry: Registry, source: str, slug: str | None) -> Naming:
    """What `source` would be called, asked of the registry the same way `ingest` asks.

    The split is `_staged`'s, minus the network: a path is itself, and a URL
    resolves to the name its bytes *would* be staged under plus the URL as its
    origin. That the staged name is knowable without fetching is the whole
    reason this command can exist — `fetch.filename_for` settles the stem from
    the address, and only the suffix waits on the content type the server sends.
    """
    if not fetch.is_url(source):
        return registry.naming(Path(source), slug=slug)
    fetch.require_web(source)
    return registry.naming(Path(fetch.filename_for(source)), slug=slug, url=source)


def _naming_note(naming: Naming, requested: str | None) -> str:
    """Why this slug is not simply the source's own name. A fresh one says nothing.

    `_outcome_note`'s shape, for the same reason: the common case is a source
    nothing here has an opinion about, and a mark on every line would bury the
    two that matter.
    """
    if naming.ingested:
        marks = ["already ingested"]
        if naming.withdrawn:
            marks.append("withdrawn")
        if requested is not None and requested != naming.slug:
            # `--slug` is honoured only for a new document, so saying nothing
            # here would let a caller believe it was about to be renamed.
            marks.append("--slug would not rename it")
        return "  " + ", ".join(marks)
    if naming.deduped:
        return f"  {naming.stem} is taken"
    return ""


def _naming_notes(named: list[tuple[str, Naming]], requested: str | None) -> list[str]:
    """The two things the lines above cannot say for themselves.

    The web note is the honest gap: a slug comes from the address, so it is
    settled here, but a media type comes from the content type the server sends
    and no dry run can know it. Stating which half is provisional is the
    difference between a prediction and a guess.

    The `--slug` note fires only where it still applies — a source already
    ingested has its name, and telling its caller to choose one would be advice
    that cannot be taken.
    """
    notes: list[str] = []
    # Only for a web source nothing here has met: one already ingested was typed
    # by the content type its server sent, so its media type is a record rather
    # than a guess and warning about it would be warning about nothing.
    if any(fetch.is_url(source) and not naming.ingested for source, naming in named):
        notes.append(
            "note: nothing was fetched. A slug comes from the address alone, so "
            "the ones above are what ingest would use; a media type comes from "
            "the content type the server sends, so the ones above are what the "
            "address implies and the fetch settles."
        )
    fresh = [naming.slug for _, naming in named if not naming.ingested]
    if fresh and requested is None:
        notes.append(
            "note: nothing is ingested yet, so `--slug <name>` still names "
            f"{', '.join(fresh)}. After ingest it is fixed: every token written "
            "against the source carries the slug, so changing it means "
            "re-ingesting and rewriting the draft."
        )
    return notes


SKILLS = ("backdraft", "backdraft-backfill", "backdraft-artifact")

# Skills directories per agent family: Claude Code reads `.claude/skills/`;
# `.agents/skills/` is the Agent Skills standard path read by OpenAI Codex,
# Cursor, Copilot and others.
AGENT_DIRS = {"claude": ".claude", "codex": ".agents"}


def _skills_source() -> Path:
    """Where the bundled skills live: package data in a wheel, repo in a checkout."""
    packaged = Path(__file__).parent / "skills"
    if packaged.is_dir():
        return packaged
    checkout = Path(__file__).parents[2] / "skills"
    if checkout.is_dir():
        return checkout
    raise UsageError("this installation carries no bundled skills")


@app.command("skill")
def skill(
    action: Annotated[str, typer.Argument(help="`install` is the only action.")] = "install",
    project: Annotated[
        bool,
        typer.Option("--project", help="Install into the project's skills directory instead of the home one."),
    ] = False,
    all_: Annotated[
        bool,
        typer.Option("--all", help="Also install the backfill and artifact-reading skills."),
    ] = False,
    agent: Annotated[
        str,
        typer.Option("--agent", help="Target agent layout: `claude`, `codex`, or `all`."),
    ] = "claude",
) -> None:
    """Install the agent skill: `backdraft skill install`, then ask for cited work.

    Copies the writing skill into your agent's skills directory. `--agent claude`
    (the default) targets Claude Code's `~/.claude/skills/`; `--agent codex`
    targets `~/.agents/skills/`, the Agent Skills standard path read by OpenAI
    Codex, Cursor, Copilot and others; `--agent all` targets both. `--project`
    installs under the current directory (`.claude/skills/`, `.agents/skills/`)
    instead of the home directory. `--all` adds the backfill and
    artifact-reading skills.
    """
    import shutil

    with guard():
        if action != "install":
            raise UsageError(f"unknown action {action!r}; try: backdraft skill install")
        if agent not in (*AGENT_DIRS, "all"):
            raise UsageError(f"unknown agent {agent!r}; try: claude, codex, or all")
        source = _skills_source()
        agents = tuple(AGENT_DIRS) if agent == "all" else (agent,)
        base = Path.cwd() if project else Path.home()
        names = SKILLS if all_ else SKILLS[:1]
        for agent_name in agents:
            target_root = base / AGENT_DIRS[agent_name] / "skills"
            for name in names:
                src = source / name
                if not src.is_dir():
                    raise UsageError(f"bundled skill missing: {name}")
                dst = target_root / name
                dst.mkdir(parents=True, exist_ok=True)
                for item in src.iterdir():
                    if item.is_file():
                        shutil.copy2(item, dst / item.name)
                typer.echo(f"installed {name} -> {dst}")
    typer.echo('next: ask your agent for cited work, e.g. "Write me a memo from ./docs, with citations."')


def _document_named(registry: Registry, slug: str) -> Document:
    """The document `slug` names, or a `UsageError` naming the ones that exist.

    The two commands here that resolve a slug — `snapshot-pages` and `forget` —
    both act *on* a document rather than offering it to read, so both take a
    withdrawn one: `forget` accepts it and says it was already withdrawn, and
    re-snapshotting is maintenance on stored pages, not a read (the 2026-09-02
    row draws the line there). So the list names every document there is, with
    the withdrawn ones marked — omitting slugs the command would have accepted
    sends a caller to fix a spelling that was right.

    That is the bug this replaced. Built from `documents()`, the list left out
    exactly the withdrawn documents, and a registry holding nothing else told
    somebody who had just withdrawn one that "nothing is ingested here".

    The gate's own missing-slug wording stays separate: there the
    withdrawn/unknown distinction is the whole answer rather than a mark, and
    `gate.reader.require_document` gives each its own next step.
    """
    document = registry.document(slug)
    if document is not None:
        return document
    known = ", ".join(
        f"{other.slug} (withdrawn)" if other.withdrawn_at else other.slug
        for other in registry.documents(include_withdrawn=True)
    )
    raise UsageError(
        f"no document with slug {slug!r}; "
        + (f"ingested: {known}" if known else "nothing is ingested here")
    )


@app.command("snapshot-pages")
def snapshot_pages(
    slug: Annotated[str, typer.Argument(help="An ingested PDF's slug.")],
    file: Annotated[
        Path | None,
        typer.Option("--file", help="The source PDF, when it moved since ingest."),
    ] = None,
    dpi: Annotated[int, typer.Option("--dpi", help="Render resolution.")] = (
        snapshots.DEFAULT_DPI
    ),
) -> None:
    """Backfill page snapshots for an already-ingested PDF. Local, no model calls.

    Ingest stores each page's image already, through both the VLM and the
    text-layer path; this command is the backfill for what ingest could not do
    at the time — a registry built before that, or a machine that had no poppler
    then and does now. Snapshots are what lets `bind` embed the cited pages into
    the artifact. Requires poppler on the machine for PDF rendering. The
    encoding budget is backdraft-scoped settings: `BACKDRAFT_SNAPSHOT_QUALITY`
    (WebP quality, 85) and `BACKDRAFT_SNAPSHOT_MAX_HEIGHT` (pixels, 1056), env
    or `.backdraft/env` — display knobs only, citation tokens never derive from
    pixels.
    """
    with opened_registry() as registry:
        document = _document_named(registry, slug)
        if document.media_type != "pdf":
            raise UsageError(f"{slug} is {document.media_type}, not a PDF")
        source = file or Path(document.path)
        if not source.is_file():
            raise UsageError(
                f"source file not found at {source}; pass --file to point at it"
            )
        stored = 0
        for number, image in snapshots.capture(registry, slug, source, dpi=dpi):
            typer.echo(f"{slug}  p{number}  {image.width}x{image.height}")
            stored += 1
        typer.echo(f"stored {stored} page snapshot(s)")


@app.command()
def forget(
    slug: Annotated[str, typer.Argument(help="Slug of the document to withdraw.")],
    yes: Annotated[
        bool, typer.Option("--yes", "-y", help="Confirm without being asked.")
    ] = False,
) -> None:
    """Withdraw a source: out of `read`, `search` and `ls`, citations intact.

    Ingest is otherwise one-way, and a folder ingest picks up what it should not
    — a scratch copy, the same document under two names, a file nobody meant to
    include. Left there it competes in `search` forever and can be cited without
    anything looking wrong, and the only way out was deleting `.backdraft/` and
    losing every other document with it.

    This withdraws rather than deletes, and the difference is the whole design.
    Nothing is removed: the document, its generations, its anchors and its
    receipts all stay, so a token already written into somebody's draft or
    artifact still shows its snippet under `backdraft show` and still names its
    source in a `bind` report. What changes is that the registry stops offering
    it — it leaves the document list, the table of contents, page reads and
    search — and `bind` reports its citations `unresolved`, saying the source
    was withdrawn and when, instead of quietly passing them.

    Ingesting the source again brings it back, as the same document under the
    same slug rather than a second one beside it.

    Asks before withdrawing. Where nothing can answer — a script, an agent, a
    pipe — pass `--yes`, which is the whole of the confirmation.
    """
    with opened_registry() as registry:
        document = _document_named(registry, slug)
        pages = registry.pages(slug)
        # Single-spaced rather than the gate headline's aligned two, because
        # this reads inside sentences as often as it stands on its own line.
        described = (
            f"{slug} ({source_name(document)}, {document.media_type}, "
            f"{len(pages)} {unit(pages)})"
        )
        back = WITHDRAWN_HINT.format(path=document.path)
        if document.withdrawn_at is not None:
            # Already where the caller asked for it to be, so not a failure —
            # but "forgot" would claim a withdrawal this run did not make, and
            # the date somebody actually withdrew it on is the useful answer.
            typer.echo(f"{described} was already {withdrawn_reason(document)}")
            typer.echo(f"[{back}]")
            return
        if not yes:
            _confirm(described)
        registry.forget(slug)
    typer.echo(f"forgot {described}")
    typer.echo(
        "it is out of `backdraft read`, `search` and `ls`. Its anchors are "
        "untouched: a token already written into a draft or an artifact still "
        "shows its receipt under `backdraft show`, and `bind` reports it "
        "`unresolved` naming this withdrawal rather than passing it silently."
    )
    typer.echo(f"[{back}]")


def _interactive() -> bool:
    """Whether there is a person on the other end of stdin to answer a prompt."""
    try:
        return sys.stdin.isatty()
    except (AttributeError, ValueError):  # pragma: no cover - a closed stdin
        return False


def _confirm(described: str) -> None:
    """Ask before withdrawing, or say how to answer where nothing can.

    `forget` is the one command that takes something away, so it asks. The
    prompt is only reachable from a terminal, and this tool's usual caller is an
    agent with no terminal — where a bare prompt is either a hang or click's
    `Aborted.`, neither of which says what to do. So a non-interactive run is
    told the flag instead, and reads it as an ordinary usage error.
    """
    if not _interactive():
        raise UsageError(
            f"forgetting {described} takes it out of `backdraft read`, `search` "
            "and `ls` (its citations keep resolving). Re-run with --yes to confirm."
        )
    if not typer.confirm(f"forget {described}?"):
        raise UsageError("nothing withdrawn")


@app.command()
def clean(
    directory: Annotated[
        Path | None,
        typer.Argument(help="Directory to tidy. Defaults to the current directory."),
    ] = None,
) -> None:
    """Tidy strays from older runs out of a working directory.

    Moves loose records into `.backdraft/records/` and deletes leftover
    `.bound.md` projections. Everything removed or moved is regenerable with
    `backdraft bind`; artifacts (`.backdraft.html`) and authored documents are
    never touched.
    """
    from .kernel.artifact import BOUND_SUFFIX, SIDECAR_SUFFIX, record_path

    with guard():
        base = (directory or Path.cwd()).resolve()
        root = find_root(base)
        touched = 0
        for stray in sorted(base.glob(f"*{BOUND_SUFFIX}")):
            stray.unlink()
            typer.echo(f"removed {stray.name}")
            touched += 1
        for stray in sorted(base.glob(f"*{SIDECAR_SUFFIX}")):
            doc_stem = stray.name.removesuffix(SIDECAR_SUFFIX)
            target = record_path(root, base / f"{doc_stem}.md")
            target.parent.mkdir(parents=True, exist_ok=True)
            stray.replace(target)
            typer.echo(f"moved {stray.name} -> {target.relative_to(root)}")
            touched += 1
        if not touched:
            typer.echo("nothing to tidy")


@app.command("ls")
def list_documents() -> None:
    """List the ingested documents: slug, name, media type, page count.

    The name is the filename, or — for a source fetched from the web — the URL
    it came from, standing in the staging filename's place rather than beside
    it. A source that extracted almost nothing — a login wall, a scan with no
    text layer — closes its row with `little text: N chars`; read it before
    citing it. A registry of ordinary files prints what it always did.
    """
    # The name is `kernel.model.source_name`'s, shared with `ingest` and the gate's
    # own list. Out of the docstring on purpose: typer prints this one to a user,
    # and a module path is a pointer into code they are not reading.
    with opened_registry() as registry:
        documents = registry.documents()
        if not documents:
            typer.echo("no documents ingested")
            return
        for document in documents:
            pages = registry.pages(document.slug)
            # The mark is a fifth field on the rows that have one and no field
            # at all on the rows that do not: a registry of ordinary sources
            # prints what it always did, and nothing has to read a column that
            # is empty for almost every row.
            mark = thin_mark(pages)
            typer.echo(
                f"{document.slug}\t{source_name(document)}\t{document.media_type}\t"
                f"{len(pages)} {unit(pages)}" + (f"\t{mark}" if mark else "")
            )


@app.command()
def export(
    out: Annotated[
        Path | None, typer.Option("--out", "-o", help="Write here instead of stdout.")
    ] = None,
) -> None:
    """Export the whole registry as JSON, every generation included.

    The `backdraft/registry-v1` format, specified in spec/registry.md: every
    document, extraction, page, anchor and receipt, plus the ledger and the
    bind reports. It is content, not a backup — page images, sheet styling and
    the search index stay in the database.
    """
    with opened_registry() as registry:
        payload = json.dumps(registry.export_json(), indent=2, ensure_ascii=False)
    if out is None:
        typer.echo(payload)
    else:
        out.write_text(payload + "\n", encoding="utf-8")
        typer.echo(f"wrote {out}")


@contextmanager
def _staged(source: str) -> Iterator[tuple[Path, dict[str, str]]]:
    """The local file `ingest` should read, plus the origin kwargs for the registry.

    A path yields itself and nothing else. A URL is fetched here — the CLI owns
    the network, the way it owns page-snapshot capture, so the registry and the
    extractors stay pure — and staged in a temporary file named for the content
    type the server declared, which is what selects the extractor. The
    directory lives until the `with` closes, because page snapshots are
    captured from that file too.

    Staging can fail on its own — a full or unwritable temporary directory —
    and that is one source's failure like any other, so it becomes a
    `BackdraftError` rather than a traceback that ends the run the rest of the
    list was promised. The cause is the machine's, not the source's, so it keeps
    the system's own wording and offers no guess about the file.
    """
    if not fetch.is_url(source):
        yield Path(source), {}
        return
    fetched = fetch.fetch(source)
    with TemporaryDirectory(prefix="backdraft-fetch-") as directory:
        staged = Path(directory) / fetch.filename_for(fetched.url, fetched.content_type)
        try:
            staged.write_bytes(fetched.data)
        except OSError as error:
            raise fetch.FetchError(
                "it was fetched but could not be staged for extraction: "
                f"{error.strerror or error}. Free space in the temporary "
                "directory, or set TMPDIR somewhere writable."
            ) from error
        yield staged, {"url": fetched.url, "fetched_at": fetched.fetched_at}


def _wants_snapshots(registry: Registry, document: Document, pages: list[Page]) -> bool:
    """Whether this ingest should render page images for `document`.

    PDFs only, and only when the current extraction carries none already — so
    the VLM path (which stores the pixels it was shown) is left alone, and a
    no-op re-ingest re-renders nothing it already has.
    """
    return (
        document.media_type == "pdf"
        and bool(pages)
        and registry.page_image(document.slug, pages[0].number) is None
    )


def _unread_report(
    unread: list[tuple[str, str]], total: int, *, verb: str, closing: str
) -> str:
    """What `ingest` could not read, as one message: the count, each source, the fix.

    One line per *source* rather than per reason — the mirror image of the
    snapshot note above, which groups because one missing poppler explains every
    document at once. Here the source is the thing the caller has to act on, and
    two files rarely fail for the same reason; a reason that does repeat (a
    config key no extractor reads) repeats cheaply.

    `verb` and `closing` are what the two callers differ on and all they differ
    on: an ingest reports what it ingested and says re-running the list is safe,
    a dry run reports what it named and says nothing was ingested to begin with.
    The `!` lines are the shape anything parsing this report reads, so they have
    one owner.
    """
    landed = total - len(unread)
    noun = "source" if total == 1 else "sources"
    # The two counts add up to the whole list, which is the fact the old
    # abandon-on-first-failure behaviour could not state: nothing was skipped.
    lines = [f"{landed} of {total} {noun} {verb}; {len(unread)} failed:"]
    lines += [f"  ! {source} — {reason}" for source, reason in unread]
    lines.append(closing)
    return "\n".join(lines)


def _vlm_gap() -> str:
    """Which condition keeps `auto` off the vision model. The deps ship by
    default, so the usual gap is the backdraft-scoped key; a broken or partial
    install (no importable vlm extractor) is still named honestly."""
    from .credentials import setting
    from .extract.base import ExtractionError, get

    has_key = bool(setting("BACKDRAFT_VLM_API_KEY"))
    try:
        get("vlm")
        importable = True
    except ExtractionError:
        importable = False
    if not importable:
        return (
            "The vision extractor could not be imported — reinstall backdraft "
            "to restore it."
        )
    if not has_key:
        return (
            "Glossy or scanned PDFs extract better through a vision model: "
            "set BACKDRAFT_VLM_API_KEY in .backdraft/env."
        )
    return "set BACKDRAFT_VLM_API_KEY in .backdraft/env to use the vision model."


def _parse_config(pairs: Iterable[str]) -> dict:
    """`key=value` strings into a config dict. Values stay strings."""
    settings: dict[str, str] = {}
    for pair in pairs:
        key, separator, value = pair.partition("=")
        if not separator or not key:
            raise UsageError(f"--config expects key=value, got {pair!r}")
        settings[key] = value
    return settings


# ---- sub-app mounts ---------------------------------------------------------


def _mount(module: str) -> bool:
    """Merge a workstream's sub-app into this one. False if it isn't built yet.

    The spec's commands are flat — `backdraft read`, not `backdraft gate read` —
    so a sub-app's commands are adopted rather than nested. A missing module is a
    partial checkout, not an error.
    """
    try:
        sub = __import__(module, fromlist=["app"]).app
    except ImportError:
        return False
    app.registered_commands.extend(sub.registered_commands)
    app.registered_groups.extend(sub.registered_groups)
    return True


for _module in ("backdraft.gate.cli", "backdraft.bind.cli", "backdraft.render.cli"):
    _mount(_module)


def main() -> None:
    """Console-script entry point."""
    app()


if __name__ == "__main__":  # pragma: no cover
    main()
