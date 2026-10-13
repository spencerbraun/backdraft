"""`cli_context.NEXT_MOVES` — what `bind` and `verify` tell a reader to do next.

The table is the one owner of the move for every kind of failure the two
reports print. These pin that it is total over the artifact format's closed
status set, that every command it names is one the CLI actually has, and that
the lines come out once per kind present, in a fixed order, quoted to be typed.
"""

from __future__ import annotations

import re

from typer.testing import CliRunner

from backdraft import cli
from backdraft.cli_context import NEXT_MOVES, RECEIPT, RECOUNT, UNMATCHED, next_moves
from backdraft.kernel.model import CitationStatus

COMMAND = re.compile(r"`backdraft ([a-z][a-z-]*)")


def _listed_commands() -> set[str]:
    """The command names `backdraft --help` prints, read off the help itself."""
    result = CliRunner().invoke(cli.app, ["--help"], terminal_width=200)
    assert result.exit_code == 0, result.output
    return {
        match.group(1)
        for line in result.output.splitlines()
        if (match := re.match(r"^│\s+([a-z][a-z-]*)\s", line))
    }


def test_every_failing_status_has_a_move() -> None:
    """The status set is closed, so the mapping is total — `resolved` excepted,
    because a status that is not a failure has nothing to do about it."""
    for status in CitationStatus:
        if status is CitationStatus.RESOLVED:
            assert status not in NEXT_MOVES
        else:
            assert status in NEXT_MOVES, status


def test_the_line_items_that_are_not_statuses_have_moves_too() -> None:
    for key in (UNMATCHED, RECEIPT, RECOUNT):
        assert key in NEXT_MOVES


def test_every_move_names_a_command_the_cli_lists() -> None:
    listed = _listed_commands()
    assert {"bind", "show", "search", "locate", "render"} <= listed
    for key, move in NEXT_MOVES.items():
        named = COMMAND.findall(move)
        assert named, f"{key} names no command"
        assert set(named) <= listed, (key, named)


def test_one_line_per_kind_present_and_none_for_the_rest() -> None:
    lines = next_moves({"drifted", "unresolved"}, doc="memo.md", session="s-a")
    assert [line.split(" — ")[0] for line in lines] == ["next: unresolved", "next: drifted"]


def test_nothing_present_is_no_lines() -> None:
    assert next_moves(set(), doc="memo.md", session="s-a") == []


def test_the_commands_carry_the_document_and_session_quoted() -> None:
    (line,) = next_moves({"drifted"}, doc="my memo.md", session="s-a")
    assert "`backdraft locate 'my memo.md' --session s-a`" in line


def test_no_session_is_no_flag() -> None:
    (line,) = next_moves({"unmatched"}, doc="memo.md", session=None)
    assert "--session" not in line
