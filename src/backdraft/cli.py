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
# The gate owns the words a document is described in — the noun for a collection
# of pages (`gate.unit`) and what to call the source itself (`gate.source_name`)
# — and `ingest`/`ls` describe the same documents its list does. A downward
# import, which SPEC § Dependency rule spells "`cli` imports everything"; the
# mount guard below is about sub-*apps*, and `gate` itself does not need typer.
from .gate import source_name, unit
from .kernel.errors import BackdraftError
from .kernel.model import Document, Page
from .registry import DIRECTORY, GENERATION, UNCHANGED, Registry

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

THIN_SOURCE_CHARS = 200
"""Below this many extracted characters, a source is probably a shell.

A login wall, a JavaScript-rendered page and a scanned PDF with no text layer
all ingest cleanly and produce almost nothing — and used to print `1 page` like
any success, so an agent could cite the shell of a source without a signal that
it was one. The number is a heuristic and is deliberately generous: a real
document with under 200 characters in it is rare, and the cost of being wrong is
one note at exit 0, never a failure. Display only — no token, no anchor and no
status derives from it."""

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


def _outcome_note(outcome: str) -> str:
    """What `ingest` did, appended to the source's line. A fresh document says nothing.

    Three outcomes printed one line: an agent re-ingesting after a fix could not
    tell a no-op from a new generation, and the two mean opposite things about
    the work already written against the source.
    """
    if outcome == UNCHANGED:
        return "  unchanged"
    if outcome == GENERATION:
        return "  new generation"
    return ""


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
    command exits 1. Re-running the same list after a fix re-ingests nothing that
    already landed unchanged.

    Each source that lands prints its slug, its name, its media type, its page
    count and how much text came out — plus `unchanged` when re-running produced
    a no-op, or `new generation` when the bytes moved, which is when citations
    into the previous snapshot can start reporting `drifted`. A source almost no
    text came out of gets a note naming the likely cause, at exit 0: a thin
    snapshot is still a real one.

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
    unread: list[tuple[str, str]] = []  # which source -> why it never landed
    with guard():
        if slug is not None and len(sources) > 1:
            raise UsageError("--slug names one document; pass one source")
        settings = _parse_config(config or [])
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
                        chars = sum(len(page.text) for page in pages)
                        typer.echo(
                            f"{document.slug}  {source_name(document)}  "
                            f"{document.media_type}  {len(pages)} {unit(pages)}  "
                            f"{chars} chars{_outcome_note(document.outcome)}"
                        )
                        if document.outcome == GENERATION:
                            regenerated.append(document.slug)
                        if chars < THIN_SOURCE_CHARS:
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
        fail(_unread_report(unread, len(sources)))


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
        document = registry.document(slug)
        if document is None:
            raise UsageError(f"no document with slug {slug!r}")
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
    it. A registry of files prints what it always did.
    """
    # The name is `gate.source_name`'s, shared with `ingest` and the gate's own
    # list. Out of the docstring on purpose: typer prints this one to a user,
    # and a module path is a pointer into code they are not reading.
    with opened_registry() as registry:
        documents = registry.documents()
        if not documents:
            typer.echo("no documents ingested")
            return
        for document in documents:
            pages = registry.pages(document.slug)
            typer.echo(
                f"{document.slug}\t{source_name(document)}\t{document.media_type}\t"
                f"{len(pages)} {unit(pages)}"
            )


@app.command()
def export(
    out: Annotated[
        Path | None, typer.Option("--out", "-o", help="Write here instead of stdout.")
    ] = None,
) -> None:
    """Export the whole registry as JSON, every generation included."""
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
    """
    if not fetch.is_url(source):
        yield Path(source), {}
        return
    fetched = fetch.fetch(source)
    with TemporaryDirectory(prefix="backdraft-fetch-") as directory:
        staged = Path(directory) / fetch.filename_for(fetched.url, fetched.content_type)
        staged.write_bytes(fetched.data)
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


def _unread_report(unread: list[tuple[str, str]], total: int) -> str:
    """What `ingest` could not read, as one message: the count, each source, the fix.

    One line per *source* rather than per reason — the mirror image of the
    snapshot note above, which groups because one missing poppler explains every
    document at once. Here the source is the thing the caller has to act on, and
    two files rarely fail for the same reason; a reason that does repeat (a
    config key no extractor reads) repeats cheaply.

    The closing line says re-running the whole list is safe, because the
    alternative is an agent hand-diffing `ls` against its own arguments to
    rebuild the half that failed.
    """
    landed = total - len(unread)
    noun = "source" if total == 1 else "sources"
    # The two counts add up to the whole list, which is the fact the old
    # abandon-on-first-failure behaviour could not state: nothing was skipped.
    lines = [f"{landed} of {total} {noun} ingested; {len(unread)} failed:"]
    lines += [f"  ! {source} — {reason}" for source, reason in unread]
    lines.append(
        "fix these and re-run the same command: a source already in the registry "
        "re-ingests as a no-op when its bytes, extractor and config are unchanged."
    )
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
