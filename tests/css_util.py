"""One CSS reader for the whole suite.

The shipped stylesheet is the only place the artifact's layout and palette are
written, so more than one suite reads it: `test_card_sizing.py` checks that
nothing inside the resizable card is pinned, and `test_theme.py` checks that the
themeable variables and the bundled default agree with it. Both need the same
timid parser, so it lives here rather than twice.

Deliberately a plain module and not a fixture, matching `golden_util`: a helper
two test files call by name is easier to follow when the import says where it
came from.
"""

from __future__ import annotations

import re

__all__ = ["by_selector", "declarations", "root_variables", "rules"]


def rules(css: str) -> list[tuple[str, str]]:
    """Every top-level rule as (selector, declarations).

    At-rules are skipped whole, which exempts the phone breakpoint on purpose:
    that card is not resizable, so it keeps the fixed caps it always had.
    """
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)
    found: list[tuple[str, str]] = []
    index = 0
    while (open_brace := css.find("{", index)) != -1:
        prelude = css[index:open_brace].strip()
        depth, cursor = 1, open_brace + 1
        while cursor < len(css) and depth:
            depth += {"{": 1, "}": -1}.get(css[cursor], 0)
            cursor += 1
        if not prelude.startswith("@"):
            found.append((prelude, css[open_brace + 1:cursor - 1]))
        index = cursor
    return found


def declarations(body: str) -> dict[str, str]:
    out = {}
    for declaration in body.split(";"):
        prop, _, value = declaration.partition(":")
        if value:
            out[prop.strip()] = value.strip()
    return out


def by_selector(css: str) -> dict[str, dict[str, str]]:
    """Declarations merged per selector, across every rule that names it."""
    merged: dict[str, dict[str, str]] = {}
    for prelude, body in rules(css):
        for selector in (s.strip() for s in prelude.split(",")):
            merged.setdefault(selector, {}).update(declarations(body))
    return merged


def root_variables(css: str) -> dict[str, str]:
    """The custom properties `:root` declares, without their `--` prefix."""
    return {
        prop[2:]: value
        for prop, value in by_selector(css)[":root"].items()
        if prop.startswith("--")
    }
