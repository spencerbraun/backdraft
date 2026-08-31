"""The gate's CLI surface: `read`, `cell`, `search`, `show`, `session`.

Mounted by the top-level `cli.py` (SPEC Addendum B), which owns the typer app.
This module holds no logic of its own — it parses flags, calls `reader`/
`searcher`, prints, and lets `cli_context.guard` map a `GateError` to exit code 1
(usage/env error).

`show` is the one command here that decides an exit code from what it found
rather than from an error: a token it could not resolve leaves as exit 1, and
the reason prints on stdout with the rest of the block, never swallowed onto
stderr, because it is an answer and not a diagnostic. It is 1 and not `bind`'s
2 — the other code for a run that completed and failed — because 2 is what a
`Stop` hook gates a document on, and a lookup must not trip it.

Discovery and session resolution come from `backdraft.cli_context`, imported at
module level: that module deliberately knows nothing about the sub-apps, so the
mount is not a cycle and there is no lazy lookup to keep in sync.
"""

from __future__ import annotations

import os
from typing import Annotated

import typer

from ..cli_context import (
    DEFAULT_SESSION,
    EXIT_USAGE,
    SESSION_ENV,
    opened_registry,
    resolve_session,
)
from .reader import DEFAULT_SESSION_NOTE
from .reader import cells as mint_cells
from .reader import read as read_pages
from .reader import render_session
from .reader import show as show_tokens
from .searcher import search as run_search

__all__ = ["app", "session_app"]

app = typer.Typer(help="Read and search ingested documents through the gate.")
session_app = typer.Typer(help="Inspect or start a ledger session.")
app.add_typer(session_app, name="session")


def _session_source(explicit: str | None) -> str:
    """Which rule supplied the session id — shown by `session show`."""
    if explicit:
        return "--session"
    if os.environ.get(SESSION_ENV):
        return SESSION_ENV
    return "default"


# ---------------------------------------------------------------------------
# commands
# ---------------------------------------------------------------------------

_SessionOption = Annotated[
    str | None,
    typer.Option("--session", "-s", help="Ledger session to mint into."),
]

_InspectedSession = Annotated[
    str | None,
    typer.Option("--session", "-s", help="Ledger session to inspect."),
]
"""`session show`'s own, because it is the one command taking this flag that
mints nothing: told it would mint into the session it is inspecting, a caller
reasonably avoids running it."""


@app.command()
def read(
    slug: Annotated[str | None, typer.Argument(help="Document slug.")] = None,
    selector: Annotated[
        str | None, typer.Argument(help="Page (`p3`), range (`p3-5`), or sheet name.")
    ] = None,
    session: _SessionOption = None,
    offset: Annotated[
        int, typer.Option("--offset", help="Units to skip (chars for pages, rows for sheets).")
    ] = 0,
    limit: Annotated[
        int | None, typer.Option("--limit", help="Units to show. Default: all of them.")
    ] = None,
) -> None:
    """List documents, show a document's contents, or read pages from one."""
    # The list and the table of contents emit no tokens, so they mint nothing.
    minting = slug is not None and selector is not None
    session_id = resolve_session(session) if minting else None
    with opened_registry() as registry:
        typer.echo(
            read_pages(
                registry, slug, selector, session=session_id, offset=offset, limit=limit
            )
        )


@app.command()
def cell(
    slug: Annotated[str, typer.Argument(help="Document slug.")],
    refs: Annotated[
        list[str], typer.Argument(help="Cell locators, like rent-roll!B10. Repeatable.")
    ],
    session: _SessionOption = None,
) -> None:
    """Mint tokens for specific cells: the token, then the verbatim value.

    The direct path to citing a cell you can see in a windowed sheet read —
    no need to search for the cell's own value.
    """
    session_id = resolve_session(session)
    with opened_registry() as registry:
        typer.echo(mint_cells(registry, slug, refs, session=session_id))


@app.command()
def show(
    tokens: Annotated[
        list[str], typer.Argument(help="Citation tokens, like bd:t12:p1.c1:c2e8. Repeatable.")
    ],
    session: _SessionOption = None,
) -> None:
    """Show what a token says: its status, where it points, the verbatim snippet.

    The inverse of minting — for a token out of an artifact, a draft, or someone
    else's message, when the question is what it actually cites. Statuses are
    bind's: `resolved`, `drifted` (both snippets print), `unresolved`,
    `malformed`. Showing is minting, so a snippet shown here is citable.

    Exit 1 if any token was unresolved or malformed; the reasons print like every
    other result.
    """
    session_id = resolve_session(session)
    with opened_registry() as registry:
        shown = show_tokens(registry, tokens, session=session_id)
        typer.echo(shown.text)
    if not shown.complete:
        raise typer.Exit(EXIT_USAGE)


@app.command()
def search(
    query: Annotated[str, typer.Argument(help="FTS5 query.")],
    in_: Annotated[
        str | None, typer.Option("--in", help="Restrict to one document slug.")
    ] = None,
    session: _SessionOption = None,
    limit: Annotated[
        int,
        typer.Option("--limit", help="Maximum results shown; a run that hits it says so."),
    ] = 20,
) -> None:
    """Search every anchor's snippet. Results are citable without a page read."""
    session_id = resolve_session(session)
    with opened_registry() as registry:
        typer.echo(run_search(registry, query, slug=in_, limit=limit, session=session_id))


@session_app.command("start")
def session_start(
    id_: Annotated[
        str | None, typer.Option("--id", help="Use this id instead of a generated one.")
    ] = None,
    label: Annotated[str | None, typer.Option("--label", help="Human note.")] = None,
) -> None:
    """Start a ledger session and print the id to export."""
    with opened_registry() as registry:
        session_id = registry.ensure_session(id_, label)
        typer.echo(f"session {session_id}  started")
        typer.echo(f"[Use it: export {SESSION_ENV}={session_id}]")


@session_app.command("show")
def session_show(session: _InspectedSession = None) -> None:
    """What this session holds: which one it is, and what it has been shown.

    The ledger read back before the draft exists. Per document a slug and a
    count of distinct anchors, under a total — the answer to "have I read enough
    to write this yet?", which was otherwise only reachable by binding a draft
    and counting `not_shown`.

    The default session says at exit 0 that it accumulates across every run in
    the registry, because that is what makes `not_shown` weaker than it reads.
    """
    resolved = resolve_session(session)
    with opened_registry() as registry:
        typer.echo(
            render_session(
                registry,
                registry.ensure_session(resolved),
                source=_session_source(session),
                # Keyed on the id rather than on which rule supplied it: an
                # explicit `--session default` lands in the same shared ledger
                # and costs the same thing.
                note=(
                    DEFAULT_SESSION_NOTE.format(env=SESSION_ENV)
                    if resolved == DEFAULT_SESSION
                    else None
                ),
            )
        )
