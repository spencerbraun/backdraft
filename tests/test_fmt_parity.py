"""fmt_cell and fmtCell format identically — held together by one table.

The Python formatter renders the server-side cell windows; the JS one, mirrored
inside the behavior script, renders the client's full-sheet view. They are
deliberate duplicates: `render/html/fmt_vectors.py` is the single table both
must satisfy, Python authoritatively and the JS by extraction — the actual
function text is cut out of `assets.SCRIPT` and run under node, so the test
exercises the bytes the artifact ships, not a transcription of them. Without
node on PATH the JS half skips; the Python half always runs.
"""

from __future__ import annotations

import json
import shutil
import subprocess

import pytest

from backdraft.render.html.assets import SCRIPT
from backdraft.render.html.fmt import fmt_cell
from backdraft.render.html.fmt_vectors import VECTORS


@pytest.mark.parametrize("raw, fmt, expected", VECTORS)
def test_fmt_cell_matches_every_vector(raw: str, fmt: str | None, expected: str) -> None:
    assert fmt_cell(raw, fmt) == expected


def _script_formatters() -> str:
    """The `fixed`/`fmt`/`fmtCell` function text, verbatim from the script."""
    start = SCRIPT.index("function fixed(")
    end = SCRIPT.index("function cellStyle")
    return SCRIPT[start:end]


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not on PATH")
def test_js_fmt_cell_matches_every_vector() -> None:
    harness = (
        _script_formatters()
        + "\nconst vectors = JSON.parse(process.argv[1]);\n"
        + "console.log(JSON.stringify(vectors.map(\n"
        + "  ([raw, fmt]) => fmtCell(raw, fmt === null ? undefined : fmt))));\n"
    )
    payload = json.dumps([[raw, fmt] for raw, fmt, _ in VECTORS])
    result = subprocess.run(
        ["node", "-e", harness, payload],
        capture_output=True,
        text=True,
        check=True,
    )
    got = json.loads(result.stdout)
    expected = [expected for _, _, expected in VECTORS]
    mismatches = [
        (raw, fmt, want, js)
        for (raw, fmt, want), js in zip(VECTORS, got, strict=True)
        if js != want
    ]
    assert not mismatches, f"fmtCell diverges from fmt_cell: {mismatches}"
    assert got == expected
