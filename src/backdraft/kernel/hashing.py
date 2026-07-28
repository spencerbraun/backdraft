"""Normalization and hashing — the only normalization in the system.

`normalize` is applied before every snippet hash so that a receipt survives
re-extraction whitespace churn (CRLF vs LF, reflowed lines, NBSP) while staying
faithful to the words. Case is preserved: a hash that ignored case would let a
typo'd transcription resolve.

Value equivalences (units, scale, number formats) are *not* here — they belong
to the value-trace verifier, which defines its own.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from typing import Any

__all__ = [
    "TOKEN_HASH_LENGTHS",
    "normalize",
    "snippet_hash",
    "token_hash",
    "hash_prefix",
    "content_hash",
    "canonical_json",
    "config_hash",
]

TOKEN_HASH_LENGTHS = (4, 6, 8)
"""Hash prefix lengths a registry mints: 4 by default, extended on collision.

The parser accepts any length in 4..8; minting only ever uses these.
"""

_WHITESPACE_RUN = re.compile(r"\s+")


def normalize(text: str) -> str:
    """Unicode NFC, then collapse every whitespace run to one space, then strip.

    Case is preserved. This is the only text normalization in the system.
    """
    return _WHITESPACE_RUN.sub(" ", unicodedata.normalize("NFC", text)).strip()


def snippet_hash(text: str) -> str:
    """`sha256(normalize(text))` as a full lowercase hexdigest."""
    return hashlib.sha256(normalize(text).encode("utf-8")).hexdigest()


def hash_prefix(digest: str, length: int = TOKEN_HASH_LENGTHS[0]) -> str:
    """The `length`-char prefix of a hexdigest, as it appears in a token."""
    if length not in TOKEN_HASH_LENGTHS:
        raise ValueError(f"token hash length must be one of {TOKEN_HASH_LENGTHS}: {length!r}")
    return digest[:length]


def token_hash(text: str, length: int = TOKEN_HASH_LENGTHS[0]) -> str:
    """The hash segment of the token naming a snippet: a prefix of its sha256."""
    return hash_prefix(snippet_hash(text), length)


def content_hash(data: bytes) -> str:
    """Document identity: `sha256` of the file's bytes, unnormalized."""
    return hashlib.sha256(data).hexdigest()


def canonical_json(value: Any) -> str:
    """Canonical JSON: sorted keys, no insignificant whitespace, UTF-8 text.

    NOTE: the spec says "canonical-JSON" without naming a profile; this is the
    conventional minimum (RFC 8785 without the number-formatting rules, which
    extractor configs do not exercise). Non-ASCII is preserved, not escaped, so
    that the encoded form is stable under NFC-equal inputs.
    """
    return json.dumps(
        value,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    )


def config_hash(config: Any) -> str:
    """Extraction config identity: `sha256` of the canonical JSON encoding."""
    return hashlib.sha256(canonical_json(config).encode("utf-8")).hexdigest()
