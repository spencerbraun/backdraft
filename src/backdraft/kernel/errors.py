"""Exception hierarchy.

One base (`BackdraftError`) so callers can catch everything the library raises;
below it, only distinctions a caller acts on differently.

`MalformedTokenError` means "this is not a token". `UnsupportedTokenError` means
"this is a token form the grammar reserves but v0 does not implement" — the
`bd:calc(...)` derivation form. The distinction exists so parsers reject the
reserved form cleanly rather than crashing or mislabelling it as garbage.
"""

from __future__ import annotations

__all__ = [
    "BackdraftError",
    "TokenError",
    "MalformedTokenError",
    "UnsupportedTokenError",
]


class BackdraftError(Exception):
    """Base for every error raised by backdraft."""


class TokenError(BackdraftError):
    """A citation token could not be turned into a `Token`."""


class MalformedTokenError(TokenError):
    """The text does not satisfy the token grammar."""


class UnsupportedTokenError(TokenError):
    """The text is a recognized but unimplemented token form (`bd:calc(...)`)."""
