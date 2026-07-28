"""The markdown projection: claims become footnote refs, receipts become notes.

The lossy, portable rendering — for a pull request, an email, a wiki, anywhere
HTML cannot go. Every receipt still travels: document, locator, verbatim quote,
snippet hash, statuses and verdicts. What it gives up is the click.

The projection is total. Every claim gets a ref, every citation gets a note, and
every non-resolved citation is repeated in a visible Unresolved section, because
failures are data.
"""

from __future__ import annotations

from ..kernel.model import BindReport, Citation, CitationStatus
from ._text import quote_lines as _quote
from ._text import short, status_note
from .placement import Placement, locate
from .sidecar import FORMAT, SIDECAR_SUFFIX

__all__ = ["render", "LABEL_PREFIX"]

LABEL_PREFIX = "bd"
"""Footnote labels are `bd1`, `bd2`, ... in document order."""

CLAIM_ECHO_CHARS = 72
"""How much of a claim a list entry echoes: one markdown line's worth."""

_Note = tuple[str, list[str]]


def render(source: str, report: BindReport) -> str:
    """Render `source` and its bind report as plain markdown with footnotes."""
    placements = locate(source, report.claims)
    notes: list[_Note] = []
    body = _body(source, placements, notes)
    sections = [body.rstrip(), "---", _receipts(report, notes), _unresolved(placements)]
    return "\n\n".join(section for section in sections if section) + "\n"


def _body(source: str, placements: list[Placement], notes: list[_Note]) -> str:
    """The document with each claim's citation construct replaced by refs."""
    pieces: list[str] = []
    cursor = 0
    for placement in placements:
        claim_notes = _notes_for(placement, len(notes))
        notes.extend(claim_notes)
        if placement.start is None or placement.end is None:
            continue
        pieces.append(source[cursor : placement.start])
        pieces.append(
            placement.claim.text + "".join(f"[^{label}]" for label, _ in claim_notes)
        )
        cursor = placement.end
    pieces.append(source[cursor:])
    return "".join(pieces)


def _notes_for(placement: Placement, offset: int) -> list[_Note]:
    """One note per citation; a claim with no citation still gets one."""
    claim = placement.claim
    if not claim.citations:
        return [(f"{LABEL_PREFIX}{offset + 1}", _unanchored_note(placement))]
    return [
        (f"{LABEL_PREFIX}{offset + position}", _note(citation, placement))
        for position, citation in enumerate(claim.citations, start=1)
    ]


def _note(citation: Citation, placement: Placement) -> list[str]:
    """The lines of one footnote: source, quote, token, drift, verdicts.

    Groups are separated by blank lines so that the quote is a blockquote in the
    footnote and not a lazy continuation of the line above it.
    """
    anchor = citation.anchor
    if anchor is not None:
        groups = [
            [f"**{anchor.slug}** · `{anchor.locator}` · {citation.status}"],
            _quote(anchor.receipt.snippet),
            [f"Token `{citation.token}` · sha256 `{anchor.receipt.snippet_sha256}`"],
        ]
    else:
        groups = [[f"unanchored · {citation.status}"], [f"Token `{citation.token}`"]]
    if citation.drifted_from is not None:
        groups.append(["As cited, before the source changed:"])
        groups.append(_quote(citation.drifted_from))
    if citation.error:
        groups.append([f"Error: {citation.error}"])
    groups.append(
        ["Verdicts: " + (_verdicts(citation) if citation.verdicts else "none run.")]
    )
    groups.append(_claim_notes(placement))
    return _joined(groups)


def _unanchored_note(placement: Placement) -> list[str]:
    """A claim bind carried but could not cite at all."""
    head = [f"unmatched · no citation — claim: “{_echo(placement.claim.text)}”"]
    return _joined([head, _claim_notes(placement)])


def _claim_notes(placement: Placement) -> list[str]:
    """What is true of the claim itself, rather than of one citation."""
    lines: list[str] = []
    if placement.claim.unmatched:
        lines.append("This claim is unmatched: bind could not anchor it.")
    if not placement.placed:
        lines.append("This claim was not located in the document text above.")
    return lines


def _joined(groups: list[list[str]]) -> list[str]:
    """Non-empty groups, separated by one blank line."""
    out: list[str] = []
    for group in groups:
        if not group:
            continue
        if out:
            out.append("")
        out.extend(group)
    return out


def _verdicts(citation: Citation) -> str:
    return "; ".join(
        f"{verdict.method} {verdict.status}" + (f" — {verdict.detail}" if verdict.detail else "")
        for verdict in citation.verdicts
    )


def _receipts(report: BindReport, notes: list[_Note]) -> str:
    """The footnote definitions, under a provenance line."""
    session = f", session `{report.session_id}`" if report.session_id else ""
    stem = report.doc_path.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    lines = [
        "## Receipts",
        "",
        f"Bound from `{report.doc_path}` — {report.mode}{session}, {report.bound_at}. "
        f"Machine-readable record: `{stem}{SIDECAR_SUFFIX}` (`{FORMAT}`).",
        "",
    ]
    for label, note in notes:
        first, *rest = note
        lines.append(f"[^{label}]: {first}")
        lines.extend(f"    {line}" if line else "" for line in rest)
        lines.append("")
    return "\n".join(lines).rstrip()


def _unresolved(placements: list[Placement]) -> str:
    """Every non-resolved citation and every unmatched claim, visibly."""
    items: list[str] = []
    for placement in placements:
        for citation in placement.claim.citations:
            if citation.status is CitationStatus.RESOLVED:
                continue
            items.append(
                f"- **{citation.status}** — `{citation.token}` "
                f"in claim {placement.number}, “{_echo(placement.claim.text)}”: "
                f"{citation.error or status_note(citation.status)}."
            )
        if placement.claim.unmatched:
            items.append(
                f"- **unmatched** — claim {placement.number}, "
                f"“{_echo(placement.claim.text)}”: bind could not anchor it."
            )
    return "\n".join(["## Unresolved", "", *(items or ["Every citation resolved."])])


def _echo(text: str) -> str:
    """A claim's text, collapsed to one line for a list entry."""
    return short(text, limit=CLAIM_ECHO_CHARS)
