"""Themes: the artifact's look, chosen once and baked in at render.

A theme is a small TOML file naming values for the CSS custom properties the
stylesheet already exposes — the colors and the three font roles — plus four
bounded heading choices. It compiles to **one block emitted after** the built-in
stylesheet, never into it:

    :root{--paper:#FFFDF8;--ink:#241F1A;…}
    .masthead h1,.doc h2{font-family:var(--serif);text-transform:none;…}

so with no theme configured the artifact is byte-identical to a build that had
never heard of theming. That is the whole discipline of this module: the default
path emits nothing.

A theme is **display only**. It may not touch layout, structure, or any
verification affordance, and it never reaches a token, a receipt or a record —
`--rail-w` (layout) and `color-scheme` (the artifact does not follow the
reader's system theme) are outside the allowlist for exactly that reason. See
the DESIGN.md row of 2026-08-04.

Keys and values are both checked against declared allowlists, so a typo fails by
name before anything is written rather than producing a half-styled file. The
values are interpolated into a `<style>` element, so the checks are also what
keeps a theme from closing the element or reaching the network — `url(...)` is
rejected with the reason, since a font the artifact would have to fetch is
precisely what its CSP forbids.

Resolution order — `--theme` > project `.backdraft/theme.toml` > user-wide
`~/.config/backdraft/theme.toml` (XDG) > built-in. The user-wide file is what
makes a preference stick across projects; the CLI supplies the project root,
because this module never goes looking for one.
"""

from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

from ..kernel.errors import BackdraftError
from ..registry import DIRECTORY

__all__ = [
    "BUNDLED",
    "CASES",
    "COLOR_VARS",
    "FONT_VARS",
    "HEADING_KEYS",
    "HEADING_SELECTOR",
    "Theme",
    "ThemeError",
    "bundled_names",
    "load",
    "loads",
    "resolve",
    "search_paths",
    "user_config_dir",
]

FILENAME = "theme.toml"
"""What the project and user-wide locations are called. One name, both places."""

BUNDLED = Path(__file__).parent / "themes"
"""The shipped themes, as the same TOML files a user would write."""

HEADING_SELECTOR = ".masthead h1,.doc h2"
"""The document's own headings — the title and the section heads.

Deliberately not the rail's, the endmatter's or the quote's: those small
uppercase labels are furniture, and a theme that restyled them would be changing
the artifact's structure rather than its look.
"""

COLOR_VARS = (
    "paper", "ink", "muted", "faint", "hover", "active", "underline",
    "hairline", "hairline-strong", "notebook", "notebook-line",
    "sel", "sel-soft", "excel-line", "excel-head", "alarm",
)
"""Every color the stylesheet reads from a custom property, in `:root` order.

`tests/test_theme.py` pins this against the stylesheet, so a color that is added
there and not here is a test failure rather than a key nobody can set.
"""

FONT_VARS = ("serif", "sans", "mono")
"""The three font roles: body text, UI text, code.

They are roles, not classifications — a sans-bodied theme sets `serif`. Renaming
them would rename a variable the stylesheet reads in fifty places for no gain.
"""

HEADING_KEYS = ("family", "case", "weight", "tracking")
"""The bounded typographic choices, compiled into `HEADING_SELECTOR`."""

CASES = ("none", "uppercase", "lowercase", "small-caps")
"""What `headings.case` accepts. `small-caps` is a font variant, not a
transform, so it is spelled here and dispatched below."""

SECTIONS = ("colors", "fonts", "headings")
"""The tables a theme file may carry, alongside the scalar `name`."""


class ThemeError(BackdraftError):
    """A theme file cannot be read, parsed, or trusted into a stylesheet."""


# ---- validation -------------------------------------------------------------

_INJECTION = re.compile(r"[;{}<>\\]|/\*|\*/|url\s*\(|expression\s*\(", re.IGNORECASE)
"""Anything that could end the declaration, the rule, the `<style>` element, or
the artifact's no-network guarantee. Checked first so its message is the one the
user sees."""

_COLOR = re.compile(
    r"^#(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$"
    r"|^(?:rgb|rgba|hsl|hsla)\([0-9.,%\s/+-]+\)$"
    r"|^[a-z]+$"
)
"""Hex, a functional color, or a CSS color keyword. `#GGG` fails here."""

_STACK = re.compile(r"^[A-Za-z0-9 ,'\"._+-]+$")
"""A font stack: family names, quotes, commas. No parens, so no `url()`."""

_LENGTH = re.compile(r"^normal$|^0$|^-?(?:\d+(?:\.\d+)?|\.\d+)(?:em|rem|px|ex|ch)$")
"""A tracking value: `normal`, a bare `0`, or a length in a font-relative or
pixel unit. The leading dot is CSS's own (`.04em`), so it is accepted."""

MAX_VALUE = 200
"""Longest a theme value may be. A font stack is a line, not a document."""


def _check(what: str, value: object, pattern: re.Pattern[str], shape: str) -> str:
    """One validated string, or a `ThemeError` naming the key and the shape."""
    if not isinstance(value, str):
        raise ThemeError(f"{what} must be text, not {type(value).__name__}")
    text = value.strip()
    if not text:
        raise ThemeError(f"{what} is empty")
    if len(text) > MAX_VALUE:
        raise ThemeError(f"{what} is longer than {MAX_VALUE} characters")
    if re.search(r"url\s*\(", text, re.IGNORECASE):
        raise ThemeError(
            f"{what} may not use url(): the artifact is one file that fetches "
            "nothing, so a font or image it would have to download can never "
            "load. Name locally installed families instead."
        )
    if _INJECTION.search(text):
        raise ThemeError(
            f"{what} contains a character a stylesheet value may not carry: "
            "one of ; { } < > \\ or a comment marker"
        )
    if not pattern.fullmatch(text):
        raise ThemeError(f"{what} is not {shape}; got {text!r}")
    return text


def _known(kind: str, key: str, known: tuple[str, ...]) -> None:
    if key not in known:
        raise ThemeError(f"unknown {kind} '{key}'; known: {', '.join(known)}")


def _table(data: dict, section: str) -> dict:
    """One TOML table, or a `ThemeError` if the file put something else there."""
    value = data.get(section, {})
    if not isinstance(value, dict):
        raise ThemeError(f"[{section}] must be a table of key = \"value\" lines")
    return value


# ---- the theme --------------------------------------------------------------


@dataclass(frozen=True)
class Theme:
    """A resolved theme: validated values, and the one CSS block they compile to.

    `variables` and `headings` hold only what the file set — a theme that names
    three colors overrides three colors, and everything else stays the built-in
    stylesheet's.
    """

    name: str
    variables: dict[str, str]
    headings: dict[str, str | int]

    def css(self) -> str:
        """The override block, emitted after the stylesheet. `""` when empty.

        Declaration order follows the allowlists rather than the file, so the
        same theme always produces the same bytes and artifacts diff cleanly.
        """
        blocks: list[str] = []
        decls = "".join(
            f"--{name}:{self.variables[name]};"
            for name in (*COLOR_VARS, *FONT_VARS)
            if name in self.variables
        )
        if decls:
            blocks.append(f":root{{{decls.rstrip(';')}}}")
        head = "".join(self._heading_decls())
        if head:
            blocks.append(f"{HEADING_SELECTOR}{{{head.rstrip(';')}}}")
        return "\n".join(blocks)

    def _heading_decls(self) -> list[str]:
        out: list[str] = []
        family = self.headings.get("family")
        if family is not None:
            stack = f"var(--{family})" if family in FONT_VARS else str(family)
            out.append(f"font-family:{stack};")
        case = self.headings.get("case")
        if case is not None:
            # both properties every time: switching themes must not leave the
            # other one set from whatever the previous choice implied
            out.append("text-transform:" + ("none" if case == "small-caps" else str(case)) + ";")
            out.append("font-variant:" + ("small-caps" if case == "small-caps" else "normal") + ";")
        weight = self.headings.get("weight")
        if weight is not None:
            out.append(f"font-weight:{weight};")
        tracking = self.headings.get("tracking")
        if tracking is not None:
            out.append(f"letter-spacing:{tracking};")
        return out


# ---- loading ----------------------------------------------------------------


def loads(text: str, *, name: str = "theme") -> Theme:
    """Parse and validate one theme document. `name` is the fallback theme name."""
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        raise ThemeError(f"not valid TOML: {error}") from error

    for key in data:
        if key != "name":
            _known("theme section", key, SECTIONS)
    declared = data.get("name", name)
    if not isinstance(declared, str) or not declared.strip():
        raise ThemeError("name must be a non-empty string")

    variables: dict[str, str] = {}
    for key, value in _table(data, "colors").items():
        _known("color", key, COLOR_VARS)
        variables[key] = _check(
            f"color '{key}'", value, _COLOR,
            "a CSS color (#1B1B1F, rgba(28,33,38,.05), or a keyword)",
        )
    for key, value in _table(data, "fonts").items():
        _known("font", key, FONT_VARS)
        variables[key] = _check(
            f"font '{key}'", value, _STACK, "a font stack (Georgia, 'Segoe UI', serif)"
        )

    headings: dict[str, str | int] = {}
    table = _table(data, "headings")
    for key in table:
        _known("heading key", key, HEADING_KEYS)
    if "family" in table:
        headings["family"] = _check(
            "heading family", table["family"], _STACK,
            f"one of {', '.join(FONT_VARS)}, or a font stack",
        )
    if "case" in table:
        case = table["case"]
        if case not in CASES:
            raise ThemeError(f"heading case must be one of {', '.join(CASES)}; got {case!r}")
        headings["case"] = case
    if "weight" in table:
        weight = table["weight"]
        if isinstance(weight, bool) or not isinstance(weight, int) or not 100 <= weight <= 900:
            raise ThemeError(f"heading weight must be a number from 100 to 900; got {weight!r}")
        headings["weight"] = weight
    if "tracking" in table:
        headings["tracking"] = _check(
            "heading tracking", table["tracking"], _LENGTH,
            "a length (.04em, 1px) or 'normal'",
        )

    return Theme(name=declared.strip(), variables=variables, headings=headings)


def load(path: Path) -> Theme:
    """Read and validate the theme file at `path`.

    Every message names the file: a theme that resolved off the search path was
    never typed on this command line, so "which theme file" is the first thing
    the reader needs.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise ThemeError(f"cannot read theme {path}: {error}") from error
    try:
        return loads(text, name=path.stem)
    except ThemeError as error:
        raise ThemeError(f"theme {path}: {error}") from error


def bundled_names() -> tuple[str, ...]:
    """The shipped theme names, sorted."""
    return tuple(sorted(path.stem for path in BUNDLED.glob("*.toml")))


def user_config_dir() -> Path:
    """`$XDG_CONFIG_HOME/backdraft`, or `~/.config/backdraft`."""
    base = os.environ.get("XDG_CONFIG_HOME")
    return (Path(base).expanduser() if base else Path.home() / ".config") / "backdraft"


def search_paths(project_root: Path | None = None) -> list[Path]:
    """Where an unflagged render looks for a theme, nearest first."""
    paths = []
    if project_root is not None:
        paths.append(project_root / DIRECTORY / FILENAME)
    paths.append(user_config_dir() / FILENAME)
    return paths


def resolve(requested: str | None = None, *, project_root: Path | None = None) -> Theme | None:
    """The theme this render uses, or `None` for the built-in look.

    `requested` is a bundled theme's name or a path to a file; without it the
    search path decides. Returning `None` rather than an empty `Theme` is what
    keeps an unthemed artifact byte-identical to one built before themes existed.
    """
    if requested is not None:
        return _named_or_path(requested)
    for path in search_paths(project_root):
        if path.is_file():
            return load(path)
    return None


def _named_or_path(requested: str) -> Theme:
    candidate = BUNDLED / f"{requested}.toml"
    if "/" not in requested and not requested.endswith(".toml") and candidate.is_file():
        return load(candidate)
    path = Path(requested).expanduser()
    if not path.is_file():
        raise ThemeError(
            f"no theme {requested!r}: not a file, and not one of the bundled themes "
            f"({', '.join(bundled_names())})"
        )
    return load(path)
