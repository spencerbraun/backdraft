"""The Extractor protocol and the registry of extractors.

An extractor turns a file into an ordered sequence of `ExtractedPage`s — a PDF
page, a sheet, or the single page a text file is. That sequence is the snapshot
the registry stores and every receipt quotes; nothing downstream reopens the
file.

`deterministic` is the honest self-report that makes the re-ingest contract
possible: a deterministic extractor run twice over identical bytes produces
identical pages, so the registry can skip the work and keep every token. The VLM
extractor says `False`; it is the preferred `auto` choice for PDFs when it is
ready (installed, key configured), because the snapshot is the receipt and
glossy layouts extract badly from the text layer.

Extractors are registered in a plain dict keyed by name. Modules register
themselves on import and `get` imports the module that owns a name on demand, so
neither pdfplumber nor openpyxl — nor the `[vlm]` extra — is imported until an
extractor that needs it is asked for.
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Protocol, runtime_checkable

from ..kernel.errors import BackdraftError
from ..kernel.model import CellValue, PageKind

__all__ = [
    "AUTO_ORDER",
    "vlm_ready",
    "EXTRACTORS",
    "ExtractedPage",
    "Extractor",
    "ExtractionError",
    "PageImage",
    "get",
    "names",
    "register",
    "select",
]


class ExtractionError(BackdraftError):
    """An extractor could not produce a snapshot of a file."""


@dataclass(frozen=True, slots=True)
class PageImage:
    """A page's visual snapshot: the image an extractor derived the text from.

    For the VLM extractor this is the page as the model was shown it (re-encoded
    WebP, quality 85), which for a
    non-deterministic extractor is the one reproducible half of the receipt.
    """

    data: bytes
    format: str  # 'webp' | 'png' | 'jpeg'
    width: int
    height: int


@dataclass(frozen=True, slots=True)
class ExtractedPage:
    """One ordered unit of a snapshot: a PDF page or a sheet.

    `text` is the page as the model will read it — for sheets, the markdown table
    with in-band `[B10]` cell references. `cells` carries the sheet's populated
    cells so the registry can mint one anchor per cell and value-trace has values
    to compare against; each `value` is a verbatim substring of `text`. `image`,
    when present, is the page's visual snapshot; the registry stores it so bind
    can embed the cited pages into the artifact. `meta`, when present, is
    JSON-shaped presentation metadata (sheet styling: bold, fills, number
    formats, column widths, merges, frozen panes) — display context only,
    never citation identity.
    """

    number: int
    kind: PageKind
    text: str
    name: str | None = None
    cells: list[CellValue] | None = None
    image: PageImage | None = None
    meta: dict | None = None


@runtime_checkable
class Extractor(Protocol):
    """Turns a file into pages. Stateless: one instance serves every ingest."""

    name: str
    version: str
    deterministic: bool

    def can_handle(self, path: Path, media_type: str) -> bool:
        """True if this extractor claims the file."""
        ...

    def extract(self, path: Path, config: dict) -> Iterator[ExtractedPage]:
        """Yield the file's pages in order, 1-based. Raises `ExtractionError`."""
        ...


EXTRACTORS: dict[str, Extractor] = {}
"""Name -> extractor. Populated as modules are imported."""

AUTO_ORDER = ("xlsx", "xls", "csv", "docx", "pptx", "pdf-text", "image", "text")
"""The built-in fallback order for `--extractor auto`. `vlm` is preferred
for PDFs when ready — see `select` — and otherwise only chosen by name."""

# NOTE: the spec is silent on how a name finds its module; a table beats a scan
# because it keeps the import of an extractor's dependencies lazy.
_MODULES = {
    "xlsx": "xlsx",
    "xls": "xls",
    "csv": "csv",
    "docx": "docx",
    "pptx": "pptx",
    "pdf-text": "pdf_text",
    "image": "image",
    "text": "text",
    "vlm": "vlm",
}


def register(extractor: Extractor) -> None:
    """Register an extractor under its own name."""
    EXTRACTORS[extractor.name] = extractor


def names() -> list[str]:
    """Every extractor name this build knows, whether or not it can be loaded."""
    return sorted(_MODULES)


def get(name: str) -> Extractor:
    """The extractor called `name`, importing its module on first use.

    Raises `ExtractionError` for an unknown name, or when the module cannot be
    imported — the `[vlm]` extra not being installed is the case that matters.
    """
    if name in EXTRACTORS:
        return EXTRACTORS[name]
    if name not in _MODULES:
        raise ExtractionError(f"unknown extractor {name!r}; known: {', '.join(names())}")
    try:
        importlib.import_module(f"{__package__}.{_MODULES[name]}")
    except ImportError as error:
        raise ExtractionError(f"extractor {name!r} is unavailable: {error}") from error
    if name not in EXTRACTORS:  # pragma: no cover - a module that forgot to register
        raise ExtractionError(f"extractor module for {name!r} registered nothing")
    return EXTRACTORS[name]


def select(path: Path, media_type: str, config: dict | None = None) -> Extractor:
    """The extractor `--extractor auto` picks.

    For PDFs, `vlm` is preferred when it is ready (installed, key configured):
    glossy layouts and info boxes extract badly from the text layer, and the
    snapshot is the receipt. Otherwise the first built-in that can handle the
    file wins; the CLI owns the one-line nudge naming the VLM option, so
    selection itself stays quiet. An explicit `--extractor` never reaches this
    function.
    """
    if media_type == "pdf" and vlm_ready(config):
        extractor = get("vlm")
        if extractor.can_handle(path, media_type):
            return extractor
    for name in AUTO_ORDER:
        try:
            extractor = get(name)
        except ExtractionError:
            # An optional extractor whose extra is not installed (the image
            # extractor without `[vlm]`) must not break auto for other files.
            continue
        if extractor.can_handle(path, media_type):
            return extractor
    if media_type == "image":
        raise ExtractionError(
            f"images need the vision extractor: install 'backdraft[vlm]' and set "
            f"BACKDRAFT_VLM_API_KEY to ingest {path.name!r}"
        )
    raise ExtractionError(f"no extractor handles {media_type!r} file {path.name!r}")


def vlm_ready(config: dict | None = None) -> bool:
    """True when the `[vlm]` extra is importable and a backdraft-scoped key exists.

    Equivalent to consent: `auto` may only choose the paid, off-machine path
    when the user deliberately configured backdraft to use it. Ambient
    provider keys are never read (see `backdraft.credentials`).
    """
    from ..credentials import setting  # noqa: PLC0415 - keep base import-light

    if not setting("BACKDRAFT_VLM_API_KEY", config, config_key="api_key"):
        return False
    try:
        get("vlm")
    except ExtractionError:
        return False
    return True
