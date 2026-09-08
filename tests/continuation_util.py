"""Reading a page read's closing line back as the arguments it names.

The closing line is a command, so a test that walks a read follows it the way a
caller would: shell-split the line and hand the flags back to `read`. Pulling
the offset out with a regex would pass on a hint no shell could run, and a hint
that has to be repaired before it runs is not a hint.
"""

from __future__ import annotations

import shlex

CONTINUE = "Continue with: "


def continuation(output: str) -> dict[str, object] | None:
    """`read` keyword arguments from the closing line, or None if it names none.

    Only the flags the line actually carries appear, so a caller can layer its
    own defaults underneath: `read(registry, **{"session": "s", **cont})`.
    """
    line = output.split("\n")[-1]
    if CONTINUE not in line:
        return None
    command = shlex.split(line.split(CONTINUE, 1)[1].rstrip("]"))
    assert command[:2] == ["backdraft", "read"], f"not a read command: {command}"
    slug, selector, *flags = command[2:]
    args: dict[str, object] = {"slug": slug, "selector": selector}
    for name, value in zip(flags[::2], flags[1::2], strict=True):
        key = name.removeprefix("--")
        args[key] = int(value) if key in {"offset", "limit"} else value
    return args
