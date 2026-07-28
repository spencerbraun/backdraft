"""Normalization and hashing: golden vectors and the equivalences they encode.

The digests below are fixed by the spec, not by the implementation: changing any
of them invalidates every token ever minted.

Vectors that turn on a specific code point spell it with `chr()`, so an editor
that normalizes the file cannot silently change what is being tested.
"""

from __future__ import annotations

import hashlib

import pytest

from backdraft.kernel import hashing

EMPTY_SHA = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
HELLO_SHA = "b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9"

E_ACUTE = chr(0x00E9)  # LATIN SMALL LETTER E WITH ACUTE
E_COMBINING = "e" + chr(0x0301)  # e + COMBINING ACUTE ACCENT
NBSP = chr(0x00A0)  # NO-BREAK SPACE
IDEOGRAPHIC_SPACE = chr(0x3000)  # IDEOGRAPHIC SPACE
ZERO_WIDTH_SPACE = chr(0x200B)  # ZERO WIDTH SPACE

NORMALIZATION_VECTORS = {
    "identity": ("hello world", "hello world"),
    "empty": ("", ""),
    "whitespace only": ("   \n\t ", ""),
    "leading and trailing": ("  hello world  ", "hello world"),
    "collapse runs": ("hello     world", "hello world"),
    "newlines collapse": ("hello\nworld", "hello world"),
    "crlf collapses": ("hello\r\nworld", "hello world"),
    "cr collapses": ("hello\rworld", "hello world"),
    "tabs collapse": ("hello\t\tworld", "hello world"),
    "form feed collapses": ("hello\x0cworld", "hello world"),
    "mixed run": ("hello \n\t  world\n", "hello world"),
    "nbsp collapses": (f"hello{NBSP}world", "hello world"),
    "ideographic space collapses": (f"hello{IDEOGRAPHIC_SPACE}world", "hello world"),
    "nfc composes": (f"caf{E_COMBINING}", f"caf{E_ACUTE}"),
    "nfc idempotent": (f"caf{E_ACUTE}", f"caf{E_ACUTE}"),
    "case preserved": ("Hello World", "Hello World"),
    "punctuation preserved": ("The DSCR is 1.42x.", "The DSCR is 1.42x."),
    "internal hyphen preserved": ("t12-audit", "t12-audit"),
    # NOTE: zero width space is not whitespace to Unicode, so it is left alone.
    "zero width space kept": (
        f"hello{ZERO_WIDTH_SPACE}world",
        f"hello{ZERO_WIDTH_SPACE}world",
    ),
}


@pytest.mark.parametrize(
    ("raw", "expected"), NORMALIZATION_VECTORS.values(), ids=list(NORMALIZATION_VECTORS)
)
def test_normalize(raw: str, expected: str) -> None:
    assert hashing.normalize(raw) == expected


def test_normalize_is_idempotent() -> None:
    for raw, _ in NORMALIZATION_VECTORS.values():
        once = hashing.normalize(raw)
        assert hashing.normalize(once) == once


SNIPPET_VECTORS = {
    "empty": ("", EMPTY_SHA),
    "spaces only": ("   ", EMPTY_SHA),
    "hello world": ("hello world", HELLO_SHA),
    "padded": ("  hello   world \n", HELLO_SHA),
    "crlf": ("hello\r\nworld", HELLO_SHA),
    "tabs": ("\thello world\t", HELLO_SHA),
    "nbsp": (f"hello{NBSP}world", HELLO_SHA),
    "composed e-acute": (
        f"caf{E_ACUTE}",
        "850f7dc43910ff890f8879c0ed26fe697c93a067ad93a7d50f466a7028a9bf4e",
    ),
    "decomposed e-acute": (
        f"caf{E_COMBINING}",
        "850f7dc43910ff890f8879c0ed26fe697c93a067ad93a7d50f466a7028a9bf4e",
    ),
    "sentence": (
        f"Caf{E_ACUTE} au lait",
        "793e7643ce558259f6fe71f9ecaaf268acbcd011a2bb4c7f561df05a133d4d08",
    ),
    "number claim": (
        "The DSCR is 1.42x.",
        "290292e35f10457eb3cc81687aaac31123958b22f75364e5f878a413878d4bfc",
    ),
    "cjk across lines": (
        "行\nの\nテスト",
        "5e3f550e6216cd053f95915bbbd5b045ead4431dc92137ef7fdec7d4e1ec73bb",
    ),
    "zero width space": (
        f"hello{ZERO_WIDTH_SPACE}world",
        "b8a413953f9f5b1b60b494711a5e92cc5f692d9d562bdcedfa582676cc50864a",
    ),
}


@pytest.mark.parametrize(
    ("text", "digest"), SNIPPET_VECTORS.values(), ids=list(SNIPPET_VECTORS)
)
def test_snippet_hash_golden(text: str, digest: str) -> None:
    assert hashing.snippet_hash(text) == digest


def test_case_changes_the_hash() -> None:
    assert hashing.snippet_hash("Hello World") != hashing.snippet_hash("hello world")


def test_token_hash_prefixes() -> None:
    assert hashing.token_hash("hello world") == HELLO_SHA[:4]
    assert hashing.token_hash("hello world", 6) == HELLO_SHA[:6]
    assert hashing.token_hash("hello world", 8) == HELLO_SHA[:8]
    assert hashing.hash_prefix(HELLO_SHA, 8) == HELLO_SHA[:8]


def test_token_hash_rejects_other_lengths() -> None:
    for length in (0, 3, 5, 7, 9, 64):
        with pytest.raises(ValueError):
            hashing.token_hash("hello world", length)


def test_token_hash_is_lowercase_hex() -> None:
    digest = hashing.token_hash("The DSCR is 1.42x.")
    assert len(digest) == 4
    assert digest == digest.lower()
    int(digest, 16)


def test_content_hash_is_unnormalized_bytes() -> None:
    assert hashing.content_hash(b"") == EMPTY_SHA
    assert hashing.content_hash(b"hello world") == HELLO_SHA
    assert hashing.content_hash(b"  hello world  ") != HELLO_SHA


def test_canonical_json_is_sorted_and_tight() -> None:
    value = {"b": 1, "a": [1, 2], "c": {"z": True}, "n": None, "s": f"caf{E_ACUTE}"}
    assert hashing.canonical_json(value) == (
        '{"a":[1,2],"b":1,"c":{"z":true},"n":null,"s":"caf' + E_ACUTE + '"}'
    )


def test_config_hash_golden() -> None:
    value = {"b": 1, "a": [1, 2], "c": {"z": True}, "n": None, "s": f"caf{E_ACUTE}"}
    assert (
        hashing.config_hash(value)
        == "cbee1a4aa57d50f89a0ebc5343d912fcac8bc673b370f4b29b3acc9f9a967395"
    )


def test_config_hash_ignores_key_order() -> None:
    assert hashing.config_hash({"a": 1, "b": 2}) == hashing.config_hash({"b": 2, "a": 1})


def test_config_hash_distinguishes_values() -> None:
    assert hashing.config_hash({"dpi": 200}) != hashing.config_hash({"dpi": 300})
    assert hashing.config_hash({}) != hashing.config_hash({"dpi": 200})


def test_config_hash_rejects_nan() -> None:
    with pytest.raises(ValueError):
        hashing.config_hash({"x": float("nan")})


def test_snippet_hash_matches_a_hand_rolled_reference() -> None:
    text = "  A   receipt\r\nquotes the snapshot.  "
    reference = hashlib.sha256(b"A receipt quotes the snapshot.").hexdigest()
    assert hashing.snippet_hash(text) == reference
