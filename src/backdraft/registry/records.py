"""The project's records, read back: which drafts cite which sources, as last bound.

Every rooted bind writes its record under `.backdraft/records/`, mirroring the
draft's path relative to the project root (`kernel.artifact.record_path`), and a
record lists every token the draft cited. That makes the records directory the
one place a project answers "who cites this source?" — the question a new
generation raises and a withdrawal raises, and that the commands raising it
could only answer with a placeholder.

The registry's `bindings` rows were the alternative and lost for the reason the
2026-09-17 row gave for `locate`: they key on the path as it was typed, so the
same draft bound from two directories is two rows and a moved draft is a row
naming nothing. The record's own location is the draft's location.

It lives here rather than in the kernel, which holds no filesystem, and rather
than in `cli`, because the gate reads it too and may not import `cli`. A record
that cannot be read is skipped and counted, never raised: a malformed file in a
directory nobody edits by hand should not stop the ingest that happens to walk
past it, and the count is what lets a caller say the list may be short.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..kernel.artifact import RECORDS_DIR, SIDECAR_SUFFIX
from ..kernel.errors import TokenError
from ..kernel.tokens import parse as parse_token
from .store import DIRECTORY

__all__ = ["CitingDraft", "RecordScan", "scan_records"]


@dataclass(frozen=True, slots=True)
class CitingDraft:
    """One draft that still exists, and how many citations its record gives each slug."""

    path: Path
    citations: dict[str, int]


@dataclass(frozen=True, slots=True)
class RecordScan:
    """Every readable record under a project root, mapped back to its draft.

    `drafts` is sorted by path. `skipped` counts records that could not be read
    or did not hold a record's shape — the drafts behind them are unknown, so a
    caller naming "every draft citing X" names every draft it *could* read.
    """

    drafts: tuple[CitingDraft, ...]
    skipped: int

    def citing(self, slugs: str | set[str] | frozenset[str]) -> tuple[CitingDraft, ...]:
        """The drafts whose last bind cited any of `slugs`, in path order."""
        wanted = {slugs} if isinstance(slugs, str) else set(slugs)
        return tuple(draft for draft in self.drafts if wanted & draft.citations.keys())


def scan_records(root: Path | None) -> RecordScan:
    """Read `<root>/.backdraft/records/` into which draft cites which slug.

    A record maps back to its draft by its own location — the directory and stem
    from where it sits under the records directory, the suffix from the
    `doc_path` it carries, since `record_path` drops the suffix. Drafts that no
    longer exist are left out: a record outlives a deleted draft, and naming a
    file that is gone sends the caller nowhere. A rootless registry, or a project
    that has never bound anything, has no records and gets an empty scan.
    """
    if root is None:
        return RecordScan(drafts=(), skipped=0)
    records = Path(root) / DIRECTORY / RECORDS_DIR
    if not records.is_dir():
        return RecordScan(drafts=(), skipped=0)
    drafts: list[CitingDraft] = []
    skipped = 0
    for record in sorted(records.rglob(f"*{SIDECAR_SUFFIX}")):
        read = _read(record)
        if read is None:
            skipped += 1
            continue
        suffix, citations = read
        stem = record.name.removesuffix(SIDECAR_SUFFIX)
        draft = Path(root) / record.parent.relative_to(records) / f"{stem}{suffix}"
        if draft.is_file():
            drafts.append(CitingDraft(path=draft, citations=citations))
    return RecordScan(drafts=tuple(sorted(drafts, key=lambda d: d.path)), skipped=skipped)


def _read(record: Path) -> tuple[str, dict[str, int]] | None:
    """A record's draft suffix and per-slug citation counts, or None if unreadable.

    Only what the scan needs is looked at. A citation whose token does not parse
    is not counted — it names no source — but does not make the record
    unreadable, since bind records malformed tokens on purpose.
    """
    try:
        payload: Any = json.loads(record.read_text(encoding="utf-8"))
        doc_path = payload["doc_path"]
        claims = payload["claims"]
        if not isinstance(doc_path, str) or not isinstance(claims, list):
            return None
        counts: Counter[str] = Counter()
        for claim in claims:
            for citation in claim["citations"]:
                try:
                    counts[parse_token(citation["token"]).slug] += 1
                except TokenError:
                    continue
    except (OSError, UnicodeDecodeError, ValueError, KeyError, TypeError):
        return None
    return Path(doc_path).suffix, dict(counts)
