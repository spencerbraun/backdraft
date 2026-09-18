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

Exit codes (SPEC § CLI): 0 clean, 1 usage or environment error, 2 a run that
completed and did not come out clean — `bind` with non-resolved citations, and
`verify` with a record that failed its checks.
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
    "CLAIM_WIDTH",
    "DEFAULT_SESSION",
    "EXIT_USAGE",
    "EXIT_UNRESOLVED",
    "HOME_ENV",
    "SESSION_ENV",
    "UsageError",
    "as_typed",
    "authored_text",
    "claim_words",
    "fail",
    "find_root",
    "guard",
    "named_root",
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
"""A command completed and what it checked did not come out clean.

`bind`'s: the run finished and a citation did not resolve. `verify`'s too, for
the same class of outcome one step later — a record that failed its own checks,
or citations that no longer resolve against the sources. Both are "ran fine, the
document is not clean", which is exactly what a `Stop` hook gates on, so both
leave through this code and a hook written for one catches the other.

Not `gate.cli`'s `show`, which stays at 1: a lookup answering "that token names
nothing" is not a document failing, and gating a document on it would be wrong.
"""


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
        return _either_form(Path(override).expanduser())
    current = (start or Path.cwd()).resolve()
    for candidate in (current, *current.parents):
        if (candidate / DIRECTORY).is_dir():
            return candidate
    return None


def named_root(path: Path) -> Path:
    """The project root of a registry the caller named outright, or `UsageError`.

    For a command that lets its caller say which registry rather than having it
    discovered — `verify --against`, where the artifact's own location is no
    evidence at all. Both forms `BACKDRAFT_HOME` takes are taken here, through the
    same rule, so the two ways of naming a registry cannot come to disagree.

    Unlike discovery it never answers None: a walk that finds nothing has found
    a directory with no project in it, but a caller who names one that is not
    there has made a mistake, and falling back to anything would hide it. It
    also refuses before anything is opened, because `Registry.open` creates what
    it does not find, and naming the wrong directory must not leave a registry in
    it. Resolved, so a report names the root the way the walk names what it finds.
    """
    home = Path(os.path.abspath(path.expanduser()))
    root = _either_form(home)
    if not (root / DIRECTORY).is_dir():
        raise UsageError(
            f"no registry at {home}: expected a project root containing {DIRECTORY}/, "
            f"or the {DIRECTORY} directory itself"
        )
    return root.resolve()


def _either_form(home: Path) -> Path:
    """The project root, whether `home` names it or its `.backdraft` directory."""
    return home.parent if home.name == DIRECTORY else home


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


# ---- the authored document --------------------------------------------------


def authored_text(doc: Path) -> str:
    """The authored markdown document's text, or `UsageError` saying why not.

    One owner for the three commands that take a `<doc.md>` — `bind`, `locate`
    and `render` — which had each written their own `is_file` check and then
    read the file wherever it fell. A decode error is not a `BackdraftError`, so
    `guard` let it through: `locate` and `render` ended in a traceback on a
    document that was not UTF-8, and `bind` printed the codec's own sentence only
    because a decode error happens to be a `ValueError`, which its handler for an
    unknown `--check` was catching. Each failure here says what to do next, the
    rule `ingest`'s reasons follow.
    """
    if not doc.is_file():
        raise UsageError(f"no such document: {doc}")
    try:
        return doc.read_text(encoding="utf-8")
    except UnicodeDecodeError as error:
        raise UsageError(
            f"{doc} is not UTF-8 text (byte {error.start} does not decode); an authored "
            "document is read as UTF-8 markdown, so re-save it in that encoding"
        ) from error
    except OSError as error:
        raise UsageError(
            f"cannot read {doc}: {error.strerror or error}; change its permissions, or "
            "work on a readable copy"
        ) from error


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


# ---- report lines -----------------------------------------------------------


def as_typed(path: Path) -> Path:
    """A path as the user would type it: relative to cwd where it sits under cwd,
    absolute otherwise.

    For a path the tool computed rather than was handed — a record path is
    derived from the project root, so it arrives absolute and has to be brought
    back. `bind` prints the record it wrote this way and `render` the record it
    looked for, so the same file reads the same on both lines, with no home
    directory in output anyone pastes.
    """
    try:
        return path.relative_to(Path.cwd().resolve())
    except ValueError:
        return path


CLAIM_WIDTH = 80
"""Characters of a claim's own words carried onto a report line item.

Enough to recognize the sentence in the document, short enough that a run with
several line items still reads as a list.
"""


def claim_words(text: str) -> str:
    """A claim's words as one line of report: collapsed to `CLAIM_WIDTH`.

    A claim span may wrap across source lines, and a line item that wraps stops
    being one line item — the report's shape is what makes it greppable.

    Shared because two commands print the same kind of line about the same
    claims: `bind` reporting what did not resolve, `verify` reporting what did
    not check out. Two copies would drift on the width and the reader would meet
    two shapes for one thing.
    """
    collapsed = " ".join(text.split())
    return collapsed[:CLAIM_WIDTH] if collapsed else "(no claim text)"
