"""The gate's CLI surface: `read`, `search`, `session`.

Mounted by the top-level `cli.py` (SPEC Addendum B), which owns the typer app.
This module holds no logic of its own — it parses flags, calls `reader`/
`searcher`, prints, and lets `cli_context.guard` map a `GateError` to exit code 1
(usage/env error).

Discovery and session resolution come from `backdraft.cli_context`, imported at
module level: that module deliberately knows nothing about the sub-apps, so the
mount is not a cycle and there is no lazy lookup to keep in sync.
"""

from __future__ import annotations

import os
from typing import Annotated

import typer

from ..cli_context import SESSION_ENV, opened_registry, resolve_session
from .reader import cells as mint_cells
from .reader import read as read_pages
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
def search(
    query: Annotated[str, typer.Argument(help="FTS5 query.")],
    in_: Annotated[
        str | None, typer.Option("--in", help="Restrict to one document slug.")
    ] = None,
    session: _SessionOption = None,
    limit: Annotated[int, typer.Option("--limit", help="Maximum results.")] = 20,
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
def session_show(session: _SessionOption = None) -> None:
    """Show which session reads and searches would mint into."""
    resolved = resolve_session(session)
    with opened_registry() as registry:
        typer.echo(
            f"session {registry.ensure_session(resolved)}  (from {_session_source(session)})"
        )
