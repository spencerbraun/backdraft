"""The registry: SQLite + FTS5 in `.backdraft/`, behind one object.

`Registry` is the only stateful thing in backdraft. The gate, bind and render
layers consume the surface in SPEC.md § Addendum A and implement none of it.

Export style (every package above the kernel uses it): this file re-exports
**names**, never submodules, and only the ones a consumer outside the package
imports — `store`'s own `__all__` is wider and is its internal contract. Reaching
past this surface (`registry.store.something`) is a signal that the something
belongs here.
"""

from __future__ import annotations

from .store import (
    DIRECTORY,
    EXPORT_FORMAT,
    Registry,
    RegistryError,
    Resolution,
    SearchHit,
    SearchResults,
    current_at,
    media_type_for,
    sanitize_sheet_name,
    slug_for,
)

__all__ = [
    "DIRECTORY",
    "EXPORT_FORMAT",
    "Registry",
    "RegistryError",
    "Resolution",
    "SearchHit",
    "SearchResults",
    "current_at",
    "media_type_for",
    "sanitize_sheet_name",
    "slug_for",
]
