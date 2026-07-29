"""Legacy .xls workbooks: one page per sheet, values only, via calamine.

The rendering is the shared sheet representation wholesale — the markdown
values table with in-band `[B10]` refs, the same caps and partial-view
titles — so a workbook saved as .xls snapshots the same shape it would as
.xlsx. calamine reads values, not styling, which is deliberate: no `meta`
rides on these pages, and the artifact's sheet view degrades to plain cells.
calamine returns typed values, so the shared formatter applies — integers
render without a trailing ".0", exactly as openpyxl values do.

Behind the `[xls]` extra: python-calamine is a Rust reader most installs
never need. The import failure below is re-raised with the install nudge so
`get("xls")` reports it, and `auto` skips this extractor when the extra is
absent (extract.base.select tolerates unavailable optional extractors).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterator

try:
    from python_calamine import CalamineWorkbook
except ImportError as _error:  # pragma: no cover - exercised via base.get
    raise ImportError("legacy .xls needs: install 'backdraft[xls]'") from _error

from .base import ExtractedPage, Extractor, ExtractionError, register
from .sheet import MAX_COLS, MAX_ROWS, bounds, partial_title, render_rows

__all__ = ["XlsExtractor", "EXTRACTOR"]

_MEDIA_TYPES = frozenset({"xls"})
_SUFFIXES = frozenset({".xls"})


class XlsExtractor:
    """calamine workbook reader. Deterministic: values in, markdown out."""

    name = "xls"
    version = "1"
    deterministic = True

    def can_handle(self, path: Path, media_type: str) -> bool:
        return media_type in _MEDIA_TYPES or path.suffix.lower() in _SUFFIXES

    def extract(self, path: Path, config: dict) -> Iterator[ExtractedPage]:
        try:
            workbook = CalamineWorkbook.from_path(str(path))
        except Exception as error:  # noqa: BLE001 - calamine raises broadly
            raise ExtractionError(f"could not open {path}: {error}") from error
        for number, name in enumerate(workbook.sheet_names, start=1):
            yield _sheet(workbook, number, name)


def _sheet(workbook: Any, number: int, name: str) -> ExtractedPage:
    full = workbook.get_sheet_by_name(name).to_python(skip_empty_area=False)
    reported_rows = len(full)
    reported_cols = max((len(row) for row in full), default=0)
    grid = [list(row[:MAX_COLS]) for row in full[:MAX_ROWS]]

    rows, cols = bounds(grid)
    if not rows or not cols:
        return ExtractedPage(
            number=number, kind="sheet", name=name,
            text=partial_title(name, rows, cols, reported_rows, reported_cols),
            cells=[],
        )
    table, cells = render_rows(grid, rows, cols)
    title = partial_title(
        name, rows, cols, max(reported_rows, rows), max(reported_cols, cols)
    )
    return ExtractedPage(
        number=number, kind="sheet", name=name,
        text=f"{title}\n\n{table}", cells=cells,
    )


EXTRACTOR: Extractor = XlsExtractor()
register(EXTRACTOR)
