"""entail: does the snippet support the claim? A model judge, behind `[entail]`.

The qualitative claim class — the one no deterministic check reaches. The
question asked is deliberately tiny and closed: given a claim and the verbatim
snippet it cites, answer `yes`, `partial`, or `no`. Nothing is asked about
truth in the world; only about whether *this* snippet supports *this* claim.

The module imports without the extra installed: `anthropic` is import-guarded, so
`--check entail` is always a valid request. There is no pre-check — without the
extra, or without `BACKDRAFT_ENTAIL_API_KEY`, every pair verifies as `skip` carrying the
reason, and the bind still completes. That is the "failures are data" reading:
a report saying the judge could not run is more use than a refusal to bind, and
`skip` never touches the exit code, which keys off resolution alone.

Batching lives in `prepare`, an optional capability bind calls once with every
(claim, citation, anchor) triple before any `verify` — see `base.py`. One
request carries `BATCH_SIZE` numbered pairs and comes back as numbered lines,
which is what makes a judge affordable over a long document. A pair whose
answer does not come back — API error, short reply, unparseable line — verifies
as `skip` with the reason, never as `fail`: a verifier that cannot reach a
finding has not found anything.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from ...credentials import setting
from ...kernel.hashing import normalize
from ...kernel.model import Anchor, Citation, Claim, Verdict, VerdictStatus
from .base import register

try:  # pragma: no cover - exercised only by the extra's presence
    import anthropic
except ImportError:  # pragma: no cover - the guarded path
    anthropic = None  # type: ignore[assignment]

__all__ = ["Entail", "entail", "MODEL", "BATCH_SIZE"]

MODEL = "claude-opus-5"
"""Judge model. Override with `BACKDRAFT_ENTAIL_MODEL`."""

BATCH_SIZE = 20
"""Pairs per request."""

MAX_SNIPPET = 2000
"""Snippet characters sent per pair. Longer receipts are truncated, marked."""

_SYSTEM = (
    "You judge whether a source snippet supports a claim. "
    "For each numbered pair, answer with exactly one word: "
    "yes (the snippet states or directly implies the claim), "
    "partial (it supports part of the claim, or supports it with qualification), "
    "no (it does not support the claim). "
    "Reply with one line per pair, formatted '<number>: <answer>', and nothing else."
)

_ANSWER = re.compile(r"^\s*(?P<number>\d+)\s*[:.)]\s*(?P<answer>yes|partial|no)\b", re.IGNORECASE)

_STATUS = {
    "yes": VerdictStatus.PASS,
    "partial": VerdictStatus.PARTIAL,
    "no": VerdictStatus.FAIL,
}


class Entail:
    """Model judge over (claim, snippet) pairs. Batched, cached per run."""

    method = "entail"

    def __init__(self) -> None:
        self._answers: dict[tuple[str, str], tuple[VerdictStatus, str]] = {}

    def applies(self, claim: Claim, citation: Citation) -> bool:
        """True for any claim with text — every claim is a qualitative claim."""
        return bool(claim.text.strip())

    def prepare(self, pairs: Sequence[tuple[Claim, Citation, Anchor]]) -> None:
        """Judge every pair up front, in batches. Optional capability."""
        questions: list[tuple[str, str]] = []
        for claim, _citation, anchor in pairs:
            key = self._key(claim, anchor)
            if key not in self._answers and key not in questions:
                questions.append(key)
        for start in range(0, len(questions), BATCH_SIZE):
            self._ask(questions[start : start + BATCH_SIZE])

    def verify(self, claim: Claim, citation: Citation, anchor: Anchor) -> Verdict:
        """The judge's answer, or `skip` with the reason it has none."""
        key = self._key(claim, anchor)
        if key not in self._answers:
            self._ask([key])
        status, detail = self._answers.get(
            key, (VerdictStatus.SKIP, "no answer returned for this pair")
        )
        return Verdict(method=self.method, status=status, detail=detail)

    def _key(self, claim: Claim, anchor: Anchor) -> tuple[str, str]:
        snippet = normalize(anchor.receipt.snippet)
        if len(snippet) > MAX_SNIPPET:
            snippet = snippet[:MAX_SNIPPET] + " […truncated]"
        return (normalize(claim.text), snippet)

    def _ask(self, batch: Sequence[tuple[str, str]]) -> None:
        """One request for one batch; record an answer for every pair in it."""
        if not batch:
            return
        if anthropic is None:
            self._record_all(batch, "the [entail] extra is not installed")
            return
        api_key = setting("BACKDRAFT_ENTAIL_API_KEY")
        if not api_key:
            self._record_all(
                batch,
                "BACKDRAFT_ENTAIL_API_KEY is not set (env or .backdraft/env); "
                "ambient ANTHROPIC_API_KEY is deliberately not read",
            )
            return
        prompt = "\n\n".join(
            f"{index}.\nCLAIM: {claim}\nSNIPPET: {snippet}"
            for index, (claim, snippet) in enumerate(batch, start=1)
        )
        try:
            response = anthropic.Anthropic(api_key=api_key).messages.create(
                model=setting("BACKDRAFT_ENTAIL_MODEL") or MODEL,
                max_tokens=4096,
                system=_SYSTEM,
                output_config={"effort": "low"},
                messages=[{"role": "user", "content": prompt}],
            )
        except Exception as error:  # noqa: BLE001 - any failure is a `skip`, never a `fail`
            self._record_all(batch, f"judge call failed: {error}")
            return
        text = "\n".join(block.text for block in response.content if block.type == "text")
        answers: dict[int, str] = {}
        for line in text.splitlines():
            if match := _ANSWER.match(line):
                answers[int(match["number"])] = match["answer"].lower()
        for index, key in enumerate(batch, start=1):
            answer = answers.get(index)
            if answer is None:
                self._answers[key] = (
                    VerdictStatus.SKIP,
                    "judge returned no answer for this pair",
                )
            else:
                self._answers[key] = (_STATUS[answer], f"judge: {answer}")

    def _record_all(self, batch: Sequence[tuple[str, str]], reason: str) -> None:
        for key in batch:
            self._answers[key] = (VerdictStatus.SKIP, reason)


entail = register(Entail())
