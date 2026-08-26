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
    assert search(fake_gate_registry, "alpha", limit=2, session="s").startswith("2 of 3 results")


# --- the silent cap ---------------------------------------------------------
#
# `--limit` truncates; the count line used to report the size of the page, so a
# reader could not tell twenty results from the first twenty of two hundred.

CAPPED = """\
2 of 3 results for "alpha"

[bd:doc:p1.c1:447d]  doc p1
  alpha one

[bd:doc:p2.c1:e902]  doc p2
  alpha two

[Read the page: backdraft read doc p1]
[Read the page: backdraft read doc p2]
[See all 3: backdraft search alpha --limit 3]"""


def _three_alphas() -> FakeDocumentRegistry:
    return FakeDocumentRegistry().add(
        pdf_document("doc", "doc.pdf", [["alpha one"], ["alpha two"], ["alpha three"]])
    )


def test_a_capped_search_names_the_total_and_how_to_widen() -> None:
    assert search(_three_alphas(), "alpha", limit=2, session="s") == CAPPED


def test_an_uncapped_search_is_unchanged() -> None:
    """Most runs are uncapped and their output is a contract — pin it byte for byte."""
    assert search(_three_alphas(), "alpha", limit=20, session="s") == """\
3 results for "alpha"

[bd:doc:p1.c1:447d]  doc p1
  alpha one

[bd:doc:p2.c1:e902]  doc p2
  alpha two

[bd:doc:p3.c1:9025]  doc p3
  alpha three

[Read the page: backdraft read doc p1]
[Read the page: backdraft read doc p2]
[Read the page: backdraft read doc p3]"""


def test_a_search_cut_to_exactly_its_matches_says_nothing_new() -> None:
    """The boundary: three of three is the whole answer, not a page of it."""
    output = search(_three_alphas(), "alpha", limit=3, session="s")
    assert output.startswith("3 results")
    assert "See all" not in output


def test_the_widen_hint_scopes_itself() -> None:
    output = search(_three_alphas(), "alpha", slug="doc", limit=1, session="s")
    assert output.startswith('1 of 3 results for "alpha" in doc')
    assert output.endswith("[See all 3: backdraft search alpha --in doc --limit 3]")


def test_the_widen_hint_is_a_command_a_shell_can_run() -> None:
    """A hint carrying `$` or a space must survive being pasted, unedited."""
    registry = FakeDocumentRegistry().add(
        pdf_document("doc", "doc.pdf", [["net $4,102,880 here"], ["net $4,102,880 twice"]])
    )
    hint = search(registry, "net $4,102,880", limit=1, session="s").splitlines()[-1]
    assert hint == "[See all 2: backdraft search 'net $4,102,880' --limit 2]"


def test_a_result_list_with_no_total_renders_uncapped() -> None:
    """`render_search` reads `total` defensively, as it reads the fallback flag."""
    from backdraft.gate.searcher import render_search

    assert render_search("anything", []) == '''\
No results for "anything".

[List documents: backdraft read]'''


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
