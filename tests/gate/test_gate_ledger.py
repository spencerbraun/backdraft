"""The load-bearing invariant: what the gate emitted, the ledger recorded.

SPEC § Workstreams: "any token the gate emits binds `resolved` in the same
session". Bind can only distinguish a cited-what-you-saw token from a token the
writer never had if this module never under-records — and `not_shown` is only
honest if it never over-records either.
"""

from __future__ import annotations

import re

from fake_registry import FakeDocumentRegistry

from backdraft.gate.reader import read
from backdraft.gate.searcher import search

TOKEN_IN_OUTPUT = re.compile(r"\[(bd:[^\]\s]+)\]")

SESSION = "run-a"


def _emitted(output: str) -> set[str]:
    return set(TOKEN_IN_OUTPUT.findall(output))


def test_page_read_records_every_token_it_emits(fake_gate_registry: FakeDocumentRegistry) -> None:
    output = read(fake_gate_registry, "t12-audit", "p1-3", session=SESSION)
    emitted = _emitted(output)
    assert len(emitted) == 4
    assert all(fake_gate_registry.was_shown(SESSION, token) for token in emitted)


def test_search_records_every_token_it_emits(fake_gate_registry: FakeDocumentRegistry) -> None:
    output = search(fake_gate_registry, "NOI", session=SESSION)
    emitted = _emitted(output)
    assert emitted
    assert all(fake_gate_registry.was_shown(SESSION, token) for token in emitted)


def test_a_searched_snippet_is_citable_without_a_page_read(
    fake_gate_registry: FakeDocumentRegistry,
) -> None:
    search(fake_gate_registry, "net operating income", session=SESSION)
    assert fake_gate_registry.shown_tokens(SESSION) == {"bd:t12-audit:p2.c2:1e7a"}


def test_sheet_read_records_the_cells_its_window_exposed(fake_gate_registry: FakeDocumentRegistry) -> None:
    """Cell tokens are not printed, but their `[B10]` references were shown."""
    read(fake_gate_registry, "rent-model", "p1", session=SESSION, limit=2)
    shown = fake_gate_registry.shown_tokens(SESSION)
    assert "bd:rent-model:p1:feef" in shown
    locators = sorted(token.split(":")[2] for token in shown)
    assert locators == [
        "p1",
        "rent-roll!A1",
        "rent-roll!A2",
        "rent-roll!B1",
        "rent-roll!B2",
    ]


def test_a_window_does_not_record_what_it_did_not_show(fake_gate_registry: FakeDocumentRegistry) -> None:
    read(fake_gate_registry, "rent-model", "p1", session=SESSION, limit=2)
    assert not any(
        "!A3" in token or "!B3" in token for token in fake_gate_registry.shown_tokens(SESSION)
    )


def test_skipped_chunks_are_not_recorded(fake_gate_registry: FakeDocumentRegistry) -> None:
    read(fake_gate_registry, "t12-audit", "p2", session=SESSION, limit=60)
    assert fake_gate_registry.shown_tokens(SESSION) == {"bd:t12-audit:p2.c1:50bd"}


def test_windows_accumulate_in_one_session(fake_gate_registry: FakeDocumentRegistry) -> None:
    read(fake_gate_registry, "t12-audit", "p2", session=SESSION, limit=60)
    read(fake_gate_registry, "t12-audit", "p2", session=SESSION, offset=55)
    assert fake_gate_registry.shown_tokens(SESSION) == {
        "bd:t12-audit:p2.c1:50bd",
        "bd:t12-audit:p2.c2:1e7a",
    }


def test_the_list_and_the_toc_mint_nothing(fake_gate_registry: FakeDocumentRegistry) -> None:
    read(fake_gate_registry)
    read(fake_gate_registry, "t12-audit")
    read(fake_gate_registry, "rent-model")
    assert fake_gate_registry.sessions() == {}


def test_reads_without_a_session_mint_nothing(fake_gate_registry: FakeDocumentRegistry) -> None:
    read(fake_gate_registry, "t12-audit", "p2")
    search(fake_gate_registry, "NOI")
    assert fake_gate_registry.sessions() == {}


def test_the_session_is_created_on_first_mint(fake_gate_registry: FakeDocumentRegistry) -> None:
    read(fake_gate_registry, "t12-audit", "p2", session=SESSION)
    assert SESSION in fake_gate_registry.sessions()


def test_sessions_do_not_leak_into_each_other(fake_gate_registry: FakeDocumentRegistry) -> None:
    read(fake_gate_registry, "t12-audit", "p1", session="run-a")
    read(fake_gate_registry, "t12-audit", "p3", session="run-b")
    assert fake_gate_registry.shown_tokens("run-a") == {"bd:t12-audit:p1.c1:5ff8"}
    assert not fake_gate_registry.was_shown("run-a", "bd:t12-audit:p3.c1:c9c9")
    assert fake_gate_registry.shown_tokens("run-b") != fake_gate_registry.shown_tokens("run-a")
