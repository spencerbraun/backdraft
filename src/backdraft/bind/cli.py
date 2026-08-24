"""`backdraft bind` — the CLI surface and the exit-code contract.

```
backdraft bind <doc.md> [--session S] [--check m1,m2] [--mode frontwalk|backfill]
```

Exit codes, per SPEC:

* **0** — clean: every citation resolved and nothing was left unmatched.
* **1** — usage or environment error: no registry, no such document, an unknown
  `--mode` or `--check` name.
* **2** — bind completed and something did not resolve. This is the code hooks
  gate on, so it is about *resolution* only: a `fail` verdict never produces it,
  because verification is evidence, not a gate.

NOTE: the spec fixes exit 2 as "completed with non-resolved citations". A
backfill claim bind could not anchor is the same failure without a citation to
hang it on, so it exits 2 as well — a backfill run that leaves claims
unattributed is not a clean run.

Every line item under the counts names the claim it belongs to, because the
caller of an exit 2 has to go edit a sentence and the token alone does not say
which one:

    ! unresolved: bd:t12-summary:p4.c1:1a2b — replacement reserve of $250 per unit per year @2900
    ! unmatched: The sponsor expects rents to grow 6% next year.

`@2900` is the claim's character offset into the authored document, which is
what tells two line items carrying the same token apart. The record JSON says
all of this already, nested; this is the same fact on one line.

Registry discovery and session resolution come from `backdraft.cli_context`
(SPEC Addendum B), imported at module level like every other sub-app's. The
registry is opened from the *document's* directory rather than the process's
cwd: `backdraft bind ../notes/memo.md` should find the registry the document
lives under.

Mounting (Addendum B): `app` is a `typer.Typer()` holding one command named
`bind` and no callback, and the top level adopts its commands rather than
nesting the app:

    app.registered_commands.extend(bind_cli.app.registered_commands)

so the command lands as `backdraft bind`, with no group name in between.
`tests/test_bind_cli.py` pins that.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Annotated

import typer

from ..cli_context import (
    EXIT_UNRESOLVED,
    EXIT_USAGE,
    UsageError,
    claim_words,
    guard,
    open_registry,
    resolve_session,
)
from ..kernel.artifact import bound_path, sidecar_path
from ..kernel.model import Citation, CitationStatus, Claim
from .binder import bind as run_bind, record_target

__all__ = ["app", "bind", "EXIT_USAGE", "EXIT_UNRESOLVED"]

app = typer.Typer(help="Bind an authored document against the registry.")

# The line-item shape — the claim's own words, collapsed to one line — is shared
# with `verify`, so `claim_words` lives in `cli_context` with the exit codes.


@app.command("bind")
def bind(
    doc: Annotated[Path, typer.Argument(help="The authored markdown document.")],
    session: Annotated[
        str | None,
        typer.Option("--session", help="Session whose ledger `not_shown` is judged against."),
    ] = None,
    check: Annotated[
        str | None,
        typer.Option(
            "--check",
            help="Comma-separated: value-trace, overlap, recompute, entail. Default: none.",
        ),
    ] = None,
    mode: Annotated[
        str,
        typer.Option(
            "--mode",
            help="frontwalk (citations already written) | backfill (also flag uncited claims).",
        ),
    ] = "frontwalk",
    lean: Annotated[
        bool,
        typer.Option("--lean", help="Skip page images in the artifact's evidence."),
    ] = False,
    bound: Annotated[
        bool,
        typer.Option("--bound", help="Also write the rewritten-markdown projection."),
    ] = False,
) -> None:
    """Resolve every citation, run enabled checks, rewrite, report."""
    with guard():
        if mode not in ("frontwalk", "backfill"):
            raise UsageError(f"unknown mode {mode!r}; expected frontwalk or backfill")
        if not doc.is_file():
            raise UsageError(f"no such document: {doc}")
        checks = [name.strip() for name in (check or "").split(",") if name.strip()]
        registry = open_registry(doc.resolve().parent)
        session_id = resolve_session(session, registry)
        try:
            report = run_bind(
                doc, registry, mode=mode, session_id=session_id, checks=checks,
                lean=lean, bound=bound,
            )
        except ValueError as error:  # unknown --check name
            raise UsageError(str(error)) from error
        finally:
            _close(registry)
    _print_report(report, doc, bound=bound, record=record_target(doc, registry))
    unmatched = [claim for claim in report.claims if claim.unmatched]
    if report.unresolved or unmatched:
        raise typer.Exit(EXIT_UNRESOLVED)


def _print_report(report, doc: Path, *, bound: bool = False, record: Path | None = None) -> None:  # noqa: ANN001 - BindReport, kernel-typed
    """The human-readable report: counts, then every line item."""
    summary = report.summary
    typer.echo(
        f"bound {summary['claims']} claim(s), {summary['citations']} citation(s) "
        f"[{report.mode}]"
    )
    for status, count in sorted(summary["by_status"].items()):
        typer.echo(f"  {status}: {count}")
    for method, statuses in sorted(summary["by_method"].items()):
        detail = ", ".join(f"{key} {value}" for key, value in sorted(statuses.items()))
        typer.echo(f"  {method}: {detail}")
    for claim, citation in _line_items(report):
        reason = f" — {citation.error}" if citation.error else ""
        typer.echo(
            f"  ! {citation.status}: {citation.token}{reason}"
            f" — {claim_words(claim.text)} @{claim.start}"
        )
    for claim in report.claims:
        if claim.unmatched:
            typer.echo(f"  ! unmatched: {claim_words(claim.text)}")
    if bound:
        typer.echo(f"wrote {bound_path(doc)}")
    typer.echo(f"wrote {_as_typed(record or sidecar_path(doc))}")


def _line_items(report) -> Iterator[tuple[Claim, Citation]]:  # noqa: ANN001 - BindReport, kernel-typed
    """Every citation that did not resolve, paired with the claim it sits on.

    `BindReport.unresolved` flattens to citations alone — the right shape for
    the exit code, the wrong one for a report a person reads, because the token
    is the one thing the reader already has and the sentence it was written on
    is the thing they need. `report.claims` carries both, so the pairing is a
    walk rather than a lookup.

    Yielded once per (claim, token), in document order. A token cited on four
    claims is four line items — four sentences to go fix — while the same token
    written twice in one href is one, since it is one place in the document.
    """
    seen: set[tuple[int, str]] = set()
    for index, claim in enumerate(report.claims):
        for citation in claim.citations:
            if citation.status is CitationStatus.RESOLVED:
                continue
            key = (index, citation.token)
            if key in seen:
                continue
            seen.add(key)
            yield claim, citation


def _as_typed(path: Path) -> Path:
    """A written path as the user would type it: relative to cwd where it sits
    under cwd, absolute otherwise.

    `render` prints the path it was handed and so is relative for free; the
    record path is computed from the project root, so it arrives absolute and
    has to be brought back. Same line, same shape, and no home directory in
    output anyone pastes.
    """
    try:
        return path.relative_to(Path.cwd().resolve())
    except ValueError:
        return path


def _close(registry) -> None:  # noqa: ANN001
    close = getattr(registry, "close", None)
    if callable(close):
        close()
