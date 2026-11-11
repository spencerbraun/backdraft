"""`cli_context.NEXT_MOVES` — what `bind` and `verify` tell a reader to do next.

The table is the one owner of the move for every kind of failure the two
reports print, keyed by the reader first: `bind`'s author and `verify`'s
auditor. These pin that each reader's table is total over the artifact format's
closed status set plus its own extra kinds, that every command it names is one
the CLI actually has, that no auditor move names a session to mint into, and
that the lines come out once per kind present, in a fixed order, quoted to be
typed.
"""

from __future__ import annotations

import re

import pytest

from backdraft import cli
from backdraft.cli_context import (
    AUDITOR,
    AUTHOR,
    CLEARED,
    NEXT_MOVES,
    RECEIPT,
    RECOUNT,
    UNMATCHED,
    moves_for,
    next_line,
    next_moves,
)
from backdraft.kernel.model import CitationStatus

COMMAND = re.compile(r"`backdraft ([a-z][a-z-]*)")


def _listed_commands() -> set[str]:
    """The command names `backdraft --help` lists: the top-level app's visible ones.

    Read off the app's registrations rather than scraped from the help text,
    whose box drawing depends on the terminal rich thinks it has.
    """
    commands = {
        info.name or info.callback.__name__.replace("_", "-")
        for info in cli.app.registered_commands
        if not info.hidden
    }
    groups = {info.name for info in cli.app.registered_groups if not info.hidden}
    return commands | groups


FAILING = {str(status) for status in CitationStatus if status is not CitationStatus.RESOLVED}
"""The status set is closed, so each table is total over it — `resolved` excepted,
because a status that is not a failure has nothing to do about it."""

EXTRAS = {AUTHOR: {UNMATCHED, CLEARED}, AUDITOR: {RECEIPT, RECOUNT}}
"""The line items each reader's report prints that are not statuses."""


def test_there_are_two_readers() -> None:
    assert set(NEXT_MOVES) == {AUTHOR, AUDITOR}


@pytest.mark.parametrize("reader", [AUTHOR, AUDITOR])
def test_each_table_is_total_over_the_statuses_plus_its_own_kinds(reader: str) -> None:
    assert CitationStatus.RESOLVED not in NEXT_MOVES[reader]
    assert set(NEXT_MOVES[reader]) == FAILING | EXTRAS[reader]


@pytest.mark.parametrize("reader", [AUTHOR, AUDITOR])
def test_every_move_names_a_command_the_cli_lists(reader: str) -> None:
    listed = _listed_commands()
    assert {"bind", "show", "search", "locate", "render"} <= listed
    for key, move in NEXT_MOVES[reader].items():
        named = COMMAND.findall(move)
        assert named, f"{reader}/{key} names no command"
        assert set(named) <= listed, (reader, key, named)


def test_no_auditor_move_names_a_session() -> None:
    """An auditor told `--session <the author's>` mints into the author's ledger."""
    for key, move in NEXT_MOVES[AUDITOR].items():
        assert "{session}" not in move, key
        assert "--session" not in move, key


def test_the_auditor_is_never_told_to_show_a_not_shown() -> None:
    """Showing is minting: the one move that would erase the finding it reports."""
    assert "backdraft show" not in NEXT_MOVES[AUDITOR][CitationStatus.NOT_SHOWN]
    assert "backdraft show" in NEXT_MOVES[AUTHOR][CitationStatus.NOT_SHOWN]


def test_one_line_per_kind_present_and_none_for_the_rest() -> None:
    lines = next_moves({"drifted", "unresolved"}, reader=AUTHOR, doc="memo.md", session="s-a")
    assert [line.split(" — ")[0] for line in lines] == ["next: unresolved", "next: drifted"]


def test_the_auditor_s_edited_file_comes_before_its_sources() -> None:
    lines = next_moves(
        {"not_shown", RECOUNT, RECEIPT}, reader=AUDITOR, doc="memo.md", session=None
    )
    assert [line.split(" — ")[0] for line in lines] == [
        "next: receipt",
        "next: recount",
        "next: not_shown",
    ]


def test_a_kind_outside_the_reader_s_table_prints_nothing() -> None:
    assert next_moves({RECEIPT}, reader=AUTHOR, doc="memo.md", session="s-a") == []
    assert next_moves({UNMATCHED}, reader=AUDITOR, doc="memo.md", session=None) == []


def test_nothing_present_is_no_lines() -> None:
    assert next_moves(set(), reader=AUTHOR, doc="memo.md", session="s-a") == []


def test_the_commands_carry_the_document_and_session_quoted() -> None:
    (line,) = next_moves({"drifted"}, reader=AUTHOR, doc="my memo.md", session="s-a")
    assert "`backdraft locate 'my memo.md' --session s-a`" in line


def test_the_auditor_ignores_a_session_it_is_handed() -> None:
    (line,) = next_moves({"not_shown"}, reader=AUDITOR, doc="memo.md", session="s-a")
    assert "s-a" not in line and "memo.md" in line


def test_no_session_is_no_flag() -> None:
    (line,) = next_moves({"unmatched"}, reader=AUTHOR, doc="memo.md", session=None)
    assert "--session" not in line


def test_the_lines_are_the_pairs_worded_and_nothing_else() -> None:
    """`verify --json` carries `moves_for`'s pairs and the reports print
    `next_moves`' lines; one is the other with a prefix, in the same order."""
    asked = {"not_shown", "drifted", RECEIPT, RECOUNT}
    pairs = moves_for(asked, reader=AUDITOR, doc="my memo.md", session=None)
    assert [kind for kind, _ in pairs] == [RECEIPT, RECOUNT, "not_shown", "drifted"]
    assert next_moves(asked, reader=AUDITOR, doc="my memo.md", session=None) == [
        next_line(kind, move) for kind, move in pairs
    ]
    assert all("{" not in move for _, move in pairs)
    assert "'my memo.md'" in pairs[0][1]
