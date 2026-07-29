"""The fmt parity table: one set of vectors for `fmt_cell` and `fmtCell`.

The Python formatter (`fmt.fmt_cell`, server-rendered cell windows) and the JS
one (`fmtCell` in `assets.SCRIPT`, the client's full-sheet view) are deliberate
duplicates that must format identically forever — a reader who sees `12%` in
the window and `13%` in the sheet has found a bug, not a discrepancy in the
sources. Python is authoritative; `tests/test_fmt_parity.py` runs both sides
over this table.

Each vector is `(raw, fmt, expected)`: the verbatim cell value as the sidecar
carries it, the Excel number-format string (None where the workbook had none —
ingest never stores `General`), and the display string both formatters must
produce. The tie vectors (12.5%, 2.5, 1,234.5) are load-bearing: Python rounds
half to even, and the JS had to be told to.
"""

from __future__ import annotations

VECTORS: list[tuple[str, str | None, str]] = [
    # percent formats: 0% / 0.0% / 0.00%
    ("0.0765", "0%", "8%"),
    ("0.0765", "0.0%", "7.6%"),
    ("0.0765", "0.00%", "7.65%"),
    ("0.125", "0%", "12%"),  # exact tie: 12.5 rounds to even
    ("-0.033", "0.0%", "-3.3%"),
    ("1", "0%", "100%"),
    # fixed decimals: 0.0 / 0.00
    ("1.5", "0.0", "1.5"),
    ("2.345", "0.00", "2.35"),
    ("2.5", "0", "2"),  # exact tie
    ("0.03125", "0.0000", "0.0312"),  # exact tie at the fourth place
    ("-1234.567", "0.00", "-1234.57"),
    # thousands grouping
    ("24850000", "#,##0", "24,850,000"),
    ("1234.5", "#,##0", "1,234"),  # exact tie
    ("-9876543", "#,##0", "-9,876,543"),
    ("1234.5", "#,##0.0", "1,234.5"),
    # currency: bare $ and quoted symbols
    ("24850000", '"$"#,##0', "$24,850,000"),
    ("1487400", '"€"#,##0', "€1,487,400"),
    ("-2500", '"$"#,##0', "$-2,500"),
    ("1234.565", '"$"#,##0.00', "$1,234.57"),
    # no format: the fmt_number fallback
    ("0.0575", None, "0.0575"),
    ("24850000", None, "24,850,000"),
    ("hello", None, "hello"),
    ("1234.5", None, "1,234"),  # exact tie in the fallback's tail branch
    ("1000000000000000", None, "1,000,000,000,000,000"),
    # "General" is filtered at ingest (extract/xlsx.py) and never stored;
    # were it to leak through, both sides agree on the (degenerate) result
    ("0.0575", "General", "0"),
    ("hello", "General", "hello"),
    # non-numeric values pass through any format untouched
    ("Debt Yield", "#,##0", "Debt Yield"),
    ("2026-03-18", "0.00", "2026-03-18"),
    # negative numbers, bare
    ("-0.5", None, "-0.5000"),
    ("-42", None, "-42"),
    # negative zero: Python's int() drops the sign, its decimal formats keep it
    ("-0", None, "0"),
    ("-0", "0.0", "-0.0"),
    # the empty cell
    ("", None, ""),
    ("", "0.00", ""),
]
