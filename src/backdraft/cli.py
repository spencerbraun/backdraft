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
from pathlib import Path
from typing import Annotated, Iterable

import typer

from .cli_context import (
    DEFAULT_SESSION,
    EXIT_UNRESOLVED,
    EXIT_USAGE,
    HOME_ENV,
    SESSION_ENV,
    UsageError,
    find_root,
    guard,
    open_registry,
    opened_registry,
    resolve_session,
)
from .extract import snapshots, vlm_ready
from .kernel.model import Document, Page
from .registry import DIRECTORY, Registry

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
    files: Annotated[list[Path], typer.Argument(help="Files to ingest.")],
    extractor: Annotated[str, typer.Option("--extractor", help="Extractor name, or `auto`.")] = (
        "auto"
    ),
    slug: Annotated[
        str | None, typer.Option("--slug", help="Slug for a new document. One file only.")
    ] = None,
    config: Annotated[
        list[str] | None,
        typer.Option("--config", help="Extractor config as `key=value`. Repeatable."),
    ] = None,
) -> None:
    """Snapshot files into the registry, minting their anchors."""
    nudge_vlm = False
    note_pptx = False
    unsnapshot: dict[str, list[str]] = {}  # why it failed -> which documents
    with guard():
        if slug is not None and len(files) > 1:
            raise UsageError("--slug names one document; pass one file")
        settings = _parse_config(config or [])
        with opened_registry() as registry:
            for path in files:
                document = registry.ingest(
                    path, extractor=extractor, slug=slug, config=settings
                )
                pages = registry.pages(document.slug)
                typer.echo(
                    f"{document.slug}  {document.filename}  "
                    f"{document.media_type}  {len(pages)} pages"
                )
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
    """Tidy a working directory: move stray records into `.backdraft/records/`
    and delete leftover `.bound.md` projections.

    Everything removed or moved is regenerable with `backdraft bind`; artifacts
    (`.backdraft.html`) and authored documents are never touched.
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
    """List the ingested documents: slug, filename, media type, page count."""
    with opened_registry() as registry:
        documents = registry.documents()
        if not documents:
            typer.echo("no documents ingested")
            return
        for document in documents:
            pages = registry.pages(document.slug)
            typer.echo(
                f"{document.slug}\t{document.filename}\t{document.media_type}\t"
                f"{len(pages)} pages"
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
