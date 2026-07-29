"""PDF text layer, via pdfplumber. One `ExtractedPage` per PDF page.

This extractor reads the text the PDF already carries; it does not look at the
pixels. A scan has no text layer, so it produces nothing to anchor — that is an
error naming the vision extractor rather than an empty registry entry, because a
document that silently ingests as blank is worse than one that refuses.

**Paragraph reconstruction.** `page.extract_text()` joins every line with a
single `\\n` and never emits a blank one, because a PDF has no paragraphs — it
has glyphs at coordinates. The chunker's first rule splits on blank lines, so
without this step that rule is dead on every PDF and sub-page anchors only ever
appear via the long-segment split. The paragraph break is still *in* the file,
just expressed as vertical space, so this extractor reads it back off the
geometry: lines in document order, the page's median line pitch as the body
leading, and a blank line inserted wherever the pitch jumps past
`PARAGRAPH_GAP_RATIO` times that median.

The line texts themselves are pdfplumber's own — `"\\n".join(extract_text_lines())`
is character-for-character `extract_text()` — so this only ever *adds* blank
lines. NOTE: it is a heuristic over a format that does not carry the answer.
A layout it reads wrong shifts chunk boundaries; it does so deterministically,
which is the property anchors actually depend on.
"""

from __future__ import annotations

import statistics
from pathlib import Path
from typing import Any, Iterator

import pdfplumber

from .base import ExtractedPage, Extractor, ExtractionError, register

__all__ = ["PARAGRAPH_GAP_RATIO", "PdfTextExtractor", "EXTRACTOR", "page_text"]

PARAGRAPH_GAP_RATIO = 1.5
"""A line starting this much further down than the median pitch opens a paragraph.

Tuned on the demo corpus, whose gaps fall in three tight clusters: 14.0pt
between body lines, 24.0pt between paragraphs (1.71x), and 31.1pt below a
heading (2.22x). 1.5 sits in the empty band between the first two clusters,
which is where typographic convention puts it too — space-after under half the
leading reads as one block, over half reads as a break.
"""

_NO_TEXT_LAYER = (
    "{path} has no text layer on any page — it is probably a scan. "
    "Use the vision extractor: set BACKDRAFT_VLM_API_KEY (env or "
    ".backdraft/env), then `backdraft ingest {path} --extractor vlm`."
)


class PdfTextExtractor:
    """pdfplumber text-layer extraction. Deterministic for a given pdfplumber."""

    name = "pdf-text"
    version = "1"
    deterministic = True

    def can_handle(self, path: Path, media_type: str) -> bool:
        return media_type == "pdf"

    def extract(self, path: Path, config: dict) -> Iterator[ExtractedPage]:
        """Yield one page per PDF page, in file order.

        Individual blank pages are yielded as empty pages — they are part of the
        document and their numbers must not shift. Only a PDF with no text
        anywhere raises.
        """
        yield from self._pages(path)

    def _pages(self, path: Path) -> Iterator[ExtractedPage]:
        found_text = False
        try:
            document = pdfplumber.open(path)
        except Exception as error:  # noqa: BLE001 - pdfminer raises broadly
            raise ExtractionError(f"could not open {path}: {error}") from error
        with document:
            for number, page in enumerate(document.pages, start=1):
                text = page_text(page)
                if text.strip():
                    found_text = True
                yield ExtractedPage(number=number, kind="page", text=text)
        if not found_text:
            raise ExtractionError(_NO_TEXT_LAYER.format(path=path))


def page_text(page: Any) -> str:
    """One page's text, with paragraph breaks restored from its layout.

    Falls back to `extract_text()` whenever the geometry cannot answer: no
    lines, a single line, or a degenerate median pitch. The fallback is the
    old behaviour exactly, so a PDF this cannot read is no worse off.
    """
    try:
        lines = page.extract_text_lines()
    except Exception:  # noqa: BLE001 - pdfminer raises broadly; never lose the page
        lines = []
    if len(lines) < 2:
        return page.extract_text() or ""
    return _join(lines)


def _join(lines: list[dict[str, Any]]) -> str:
    """Line texts joined, blank-line separated wherever the pitch jumps."""
    gaps = [
        float(later["top"]) - float(earlier["top"])
        for earlier, later in zip(lines, lines[1:], strict=False)
    ]
    pitch = statistics.median(gaps)
    if pitch <= 0:
        # Overlapping or unordered lines: no baseline to compare against.
        return "\n".join(line["text"] for line in lines)
    threshold = pitch * PARAGRAPH_GAP_RATIO
    out = [lines[0]["text"]]
    for gap, line in zip(gaps, lines[1:], strict=True):
        out.append("\n\n" if gap > threshold else "\n")
        out.append(line["text"])
    return "".join(out)


EXTRACTOR: Extractor = PdfTextExtractor()
register(EXTRACTOR)
