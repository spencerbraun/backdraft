"""The card divides its own height; nothing inside it is pinned to a fixed one.

The card is user-resizable, so every region inside it is a viewport rather than
a box: drag the card taller and the evidence grows, drag it short and the
evidence scrolls inside itself while the header, the source selector and the
tabs stay put. A fixed `max-height` anywhere inside breaks that — it was the
original bug, a quote pinned at 15rem inside a card twice as tall — and so does
a flexing region that forgets `min-height`, since a flex item's automatic
minimum is its content and refuses to shrink below it.

These read the shipped stylesheet, which is the only place the layout is
written. They are the standing half of the check; the moving half is looking at
a real artifact in a browser, which is how the `[hidden]` rule below was found.
"""

from __future__ import annotations

import re

from backdraft.render.html.assets import STYLESHEET, STYLESHEET_MIN

# every region the card lays out; `.note` reuses three of them on a page that
# does not resize, and is exempt by the same reasoning
CARD_REGION = re.compile(
    r"\.(?:card|cite|evidence|tabs?|pane|plate|grid|gridwrap|quote|drift"
    r"|record|pagetext|rawtext|srcsel|srccount)\b"
)
FIXED_LENGTH = re.compile(r"\d+(?:\.\d+)?(?:px|rem|em)\b")


def _rules(css: str) -> list[tuple[str, str]]:
    """Every top-level rule as (selector, declarations).

    At-rules are skipped whole, which exempts the phone breakpoint on purpose:
    that card is not resizable, so it keeps the fixed caps it always had.
    """
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)
    rules: list[tuple[str, str]] = []
    index = 0
    while (open_brace := css.find("{", index)) != -1:
        prelude = css[index:open_brace].strip()
        depth, cursor = 1, open_brace + 1
        while cursor < len(css) and depth:
            depth += {"{": 1, "}": -1}.get(css[cursor], 0)
            cursor += 1
        if not prelude.startswith("@"):
            rules.append((prelude, css[open_brace + 1:cursor - 1]))
        index = cursor
    return rules


def _declarations(body: str) -> dict[str, str]:
    out = {}
    for declaration in body.split(";"):
        prop, _, value = declaration.partition(":")
        if value:
            out[prop.strip()] = value.strip()
    return out


def _by_selector(css: str) -> dict[str, dict[str, str]]:
    """Declarations merged per selector, across every rule that names it."""
    merged: dict[str, dict[str, str]] = {}
    for prelude, body in _rules(css):
        for selector in (s.strip() for s in prelude.split(",")):
            merged.setdefault(selector, {}).update(_declarations(body))
    return merged


# ---- no fixed heights -------------------------------------------------------


def test_nothing_inside_the_card_is_pinned_to_a_fixed_height() -> None:
    pinned = [
        (selector, prop, decls[prop])
        for selector, decls in _by_selector(STYLESHEET).items()
        if CARD_REGION.search(selector) and ".note" not in selector
        for prop in ("height", "max-height")
        if prop in decls and FIXED_LENGTH.search(decls[prop])
    ]
    assert not pinned, f"fixed heights inside the resizable card: {pinned}"


def test_the_cards_own_caps_are_relative_to_the_viewport_and_the_card() -> None:
    """What replaced the fixed caps: the card tracks the window, the blocks
    inside it track the card."""
    by_selector = _by_selector(STYLESHEET)
    assert by_selector[".card"]["max-height"] == "82vh"
    for selector in (".card .quote", ".card .drift", ".card .record"):
        assert by_selector[selector]["max-height"] == "40%"


def test_the_notes_keep_their_fixed_cap() -> None:
    """The end matter is a page, not a viewport: nothing there resizes."""
    assert _by_selector(STYLESHEET)[".note .quote"]["max-height"] == "15rem"


# ---- the flex column --------------------------------------------------------


def test_the_card_is_a_flex_column() -> None:
    card = _by_selector(STYLESHEET)[".card"]
    assert card["display"] == "flex"
    assert card["flex-direction"] == "column"


def test_hidden_still_hides_a_card_that_declares_a_display() -> None:
    """An author `display` outranks the UA sheet's `[hidden]{display:none}`.
    Without this rule every card in the artifact renders at once."""
    assert ".card[hidden]{display:none}" in STYLESHEET_MIN
    assert _by_selector(STYLESHEET)[".card[hidden]"]["display"] == "none"


def test_every_flexing_region_declares_its_min_height() -> None:
    """`min-height` is `auto` on a flex item, which refuses to shrink below its
    content — the one mistake that turns this layout back into a clipped card.
    Rows pinned with `flex:0 0 auto` never shrink and need no floor."""
    missing = [
        selector
        for selector, decls in _by_selector(STYLESHEET).items()
        if decls.get("flex", "").endswith("auto")
        and not decls["flex"].startswith("0 0")
        and "min-height" not in decls
    ]
    assert not missing, f"flexing regions with no min-height: {missing}"


def test_the_evidence_region_keeps_a_floor() -> None:
    """It shrinks, but never to nothing: the citation scrolls first."""
    assert _by_selector(STYLESHEET)[".evidence"]["min-height"] == "5rem"


# ---- the sheet views share their sticky headers -----------------------------


def test_both_sheet_views_stick_their_headers_from_one_rule() -> None:
    """The card's window scrolls now that it flexes, so it needs what the
    overlay already had — and takes it from the same rule, not a copy."""
    for prelude, body in _rules(STYLESHEET):
        if "position" in _declarations(body) and ".sheettable thead th" in prelude:
            assert ".grid thead th" in prelude
            break
    else:  # pragma: no cover - the assertion above is the point
        raise AssertionError("no sticky rule for the sheet header")
