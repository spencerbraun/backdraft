"""Search results as rendered: token, document, page, excerpt, read hint."""

from __future__ import annotations

import pytest
from fake_registry import FakeDocumentRegistry, pdf_document

from backdraft.gate.reader import GateError
from backdraft.gate.searcher import EXCERPT_CHARS, PHRASE_FALLBACK_NOTE, search

RESULT = """\
1 result for "net operating income"

[bd:t12-audit:p2.c2:1e7a]  t12-audit p2
  Trailing twelve month net operating income was $4,102,880.

[Read the page: backdraft read t12-audit p2]"""

SCOPED = """\
2 results for "NOI" in rent-model

[bd:rent-model:p1:feef]  rent-model p1
  ## Sheet: Rent Roll - Values View with cell references | Row | A | B | \
|---|---|---| | 1 | [A1] Property | [B1] NOI | | 2 | [A2] Elm St | [B2] 1,204,000 | | 3 |...

[bd:rent-model:rent-roll!B1:29e2]  rent-model p1
  NOI

[Read the page: backdraft read rent-model p1]"""

EMPTY = """\
No results for "zzz".

[List documents: backdraft read]"""


def test_result(fake_gate_registry: FakeDocumentRegistry) -> None:
    assert search(fake_gate_registry, "net operating income", session="s") == RESULT


def test_scoped_to_one_document(fake_gate_registry: FakeDocumentRegistry) -> None:
    assert search(fake_gate_registry, "NOI", slug="rent-model", session="s") == SCOPED


def test_no_results(fake_gate_registry: FakeDocumentRegistry) -> None:
    assert search(fake_gate_registry, "zzz", session="s") == EMPTY


def test_no_results_in_scope(fake_gate_registry: FakeDocumentRegistry) -> None:
    assert search(fake_gate_registry, "zzz", slug="t12-audit", session="s").startswith(
        'No results for "zzz" in t12-audit.'
    )


def test_unknown_scope_is_an_error(fake_gate_registry: FakeDocumentRegistry) -> None:
    with pytest.raises(GateError):
        search(fake_gate_registry, "NOI", slug="nope")


def test_one_read_hint_per_matched_page() -> None:
    fake_gate_registry = FakeDocumentRegistry().add(
        pdf_document("doc", "doc.pdf", [["alpha one"], ["alpha two"], ["beta"]])
    )
    hints = [
        line for line in search(fake_gate_registry, "alpha", session="s").split("\n") if "Read" in line
    ]
    assert hints == [
        "[Read the page: backdraft read doc p1]",
        "[Read the page: backdraft read doc p2]",
    ]


def test_read_hints_are_deduplicated() -> None:
    fake_gate_registry = FakeDocumentRegistry().add(pdf_document("doc", "doc.pdf", [["alpha", "alpha too"]]))
    output = search(fake_gate_registry, "alpha", session="s")
    assert output.count("[Read the page: backdraft read doc p1]") == 1


def test_excerpt_is_one_line_and_bounded() -> None:
    long = "word " * 200
    fake_gate_registry = FakeDocumentRegistry().add(pdf_document("doc", "doc.pdf", [[f"start {long}end"]]))
    excerpt = search(fake_gate_registry, "start", session="s").split("\n")[3]
    assert excerpt.startswith("  start word")
    assert excerpt.endswith("...")
    assert len(excerpt.strip()) == EXCERPT_CHARS + len("...")


def test_limit_is_passed_through() -> None:
    fake_gate_registry = FakeDocumentRegistry().add(
        pdf_document("doc", "doc.pdf", [["alpha one"], ["alpha two"], ["alpha three"]])
    )
    assert search(fake_gate_registry, "alpha", limit=2, session="s").startswith("2 results")


# --- the phrase fallback ----------------------------------------------------
#
# A query FTS5 cannot parse is retried as a quoted phrase. That asks a different
# question from the one the caller wrote, so the results say so.

FALLBACK = """\
1 result for "$4,102,880"
(query retried as a phrase)

[bd:t12-audit:p2.c2:1e7a]  t12-audit p2
  Trailing twelve month net operating income was $4,102,880.

[Read the page: backdraft read t12-audit p2]"""


def test_a_retried_query_is_noted_once(fake_gate_registry: FakeDocumentRegistry) -> None:
    assert search(fake_gate_registry, "$4,102,880", session="s") == FALLBACK


def test_a_query_that_parses_carries_no_note(fake_gate_registry: FakeDocumentRegistry) -> None:
    assert PHRASE_FALLBACK_NOTE not in search(fake_gate_registry, "net operating income", session="s")


def test_the_note_survives_an_empty_result(fake_gate_registry: FakeDocumentRegistry) -> None:
    """Otherwise "no results" reads as an absent fact rather than a changed query."""
    output = search(fake_gate_registry, "zzz/1.42x", session="s")
    assert output.splitlines()[:2] == ['No results for "zzz/1.42x".', PHRASE_FALLBACK_NOTE]


def test_a_result_list_without_the_flag_still_renders() -> None:
    """`render_search` reads the flag defensively — a plain list is legal."""
    from backdraft.gate.searcher import render_search

    assert PHRASE_FALLBACK_NOTE not in render_search("anything", [])
