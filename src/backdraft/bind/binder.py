"""bind: resolve → verify → rewrite → report.

The postprocess. It takes the document as written — claim spans carrying raw
tokens — and turns every token back into the receipt it names: a doc name, a
locator, and the verbatim quote the writer saw. What it cannot resolve it
reports; what it reports it never drops.

Three rules hold everywhere in this module:

* **Never edit a claim's text.** Bind rewrites the citation *around* a claim
  (`[claim](bd:…)` → `[claim](#cite-1)`); the words are the author's.
* **Never drop a citation.** Every token the author wrote gets a number, a
  References entry, and a line in the report — malformed ones included.
* **Verification never gates.** The exit-code contract keys off citation
  resolution alone; verdicts are evidence recorded beside it.

Outputs, per bind run over `notes.md`:

* `notes.bound.md` — the rewritten document plus a generated References section.
  A separate file, not an in-place edit: the authored document with its tokens
  is the source of truth and bind is re-runnable against it.
* `notes.backdraft.json` — the sidecar: the self-describing artifact payload
  (`$format` + `$legend` wrapped around `BindReport.to_dict()`), which is what a
  reader who has only this file needs. The row saved to `bindings.report_json`
  is the bare `BindReport.to_dict()` instead: the registry already knows what
  format it stores, so the legend would be noise in a database column.

NOTE: both filenames belong to the artifact format, not to this module —
`kernel/artifact.py` owns the suffixes and the path math (spec/artifact.md
§ Naming), so bind, render and any other implementation agree on where a bound
document's pieces live. They are re-exported here because this module's callers
already ask bind where it wrote.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from ..kernel.artifact import (  # noqa: F401  (re-exported: naming is kernel-owned)
    BOUND_SUFFIX,
    SIDECAR_SUFFIX,
    bound_path,
    record_path,
    sidecar_path,
)
from ..kernel.artifact import dumps as artifact_dumps
from ..kernel.claims import parse_claims
from ..kernel.model import (
    Anchor,
    BindMode,
    BindReport,
    Citation,
    CitationStatus,
    Claim,
)
from ..kernel.tokens import format_locator
from . import evidence as evidence_module
from .verify.base import Verifier, selected
from .verify.value_trace import extract_values

if TYPE_CHECKING:  # pragma: no cover - bind consumes the registry, never extends it
    from ..registry.store import Registry

__all__ = [
    "bind",
    "bound_path",
    "record_path",
    "record_target",
    "sidecar_path",
    "propose_anchors",
    "search_query",
    "BOUND_SUFFIX",
    "SIDECAR_SUFFIX",
    "PROPOSAL_LIMIT",
]

# BOUND_SUFFIX, SIDECAR_SUFFIX, `bound_path` and `sidecar_path` come from
# `kernel.artifact`: the names of a bind run's outputs, like the format inside
# them, are shared vocabulary between bind (the writer) and render (the reader).

PROPOSAL_LIMIT = 3
"""Search hits proposed per unmatched claim in backfill mode."""

QUERY_TERMS = 5
"""Distinctive words kept from a claim when searching for its anchor."""

QUERY_VALUES = 2
"""Numbers from a claim carried into the query as terms of their own."""

_REFERENCES_HEADING = "## References"
_UNMATCHED_HEADING = "## Unmatched claims"

_WORD = re.compile(r"[A-Za-z][A-Za-z'’]*")
_VALUE = re.compile(r"\d[\d,]*(?:\.\d+)?")

_STOPWORDS = frozenset(
    """
    a an and are as at be been but by can could did do does for from had has
    have how in into is it its may might must no not of off on one only or other
    our out over per shall should since so some such than that the their them
    then there these they this those through to under until up upon was were
    what when where which while who whom why will with within would you your
    also being both each either every less more most much nor same still
    thus very
    """.split()
)
"""Words that carry no discriminating power in a corpus of analyst prose.

Deliberately not the full NLTK list: a term dropped here is a term the proposal
cannot rank on, and words like `net`, `total` and `gross` earn their place in
this domain even though a general-purpose list would bin them.
"""


def bind(
    doc_path: Path,
    registry: Registry,
    *,
    mode: BindMode = "frontwalk",
    session_id: str | None = None,
    checks: Sequence[str] = (),
    write: bool = True,
    lean: bool = False,
    bound: bool = False,
) -> BindReport:
    """Bind one authored document. Returns the report; writes the artifacts.

    `checks` names the verification methods to run (`--check`); empty means no
    verifier runs and the report carries no verdict rows. `session_id` is what
    `not_shown` is judged against — without one, frontwalk mode cannot tell a
    cited-what-you-saw token from a valid token that was never shown, so it
    does not claim to. `write=False` computes the report without touching the
    filesystem or the registry. `lean` skips page images in the evidence block
    (text windows and sheet values are always included). `bound` also writes
    the rewritten-markdown projection (`memo.bound.md`) — off by default, so
    the standard working set is three files: the authored document, the
    record, the artifact.
    """
    source = doc_path.read_text(encoding="utf-8")
    verifiers = selected(checks)
    claims = [
        _resolve_claim(claim, registry, mode=mode, session_id=session_id)
        for claim in parse_claims(source)
    ]
    proposals: dict[int, tuple[Anchor, ...]] = {}
    if mode == "backfill":
        claims = _backfill(claims, source, registry, proposals)
    claims = _verify(claims, verifiers)
    report = BindReport(
        doc_path=str(doc_path),
        mode=mode,
        bound_at=_now(),
        claims=tuple(claims),
        session_id=session_id,
        evidence=evidence_module.assemble(registry, claims, lean=lean),
    )
    if write:
        if bound:
            bound_path(doc_path).write_text(
                rewrite(source, report, registry, proposals), encoding="utf-8"
            )
        # The record is the self-describing artifact payload ($format + $legend
        # around the report). With a rooted registry it lives out of the
        # authored directory (.backdraft/records/); a fake or rootless registry
        # keeps the portable beside-the-document form. The registry row carries
        # the bare report — the evidence block is heavy and reproducible.
        target = record_target(doc_path, registry)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(artifact_dumps(report), encoding="utf-8")
        registry.save_binding(
            doc_path=str(doc_path),
            session_id=session_id,
            mode=mode,
            report_json=json.dumps(
                report.to_dict(include_evidence=False), indent=2, ensure_ascii=False
            ),
        )
    return report


def record_target(doc_path: Path, registry) -> Path:  # noqa: ANN001
    """Where this bind writes its record: the registry's records dir, or beside."""
    root = getattr(registry, "root", None)
    if root is None:
        return sidecar_path(doc_path)
    return record_path(Path(root).resolve(), doc_path.resolve())


def propose_anchors(
    registry: Registry, text: str, *, limit: int = PROPOSAL_LIMIT
) -> tuple[Anchor, ...]:
    """Search hits bind offers for an unanchored claim. Proposals only.

    Backfill proposes; it never attaches. An anchor bind chose for a claim the
    author did not cite would be a citation nobody made.
    """
    query = search_query(text)
    if not query:
        return ()
    try:
        hits = registry.search(query, limit=limit)
    except Exception:  # noqa: BLE001 - a search that fails proposes nothing
        return ()
    return tuple(hit.anchor for hit in hits[:limit])


def search_query(text: str) -> str:
    """The FTS5 query a claim's own words make. Empty when it has none to give.

    A claim sentence is not a query. Handed to FTS5 verbatim, an ordinary one —
    *"Real estate taxes of $412,300 are the largest single expense line."* —
    fails to parse on the `$`, the `,` and the `.`, falls through to the quoted-
    phrase retry, and matches nothing at all, because no snippet contains that
    exact sentence. Backfill's proposals were therefore always empty or driven by
    stopword overlap.

    So the claim is reduced to what distinguishes it:

    * stopwords and one/two-letter fragments go;
    * an all-caps acronym (`NOI`, `DSCR`, `LTV`) outranks everything, because a
      corpus of prose has few of them and analysts write in them;
    * otherwise longer words rank first — a crude stand-in for rarity, but the
      right crudeness, since it prefers `reassessment` over `year`;
    * the top `QUERY_TERMS` survive, joined with `OR` so ranking sorts by how
      many matched rather than requiring all of them;
    * up to `QUERY_VALUES` numbers ride along as their own terms — `412,300` is
      the single most distinctive thing in that sentence.

    Every term is quoted, which both keeps punctuation out of FTS5's grammar and
    makes it impossible for a claim containing the word "or" to become an
    operator.
    """
    # Deduplicated on case, but the first spelling is kept: `NOI` has to still
    # look like an acronym when the sentence later says `noi`.
    seen: dict[str, str] = {}
    for word in _WORD.findall(text):
        if _is_content(word):
            seen.setdefault(word.lower(), word)
    # `sorted` is stable, so words of equal rank stay in the order they were
    # written — the query is a pure function of the claim, as proposals must be.
    ranked = sorted(seen.values(), key=_distinctiveness)
    values = sorted(dict.fromkeys(_VALUE.findall(text)), key=len, reverse=True)
    terms = [*ranked[:QUERY_TERMS], *values[:QUERY_VALUES]]
    return " OR ".join(f'"{term.lower()}"' for term in terms)


def _is_content(word: str) -> bool:
    """A word worth searching for: not a stopword, not a two-letter fragment."""
    return len(word) > 2 and word.lower() not in _STOPWORDS


def _distinctiveness(word: str) -> tuple[int, int]:
    """Sort key: acronyms first, then longest first."""
    return (0 if word.isupper() else 1, -len(word))


# --- resolution ------------------------------------------------------------


def _resolve_claim(
    claim: Claim, registry: Registry, *, mode: BindMode, session_id: str | None
) -> Claim:
    citations = tuple(
        _resolve_citation(citation, registry, mode=mode, session_id=session_id)
        for citation in claim.citations
    )
    return Claim(
        text=claim.text,
        start=claim.start,
        end=claim.end,
        citations=citations,
        unmatched=claim.unmatched,
    )


def _current_counterpart(registry: Registry, anchor: Anchor) -> Anchor | None:
    """The current generation's anchor at `anchor`'s locator, if it survived."""
    if anchor.page_number is None:
        return None
    for candidate in registry.anchors_for_page(anchor.slug, anchor.page_number):
        if candidate.locator == anchor.locator:
            return candidate
    return None


def _resolve_citation(
    citation: Citation, registry: Registry, *, mode: BindMode, session_id: str | None
) -> Citation:
    """One citation's status, from the closed set.

    `malformed` is already decided by the kernel and is never revisited: a
    token that does not parse cannot be looked up.
    """
    if citation.status is CitationStatus.MALFORMED:
        return citation
    resolution = registry.resolve(citation.token)
    if resolution is None:
        return Citation(token=citation.token, status=CitationStatus.UNRESOLVED)
    anchor = resolution.anchor
    if not resolution.current:
        # The drift contract (kernel fixture, spec/artifact.md): `drifted_from`
        # is the snippet the writer cited; `anchor` is what stands at that
        # locator now, found via `anchors_for_page` on the current generation.
        # When the locator itself is gone, the cited anchor stands in and the
        # two sides of the diff agree — still `drifted`, because the token no
        # longer resolves against the current generation.
        current = _current_counterpart(registry, anchor)
        return Citation(
            token=citation.token,
            status=CitationStatus.DRIFTED,
            anchor=current or anchor,
            drifted_from=anchor.receipt.snippet,
        )
    if mode == "frontwalk" and session_id is not None:
        if not registry.was_shown(session_id, citation.token):
            return Citation(
                token=citation.token, status=CitationStatus.NOT_SHOWN, anchor=anchor
            )
    return Citation(token=citation.token, status=CitationStatus.RESOLVED, anchor=anchor)


# --- backfill --------------------------------------------------------------


def _backfill(
    claims: list[Claim],
    source: str,
    registry: Registry,
    proposals: dict[int, tuple[Anchor, ...]],
) -> list[Claim]:
    """Mark and propose for every claim backfill could not anchor.

    Two kinds land here. A claim the author cited whose citations all failed —
    the token is there, the anchor is not. And a factual sentence carrying no
    citation at all, which is the whole backfill case: an existing document
    plus ingested sources, where the report has to name what is still
    unattributed rather than say nothing.
    """
    marked: list[Claim] = []
    for claim in claims:
        if any(citation.anchor is not None for citation in claim.citations):
            marked.append(claim)
            continue
        marked.append(
            Claim(
                text=claim.text,
                start=claim.start,
                end=claim.end,
                citations=claim.citations,
                unmatched=True,
            )
        )
    covered = [(claim.start, claim.end) for claim in claims]
    for start, end in _candidate_spans(source, covered):
        marked.append(Claim(text=source[start:end], start=start, end=end, unmatched=True))
    marked.sort(key=lambda claim: claim.start)
    for index, claim in enumerate(marked):
        if claim.unmatched:
            proposals[index] = propose_anchors(registry, claim.text)
    return marked


def _candidate_spans(source: str, covered: Sequence[tuple[int, int]]) -> list[tuple[int, int]]:
    """Sentences that look like factual claims and carry no citation.

    NOTE: the spec does not say what an uncited claim *is*, so this takes the
    narrowest reading that still makes backfill useful: a sentence, outside a
    fenced code block or a heading, that contains at least one value. A claim
    with a number or a date is the claim class backfill can actually search
    for; treating every sentence as a claim would bury the report it is meant
    to be.
    """
    spans: list[tuple[int, int]] = []
    for start, end in _sentences(source):
        if any(start < c_end and c_start < end for c_start, c_end in covered):
            continue
        if not extract_values(source[start:end]):
            continue
        spans.append((start, end))
    return spans


def _sentences(source: str) -> list[tuple[int, int]]:
    """Sentence spans in prose lines, as `(start, end)` offsets into `source`."""
    spans: list[tuple[int, int]] = []
    offset = 0
    fenced = False
    for line in source.splitlines(keepends=True):
        stripped = line.strip()
        if stripped.startswith("```"):
            fenced = not fenced
            offset += len(line)
            continue
        if fenced or not stripped or stripped.startswith("#"):
            offset += len(line)
            continue
        for start, end in _split_sentences(line):
            spans.append((offset + start, offset + end))
        offset += len(line)
    return spans


def _split_sentences(line: str) -> list[tuple[int, int]]:
    """Sentence spans within one line: terminal `.!?` followed by a space."""
    spans: list[tuple[int, int]] = []
    start = 0
    index = 0
    length = len(line)
    while index < length:
        if line[index] in ".!?" and (index + 1 >= length or line[index + 1].isspace()):
            end = index + 1
            if line[start:end].strip():
                spans.append((start + _lead(line[start:end]), end))
            start = end
        index += 1
    tail = line[start:]
    if tail.strip():
        spans.append((start + _lead(tail), start + len(tail.rstrip())))
    return spans


def _lead(text: str) -> int:
    return len(text) - len(text.lstrip())


# --- verification ----------------------------------------------------------


def _verify(claims: list[Claim], verifiers: Sequence[Verifier]) -> list[Claim]:
    """Run enabled verifiers over every citation that reached an anchor.

    A citation with no anchor has no snippet to check against, so no method
    applies to it — `unresolved` and `malformed` carry no verdicts. A verifier
    whose `applies` is False writes no row: the report never implies a method
    looked at a claim it never read.
    """
    if not verifiers:
        return claims
    pairs = [
        (claim, citation, citation.anchor)
        for claim in claims
        for citation in claim.citations
        if citation.anchor is not None
    ]
    for verifier in verifiers:
        prepare = getattr(verifier, "prepare", None)
        if callable(prepare):
            applicable = [
                (claim, citation, anchor)
                for claim, citation, anchor in pairs
                if verifier.applies(claim, citation)
            ]
            if applicable:
                prepare(applicable)
    verified: list[Claim] = []
    for claim in claims:
        citations = tuple(
            _verify_citation(claim, citation, verifiers) for citation in claim.citations
        )
        verified.append(
            Claim(
                text=claim.text,
                start=claim.start,
                end=claim.end,
                citations=citations,
                unmatched=claim.unmatched,
            )
        )
    return verified


def _verify_citation(
    claim: Claim, citation: Citation, verifiers: Sequence[Verifier]
) -> Citation:
    if citation.anchor is None:
        return citation
    verdicts = tuple(
        verifier.verify(claim, citation, citation.anchor)
        for verifier in verifiers
        if verifier.applies(claim, citation)
    )
    return Citation(
        token=citation.token,
        status=citation.status,
        anchor=citation.anchor,
        drifted_from=citation.drifted_from,
        verdicts=verdicts,
        error=citation.error,
    )


# --- rewrite ---------------------------------------------------------------


def rewrite(
    source: str,
    report: BindReport,
    registry: Registry,
    proposals: dict[int, tuple[Anchor, ...]] | None = None,
) -> str:
    """The authored document with tokens replaced by readable citations.

    Citations are numbered 1..N in document order, **one number per distinct
    token**: three claims citing the same anchor share number 4 and the anchor's
    quote appears once. Numbering per citation instead would repeat a 1200-char
    snippet down the page once per citing claim, which is how a References
    section stops being readable — and a reader who sees `[4]` twice has learned
    something true, that both claims rest on the same evidence.

    A claim's span becomes `[claim](#cite-n)`; a claim carrying more than one
    citation gets the extra numbers appended as their own links, so no citation
    loses its anchor and the claim's own words stay exactly as written. Uncited
    backfill claims are left untouched — bind has nothing to attach to them.

    NOTE: this is a rendering rule only. The report and the sidecar still carry
    every citation the author wrote, individually.
    """
    proposals = proposals or {}
    numbers, entries = _numbering(report)
    pieces: list[str] = []
    cursor = 0
    for index, claim in enumerate(report.claims):
        if not claim.citations:
            continue
        pieces.append(source[cursor : claim.start])
        pieces.append(_rewrite_claim(claim, numbers[index]))
        cursor = claim.end
    pieces.append(source[cursor:])
    body = "".join(pieces).rstrip("\n")
    sections = [body, _references(report, entries, registry)]
    unmatched = _unmatched_section(report, proposals, registry)
    if unmatched:
        sections.append(unmatched)
    return "\n\n".join(sections) + "\n"


def _numbering(report: BindReport) -> tuple[dict[int, list[int]], list[Citation]]:
    """Citation numbers per claim index, and the citation each number names.

    Numbers are 1-based over the whole document and keyed on the token, so a
    token cited from three places is numbered once, at its first appearance.
    Returns `({claim index: [numbers]}, [citation for 1, citation for 2, ...])`.
    """
    assigned: dict[str, int] = {}
    entries: list[Citation] = []
    numbers: dict[int, list[int]] = {}
    for index, claim in enumerate(report.claims):
        row: list[int] = []
        for citation in claim.citations:
            if citation.token not in assigned:
                assigned[citation.token] = len(entries) + 1
                entries.append(citation)
            number = assigned[citation.token]
            # A claim that cites one token twice links to it once; the report
            # still carries both citations.
            if number not in row:
                row.append(number)
        numbers[index] = row
    return numbers, entries


def _rewrite_claim(claim: Claim, numbers: Sequence[int]) -> str:
    first, *rest = numbers
    out = f"[{claim.text}](#cite-{first})"
    for number in rest:
        out += f"[{number}](#cite-{number})"
    return out


def _references(report: BindReport, entries: Sequence[Citation], registry: Registry) -> str:
    """The generated References section: doc name, locator, verbatim quote.

    One entry per distinct token — `entries` is already deduplicated by
    `_numbering`, and its index is the citation number.
    """
    lines = [_REFERENCES_HEADING, ""]
    if report.summary["citations"] == 0:
        lines.append("_No citations._")
    for number, citation in enumerate(entries, start=1):
        lines.append(f'<a id="cite-{number}"></a>**[{number}]** {_entry(citation, registry)}')
        lines.append("")
        if citation.anchor is not None:
            lines.append(_quote(citation.anchor.receipt.snippet))
            lines.append("")
    return "\n".join(lines).rstrip("\n")


def _entry(citation: Citation, registry: Registry) -> str:
    """One reference line: what the citation names, and how it resolved."""
    status = str(citation.status)
    if citation.anchor is None:
        detail = f" — {citation.error}" if citation.error else ""
        return f"`{citation.token}` — {status}{detail}"
    anchor = citation.anchor
    name = _doc_name(registry, anchor.slug)
    locator = format_locator(anchor.locator)
    note = ""
    if citation.status is CitationStatus.DRIFTED:
        note = " (snippet from a superseded extraction)"
    elif citation.status is CitationStatus.NOT_SHOWN:
        note = " (not in the session ledger)"
    return f"{name} — `{locator}` — {status}{note}"


def _unmatched_section(
    report: BindReport, proposals: dict[int, tuple[Anchor, ...]], registry: Registry
) -> str:
    """Backfill's open list: claims bind could not anchor, and what it found.

    NOTE: `BindReport` carries the `unmatched` flag but has no field for
    proposals, and the kernel is not bind's to extend — so the proposals live
    here, in the document a human reads, while the sidecar carries the flag.
    """
    entries = [
        (index, claim) for index, claim in enumerate(report.claims) if claim.unmatched
    ]
    if not entries:
        return ""
    lines = [_UNMATCHED_HEADING, ""]
    for index, claim in entries:
        lines.append(f"- {claim.text.strip()}")
        for anchor in proposals.get(index, ()):
            name = _doc_name(registry, anchor.slug)
            lines.append(f"  - proposed: `{anchor.token}` — {name}")
        if not proposals.get(index):
            lines.append("  - proposed: none")
        lines.append("")
    return "\n".join(lines).rstrip("\n")


def _doc_name(registry: Registry, slug: str) -> str:
    """The document's human handle: its filename, or the slug if unknown."""
    try:
        document = registry.document(slug)
    except Exception:  # noqa: BLE001 - a name lookup never fails a bind
        return slug
    return document.filename if document is not None else slug


def _quote(snippet: str) -> str:
    """The verbatim snippet as a markdown blockquote, line for line."""
    lines = snippet.splitlines() or [""]
    return "\n".join(f"> {line}".rstrip() for line in lines)


def _now() -> str:
    """ISO-8601 UTC, matching the DDL's `TEXT` timestamps."""
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
