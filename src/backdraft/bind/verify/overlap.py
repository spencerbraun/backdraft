"""overlap: how much of the claim's wording is actually in the snippet.

Report-only, by construction: this method never returns `fail`. Word overlap is
a signal about paraphrase, not a decision about truth — a faithful summary can
share almost no vocabulary with its source, and a plagiarised sentence shares
all of it. The worst verdict is `partial`, and the ratio travels in `detail` so
a reader can judge it.

Two behaviours, one method:

* **Quoted spans** — if the claim quotes (`"…"`, `“…”`, `'…'`), each quoted span
  must appear verbatim in the snippet. A quotation is a checkable assertion, so
  this is an exact substring test over normalized text; a case-only difference
  is `partial`, as is a quote that is not there at all.
* **Everything else** — the fraction of the claim's word tokens that occur in
  the snippet, at or above `PASS_RATIO` ⇒ `pass`.

NOTE: no stopword list and no stemming. Both are tuning knobs on a heuristic
whose output is advisory, and a stopword list is a language-specific table this
codebase should not start carrying.
"""

from __future__ import annotations

import re

from ...kernel.hashing import normalize
from ...kernel.model import Anchor, Citation, Claim, Verdict, VerdictStatus
from ...kernel.tokens import CellLocator
from .base import register

__all__ = ["Overlap", "overlap", "PASS_RATIO"]

PASS_RATIO = 0.6
"""Share of the claim's word tokens that must occur in the snippet to `pass`."""

_QUOTED = re.compile(r"\"([^\"]{2,})\"|“([^”]{2,})”|'([^']{3,})'")
_TOKEN = re.compile(r"[0-9a-z]+(?:[.,][0-9]+)*")


def quoted_spans(text: str) -> list[str]:
    """Every quoted span in `text`, normalized, in order."""
    spans: list[str] = []
    for match in _QUOTED.finditer(normalize(text)):
        span = next(group for group in match.groups() if group is not None)
        spans.append(normalize(span))
    return spans


def word_tokens(text: str) -> list[str]:
    """Lowercased word tokens: letters, digits, and numerals kept whole."""
    return _TOKEN.findall(normalize(text).lower())


class Overlap:
    """Span overlap between a claim and its anchor snippet. Never fails."""

    method = "overlap"

    def applies(self, claim: Claim, citation: Citation) -> bool:
        """True whenever the claim has words to compare."""
        return bool(word_tokens(claim.text))

    def verify(self, claim: Claim, citation: Citation, anchor: Anchor) -> Verdict:
        """Exact-substring for quoted spans; token overlap ratio otherwise."""
        if isinstance(anchor.locator, CellLocator):
            # A cell's snippet is one value; measuring how much of a sentence's
            # wording appears in it says nothing. Recorded as skip, not noise.
            return Verdict(
                method=self.method,
                status=VerdictStatus.SKIP,
                detail="wording overlap does not apply to a single cell",
            )
        snippet = normalize(anchor.receipt.snippet)
        spans = quoted_spans(claim.text)
        if spans:
            return self._verify_quotes(spans, snippet)
        tokens = word_tokens(claim.text)
        present = [token for token in tokens if token in set(word_tokens(snippet))]
        ratio = len(present) / len(tokens)
        detail = f"{len(present)}/{len(tokens)} claim tokens in snippet (ratio {ratio:.2f})"
        status = VerdictStatus.PASS if ratio >= PASS_RATIO else VerdictStatus.PARTIAL
        return Verdict(method=self.method, status=status, detail=detail)

    def _verify_quotes(self, spans: list[str], snippet: str) -> Verdict:
        missing: list[str] = []
        miscased: list[str] = []
        for span in spans:
            if span in snippet:
                continue
            if span.lower() in snippet.lower():
                miscased.append(span)
            else:
                missing.append(span)
        if missing:
            return Verdict(
                method=self.method,
                status=VerdictStatus.PARTIAL,
                detail="quoted span not in snippet: " + ", ".join(repr(s) for s in missing),
            )
        if miscased:
            return Verdict(
                method=self.method,
                status=VerdictStatus.PARTIAL,
                detail="quoted span differs in case: " + ", ".join(repr(s) for s in miscased),
            )
        return Verdict(
            method=self.method,
            status=VerdictStatus.PASS,
            detail=f"{len(spans)} quoted span(s) verbatim in snippet",
        )


overlap = register(Overlap())
