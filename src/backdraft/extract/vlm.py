"""The VLM extractor: pdf -> page images -> a vision model, one page at a time.

The shape is simple and kept thin: render each page, ask an OpenAI-compatible
vision model for markdown, use the answer as the page. This is the recommended
path for real PDFs — glossy layouts, info boxes, scans — because the snapshot is
the receipt, and the model's clean reading of the page beats scrambled
text-layer order.

The client is always the `openai` SDK; a router is injected through `base_url`.
The default provider is OpenRouter running Gemini 3.1 Flash Lite; any
OpenAI-compatible provider works through `base_url`. See `client_settings`.

`deterministic = False`, honestly: the same PDF ingested twice yields different
text, so the registry never short-circuits a re-ingest and every anchor whose
snippet moved gets a new token. That is the correct, visible outcome — a model's
transcription is not a snapshot anyone can reproduce.

`--extractor auto` prefers this extractor for PDFs when it is ready (installed,
key configured); otherwise `auto` falls back to the text layer and the CLI says
so. The deps ship with backdraft; `pdf2image` requires poppler on the PATH.
"""

from __future__ import annotations

import base64
import io
import sys
import tempfile
from pathlib import Path
from typing import Iterator

from openai import OpenAI
from pdf2image import convert_from_path

from .base import ExtractedPage, Extractor, ExtractionError, PageImage, register
from .vlm_settings import (  # noqa: F401  (re-exported)
    DEFAULT_MODEL,
    MAX_IMAGE_HEIGHT,
    OPENROUTER_BASE_URL,
    SNAPSHOT_QUALITY,
    client_settings,
    concurrency,
    retries,
    run_ordered,
    snapshot_max_height,
    snapshot_quality,
    timeout_seconds,
    with_retries,
)

__all__ = [
    "DEFAULT_MODEL",
    "OPENROUTER_BASE_URL",
    "SYSTEM_PROMPT",
    "VlmExtractor",
    "EXTRACTOR",
    "client_settings",
]

DEFAULT_DPI = 200

SYSTEM_PROMPT = (
    "Convert this document page to markdown. Follow these rules strictly:\n\n"
    "VERBATIM TEXT: Write all visible text exactly as shown — headings, labels, "
    "captions, data values.\n\n"
    "VISUAL ELEMENTS: Use [IMAGE: description], [MAP: description] or "
    "[CHART: description] brackets. Describe what the visual communicates.\n\n"
    "TABLES: Use markdown table format with all data preserved.\n\n"
    "STRUCTURE: Use markdown headings (#, ##) to reflect page hierarchy.\n\n"
    "DO NOT: add commentary, preambles like 'Here is...', or explanatory text "
    "outside brackets. Never invent URLs.\n\n"
    "Output only the converted content."
)


class VlmExtractor:
    """pdf -> page images -> vision model. Non-deterministic by construction."""

    name = "vlm"
    version = "1"
    deterministic = False

    def can_handle(self, path: Path, media_type: str) -> bool:
        return media_type == "pdf"

    def extract(self, path: Path, config: dict) -> Iterator[ExtractedPage]:
        """Yield one page per PDF page, transcribed by the model.

        Config keys (all optional): `model`, `base_url`, `api_key`, `dpi`.
        Provider resolution is `client_settings`; OpenRouter is first-class.
        """
        model, api_key, base_url = client_settings(config)
        client = OpenAI(api_key=api_key, base_url=base_url, timeout=timeout_seconds(config))
        dpi = int(config.get("dpi") or DEFAULT_DPI)
        attempts = retries(config)
        max_height = snapshot_max_height(config)
        quality = snapshot_quality(config)

        with tempfile.TemporaryDirectory() as workdir:
            try:
                images = convert_from_path(str(path), dpi=dpi, fmt="png")
            except Exception as error:  # noqa: BLE001 - pdf2image raises broadly
                raise ExtractionError(f"could not render {path} to images: {error}") from error
            image_paths: list[Path] = []
            snapshots: list[PageImage] = []
            for number, image in enumerate(images, start=1):
                if image.height > max_height:
                    scale = max_height / image.height
                    image = image.resize(
                        (max(1, round(image.width * scale)), max_height)
                    )
                image_path = Path(workdir) / f"page_{number:04d}.png"
                image.save(image_path, format="PNG")
                image_paths.append(image_path)
                buffer = io.BytesIO()
                image.save(buffer, format="WEBP", quality=quality)
                snapshots.append(PageImage(
                    data=buffer.getvalue(), format="webp",
                    width=image.width, height=image.height,
                ))

            texts = run_ordered(
                image_paths,
                lambda image_path: with_retries(
                    lambda: _transcribe(client, model, image_path), attempts=attempts
                ),
                workers=concurrency(config),
                progress=_progress(path.name, len(image_paths)),
            )
            for number, text in enumerate(texts, start=1):
                yield ExtractedPage(
                    number=number, kind="page", text=text,
                    image=snapshots[number - 1],
                )


def _progress(name: str, total: int):
    """Progress to stderr: a live counter on a tty, one line per page otherwise."""
    tty = sys.stderr.isatty()

    def report(done: int, _total: int) -> None:
        if tty:
            end = "\n" if done == total else "\r"
            print(f"vlm: {name}  {done}/{total} pages", file=sys.stderr, end=end, flush=True)
        else:
            print(f"vlm: {name}  page {done}/{total}", file=sys.stderr, flush=True)

    return report


def _transcribe(client: OpenAI, model: str, image_path: Path) -> str:
    """One page image -> markdown. Raises `ExtractionError` on any API failure."""
    encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Extract text from this page."},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{encoded}"},
                        },
                    ],
                },
            ],
        )
    except Exception as error:  # noqa: BLE001 - client raises broadly
        raise ExtractionError(f"vlm call failed for {image_path.name}: {error}") from error
    return response.choices[0].message.content or ""


EXTRACTOR: Extractor = VlmExtractor()
register(EXTRACTOR)
