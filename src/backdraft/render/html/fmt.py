"""Sheet-value display formatting.

`fmt_cell` renders a workbook value through its Excel number format for the
server-rendered cell windows; the behavior script (`assets.SCRIPT`) carries a
JS mirror, `fmtCell`, for the client-side full-sheet view. The two are
deliberate duplicates and must format identically — Python is authoritative,
and `tests/test_fmt_parity.py` holds them together over one shared vector
table (`fmt_vectors.py`).

Display only, everywhere: the record and every receipt keep the verbatim value.
"""

from __future__ import annotations

import re


def fmt_number(raw: str) -> str:
    """Sheet values display formatted; the record keeps the verbatim value."""
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return raw
    if value == int(value) and abs(value) < 1e15:
        return f"{int(value):,}"
    if 0 < abs(value) < 1:
        return f"{value:.4f}"
    return f"{value:,.0f}"


def _is_number(raw: str) -> bool:
    try:
        float(raw)
        return True
    except (TypeError, ValueError):
        return False


def fmt_cell(raw: str, fmt: str | None) -> str:
    """A sheet value displayed through its Excel number format.

    Covers the formats that carry meaning in evidence — percent, currency,
    grouping, fixed decimals — and falls back to `fmt_number` for the rest.
    Display only: the record and every receipt keep the verbatim value.
    """
    if not fmt or not _is_number(raw):
        return fmt_number(raw)
    value = float(raw)
    if "%" in fmt:
        match = re.search(r"0\.(0+)%", fmt)
        decimals = len(match.group(1)) if match else 0
        return f"{value * 100:.{decimals}f}%"
    match = re.search(r"0\.(0+)", fmt)
    decimals = len(match.group(1)) if match else 0
    grouped = "," in fmt
    text = f"{value:,.{decimals}f}" if grouped else f"{value:.{decimals}f}"
    quoted = re.search(r'"([^"]*)"', fmt)
    symbol = quoted.group(1) if quoted else ("$" if "$" in fmt else "")
    return symbol + text


def _width_px(width: float) -> int:
    """Excel column width units to pixels, clamped to sane bounds."""
    return max(40, min(400, round(float(width) * 8)))


def _style_attr(style: dict | None, *, cited: bool = False) -> str:
    """Inline CSS for one cell's workbook styling. A cited cell keeps the
    citation highlight: its fill and color are the citation's, not the sheet's."""
    if not style:
        return ""
    rules = []
    if style.get("b"):
        rules.append("font-weight:600")
    if not cited:
        if style.get("bg"):
            rules.append(f"background:#{style['bg']}")
        if style.get("fg"):
            rules.append(f"color:#{style['fg']}")
    return f' style="{";".join(rules)}"' if rules else ""
