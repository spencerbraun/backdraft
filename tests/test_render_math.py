"""Math in an authored document: what is math, what only looks like it, and what
happens when the converter is absent or the formula is malformed."""

from __future__ import annotations

import pytest

from backdraft.render import math
from backdraft.render.markdown import inline, to_html


@pytest.fixture
def no_converter(monkeypatch: pytest.MonkeyPatch) -> None:
    """The `[math]` extra uninstalled, without uninstalling it."""
    monkeypatch.setattr(math, "_LOOKED", True)
    monkeypatch.setattr(math, "_CONVERTER", None)


def found(text: str) -> list[math.Math]:
    items: list[math.Math] = []
    math.protect(text, items)
    return items


def test_currency_is_never_math() -> None:
    """The hazard this guard exists for: a finance memo is full of dollars.

    A currency amount is preceded by a space, so under Pandoc's rule it can
    never close a span, and two amounts in a paragraph never pair.
    """
    assert found("Costs $250 and $300 and $1.2M.") == []
    assert found("Rent of $250 per unit against $1.2M of debt.") == []
    assert found("Reserves of $250 per unit per year.") == []


def test_code_is_skipped_rather_than_scanned() -> None:
    """`$PATH` and `$HOME` in a shell snippet are not a formula."""
    assert found("Shell `$PATH` and `$HOME` vars.") == []
    assert found("```\nexport $FOO\necho $BAR\n```\n") == []
    assert found("A $x$ and code `$y$` mixed.") == [math.Math("x", False, 0, "$x$")]


def test_the_four_delimiters() -> None:
    assert [(m.tex, m.display) for m in found(r"a $x+1$ b")] == [("x+1", False)]
    assert [(m.tex, m.display) for m in found(r"a \(x+1\) b")] == [("x+1", False)]
    assert [(m.tex, m.display) for m in found(r"a $$x+1$$ b")] == [("x+1", True)]
    assert [(m.tex, m.display) for m in found(r"a \[x+1\] b")] == [("x+1", True)]


def test_a_span_may_not_cross_a_blank_line() -> None:
    assert found("a $line and\n\nanother$ one") == []


def test_math_becomes_mathml() -> None:
    pytest.importorskip("latex2mathml", reason="[math] extra not installed")
    out = inline(r"Coverage is $\frac{NOI}{D}$ today.", [])
    assert "<math" in out and "<mfrac>" in out and "$" not in out


def test_display_math_is_a_block() -> None:
    pytest.importorskip("latex2mathml", reason="[math] extra not installed")
    assert 'display="block"' in to_html("$$E = mc^2$$", (), [])


def test_without_the_extra_math_is_verbatim_but_never_corrupted(no_converter: None) -> None:
    """The degradation path: unrendered, but not rewritten."""
    out = inline(r"With $x_1$ and $x_2$ the spread widens.", [])
    assert "<em>" not in out
    assert "$x_1$" in out and "$x_2$" in out
    assert 'class="math"' in out


def test_backslash_delimiters_survive_the_escape_pass(no_converter: None) -> None:
    """`\\(` and `\\)` were eaten as markdown escapes before math was lifted out."""
    out = inline(r"Inline \(a^2 + b^2 = c^2\) here.", [])
    assert r"\(a^2 + b^2 = c^2\)" in out


def test_malformed_math_is_data_not_a_traceback() -> None:
    pytest.importorskip("latex2mathml", reason="[math] extra not installed")
    items: list[math.Math] = []
    out = inline(r"A broken one \[ \begin{bmatrix} a \] here.", items)
    assert items[0].error == "missing end"
    assert "math-error" in out
    assert r"\begin{bmatrix}" in out, "the source is shown as written"


def test_evidence_gets_no_math_rendering() -> None:
    """A receipt's snippet must read as it was extracted, not as prose would."""
    out = to_html(r"Coverage is $\frac{NOI}{D}$ today.")
    assert "<math" not in out and r"$\frac{NOI}{D}$" in out


def test_one_collector_numbers_math_across_calls() -> None:
    """The page shares a collector so a formula's anchor is unique page-wide."""
    items: list[math.Math] = []
    inline(r"first $a$", items)
    to_html(r"second $b$", (), items)
    assert [m.anchor for m in items] == ["bd-math-1", "bd-math-2"]
