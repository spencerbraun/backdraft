"""The artifact format: its version string, its legend, its file names, its payload.

Kernel-owned because the format is shared vocabulary: bind writes the sidecar,
render reads and re-emits it, and neither may import the other. The prose spec
is `spec/artifact.md`; this module is its single in-code copy.

**Naming is part of the format.** What a bind run and a render run are called on
disk is how a reader (person, agent, or another implementation) finds the pieces
of one document's record, so the suffixes and the path math live here rather than
in whichever layer happens to write each file. `spec/artifact.md` § Naming is the
normative statement; the constants below are its in-code copy.

NOTE on kernel purity: `pathlib` is imported for path *math* only. Nothing here
touches the filesystem — these functions compute names, they do not read or write
(`tests/test_invariants.py` enforces that distinction).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .model import BindReport

__all__ = [
    "FORMAT",
    "LEGEND",
    "ARTIFACT_SUFFIX",
    "BOUND_SUFFIX",
    "FOOTNOTES_SUFFIX",
    "SIDECAR_SUFFIX",
    "bound_path",
    "sidecar_path",
    "RECORDS_DIR",
    "record_path",
    "sidecar",
    "dumps",
]

FORMAT = "backdraft/artifact-v1"
"""The artifact format string. Readers match it exactly; see `LEGEND["version"]`."""

# ---- the naming family ------------------------------------------------------
#
# Every name is `<stem of the authored document>` + one of these suffixes, so a
# single `memo.md` produces `memo.bound.md`, `memo.backdraft.json`,
# `memo.backdraft.html` and `memo.footnotes.md`, and a directory listing sorts
# them together. The `.backdraft.*` pair is the artifact record proper — the same
# payload, machine-readable and human-readable; the other two are projections.

BOUND_SUFFIX = ".bound.md"
"""bind's rewritten document: `memo.md` -> `memo.bound.md`."""

SIDECAR_SUFFIX = ".backdraft.json"
"""A document's sidecar sits beside it: `memo.md` -> `memo.backdraft.json`."""

ARTIFACT_SUFFIX = ".backdraft.html"
"""The self-contained artifact: `memo.md` -> `memo.backdraft.html`."""

FOOTNOTES_SUFFIX = ".footnotes.md"
"""render's markdown projection: `memo.md` -> `memo.footnotes.md`.

Named for what it is rather than `.backdraft.md`, which would join the sidecar's
family without being the record, and rather than `.bound.md`, which is bind's
output and is a different document.
"""


def bound_path(doc_path: Path) -> Path:
    """Where bind's rewritten document goes."""
    return doc_path.with_name(doc_path.stem + BOUND_SUFFIX)


def sidecar_path(doc_path: Path) -> Path:
    """The beside-the-document record path: `memo.md` -> `memo.backdraft.json`.

    This is the *portable* location — the one a reader handed a document and
    its record uses. A project with a registry stores records out of sight
    instead; see `record_path`.
    """
    return doc_path.with_name(doc_path.stem + SIDECAR_SUFFIX)


RECORDS_DIR = "records"
"""Records live under `.backdraft/records/`, mirroring each document's path
relative to the project root — the authored directory shows only the document
and its artifact."""


def record_path(root: Path, doc_path: Path) -> Path:
    """Where a project stores a document's record: out of the authored directory.

    `<root>/.backdraft/records/<doc's path relative to root>` with the sidecar
    suffix, so distinct documents can never collide. A document outside `root`
    falls back to the beside-the-document path.

    Pure path math (the kernel invariant): both arguments must already be
    resolved to comparable absolute forms — callers hold the filesystem.
    """
    try:
        relative = Path(doc_path).relative_to(Path(root))
    except ValueError:
        return sidecar_path(doc_path)
    return (
        Path(root) / ".backdraft" / RECORDS_DIR / relative.parent
        / (relative.stem + SIDECAR_SUFFIX)
    )


LEGEND: dict[str, Any] = {
    "what_this_is": (
        "A bound document: every claim its author cited, recorded with the verbatim "
        "evidence behind it. This legend describes the object around it so that a "
        "reader who has never seen backdraft — person or model — can use the record "
        "without any other file, any registry, and any network access."
    ),
    "how_to_read": [
        "`claims` is the record, in document order. Each claim is a span of the "
        "authored document: `text` is the words the citations support, and "
        "`start`/`end` are character offsets into the authored source, bounding the "
        "whole markdown construct the author wrote.",
        "Each entry in a claim's `citations` names one anchor by its `token` and "
        "carries what binding found: a `status`, an `anchor` when one was found, "
        "`drifted_from` when the source moved, `error` when the token did not parse, "
        "and `verdicts` from whichever verification methods were switched on.",
        "An `anchor` is the receipt: `slug` names the source document, `locator` "
        "names the place inside it, `snippet` is the verbatim text that was quoted, "
        "and `snippet_sha256` is that snippet's hash. The snippet is present in "
        "full — you never need the source document to read the evidence.",
        "A claim with `unmatched` true is one that binding could not anchor at all. "
        "It is listed because it was written, not because it was verified.",
        "Every citation whose `status` is not `resolved` is a failure that was kept "
        "rather than hidden. Read those first; they are the interesting part.",
        "`summary` is derived from `claims` and is never authoritative on its own. "
        "If the two disagree, recount from `claims`.",
    ],
    "token": (
        "`bd:<slug>:<locator>:<hash>` is the textual name of an anchor. `hash` is the "
        "leading 4 to 8 hex characters of sha256 over the normalized snippet, where "
        "normalize is: Unicode NFC, then every whitespace run collapsed to one space, "
        "then strip, case preserved."
    ),
    "locator_forms": {
        "p8": "page or sheet 8, whole",
        "p8.c3": (
            "chunk 3 within page 8 — chunks are deterministic paragraph-scale "
            "subdivisions of a page, numbered from 1"
        ),
        "rent-roll!B10": "sheet `rent-roll`, cell B10, A1 notation",
        "rent-roll!B10:C12": "sheet `rent-roll`, rectangular range",
    },
    "citation_status": {
        "resolved": (
            "the anchor was found in the source document's current extraction; "
            "`anchor.snippet` is what the source says now and what the author cited"
        ),
        "drifted": (
            "the anchor was found only in a superseded extraction — the source changed "
            "after the claim was written. `drifted_from` is the snippet the author saw; "
            "`anchor.snippet` is what stands there now. Compare them before trusting "
            "the claim"
        ),
        "not_shown": (
            "a real anchor, but it was never shown to the writer in the recorded "
            "session: the claim cites something its author did not read"
        ),
        "unresolved": (
            "a well-formed token naming no anchor in any generation of any source. "
            "Treat the claim as uncited"
        ),
        "malformed": (
            "the citation text is not a token; `error` says why. Reported verbatim "
            "rather than dropped"
        ),
    },
    "verdict_status": {
        "pass": "the method ran and the claim survived it",
        "fail": "the method ran and the claim did not survive it",
        "partial": "the method ran and found partial support; `detail` says how much",
        "skip": "the method did not apply to this claim and citation",
    },
    "verdicts_are_evidence": (
        "Verification methods are opt-in switches, never gates. A method missing from "
        "a citation's `verdicts` was not run — that is not a pass. `summary.by_method` "
        "counts only what actually ran, as {method: {verdict status: count}}."
    ),
    "verify_this_record": [
        "1. For every citation carrying an `anchor`, recompute sha256 over the "
        "normalized `snippet`: it must equal `anchor.snippet_sha256`, and the `hash` "
        "segment of `token` must be a prefix of it.",
        "2. The `slug` and `locator` segments of `token` must equal `anchor.slug` and "
        "`anchor.locator`.",
        "3. Recount `summary` from `claims`.",
        "Steps 1 to 3 need nothing but this object. If you also hold the source "
        "documents, look `locator` up in the document named by `slug` and compare its "
        "text against `snippet`; that is the only check this record cannot make of "
        "itself.",
    ],
    "evidence": (
        "Optional. Evidence context for the cited sources, bounded by what is cited "
        "— never the whole corpus. `documents` maps slug to {filename, media_type}, "
        "plus {url, fetched_at} for a source fetched from the web: the page the bytes "
        "came from, after redirects, and when they were taken. Provenance only — the "
        "sha256 is the identity, and a source read from a file carries neither key. "
        "`pages` maps `slug:pN` to a page image {format, width, height, data} where "
        "`data` is base64; for a vision-model extraction this is the page as the "
        "model was shown it. `pagetexts` maps `slug:pN` to that page's extracted "
        "text. `windows` maps `slug:<locator>` to a small cell grid around a cited "
        "cell: {sheet, cited, cols, rows}, plus optional `styles` {cells, widths} "
        "carrying the workbook's own presentation for those cells. `sheets` maps "
        "`slug:<sheet>` to the full cited sheet's values: {name, nrows, ncols, rows}, "
        "plus optional `meta` {palette, cells, widths, merged, frozen} — cell styling "
        "as palette indices, column widths in Excel units, merged ranges, the frozen "
        "pane. Styling is display context only and is never part of citation "
        "identity: snippets and hashes are computed from values alone. A record without "
        "`evidence` is still complete — evidence is context, snippets are the proof. "
        "The HTML artifact may omit `pages[*].data` from its embedded copy of this "
        "object when the same bytes are present in the page as image elements."
    ),
    "version": (
        "The format string in `$format` is matched exactly, as an opaque string. A "
        "reader that does not recognize `backdraft/artifact-v1` must not guess: later "
        "versions may reuse these field names with different meanings. There is no "
        "compatibility range and no minor-version negotiation."
    ),
}
"""Normative. The artifact teaches its own decoding; `spec/artifact.md` specifies it."""


def sidecar(report: BindReport) -> dict[str, Any]:
    """The sidecar payload: `$format`, `$legend`, then the report, in that order."""
    return {"$format": FORMAT, "$legend": LEGEND, **report.to_dict()}


def dumps(report: BindReport) -> str:
    """The sidecar as text: UTF-8, two-space indent, trailing newline.

    Deterministic — the same report always produces the same bytes, so artifacts
    diff cleanly.
    """
    return json.dumps(sidecar(report), indent=2, ensure_ascii=False) + "\n"
