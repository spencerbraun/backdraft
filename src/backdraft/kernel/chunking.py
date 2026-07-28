"""The deterministic chunker (normative prose copy in spec/chunking.md).

`chunk(page_text) -> [Chunk(ordinal, text, start, end)]`. Pure and total: the
same page text always yields the same chunks, and no input raises.

Determinism is the whole point. A chunk's ordinal is half of its anchor identity
(extraction, page number, ordinal), so a chunker that rebalanced or capped chunk
counts would silently move every citation on the page. There is deliberately no
per-page rebalancing and no chunk-count cap.

The algorithm:

1. Split on blank lines (``\\n\\s*\\n``).
2. Merge forward: a segment shorter than 200 chars merges into the following
   segment; the last segment merges backward instead.
3. Split long: a segment longer than 2400 chars splits at the sentence boundary
   nearest each 1200-char multiple. A sentence boundary is a terminal ``.!?``
   followed by whitespace and an uppercase letter or digit — no abbreviation
   table, because splitting slightly wrong only shifts a boundary, and it does so
   deterministically. A final piece under 200 chars merges backward: step 2 ran
   before the split and could not see it.
4. Ordinals ``c1..cN`` in order.

Offsets are exact: ``page_text[chunk.start:chunk.end] == chunk.text`` for every
chunk. NOTE: a chunk's text is therefore the verbatim source region, including
any blank-line separators that merging swallowed; only the outer edges are
trimmed of whitespace. This keeps offsets meaningful for future span features and
costs nothing, since `hashing.normalize` collapses interior whitespace anyway.
"""

from __future__ import annotations

import re

from .model import Chunk

__all__ = [
    "MIN_CHARS",
    "MAX_CHARS",
    "TARGET_CHARS",
    "chunk",
]

MIN_CHARS = 200
"""Segments shorter than this merge into a neighbour."""

MAX_CHARS = 2400
"""Segments longer than this are split."""

TARGET_CHARS = 1200
"""Long segments split near each multiple of this."""

_BLANK_LINE = re.compile(r"\n\s*\n")
# NOTE: the spec says "terminal .!? + space"; we accept a run of whitespace so a
# double space or a wrapped line still reads as a boundary.
_SENTENCE_BOUNDARY = re.compile(r"[.!?]\s+(?=[A-Z0-9])")

type _Span = tuple[int, int]


def chunk(page_text: str) -> list[Chunk]:
    """Chunk one page's text. Returns `[]` for empty or whitespace-only pages."""
    spans: list[_Span] = []
    for span in _merge_short(_split_paragraphs(page_text)):
        spans.extend(_split_long(page_text, span))
    return [
        Chunk(ordinal=ordinal, text=page_text[start:end], start=start, end=end)
        for ordinal, (start, end) in enumerate(spans, start=1)
    ]


def _split_paragraphs(text: str) -> list[_Span]:
    """Blank-line separated regions, edge-trimmed, empties dropped."""
    spans: list[_Span] = []
    cursor = 0
    for separator in _BLANK_LINE.finditer(text):
        spans.append((cursor, separator.start()))
        cursor = separator.end()
    spans.append((cursor, len(text)))
    return [span for span in (_trim(text, *raw) for raw in spans) if span[0] < span[1]]


def _merge_short(spans: list[_Span]) -> list[_Span]:
    """Merge forward while a group is under `MIN_CHARS`; the last merges backward.

    NOTE: length is measured over the source region (`end - start`), which for a
    single segment is exactly its character count and for a merged group also
    counts the blank line it absorbed.
    """
    groups: list[_Span] = []
    index = 0
    while index < len(spans):
        start, end = spans[index]
        index += 1
        while end - start < MIN_CHARS and index < len(spans):
            end = spans[index][1]
            index += 1
        groups.append((start, end))
    if len(groups) > 1 and groups[-1][1] - groups[-1][0] < MIN_CHARS:
        last = groups.pop()
        start, _ = groups.pop()
        groups.append((start, last[1]))
    return groups


def _split_long(text: str, span: _Span) -> list[_Span]:
    """Split a span over `MAX_CHARS` at sentence boundaries near each target."""
    start, end = span
    length = end - start
    if length <= MAX_CHARS:
        return [span]
    boundaries = [
        start + match.end() for match in _SENTENCE_BOUNDARY.finditer(text[start:end])
    ]
    if not boundaries:
        return [span]

    cuts: list[int] = []
    previous = start
    target = TARGET_CHARS
    while target < length:
        goal = start + target
        # NOTE: nearest wins; ties go to the earlier boundary.
        candidates = [offset for offset in boundaries if previous < offset < end]
        if candidates:
            best = min(candidates, key=lambda offset: (abs(offset - goal), offset))
            cuts.append(best)
            previous = best
        target += TARGET_CHARS

    edges = [start, *cuts, end]
    pieces = [
        _trim(text, edges[i], edges[i + 1]) for i in range(len(edges) - 1)
    ]
    return _absorb_tail([piece for piece in pieces if piece[0] < piece[1]])


def _absorb_tail(pieces: list[_Span]) -> list[_Span]:
    """Merge an undersized final piece backward, the way rule 2 merges backward.

    Merging runs before splitting, so rule 2 cannot see the pieces rule 3 is
    about to create: a 2500-char region splits near 1200 and leaves a ~100-char
    tail that rule 2 would have absorbed had it been a paragraph. That tail is a
    chunk in name only — too small to carry context, and it becomes an anchor
    whose receipt is a sentence fragment. So rule 3 applies rule 2's backward
    merge to its own output, which is where that rule already sends a trailing
    short region. `pieces` is a fresh list and is mutated in place.
    """
    if len(pieces) > 1 and pieces[-1][1] - pieces[-1][0] < MIN_CHARS:
        last = pieces.pop()
        start, _ = pieces.pop()
        pieces.append((start, last[1]))
    return pieces


def _trim(text: str, start: int, end: int) -> _Span:
    """Shrink a span past leading and trailing whitespace."""
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return (start, end)
