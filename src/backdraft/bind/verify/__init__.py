"""Verification methods: independent switches, recorded as evidence, never gates.

Importing this package registers every method in `VERIFIERS`; `selected(names)`
turns `--check value-trace,overlap` into the list bind runs. All switches are
off by default — a bind with no `--check` writes no verdict rows at all, and the
report's shape is unchanged either way.
"""

from __future__ import annotations

from .base import VERIFIERS, Verifier, register, selected
from .entail import Entail, entail
from .overlap import Overlap, overlap
from .recompute import Recompute, recompute
from .value_trace import ValueTrace, value_trace

__all__ = [
    "VERIFIERS",
    "Verifier",
    "register",
    "selected",
    "ValueTrace",
    "value_trace",
    "Overlap",
    "overlap",
    "Recompute",
    "recompute",
    "Entail",
    "entail",
]
