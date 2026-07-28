"""Markdown and plain text: the whole file is one page.

A text file has no native pagination, so it gets page 1 and the chunker supplies
the sub-page structure — `bd:notes:p1.c3:a7f3` addresses the third paragraph
group. NOTE: the spec leaves heading-path and line-range locator forms open; page
1 plus chunks needs no new locator form, so v0 uses it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterator

from .base import ExtractedPage, Extractor, register

__all__ = ["TextExtractor", "EXTRACTOR"]


class TextExtractor:
    """md/txt passthrough. Deterministic: it is a decode."""

    name = "text"
    version = "1"
    deterministic = True

    def can_handle(self, path: Path, media_type: str) -> bool:
        return media_type == "text"

    def extract(self, path: Path, config: dict) -> Iterator[ExtractedPage]:
        """The file's text as page 1.

        NOTE: undecodable bytes are replaced rather than raising. A snapshot with
        a replacement character still anchors; a failed ingest anchors nothing.
        Universal newlines mean CRLF and LF files snapshot identically.
        """
        yield ExtractedPage(
            number=1,
            kind="page",
            text=path.read_text(encoding="utf-8", errors="replace"),
        )


EXTRACTOR: Extractor = TextExtractor()
register(EXTRACTOR)
