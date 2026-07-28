"""Finding each claim's span in the document render receives.

Render's only inputs are an authored document and a sidecar; the registry may be
gone. A claim carries `start`/`end` into the document bind read, which is usually
the document render is handed — but bind also rewrites citations into readable
form, so the file on disk may be the rewritten one and the offsets may have
moved. Rather than guess, we try three locators in order and record which claims
could not be placed at all; an unplaced claim still appears in the artifact, in
its own section, because nothing drops silently.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from ..kernel.model import Claim

__all__ = ["Placement", "locate"]


@dataclass(frozen=True, slots=True)
class Placement:
    """One claim and where it sits in the document being rendered.

    `number` is the claim's 1-based position in document order — the number the
    artifact labels it with. `start`/`end` are None when the claim's text could
    not be found in the document at all.
    """

    number: int
    claim: Claim
    start: int | None = None
    end: int | None = None

    @property
    def placed(self) -> bool:
        """True when this claim has a span in the document body."""
        return self.start is not None and self.end is not None


def locate(source: str, claims: Sequence[Claim]) -> list[Placement]:
    """Place every claim in `source`, in document order.

    Three locators, in order of confidence:

    1. the recorded offsets, when the construct they bound is still there;
    2. the first `[claim text](` link at or after the previous claim — the shape
       bind leaves behind when it rewrites tokens into readable citations;
    3. the first bare occurrence of the claim's text, for a document whose
       citations were projected away entirely.

    A claim that matches none of the three is returned unplaced.
    """
    placements: list[Placement] = []
    cursor = 0
    for number, claim in enumerate(claims, start=1):
        span = _at_offsets(source, claim) or _as_link(source, claim, cursor)
        if span is None:
            span = _as_text(source, claim, cursor)
        if span is None:
            placements.append(Placement(number=number, claim=claim))
            continue
        start, end = span
        placements.append(Placement(number=number, claim=claim, start=start, end=end))
        cursor = end
    return placements


def _at_offsets(source: str, claim: Claim) -> tuple[int, int] | None:
    """The recorded span, if the document still holds the construct bind saw."""
    if not 0 <= claim.start < claim.end <= len(source):
        return None
    construct = source[claim.start : claim.end]
    if construct == claim.text:
        return (claim.start, claim.end)
    if construct.startswith(f"[{claim.text}](") and construct.endswith(")"):
        return (claim.start, claim.end)
    return None


def _as_link(source: str, claim: Claim, cursor: int) -> tuple[int, int] | None:
    """The first `[claim text](...)` link at or after `cursor`.

    NOTE: the closing parenthesis is the first one after the opener. Tokens
    cannot contain parentheses, and the readable citations bind writes are
    fragment references, so this is exact for every href render can meet.
    """
    start = source.find(f"[{claim.text}](", cursor)
    if start < 0:
        return None
    close = source.find(")", start + len(claim.text) + 3)
    if close < 0:
        return None
    return (start, close + 1)


def _as_text(source: str, claim: Claim, cursor: int) -> tuple[int, int] | None:
    """The first bare occurrence of the claim's text at or after `cursor`."""
    if not claim.text:
        return None
    start = source.find(claim.text, cursor)
    if start < 0:
        return None
    return (start, start + len(claim.text))
