"""bind — resolve claims against the registry, verify, report.

The postprocess between writing and rendering: every token becomes its receipt,
every failure becomes a line item, and nothing the author wrote is dropped or
edited. `binder.bind` is the whole entry point; `verify` holds the optional
methods, all off unless `--check` names them.

Export style (shared by every package above the kernel): **names**, never
submodules. `bind.cli` is not imported here — it needs typer; the library does
not. The suffixes and path helpers below are `kernel/artifact.py`'s: the names a
bind run writes are part of the artifact format, and bind re-exports them because
its callers ask bind where it wrote.
"""

from __future__ import annotations

from .binder import (
    BOUND_SUFFIX,
    PROPOSAL_LIMIT,
    SIDECAR_SUFFIX,
    bind,
    bound_path,
    propose_anchors,
    search_query,
    sidecar_path,
)

__all__ = [
    "bind",
    "bound_path",
    "sidecar_path",
    "propose_anchors",
    "search_query",
    "BOUND_SUFFIX",
    "SIDECAR_SUFFIX",
    "PROPOSAL_LIMIT",
]
