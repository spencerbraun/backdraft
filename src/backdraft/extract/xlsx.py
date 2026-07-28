"""Workbooks: one page per sheet, rendered as a markdown table with in-band refs.

This representation is what makes cell-level attribution work, because the
coordinates sit *in the text the model reads*:

```
## Sheet: rent-roll - Values View with cell references

| Row | A | B |
|---|---|---|
| 1 | [A1] Unit | [B1] Rent |
| 2 | [A2] 101 | [B2] 2400 |
```

A model that copies `2400` out of that table has already seen `[B2]`, so the
registry can compose `bd:model:rent-roll!B2:9e2f` for it. Nothing about the
location travels in a side channel.

The hardening here was earned on real files:
hard row/column caps, an inflated-dimension placeholder page (Excel formats empty
cells and reports a million rows), trailing empty row/column trimming, and cell
truncation. NOTE: the caps mean a snapshot can be a *partial* view of a sheet;
the page title says so, which is the honest failure the spec's "failures are
data" principle asks for.

Reader choice: openpyxl alone. python-calamine tolerates more malformed files,
but openpyxl is already a dependency (column-letter arithmetic, fixtures) and one
reader means one representation to keep golden. NOTE: if malformed workbooks show
up in practice, calamine belongs behind an optional fallback, not a second
default.
"""

from __future__ import annotations

from decimal import Decimal
from math import isfinite
from pathlib import Path
from typing import Any, Iterator

from openpyxl import load_workbook
from openpyxl.utils import get_column_letter

from ..kernel.model import CellValue
from .base import ExtractedPage, Extractor, ExtractionError, register

__all__ = ["MAX_COLS", "MAX_ROWS", "XlsxExtractor", "EXTRACTOR"]

MAX_ROWS = 2_000
"""Hard cap on rows scanned per sheet."""

MAX_COLS = 200
"""Hard cap on columns scanned per sheet."""

MAX_CELL_CHARS = 150
"""A cell longer than this is truncated with an ellipsis."""

_MEDIA_TYPES = frozenset({"xlsx"})
_SUFFIXES = frozenset({".xlsx", ".xlsm", ".xltx", ".xltm"})


class XlsxExtractor:
    """openpyxl workbook reader. Deterministic: values in, markdown out."""

    name = "xlsx"
    version = "1"
    deterministic = True

    def can_handle(self, path: Path, media_type: str) -> bool:
        return media_type in _MEDIA_TYPES or path.suffix.lower() in _SUFFIXES

    def extract(self, path: Path, config: dict) -> Iterator[ExtractedPage]:
        """Yield one page per sheet, in workbook order.

        Sheet names are yielded as the workbook spells them; the registry
        sanitizes them to the sheetref charset when it mints tokens.
        """
        try:
            workbook = load_workbook(path, data_only=True, read_only=True)
        except Exception as error:  # noqa: BLE001 - openpyxl raises broadly
            raise ExtractionError(f"could not open {path}: {error}") from error
        try:
            for number, name in enumerate(workbook.sheetnames, start=1):
                yield self._sheet(workbook[name], number, name)
        finally:
            workbook.close()

    def _sheet(self, worksheet: Any, number: int, name: str) -> ExtractedPage:
        reported_rows = worksheet.max_row or 0
        reported_cols = worksheet.max_column or 0
        if reported_rows > MAX_ROWS or reported_cols > MAX_COLS:
            return ExtractedPage(
                number=number,
                kind="sheet",
                name=name,
                text=_placeholder(name, reported_rows, reported_cols),
                cells=[],
            )

        grid = _read_grid(worksheet)
        rows, cols = _bounds(grid)
        if not rows or not cols:
            return ExtractedPage(
                number=number,
                kind="sheet",
                name=name,
                text=_title(name, rows, cols, reported_rows, reported_cols),
                cells=[],
            )

        table, cells = _render(grid, rows, cols)
        title = _title(name, rows, cols, reported_rows, reported_cols)
        return ExtractedPage(
            number=number,
            kind="sheet",
            name=name,
            text=f"{title}\n\n{table}",
            cells=cells,
        )


def _read_grid(worksheet: Any) -> list[list[Any]]:
    """The sheet's values, capped. Read once: read-only sheets stream."""
    return [
        list(row)
        for row in worksheet.iter_rows(
            min_row=1, max_row=MAX_ROWS, max_col=MAX_COLS, values_only=True
        )
    ]


def _has_data(value: Any) -> bool:
    """True if a cell holds data rather than formatting or emptiness."""
    return value is not None and bool(str(value).strip())


def _bounds(grid: list[list[Any]]) -> tuple[int, int]:
    """The (rows, cols) actually holding data — trailing empties trimmed off."""
    rows = 0
    cols = 0
    for row_index, row in enumerate(grid, start=1):
        for col_index, value in enumerate(row, start=1):
            if _has_data(value):
                rows = row_index
                cols = max(cols, col_index)
    return rows, cols


def _format_value(value: Any) -> str:
    """A cell as text: integers unadorned, floats at full precision, dates ISO-8601.

    Rounding here would be a correctness bug, not a display choice. The page text
    is the snapshot and the snapshot is the receipt: a cap rate stored as
    `0.0575` and written down as `0.058` cannot be value-traced against the claim
    "5.75%" that was read off it, and the cell anchor's snippet — the thing a
    reader is shown as proof — would disagree with the workbook.
    """
    if value is None:
        return ""
    if isinstance(value, bool):
        # NOTE: before the int branch — bool is an int and `str(int(True))` is "1".
        return str(value)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return _float_text(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _float_text(value: float) -> str:
    """A float as the shortest text that reads back as the same float.

    `repr` gives that shortest round-trip form, which is what keeps `0.0575` from
    becoming `0.057499999999999996`. Routing it through `Decimal` only drops the
    exponent, so a small rate reads as `0.000001` rather than `1e-06` — the form
    it has in the workbook, and the form a claim would quote.
    """
    if not isfinite(value):
        return repr(value)
    if value.is_integer():
        return str(int(value))
    return format(Decimal(repr(value)), "f")


def _cell_text(value: Any) -> str:
    """A formatted cell, truncated, with markdown's `|` neutralized."""
    text = _format_value(value).replace("\n", " ").replace("|", "\\|")
    if len(text) > MAX_CELL_CHARS:
        text = text[: MAX_CELL_CHARS - 3] + "..."
    return text


def _render(
    grid: list[list[Any]], rows: int, cols: int
) -> tuple[str, list[CellValue]]:
    """The markdown table and the cell values it carries.

    Every non-empty cell gets a `[B10]` prefix in the table and a `CellValue`
    whose `value` is the cell text *as it appears in the table* — the receipt has
    to be verbatim from the snapshot, truncation and all.
    """
    header = ["Row", *(get_column_letter(col) for col in range(1, cols + 1))]
    lines = [
        "| " + " | ".join(header) + " |",
        "|" + "|".join(["---"] * len(header)) + "|",
    ]
    cells: list[CellValue] = []
    for row_index in range(1, rows + 1):
        row = grid[row_index - 1] if row_index <= len(grid) else []
        rendered = [str(row_index)]
        for col_index in range(1, cols + 1):
            value = row[col_index - 1] if col_index <= len(row) else None
            text = _cell_text(value)
            if text:
                ref = f"{get_column_letter(col_index)}{row_index}"
                cells.append(CellValue(ref=ref, value=text))
                text = f"[{ref}] {text}"
            rendered.append(text)
        lines.append("| " + " | ".join(rendered) + " |")
    return "\n".join(lines), cells


def _title(name: str, rows: int, cols: int, reported_rows: int, reported_cols: int) -> str:
    """The page's heading, which says when the view is partial."""
    note = ""
    if reported_rows > rows or reported_cols > cols:
        note = f" (showing {rows}x{cols} of {reported_rows}x{reported_cols})"
    return f"## Sheet: {name}{note} - Values View with cell references"


def _placeholder(name: str, rows: int, cols: int) -> str:
    """The page a sheet gets when its reported dimensions are absurd."""
    return (
        f"## Sheet: {name}\n\n"
        f"**Sheet could not be processed.**\n\n"
        f"Reported dimensions ({rows:,} rows x {cols:,} columns) exceed processing "
        f"limits ({MAX_ROWS:,} x {MAX_COLS:,}). This typically occurs when Excel "
        f"applies formatting to empty cells, inflating the apparent sheet size."
    )


EXTRACTOR: Extractor = XlsxExtractor()
register(EXTRACTOR)
