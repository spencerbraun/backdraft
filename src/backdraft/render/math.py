"""Math in an authored document: recognized, protected, and converted to MathML.

An author writing about a coverage ratio writes `$\\mathrm{DSCR} = \\frac{NOI}{D}$`,
and before this module the markdown renderer handed the reader raw TeX at best
and corrupted TeX at worst — `\\(a^2\\)` lost its delimiters to the backslash-escape
pass. So math is lifted out of the source *before* any markdown rule sees it and
put back after, which is the same protection code spans get by being matched
first.

The conversion is `latex2mathml`, an optional dependency behind the `[math]`
extra. MathML is the target rather than a bundled KaTeX because it is static
markup the browser lays out itself: no script, no font file, no external request,
so the artifact's self-containment holds by construction instead of by care. The
cost is that MathML leans on a system math font, which is the one place the
artifact's fixed-at-render promise is soft — see the DESIGN row.

Without the extra installed, math is still never *corrupted*: it renders verbatim
in a `.math` span. That is the degradation path, not the destination.

**Dollars are hazardous.** A finance memo is full of `$250 per unit` and `$1.2M`,
and a naive `$...$` rule pairs them into nonsense. The guard is Pandoc's, and it
is why that does not happen: the opening `$` must be followed by a non-space, the
closing `$` must be preceded by a non-space and not followed by a digit, and the
span may not cross a blank line. A currency amount is preceded by a space, so it
can never close a span, and the pair never forms.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from typing import Callable, Sequence

__all__ = ["Math", "available", "protect", "restore"]

PLACEHOLDER = "\x02m{index}\x02"

# Ordered alternation. `fenced` and `code` exist only to be *skipped*: they match
# first so that a shell snippet's `$PATH` and `$HOME` are never read as a formula.
# Their text is returned untouched, so block and inline code render exactly as
# they did before this module existed.
_SCAN_RE = re.compile(
    r"""
      (?P<fenced>^[ \t]*(?P<f>```+|~~~+)[^\n]*$.*?^[ \t]*(?P=f)[ \t]*$)
    | (?P<code>(?P<t>`+).+?(?P=t))
    | (?P<display>\$\$(?P<dtex>(?:[^$]|\$(?!\$))+?)\$\$|\\\[(?P<btex>.+?)\\\])
    | \\\((?P<ptex>.+?)\\\)
    | (?P<dollar>\$(?![\s$])(?P<itex>(?:[^$\n]|\n(?!\s*\n))+?)(?<![\s])\$(?!\d))
    """,
    re.VERBOSE | re.MULTILINE | re.DOTALL,
)


@dataclass(slots=True)
class Math:
    """One math span lifted out of a document, and what became of it."""

    tex: str
    display: bool
    index: int
    source: str  # the original text, delimiters included
    error: str | None = field(default=None)

    @property
    def anchor(self) -> str:
        return f"bd-math-{self.index + 1}"


def available() -> bool:
    """Whether the `[math]` extra is installed, so math can become MathML."""
    return _convert() is not None


_CONVERTER: Callable[..., str] | None = None
_LOOKED = False


def _convert() -> Callable[..., str] | None:
    """The converter, imported once and only when a document actually has math."""
    global _CONVERTER, _LOOKED
    if not _LOOKED:
        _LOOKED = True
        try:
            from latex2mathml.converter import convert
        except ModuleNotFoundError:
            _CONVERTER = None
        else:
            _CONVERTER = convert
    return _CONVERTER


def protect(text: str, found: list[Math]) -> str:
    """Replace every math span in `text` with a placeholder, recording each.

    Code — fenced or inline — is skipped rather than captured, so nothing inside
    it is ever read as math. `found` is appended to and its indices are the
    placeholder ids, so one list may be shared across several calls.
    """

    def take(match: re.Match[str]) -> str:
        if match["fenced"] is not None or match["code"] is not None:
            return match.group(0)
        if (tex := match["dtex"]) is not None or (tex := match["btex"]) is not None:
            display = True
        elif (tex := match["ptex"]) is not None:
            display = False
        else:
            tex, display = match["itex"], False
        found.append(Math(tex.strip(), display, len(found), match.group(0)))
        return PLACEHOLDER.format(index=found[-1].index)

    return _SCAN_RE.sub(take, text)


def restore(rendered: str, found: Sequence[Math]) -> str:
    """Substitute each placeholder in `rendered` with the math it stands for."""
    for item in found:
        marker = PLACEHOLDER.format(index=item.index)
        if marker in rendered:
            rendered = rendered.replace(marker, _html(item))
    return rendered


def _html(item: Math) -> str:
    """One math span as HTML: MathML if it converted, the source if it did not."""
    convert = _convert()
    if convert is not None:
        try:
            return convert(item.tex, display="block" if item.display else "inline")
        except Exception as exc:  # noqa: BLE001 — any converter failure is data
            item.error = _reason(exc)
    return (
        f'<span class="math{" math-error" if item.error else ""}" id="{item.anchor}"'
        f'{f" title={html.escape(item.error, quote=True)!r}" if item.error else ""}>'
        f"{html.escape(item.source, quote=False)}</span>"
    )


def _reason(exc: Exception) -> str:
    """A converter exception as a sentence, since a traceback is not an answer."""
    name = type(exc).__name__.removesuffix("Error")
    spelled = re.sub(r"(?<!^)(?=[A-Z])", " ", name).lower()
    detail = str(exc).strip()
    return f"{spelled}{f': {detail}' if detail else ''}"
