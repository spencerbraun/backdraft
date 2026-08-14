"""What every command needs before it can do anything: a registry and a session.

Discovery, session resolution, the exit codes and the one error guard live here
rather than in `cli.py` so that the sub-apps can import them the ordinary way.
The top level imports `gate.cli`, `bind.cli` and `render.cli` in order to mount
them (SPEC Addendum B), so anything they read off `cli.py` has to be fetched
lazily inside each command — which is how three copies of the same lookup grew.
This module breaks the cycle instead: it imports typer, the kernel and the
registry, and **never a sub-app**, so it is importable from anywhere.

`cli.py` re-exports these names, because `cli.find_root` / `cli.open_registry` /
`cli.resolve_session` are what the spec, the tests and the docs already call the
CLI's own surface. This module is the definition; `cli.py` is the front door.

Exit codes (SPEC § CLI): 0 clean, 1 usage or environment error, 2 bind completed
with non-resolved citations.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, NoReturn

import typer

from .kernel.errors import BackdraftError
from .registry import DIRECTORY, Registry

if TYPE_CHECKING:
    from collections.abc import Iterator

__all__ = [
    "DEFAULT_SESSION",
    "EXIT_USAGE",
    "EXIT_UNRESOLVED",
    "HOME_ENV",
    "SESSION_ENV",
    "UsageError",
    "fail",
    "find_root",
    "guard",
    "open_registry",
    "opened_registry",
    "resolve_session",
]

HOME_ENV = "BACKDRAFT_HOME"
SESSION_ENV = "BACKDRAFT_SESSION"

DEFAULT_SESSION = "default"
"""The auto-created session. Stable across invocations, so reads accumulate."""

EXIT_USAGE = 1
"""Usage or environment error — and everything else that is not exit 2.

`gate.cli`'s `show` also leaves through this code when a token it was handed
named nothing, which is not a usage error: the command ran and answered. It is
still 1 rather than 2 because 2 is `bind`'s alone (below), and a `Stop` hook
gating on 2 must not be tripped by a lookup. `show` prints its reasons on stdout
either way, so the caller reads the answer, not the code.
"""

EXIT_UNRESOLVED = 2
"""`bind` completed and something did not resolve. Owned by `bind`; hooks gate on it."""


class UsageError(BackdraftError):
    """The command cannot run as asked: no registry, no such file, bad flag.

    A domain error like any other, so it travels out of a helper and is turned
    into a message and an exit code in exactly one place (`guard`).
    """


# ---- discovery --------------------------------------------------------------


def find_root(start: Path | None = None) -> Path | None:
    """The nearest directory containing `.backdraft/`, walking up from `start`.

    `BACKDRAFT_HOME` overrides the walk. It may name either the project root or
    the `.backdraft` directory itself — NOTE: the spec does not say which, and
    guessing wrong is a confusing failure, so both are accepted.
    """
    override = os.environ.get(HOME_ENV)
    if override:
        home = Path(override).expanduser()
        return home.parent if home.name == DIRECTORY else home
    current = (start or Path.cwd()).resolve()
    for candidate in (current, *current.parents):
        if (candidate / DIRECTORY).is_dir():
            return candidate
    return None


def open_registry(start: Path | None = None) -> Registry:
    """Open the discovered registry, or raise `UsageError` for `guard` to report."""
    root = find_root(start)
    if root is None:
        raise UsageError(
            f"no {DIRECTORY}/ found in this directory or any parent; run `backdraft init`"
        )
    return Registry.open(root)


def resolve_session(session: str | None = None, registry: Registry | None = None) -> str:
    """The session this invocation belongs to.

    Precedence: `--session` flag, then `BACKDRAFT_SESSION`, then the default
    session. Pure name resolution — pass `registry` to also create the session
    row. The gate's reader/searcher ensure the session themselves, so their CLI
    passes no registry. Shared with the gate and bind sub-apps so every command
    agrees on which ledger it is writing to.
    """
    chosen = session or os.environ.get(SESSION_ENV) or DEFAULT_SESSION
    if registry is not None:
        registry.ensure_session(chosen)
    return chosen


# ---- the error path ---------------------------------------------------------


def fail(message: str, code: int = EXIT_USAGE) -> NoReturn:
    """One line on stderr, then exit. The only place a command prints an error."""
    typer.echo(f"backdraft: {message}", err=True)
    raise typer.Exit(code)


@contextmanager
def guard(code: int = EXIT_USAGE) -> Iterator[None]:
    """Turn any `BackdraftError` raised inside into a message and an exit code.

    Libraries raise; the CLI maps — once, here. Every subclass is covered, so a
    `GateError`, an `ExtractionError`, a `RegistryError` and a `UsageError` all
    reach the user as one line rather than a traceback, and a command that wants
    a different exit code passes one instead of writing its own handler.
    """
    try:
        yield
    except BackdraftError as error:
        fail(str(error), code)


@contextmanager
def opened_registry(start: Path | None = None) -> Iterator[Registry]:
    """The discovered registry, guarded and always closed.

    The shape almost every command wants: discovery failures and domain errors
    raised in the body both become exit 1, and the connection closes either way.
    """
    with guard():
        registry = open_registry(start)
        try:
            yield registry
        finally:
            registry.close()
