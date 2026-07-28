"""One golden-file idiom for the whole suite.

    BACKDRAFT_UPDATE_GOLDEN=1 uv run pytest

A golden file pins a published surface — the chunker's output, the artifact, the
markdown projection, the rewritten document. Comparing is the test; regenerating
is a deliberate act, so it lives behind an environment variable rather than a
flag someone can pass by muscle memory.

Deliberately a plain module and not a fixture: the star-imported conftest is
shared vocabulary between suites, and a helper that four test files call by name
is easier to follow when the import says where it came from.
"""

from __future__ import annotations

import os
from pathlib import Path

__all__ = ["UPDATE_ENV", "assert_golden", "updating"]

UPDATE_ENV = "BACKDRAFT_UPDATE_GOLDEN"
"""Set it to regenerate every golden file the run touches."""


def updating() -> bool:
    """True when this run regenerates goldens instead of checking them."""
    return bool(os.environ.get(UPDATE_ENV))


def assert_golden(path: Path, actual: str) -> None:
    """Assert `actual` is what `path` holds, or write it there when updating.

    The comparison is on bytes as text: a golden file is a diff a reviewer reads,
    so whitespace and ordering count.
    """
    if updating():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(actual, encoding="utf-8")
    expected = path.read_text(encoding="utf-8")
    assert actual == expected, (
        f"{path} is out of date; regenerate with {UPDATE_ENV}=1 if the change is intended"
    )
