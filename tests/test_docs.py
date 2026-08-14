"""The repo's own documents, checked for the ways they rot silently.

DESIGN.md's decision log is appended to a row at a time, by an agent, on the day
the decision is made. That is the whole point of it — and it means the file's
structure is maintained by whoever is least likely to re-read the file. A stray
blank line between two rows ends the markdown table and starts a new one, which
costs nothing to write, renders wrong everywhere the file is read, and shows up
in no test and no diff review. It has happened. So it is pinned here.
"""

from __future__ import annotations

import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parent.parent
DESIGN = REPO / "DESIGN.md"

ROW = re.compile(r"^\| (\d{4}-\d{2}-\d{2}) \|")


def _decision_log() -> list[str]:
    """The decision table's lines, from its header to the blank line that ends it."""
    lines = DESIGN.read_text(encoding="utf-8").split("\n")
    start = next(i for i, line in enumerate(lines) if line.startswith("| Date |"))
    end = next(i for i in range(start, len(lines)) if not lines[i].strip())
    return lines[start:end]


def test_the_decision_log_is_one_unbroken_table() -> None:
    """Every dated row sits in the table, not in one of two tables."""
    dated = [line for line in DESIGN.read_text(encoding="utf-8").split("\n") if ROW.match(line)]
    assert dated, "the decision log has no rows"
    # The table is its header, its separator, then one row per decision.
    assert len(_decision_log()) - 2 == len(dated), (
        "a dated row falls outside the decision table — a blank line between two "
        "rows splits it in two, and markdown renders the second half as a new table"
    )


def test_the_decision_log_reads_oldest_first() -> None:
    """Appended daily, so out-of-order means a row landed in the wrong place."""
    dates = [match.group(1) for line in _decision_log() if (match := ROW.match(line))]
    assert dates == sorted(dates), "decision rows are out of date order"
