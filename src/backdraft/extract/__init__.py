"""Extractors: files in, ordered pages out.

The protocol and the registry live in `base`; the built-ins (`text`, `pdf-text`,
`xlsx`) and the `[vlm]` extra are imported on demand by `base.get`, so importing
this package costs nothing but the protocol.

Export style (shared by every package above the kernel): **names**, never
submodules, and only what a consumer outside the package imports.
"""

from __future__ import annotations

from .base import (
    AUTO_ORDER,
    EXTRACTORS,
    ExtractedPage,
    ExtractionError,
    Extractor,
    get,
    names,
    register,
    select,
    vlm_ready,
)

__all__ = [
    "AUTO_ORDER",
    "EXTRACTORS",
    "ExtractedPage",
    "Extractor",
    "ExtractionError",
    "get",
    "names",
    "register",
    "select",
    "vlm_ready",
]
