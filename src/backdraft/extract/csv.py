"""CSV files: a workbook with one sheet.

The representation is the xlsx one wholesale — a markdown values table with
in-band `[B2]` refs, one `CellValue` per populated cell — so cell citations,
windows, and the artifact's sheet view work identically. The sheet is named
after the file's stem, which is what a reader would call it.

Deterministic and keyless: stdlib `csv` with dialect sniffing, utf-8 first
(BOM tolerated) and latin-1 as the fallback that cannot fail. The same
hardening as workbooks applies — row/column caps and an honest partial-view
note — because "someone exported this from something" is the whole genre.
"""

from __future__ import annotations

import csv as _csv
from pathlib import Path
from typing import Iterator

from .base import ExtractedPage, Extractor, ExtractionError, register
from .sheet import MAX_COLS, MAX_ROWS, bounds, partial_title, render_rows

__all__ = ["CsvExtractor", "EXTRACTOR"]

_MEDIA_TYPES = frozenset({"csv"})
_SUFFIXES = frozenset({".csv", ".tsv"})

_SNIFF_BYTES = 64 * 1024
"""How much of the file the dialect sniffer sees."""


class CsvExtractor:
    """One sheet per file. Deterministic: bytes in, markdown out."""

    name = "csv"
    version = "1"
    deterministic = True

    def can_handle(self, path: Path, media_type: str) -> bool:
        return media_type in _MEDIA_TYPES or path.suffix.lower() in _SUFFIXES

    def extract(self, path: Path, config: dict) -> Iterator[ExtractedPage]:
        text = _read_text(path)
        dialect = _dialect(text, path)
        reported_rows = 0
        reported_cols = 0
        grid: list[list[str]] = []
        for row in _csv.reader(text.splitlines(), dialect=dialect):
            reported_rows += 1
            reported_cols = max(reported_cols, len(row))
            if reported_rows <= MAX_ROWS:
                grid.append([cell for cell in row[:MAX_COLS]])

        name = path.stem
        rows, cols = bounds(grid)
        if not rows or not cols:
            yield ExtractedPage(
                number=1, kind="sheet", name=name,
                text=partial_title(name, rows, cols, reported_rows, reported_cols),
                cells=[],
            )
            return
        table, cells = render_rows(grid, rows, cols)
        title = partial_title(
            name, rows, cols, max(reported_rows, rows), max(reported_cols, cols)
        )
        yield ExtractedPage(
            number=1, kind="sheet", name=name,
            text=f"{title}\n\n{table}", cells=cells,
        )


def _read_text(path: Path) -> str:
    """The file as text: utf-8 (BOM tolerated) first, latin-1 as the floor."""
    try:
        data = path.read_bytes()
    except OSError as error:
        raise ExtractionError(f"could not read {path}: {error}") from error
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("latin-1")


def _dialect(text: str, path: Path):  # noqa: ANN202 - csv.Dialect subclass
    """The sniffed dialect; tabs for .tsv and excel-default when sniffing fails."""
    sample = text[:_SNIFF_BYTES]
    try:
        return _csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except _csv.Error:
        if path.suffix.lower() == ".tsv":
            return _csv.excel_tab
        return _csv.excel


EXTRACTOR: Extractor = CsvExtractor()
register(EXTRACTOR)
