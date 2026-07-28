"""The Verifier protocol and the registry of verification methods.

A verifier answers one question about one (claim, citation) pair and records a
`Verdict`. Verdicts are evidence, never gates: bind's exit code keys off
citation *resolution*, never off a verdict. All methods are off by default;
`--check value-trace,overlap` opts in.

`applies` is the method's own claim-class filter — value-trace applies only to
claims carrying a value, `recompute` applies to nothing until `bd:calc` lands.
An enabled verifier that does not apply writes no verdict row, so a report never
implies a method looked at a claim it never read.

Optional capability, not part of the protocol: a verifier may define
``prepare(pairs)`` taking the full list of ``(claim, citation, anchor)`` triples
bind is about to verify. Bind calls it once, before any `verify`, when it is
present — this is how `entail` batches its judge calls. Verifiers without it are
unaffected.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from ...kernel.model import Anchor, Citation, Claim, Verdict

__all__ = ["Verifier", "VERIFIERS", "register", "selected"]


@runtime_checkable
class Verifier(Protocol):
    """One verification method."""

    method: str
    """`value-trace` | `overlap` | `recompute` | `entail`."""

    def applies(self, claim: Claim, citation: Citation) -> bool:
        """True when this method has something to say about this pair."""
        ...

    def verify(self, claim: Claim, citation: Citation, anchor: Anchor) -> Verdict:
        """The method's finding, as a `Verdict` carrying `self.method`."""
        ...


VERIFIERS: dict[str, Verifier] = {}
"""Every registered method, by name. Registration happens on import."""


def register(verifier: Verifier) -> Verifier:
    """Register `verifier` under its `method` name and return it."""
    VERIFIERS[verifier.method] = verifier
    return verifier


def selected(names: Sequence[str]) -> list[Verifier]:
    """The verifiers named by `--check`, in the order given.

    Raises `ValueError` for an unknown method name — a usage error, which the
    CLI reports as exit 1 rather than running a bind with a silent typo.
    """
    chosen: list[Verifier] = []
    for name in names:
        if name not in VERIFIERS:
            known = ", ".join(sorted(VERIFIERS))
            raise ValueError(f"unknown verification method {name!r}; known methods: {known}")
        verifier = VERIFIERS[name]
        if verifier not in chosen:
            chosen.append(verifier)
    return chosen
