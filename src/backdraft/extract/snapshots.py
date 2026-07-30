"""Page snapshots: PDF pages rendered locally to images. Display only.

The VLM extractor stores each page's image because for a non-deterministic
extractor the input pixels are the one reproducible half of the receipt. Those
same images are what `bind` embeds into the artifact, so a keyless text-layer
ingest that stores none produces visually poorer receipts for no principled
reason. This module is the local renderer that closes the gap — poppler through
pdf2image, no model calls, nothing leaving the machine — shared by the
automatic capture at `ingest` and the manual `snapshot-pages` backfill.

**The renderer lives here, not in `pdf-text`.** `pdf-text` is
`deterministic = True`, and an extractor whose output varied with whether
poppler happened to be installed would not be: the same bytes would extract to
pages with images on one machine and without on another, and a deterministic
extractor's identity is its contract. So capture is a step *after* extraction,
over pages that already exist, writing only to `page_images` — a table nothing
in the token, chunk, or receipt path reads. Snapshots never touch citation
identity, which is what makes it safe for them to be best-effort.

Rendering is one poppler call per page rather than one for the document: a
200-page PDF at 200 dpi is a couple of gigabytes of decoded bitmap held at once,
and ingest now does this unprompted. Slower, bounded, and the shape the backfill
already used.
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import TYPE_CHECKING, Iterator

from ..kernel.errors import BackdraftError
from .base import PageImage

if TYPE_CHECKING:  # pragma: no cover - the registry imports this package
    from ..registry.store import Registry

__all__ = ["DEFAULT_DPI", "SnapshotError", "capture", "render"]

DEFAULT_DPI = 200
"""Render resolution. Matches the VLM extractor's, so both paths store alike."""

POPPLER_HINT = (
    "poppler is not installed, so PDF pages cannot be rendered here "
    "(macOS: `brew install poppler`; Debian/Ubuntu: `apt install poppler-utils`)"
)


class SnapshotError(BackdraftError):
    """Page snapshots could not be rendered on this machine."""


def render(
    source: Path,
    numbers: Iterator[int] | list[int],
    *,
    dpi: int = DEFAULT_DPI,
    config: dict | None = None,
) -> Iterator[tuple[int, PageImage]]:
    """Render the named pages of `source`, one WebP snapshot each, in order.

    The encoding budget is `BACKDRAFT_SNAPSHOT_MAX_HEIGHT` (pixels, downscaled
    to fit) and `BACKDRAFT_SNAPSHOT_QUALITY` — display knobs, since no token
    derives from pixels. Raises `SnapshotError` when this machine cannot render
    PDFs at all, or when poppler refuses this particular file.
    """
    try:
        from PIL import Image  # noqa: F401  (pdf2image needs it anyway)
        from pdf2image import convert_from_path
        from pdf2image.exceptions import PopplerNotInstalledError
    except ImportError as error:
        raise SnapshotError(
            "the PDF rendering dependencies are missing — "
            f"reinstall backdraft to restore them ({error})"
        ) from error
    from .vlm_settings import snapshot_max_height, snapshot_quality

    max_height = snapshot_max_height(config)
    quality = snapshot_quality(config)
    for number in numbers:
        try:
            images = convert_from_path(
                str(source), dpi=dpi, fmt="png",
                first_page=number, last_page=number,
            )
        except PopplerNotInstalledError as error:
            raise SnapshotError(POPPLER_HINT) from error
        except Exception as error:  # noqa: BLE001 - pdf2image raises broadly
            raise SnapshotError(f"could not render page {number} of {source}: {error}") from error
        if not images:
            raise SnapshotError(f"{source} has no page {number} to render")
        image = images[0]
        if image.height > max_height:
            scale = max_height / image.height
            image = image.resize((max(1, round(image.width * scale)), max_height))
        buffer = io.BytesIO()
        image.save(buffer, format="WEBP", quality=quality)
        yield number, PageImage(
            data=buffer.getvalue(), format="webp",
            width=image.width, height=image.height,
        )


def capture(
    registry: Registry,
    slug: str,
    source: Path,
    *,
    dpi: int = DEFAULT_DPI,
    config: dict | None = None,
) -> Iterator[tuple[int, PageImage]]:
    """Render every page of the current extraction and store it as its snapshot.

    Yields each `(number, image)` as it lands, so a caller can report progress
    per page or just count them. Storage is one commit per page: an interrupted
    capture leaves the pages it finished, and re-running replaces them.
    """
    extraction_id = registry.current_extraction_id(slug)
    if extraction_id is None:
        raise SnapshotError(f"{slug} has no current extraction to snapshot")
    numbers = [page.number for page in registry.pages(slug)]
    for number, image in render(source, numbers, dpi=dpi, config=config):
        registry.save_page_image(
            extraction_id, number,
            data=image.data, format=image.format,
            width=image.width, height=image.height,
        )
        yield number, image
