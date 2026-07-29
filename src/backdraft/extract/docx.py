"""Word documents: heading sections become pages.

A DOCX has no pages — pagination is a print-time artifact of fonts and
margins, and re-flowing it would move every anchor. Headings are the
document's own stable structure, so they carry the pagination. The rule,
pinned: a paragraph's effective outline level is `w:outlineLvl` from its
direct formatting, else the first `w:outlineLvl` found walking its style
chain (Heading 1 carries 0, Heading 2 carries 1). The split level is the
smallest outline level present in the document among {0, 1} — Heading 1 when
any exist, else Heading 2. A paragraph at the split level starts a new
section and is the first line of that section; content before the first
heading is section 1; a document with no level-0/1 headings is a single
section. Each section is one `ExtractedPage` with kind="page", so locators
stay the ordinary `pN.cM` — no token-grammar change.

A page is titled by its heading, truncated to 80 characters; a single-section
document (and a preamble section before the first heading) takes the file
stem. Body content is read in strict document order via
`document.iter_inner_content()`: paragraphs become text blocks separated by
blank lines (the chunker splits on blank lines), consecutive empty paragraphs
collapse, and tables render as markdown pipe tables in place — first row as
the header — like sheet rows do.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterator

from docx import Document as open_docx

from .base import ExtractedPage, Extractor, ExtractionError, register

__all__ = ["DocxExtractor", "EXTRACTOR"]

_MEDIA_TYPES = frozenset({"docx"})
_SUFFIXES = frozenset({".docx"})

MAX_TITLE_CHARS = 80
"""A page title is its heading, truncated to this."""


class DocxExtractor:
    """python-docx reader. Deterministic: body XML in, section pages out."""

    name = "docx"
    version = "1"
    deterministic = True

    def can_handle(self, path: Path, media_type: str) -> bool:
        return media_type in _MEDIA_TYPES or path.suffix.lower() in _SUFFIXES

    def extract(self, path: Path, config: dict) -> Iterator[ExtractedPage]:
        try:
            document = open_docx(str(path))
        except Exception as error:  # noqa: BLE001 - python-docx raises broadly
            raise ExtractionError(f"could not open {path}: {error}") from error
        items = list(_items(document))
        split = _split_level(items)
        for number, (title, blocks) in enumerate(
            _sections(items, split, path.stem), start=1
        ):
            yield ExtractedPage(
                number=number,
                kind="page",
                name=title[:MAX_TITLE_CHARS],
                text="\n\n".join(blocks),
            )


def _items(document: Any) -> Iterator[tuple[int | None, str]]:
    """The body in strict document order: (outline level, block text) pairs.

    Tables carry level None; empty paragraphs are dropped here, which is what
    collapses consecutive empty paragraphs — blocks are joined by one blank
    line regardless of how many separated them.
    """
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    for item in document.iter_inner_content():
        if isinstance(item, Paragraph):
            text = item.text.strip()
            if text:
                yield _outline_level(item), text
        elif isinstance(item, Table):
            rendered = _table(item)
            if rendered:
                yield None, rendered


def _outline_level(paragraph: Any) -> int | None:
    """`w:outlineLvl` from direct formatting, else the paragraph's style chain."""
    level = _outline_of(paragraph._p)
    if level is not None:
        return level
    style = paragraph.style
    seen: set[str | None] = set()
    while style is not None and style.style_id not in seen:
        seen.add(style.style_id)
        level = _outline_of(style.element)
        if level is not None:
            return level
        style = style.base_style
    return None


def _outline_of(element: Any) -> int | None:
    values = element.xpath("./w:pPr/w:outlineLvl/@w:val")
    return int(values[0]) if values else None


def _split_level(items: list[tuple[int | None, str]]) -> int | None:
    """The smallest outline level present among {0, 1}, or None."""
    levels = {level for level, _ in items if level in (0, 1)}
    return min(levels) if levels else None


def _sections(
    items: list[tuple[int | None, str]], split: int | None, stem: str
) -> Iterator[tuple[str, list[str]]]:
    """(title, blocks) per section. Always at least one, even for an empty body."""
    title = stem
    blocks: list[str] = []
    started = False
    for level, text in items:
        if split is not None and level == split:
            if started or blocks:
                yield title, blocks
            title = text
            blocks = [text]
            started = True
            continue
        blocks.append(text)
    yield title, blocks


def _table(table: Any) -> str:
    """A markdown pipe table, first row as the header."""
    rows = [
        [_cell(cell.text) for cell in row.cells]
        for row in table.rows
    ]
    if not rows:
        return ""
    lines = ["| " + " | ".join(rows[0]) + " |"]
    lines.append("|" + "|".join(["---"] * len(rows[0])) + "|")
    for row in rows[1:]:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def _cell(text: str) -> str:
    """A table cell on one line, with markdown's `|` neutralized."""
    return " ".join(text.split()).replace("|", "\\|")


EXTRACTOR: Extractor = DocxExtractor()
register(EXTRACTOR)
