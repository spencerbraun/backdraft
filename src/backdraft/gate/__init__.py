"""The gate: the only way source text reaches a writer's context.

`read` lists, tables-of-contents and pages; `search` queries the FTS index;
`show` runs a token back to the snippet it names. All three mint what they emit
into the session ledger, which is what makes the design's central claim true —
the set of citable tokens is exactly the set the gate emitted, and bind can tell
a cited-what-you-saw token from a token the writer never had.

`gate.cli` is mounted by the top-level CLI (SPEC Addendum B) and is imported
separately, so this package stays importable without typer.

Export style (shared by every package above the kernel): **names**, never
submodules, and only what a consumer outside the package imports.
"""

from __future__ import annotations

from .reader import (
    WITHDRAWN_HINT,
    GateError,
    Selection,
    read,
    render_documents,
    render_page_read,
    render_toc,
    select_pages,
    source_name,
    unit,
)
from .searcher import render_search, search

__all__ = [
    "WITHDRAWN_HINT",
    "GateError",
    "Selection",
    "read",
    "render_documents",
    "render_toc",
    "render_page_read",
    "select_pages",
    "source_name",
    "unit",
    "search",
    "render_search",
]
