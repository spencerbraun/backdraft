"""Images (VLM extractor): a photographed or scanned page is a one-page document.

This is the VLM pipeline minus pdf2image — the file already is the page. The
image itself is stored as the page's snapshot (re-encoded WebP, same as PDF
page snapshots), which makes it the reproducible half of the receipt; the
model's transcription is the readable half. `deterministic = False` for the
same honest reason as the PDF path.

There is no keyless floor: an image has no text layer, so without the extra
and a backdraft-scoped key there is nothing true to snapshot, and ingest says
so rather than storing an empty page.
"""

from __future__ import annotations

import io
import tempfile
from pathlib import Path
from types import MappingProxyType
from typing import Iterator

from openai import OpenAI
from PIL import Image

from .base import ExtractedPage, Extractor, ExtractionError, PageImage, register
from .snapshots import ENCODE_KEYS
from .vlm import _transcribe
from .vlm_settings import (
    PROVIDER_KEYS,
    client_settings,
    retries,
    snapshot_max_height,
    snapshot_quality,
    timeout_seconds,
    with_retries,
)

__all__ = ["ImageExtractor", "EXTRACTOR"]

_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".tif", ".tiff", ".webp"})


class ImageExtractor:
    """image file -> vision model -> one page. Non-deterministic by construction."""

    name = "image"
    version = "1"
    deterministic = False
    # No `dpi`: the file already is the page, so there is nothing to rasterize —
    # this path only fits and encodes what it was handed.
    config_keys = MappingProxyType({**PROVIDER_KEYS, **ENCODE_KEYS})

    def can_handle(self, path: Path, media_type: str) -> bool:
        return media_type == "image" or path.suffix.lower() in _SUFFIXES

    def extract(self, path: Path, config: dict) -> Iterator[ExtractedPage]:
        """Yield the single page, transcribed by the model.

        Every key is optional and every one is declared in `config_keys`.
        Provider resolution is `client_settings` — the same consent rules as
        PDFs.
        """
        model, api_key, base_url = client_settings(config)
        client = OpenAI(api_key=api_key, base_url=base_url, timeout=timeout_seconds(config))

        try:
            image = Image.open(path)
            image.load()
        except Exception as error:  # noqa: BLE001 - PIL raises broadly
            raise ExtractionError(f"could not open {path} as an image: {error}") from error
        if image.mode not in ("RGB", "L"):
            image = image.convert("RGB")
        max_height = snapshot_max_height(config)
        if image.height > max_height:
            scale = max_height / image.height
            image = image.resize((max(1, round(image.width * scale)), max_height))

        buffer = io.BytesIO()
        image.save(buffer, format="WEBP", quality=snapshot_quality(config))
        snapshot = PageImage(
            data=buffer.getvalue(), format="webp",
            width=image.width, height=image.height,
        )

        with tempfile.TemporaryDirectory() as workdir:
            page_path = Path(workdir) / "page_0001.png"
            image.save(page_path, format="PNG")
            text = with_retries(
                lambda: _transcribe(client, model, page_path),
                attempts=retries(config),
            )
        yield ExtractedPage(number=1, kind="page", text=text, image=snapshot)


EXTRACTOR: Extractor = ImageExtractor()
register(EXTRACTOR)
