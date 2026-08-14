"""`backdraft show`: a token run back to the snippet it names.

Golden strings rather than substring checks, for the same reason the reader's
own tests are: this output is what an agent reads and what the skills quote, so a
diff here should be read as a change to a published surface.

Drift lives in `tests/test_gate_integration.py` instead — it is a property of
having two extraction generations, which the fake registry does not have and
should not grow.
"""

from __future__ import annotations

from fake_registry import FakeDocumentRegistry

from backdraft.gate.reader import GRAMMAR_HINT, Shown, show

CHUNK = "bd:t12-audit:p2.c1:50bd"
CELL = "bd:rent-model:rent-roll!B2:32c5"

RESOLVED = """\
[bd:t12-audit:p2.c1:50bd]  resolved  t12-audit p2.c1
The portfolio comprises 14 assets across three markets.

[Read the page: backdraft read t12-audit p2]"""

BOTH = """\
[bd:rent-model:rent-roll!B2:32c5]  resolved  rent-model rent-roll!B2
1,204,000

[bd:t12-audit:p2.c1:50bd]  resolved  t12-audit p2.c1
The portfolio comprises 14 assets across three markets.

[Read the page: backdraft read rent-model p1]
[Read the page: backdraft read t12-audit p2]"""

UNRESOLVED = """\
[bd:t12-audit:p9.c1:1a2b]  unresolved
t12-audit carries no anchor named by this token, in any extraction; the locator \
or the hash is wrong

[Table of contents: backdraft read t12-audit]"""

UNKNOWN_SLUG = """\
[bd:nope:p1.c1:1a2b]  unresolved
no document with slug 'nope'; run `backdraft read` to list what is ingested"""


def test_a_resolved_token_prints_its_locator_and_verbatim_snippet(
    fake_gate_registry: FakeDocumentRegistry,
) -> None:
    assert show(fake_gate_registry, [CHUNK]).text == RESOLVED


def test_several_tokens_print_in_argument_order(
    fake_gate_registry: FakeDocumentRegistry,
) -> None:
    """Argument order, not registry order: the caller's list is the answer's shape."""
    assert show(fake_gate_registry, [CELL, CHUNK]).text == BOTH


def test_showing_is_minting(fake_gate_registry: FakeDocumentRegistry) -> None:
    """The gate's whole contract, at this surface: shown is citable.

    `tests/test_gate_integration.py` carries the other half — that a document
    citing a shown token then binds `resolved` rather than `not_shown`.
    """
    show(fake_gate_registry, [CHUNK, CELL], session="s1")
    assert fake_gate_registry.shown_tokens("s1") == {CHUNK, CELL}


def test_nothing_is_minted_without_a_session(
    fake_gate_registry: FakeDocumentRegistry,
) -> None:
    show(fake_gate_registry, [CHUNK])
    assert fake_gate_registry.shown_tokens("default") == set()


def test_a_well_formed_token_naming_nothing_says_which_half_is_wrong(
    fake_gate_registry: FakeDocumentRegistry,
) -> None:
    """`unresolved` alone does not say whether to fix the slug or the locator."""
    shown = show(fake_gate_registry, ["bd:t12-audit:p9.c1:1a2b"])
    assert shown.text == UNRESOLVED
    assert shown.complete is False


def test_an_unknown_slug_is_named_as_such(fake_gate_registry: FakeDocumentRegistry) -> None:
    shown = show(fake_gate_registry, ["bd:nope:p1.c1:1a2b"])
    assert shown.text == UNKNOWN_SLUG
    assert shown.complete is False


def test_an_unknown_slug_says_where_to_look_once(
    fake_gate_registry: FakeDocumentRegistry,
) -> None:
    """The reason already ends in `LIST_HINT`; a bracketed hint saying the same
    thing three lines down is the reader deciding which of two to trust."""
    text = show(fake_gate_registry, ["bd:nope:p1.c1:1a2b"]).text
    assert text.count("backdraft read") == 1


def test_a_malformed_token_names_the_reason_and_the_grammar(
    fake_gate_registry: FakeDocumentRegistry,
) -> None:
    shown = show(fake_gate_registry, ["bd:t12-audit:p2c1:50bd"])
    assert shown.text == "\n".join(
        [
            "[bd:t12-audit:p2c1:50bd]  malformed",
            "invalid locator: 'p2c1'",
            "",
            GRAMMAR_HINT,
        ]
    )
    assert shown.complete is False


def test_the_reserved_derivation_form_is_malformed_here_too(
    fake_gate_registry: FakeDocumentRegistry,
) -> None:
    """The same call bind's kernel step makes, so the two agree on `bd:calc(...)`."""
    shown = show(fake_gate_registry, ["bd:calc(a/b)"])
    assert "malformed" in shown.text
    assert "not supported in v0" in shown.text
    assert shown.complete is False


def test_a_failure_never_swallows_the_tokens_beside_it(
    fake_gate_registry: FakeDocumentRegistry,
) -> None:
    """Failures are data: the run finishes the list and reports what it could not do."""
    shown = show(fake_gate_registry, ["bd:nope:p1.c1:1a2b", CHUNK, "bd:t12-audit:p2c1:50bd"])
    lines = shown.text.split("\n")
    assert lines[0].endswith("unresolved")
    assert "The portfolio comprises 14 assets across three markets." in lines
    assert lines[-2:] == [
        "[Read the page: backdraft read t12-audit p2]",
        GRAMMAR_HINT,
    ]
    assert shown.complete is False


def test_no_tokens_says_so_rather_than_printing_nothing(
    fake_gate_registry: FakeDocumentRegistry,
) -> None:
    """Unreachable through the CLI, which requires an argument — but a library
    caller with an empty list gets an answer, not an empty string."""
    assert show(fake_gate_registry, []) == Shown(text="(no tokens)", complete=True)


def test_a_repeated_token_prints_twice_and_hints_once(
    fake_gate_registry: FakeDocumentRegistry,
) -> None:
    """The caller asked twice, so it is answered twice; the hint is one place to go."""
    text = show(fake_gate_registry, [CHUNK, CHUNK]).text
    assert text.count("[Read the page: backdraft read t12-audit p2]") == 1
    assert text.count("resolved  t12-audit p2.c1") == 2
