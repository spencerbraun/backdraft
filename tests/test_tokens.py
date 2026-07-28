"""The grammar: round-trip, fuzz, and the rejection table."""

from __future__ import annotations

import random
import string

import pytest

from backdraft.kernel import tokens
from backdraft.kernel.errors import MalformedTokenError, UnsupportedTokenError

SPEC_EXAMPLES = [
    "bd:t12-audit:p8.c3:a7f3",
    "bd:model:rent-roll!B10:9e2f",
    "bd:t12-audit:p8:c114",
]

VALID = [
    *SPEC_EXAMPLES,
    "bd:ab:p1:0000",
    "bd:a1:p999:ffffffff",
    "bd:doc-2:p12.c7:deadbeef",
    "bd:model:rent-roll!B10:C12:9e2f",
    "bd:model:Sheet1!A1:abcd",
    "bd:model:Sheet1!AA100:AB200:abcdef",
    "bd:calc-sheet:p1:abcd",  # a slug may be spelled "calc"; only "calc(" is reserved
    "bd:calc:p1:abcd",
]


@pytest.mark.parametrize("text", VALID)
def test_round_trip(text: str) -> None:
    assert tokens.parse(text).format() == text


@pytest.mark.parametrize("text", VALID)
def test_validate_accepts(text: str) -> None:
    assert tokens.validate(text)


def test_parsed_parts() -> None:
    token = tokens.parse("bd:t12-audit:p8.c3:a7f3")
    assert token.slug == "t12-audit"
    assert token.hash == "a7f3"
    assert token.locator == tokens.ChunkLocator(page=8, ordinal=3)
    assert token.kind == "chunk"


def test_page_locator() -> None:
    token = tokens.parse("bd:t12-audit:p8:c114")
    assert token.locator == tokens.PageLocator(page=8)
    assert token.kind == "page"


def test_cell_locator() -> None:
    token = tokens.parse("bd:model:rent-roll!B10:9e2f")
    assert token.locator == tokens.CellLocator(sheet="rent-roll", cell=tokens.Cell("B", 10))
    assert token.kind == "cell"


def test_range_locator() -> None:
    token = tokens.parse("bd:model:rent-roll!B10:C12:9e2f")
    assert token.locator == tokens.CellLocator(
        sheet="rent-roll", cell=tokens.Cell("B", 10), end=tokens.Cell("C", 12)
    )
    assert token.kind == "range"
    assert token.hash == "9e2f"


def test_locators_are_typed_not_strings() -> None:
    for text in VALID:
        assert not isinstance(tokens.parse(text).locator, str)


def test_format_token_from_parts() -> None:
    assert (
        tokens.format_token("t12-audit", tokens.ChunkLocator(8, 3), "a7f3")
        == "bd:t12-audit:p8.c3:a7f3"
    )


def test_locator_round_trip() -> None:
    for text in ("p8", "p8.c3", "rent-roll!B10", "rent-roll!B10:C12"):
        assert tokens.format_locator(tokens.parse_locator(text)) == text


# --- the reserved derivation form -------------------------------------------

RESERVED = [
    "bd:calc(model:rent-roll!B10 / t12-audit:p4.c1)",
    "bd:calc()",
    "bd:calc(anything at all",
]


@pytest.mark.parametrize("text", RESERVED)
def test_reserved_derivation_is_recognized_but_unsupported(text: str) -> None:
    with pytest.raises(UnsupportedTokenError) as caught:
        tokens.parse(text)
    assert "bd:calc" in str(caught.value)
    assert not isinstance(caught.value, MalformedTokenError)
    assert not tokens.validate(text)


# --- the rejection table -----------------------------------------------------

MALFORMED = {
    "empty": "",
    "no prefix": "t12-audit:p8:a7f3",
    "wrong prefix": "bx:t12-audit:p8:a7f3",
    "prefix only": "bd:",
    "slug only": "bd:t12-audit",
    "missing hash": "bd:t12-audit:p8",
    "empty slug": "bd::p8:a7f3",
    "one-char slug": "bd:a:p8:a7f3",
    "uppercase slug": "bd:T12:p8:a7f3",
    "underscore in slug": "bd:t12_audit:p8:a7f3",
    "slug starts with hyphen": "bd:-t12:p8:a7f3",
    "slug too long": "bd:" + "a" * 33 + ":p8:a7f3",
    "empty locator": "bd:t12-audit::a7f3",
    "unknown locator": "bd:t12-audit:x8:a7f3",
    "page zero": "bd:t12-audit:p0:a7f3",
    "page leading zero": "bd:t12-audit:p08:a7f3",
    "chunk zero": "bd:t12-audit:p8.c0:a7f3",
    "chunk missing ordinal": "bd:t12-audit:p8.c:a7f3",
    "chunk missing page": "bd:t12-audit:p.c3:a7f3",
    "empty hash": "bd:t12-audit:p8:",
    "hash too short": "bd:t12-audit:p8:a7f",
    "hash too long": "bd:t12-audit:p8:a7f3a7f3a",
    "uppercase hash": "bd:t12-audit:p8:A7F3",
    "non-hex hash": "bd:t12-audit:p8:zzzz",
    "empty sheet": "bd:model:!B10:9e2f",
    "empty cell": "bd:model:rent-roll!:9e2f",
    "empty range end": "bd:model:rent-roll!B10::9e2f",
    "range end missing row": "bd:model:rent-roll!B10:C:9e2f",
    "lowercase cell column": "bd:model:rent-roll!b10:9e2f",
    "cell without row": "bd:model:rent-roll!B:9e2f",
    "cell row zero": "bd:model:rent-roll!B0:9e2f",
    "sheet with whitespace": "bd:model:rent roll!B10:9e2f",
    "leading whitespace": " bd:t12-audit:p8:a7f3",
    "trailing whitespace": "bd:t12-audit:p8:a7f3 ",
    "internal whitespace": "bd:t12-audit:p8 :a7f3",
    "three citations glued": "bd:a1:p8:a7f3;bd:a1:p9:a7f4",
}


@pytest.mark.parametrize("text", MALFORMED.values(), ids=list(MALFORMED))
def test_rejection_table(text: str) -> None:
    with pytest.raises(MalformedTokenError):
        tokens.parse(text)
    assert not tokens.validate(text)


def test_parse_rejects_non_strings() -> None:
    with pytest.raises(MalformedTokenError):
        tokens.parse(None)  # type: ignore[arg-type]


def test_constructors_validate() -> None:
    with pytest.raises(MalformedTokenError):
        tokens.Token(slug="T12", locator=tokens.PageLocator(1), hash="a7f3")
    with pytest.raises(MalformedTokenError):
        tokens.Token(slug="t12", locator=tokens.PageLocator(1), hash="A7F3")
    with pytest.raises(MalformedTokenError):
        tokens.PageLocator(page=0)
    with pytest.raises(MalformedTokenError):
        tokens.ChunkLocator(page=1, ordinal=0)
    with pytest.raises(MalformedTokenError):
        tokens.Cell(column="b", row=1)
    with pytest.raises(MalformedTokenError):
        tokens.Cell(column="B", row=0)
    with pytest.raises(MalformedTokenError):
        tokens.CellLocator(sheet="rent roll", cell=tokens.Cell("B", 10))


# --- hrefs -------------------------------------------------------------------


def test_split_href_single() -> None:
    assert tokens.split_href("bd:a1:p8:a7f3") == ["bd:a1:p8:a7f3"]


def test_split_href_multiple() -> None:
    assert tokens.split_href("bd:a1:p8:a7f3;bd:a1:p9:a7f4") == [
        "bd:a1:p8:a7f3",
        "bd:a1:p9:a7f4",
    ]


def test_split_href_drops_empty_pieces() -> None:
    assert tokens.split_href("bd:a1:p8:a7f3; ;") == ["bd:a1:p8:a7f3"]


def test_is_token_href() -> None:
    assert tokens.is_token_href("bd:a1:p8:a7f3")
    assert tokens.is_token_href("bd:garbage")  # shallow on purpose: bind reports it
    assert tokens.is_token_href("https://example.com;bd:a1:p8:a7f3")
    assert not tokens.is_token_href("https://example.com")
    assert not tokens.is_token_href("")
    assert not tokens.is_token_href("#section")


# --- property-style fuzz -----------------------------------------------------


def _random_slug(rng: random.Random) -> str:
    alphabet = string.ascii_lowercase + string.digits
    head = rng.choice(alphabet)
    tail = "".join(rng.choice(alphabet + "-") for _ in range(rng.randint(1, 31)))
    return head + tail


def _random_locator(rng: random.Random) -> tokens.Locator:
    match rng.randint(0, 3):
        case 0:
            return tokens.PageLocator(page=rng.randint(1, 5000))
        case 1:
            return tokens.ChunkLocator(page=rng.randint(1, 5000), ordinal=rng.randint(1, 400))
        case 2:
            return tokens.CellLocator(sheet=_random_sheet(rng), cell=_random_cell(rng))
        case _:
            return tokens.CellLocator(
                sheet=_random_sheet(rng), cell=_random_cell(rng), end=_random_cell(rng)
            )


def _random_sheet(rng: random.Random) -> str:
    alphabet = string.ascii_letters + string.digits + "-_."
    return "".join(rng.choice(alphabet) for _ in range(rng.randint(1, 24)))


def _random_cell(rng: random.Random) -> tokens.Cell:
    column = "".join(rng.choice(string.ascii_uppercase) for _ in range(rng.randint(1, 3)))
    return tokens.Cell(column=column, row=rng.randint(1, 100000))


def _random_hash(rng: random.Random) -> str:
    return "".join(rng.choice(string.hexdigits.lower()[:16]) for _ in range(rng.choice((4, 6, 8))))


def test_fuzz_round_trip() -> None:
    rng = random.Random(20260727)  # NOTE: seeded, so a failure is reproducible
    for _ in range(2000):
        expected = tokens.Token(
            slug=_random_slug(rng), locator=_random_locator(rng), hash=_random_hash(rng)
        )
        text = expected.format()
        parsed = tokens.parse(text)
        assert parsed == expected
        assert parsed.format() == text
        assert tokens.validate(text)


def _parses_or_raises_token_error(text: str) -> None:
    """Either it parses and formats back, or it raises a TokenError. Never else."""
    try:
        parsed = tokens.parse(text)
    except (MalformedTokenError, UnsupportedTokenError):
        assert tokens.validate(text) is False
        return
    assert parsed.format() == text
    assert tokens.validate(text) is True


def test_fuzz_mutations_never_crash() -> None:
    rng = random.Random(1)
    noise = " ;:!.()pcA0-Z\\\n"
    for _ in range(200):
        text = tokens.Token(
            slug=_random_slug(rng), locator=_random_locator(rng), hash=_random_hash(rng)
        ).format()
        for cut in range(len(text) + 1):
            _parses_or_raises_token_error(text[:cut])
        for _ in range(8):
            position = rng.randrange(len(text))
            _parses_or_raises_token_error(
                text[:position] + rng.choice(noise) + text[position + 1 :]
            )
