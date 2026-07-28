"""Shared fixtures.

The gate's corpus lives here so the rendering tests and the ledger tests read the
same documents: a small PDF and a small workbook, both with explicit anchors.
"""

from __future__ import annotations

import pytest
from fake_registry import FakeDocumentRegistry, Ids, pdf_document, sheet_document

AUDIT_PAGES = [
    ["Cover. T12 Audit prepared for Acme Capital, March 2026."],
    [
        "The portfolio comprises 14 assets across three markets.",
        "Trailing twelve month net operating income was $4,102,880.",
    ],
    ["Occupancy averaged 93.4% over the period."],
]

# The markdown table exactly as `extract/xlsx.py` renders one; `sheet_document`
# puts the `## Sheet: …` title above it, which is where the page text's first
# line really comes from.
RENT_ROLL = [
    "| Row | A | B |",
    "|---|---|---|",
    "| 1 | [A1] Property | [B1] NOI |",
    "| 2 | [A2] Elm St | [B2] 1,204,000 |",
    "| 3 | [A3] Oak Ave | [B3] 986,500 |",
]

ASSUMPTIONS = [
    "| Row | A | B |",
    "|---|---|---|",
    "| 1 | [A1] Vacancy | [B1] 6.6% |",
]


@pytest.fixture
def fake_gate_registry() -> FakeDocumentRegistry:
    """A two-document registry: one PDF of three pages, one book of two sheets."""
    ids = Ids()
    return (
        FakeDocumentRegistry()
        .add(
            pdf_document(
                "t12-audit",
                "t12-audit-report.pdf",
                AUDIT_PAGES,
                summaries=["Cover page."],
                ids=ids,
            )
        )
        .add(
            sheet_document(
                "rent-model",
                "rent-model.xlsx",
                [("Rent Roll", RENT_ROLL), ("Assumptions", ASSUMPTIONS)],
                ids=ids,
            )
        )
    )
