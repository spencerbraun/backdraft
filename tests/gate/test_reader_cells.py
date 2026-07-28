"""`backdraft cell`: direct cell-token minting through the gate."""

from __future__ import annotations

import pytest

from backdraft.gate.reader import GateError, cells


def test_cell_minting_prints_token_and_value_and_records_shown(fake_gate_registry) -> None:
    output = cells(
        fake_gate_registry, "rent-model", ["rent-roll!B2"], session="s1"
    )
    (line,) = output.splitlines()
    assert line.startswith("[bd:rent-model:rent-roll!B2:")
    anchor = next(
        anchor
        for anchor in fake_gate_registry.anchors_for_page("rent-model", 1)
        if str(anchor.locator) == "rent-roll!B2"
    )
    assert anchor.receipt.snippet in line
    assert fake_gate_registry.was_shown("s1", anchor.token)


def test_unknown_sheet_and_empty_cell_are_usage_errors(fake_gate_registry) -> None:
    with pytest.raises(GateError, match="no sheet"):
        cells(fake_gate_registry, "rent-model", ["nope!B10"], session=None)
    with pytest.raises(GateError, match="mint nothing"):
        cells(fake_gate_registry, "rent-model", ["rent-roll!Z99"], session=None)
    with pytest.raises(GateError, match="sheet!REF"):
        cells(fake_gate_registry, "rent-model", ["B10"], session=None)
