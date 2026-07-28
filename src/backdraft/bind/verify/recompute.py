"""recompute: deterministic re-execution of a declared derivation.

Registered and inert. `applies` returns False for every pair, so enabling
`--check recompute` is legal, changes nothing, and writes no verdict rows.

The method exists because the citation grammar reserves a derivation form —
`bd:calc(<expr over tokens>)`, see `kernel/tokens.py` and `spec/tokens.md` —
whose whole point is that "the numbers tie" becomes a deterministic check
instead of a slogan. v0 does not implement that grammar: `kernel.tokens.parse`
raises `UnsupportedTokenError` for it and bind reports such a citation as
`malformed`, which means no citation reaching a verifier can ever carry a
derivation. When the grammar lands, `applies` becomes "the citation is a
derivation" and `verify` evaluates the expression over its operand anchors.

Registering the stub now keeps the method name in the closed set from day one,
so a report's `by_method` table has a stable shape across versions.
"""

from __future__ import annotations

from ...kernel.model import Anchor, Citation, Claim, Verdict, VerdictStatus
from .base import register

__all__ = ["Recompute", "recompute"]


class Recompute:
    """Re-executes declared derivations. Applies to nothing until `bd:calc`."""

    method = "recompute"

    def applies(self, claim: Claim, citation: Citation) -> bool:
        """Always False: no v0 citation can carry a derivation."""
        return False

    def verify(self, claim: Claim, citation: Citation, anchor: Anchor) -> Verdict:
        """Unreachable in v0; `skip`, never an exception, if ever called."""
        return Verdict(
            method=self.method,
            status=VerdictStatus.SKIP,
            detail="derivations (bd:calc) are reserved and not implemented in v0",
        )


recompute = register(Recompute())
