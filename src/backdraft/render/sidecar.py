"""The sidecar: one bind run, written as a standalone self-describing JSON file.

The sidecar is the machine-readable half of the artifact. It is exactly a
`BindReport` payload with two reserved keys in front of it:

* ``$format`` — ``backdraft/artifact-v1``, matched exactly (never parsed, never
  range-checked); and
* ``$legend`` — prose that teaches a reader who has never seen backdraft how to
  decode the rest of the object.

The HTML artifact embeds this same payload, byte for byte, in its JSON island:
``render --to json`` and the island of ``render --to html`` are the same bytes,
so a reader can treat either as the record.

The format itself — `FORMAT`, `LEGEND`, `SIDECAR_SUFFIX`, `sidecar_path`, and the
`sidecar` / `dumps` writers — lives in `kernel/artifact.py`, because bind writes
it and render reads it and neither owns it; the file's *name* is part of the
format for the same reason. This module is the render-side door onto it: it
re-exports those names and adds the reader that turns a sidecar file back into a
`BindReport`. `spec/artifact.md` is the prose specification; where it and the
kernel's legend disagree, the spec file decides.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..kernel.artifact import (  # noqa: F401  (re-exported: the format is kernel-owned)
    FORMAT,
    ISLAND_ID,
    LEGEND,
    SIDECAR_SUFFIX,
    dumps,
    record_path,
    sidecar,
    sidecar_path,
)
from ..kernel.model import (
    Anchor,
    BindReport,
    Citation,
    CitationStatus,
    Claim,
    Receipt,
    Verdict,
    VerdictStatus,
)
from ..kernel.tokens import parse_locator

__all__ = [
    "FORMAT",
    "ISLAND_ID",
    "LEGEND",
    "SIDECAR_SUFFIX",
    "sidecar",
    "dumps",
    "write",
    "read",
    "read_payload",
    "island",
    "to_report",
    "sidecar_path",
    "find_sidecar",
]


def write(report: BindReport, path: Path) -> Path:
    """Write the sidecar to `path`. Returns the path written."""
    path.write_text(dumps(report), encoding="utf-8")
    return path


def read(path: Path) -> BindReport:
    """Read a sidecar file back into a `BindReport`.

    Raises `ValueError` if the file is not a payload of this exact format.
    """
    return to_report(json.loads(path.read_text(encoding="utf-8")))


def read_payload(path: Path) -> dict[str, Any]:
    """The record inside either half of the artifact, as the payload dict.

    A `.backdraft.json` *is* the payload; a `.backdraft.html` carries the same
    object in its record island. Both are accepted because both are what a
    reader gets handed, and which one arrived says nothing about what may be
    asked of it — the HTML is the half people forward, and refusing it would
    make the readable half the unreadable one.

    Decided by content, not by extension: the file is parsed as JSON, and only
    a file that is not JSON is looked at as a page. So a sidecar someone renamed
    still reads, and a file that is neither raises `ValueError` naming what it
    was expected to be rather than a parser's complaint about byte 1.
    """
    text = path.read_text(encoding="utf-8")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        payload = island(text)
    if not isinstance(payload, dict):
        kind = type(payload).__name__
        raise ValueError(f"{path.name} holds no artifact payload (found a bare {kind})")
    return payload


def island(page: str) -> dict[str, Any]:
    """The record island of a rendered artifact: `<script … id="…">` to `</script>`.

    The island's bytes are JSON, escaped so that no snippet can close the
    element (`<` `>` `&` written as `\u003c` `\u003e` `\u0026`) — which a JSON
    parser undoes on its own. Nothing is HTML-unescaped: there are no entities
    in there to undo, and doing it anyway would corrupt any snippet that quotes
    an ampersand. `spec/artifact.md` § The HTML artifact is the normative
    statement; `ISLAND_ID` is the kernel's copy of where to look.
    """
    head = f'<script type="application/json" id="{ISLAND_ID}">'
    _, found, rest = page.partition(head)
    if not found:
        raise ValueError(
            f"it is neither JSON nor a page carrying a <script id=\"{ISLAND_ID}\"> "
            "record island"
        )
    body, closed, _ = rest.partition("</script>")
    if not closed:
        raise ValueError(f"the {ISLAND_ID} island is unterminated")
    try:
        return json.loads(body)
    except json.JSONDecodeError as error:
        raise ValueError(f"the {ISLAND_ID} island is not valid JSON: {error}") from error


def to_report(payload: dict[str, Any]) -> BindReport:
    """Rebuild the `BindReport` a sidecar payload carries.

    `$format` is matched exactly; a payload carrying anything else is refused
    rather than interpreted. Round-trip is stable at the payload level:
    `sidecar(to_report(payload)) == payload` for any payload this accepts.

    NOTE: `Anchor.extraction_id`, `start` and `end` are registry-side fields the
    sidecar deliberately does not carry, so they come back `None`; `page_number`
    is recovered from the locator when the locator has one.
    """
    if not isinstance(payload, dict):
        raise ValueError(f"sidecar payload must be an object, not {type(payload).__name__}")
    found = payload.get("$format")
    if found != FORMAT:
        raise ValueError(f"unknown artifact format {found!r}; this reader speaks {FORMAT!r}")
    return BindReport(
        doc_path=payload["doc_path"],
        mode=payload["mode"],
        bound_at=payload["bound_at"],
        session_id=payload.get("session_id"),
        claims=tuple(_claim(entry) for entry in payload.get("claims", ())),
        evidence=payload.get("evidence"),
    )


def find_sidecar(doc_path: Path) -> Path | None:
    """The document's record, or None.

    Looked for in order: beside the document (`<stem>.backdraft.json` — the
    portable form a reader is handed), the whole-filename variant a person
    types (`memo.md.backdraft.json`), then the project's records store —
    `.backdraft/records/` under the nearest ancestor holding a `.backdraft`
    directory, which is where a rooted bind writes.
    """
    for candidate in (sidecar_path(doc_path), doc_path.with_name(doc_path.name + SIDECAR_SUFFIX)):
        if candidate.is_file():
            return candidate
    resolved = doc_path.resolve()
    for ancestor in resolved.parents:
        if (ancestor / ".backdraft").is_dir():
            candidate = record_path(ancestor, resolved)
            return candidate if candidate.is_file() else None
    return None


def _claim(entry: dict[str, Any]) -> Claim:
    return Claim(
        text=entry["text"],
        start=entry["start"],
        end=entry["end"],
        unmatched=bool(entry.get("unmatched", False)),
        citations=tuple(_citation(item) for item in entry.get("citations", ())),
    )


def _citation(entry: dict[str, Any]) -> Citation:
    token = entry["token"]
    anchor = entry.get("anchor")
    return Citation(
        token=token,
        status=CitationStatus(entry["status"]),
        anchor=_anchor(anchor, token) if anchor is not None else None,
        drifted_from=entry.get("drifted_from"),
        error=entry.get("error"),
        verdicts=tuple(_verdict(item) for item in entry.get("verdicts", ())),
    )


def _anchor(entry: dict[str, Any], token: str) -> Anchor:
    locator = parse_locator(entry["locator"])
    return Anchor(
        slug=entry["slug"],
        locator=locator,
        receipt=Receipt(snippet=entry["snippet"], snippet_sha256=entry["snippet_sha256"]),
        token=token,
        page_number=getattr(locator, "page", None),
    )


def _verdict(entry: dict[str, Any]) -> Verdict:
    return Verdict(
        method=entry["method"],
        status=VerdictStatus(entry["status"]),
        detail=entry.get("detail", ""),
    )
