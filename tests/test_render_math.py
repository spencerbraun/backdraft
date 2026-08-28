"""Math in an authored document: what is math, what only looks like it, and what
happens when the converter is absent or the formula is malformed."""

from __future__ import annotations

import dataclasses

import pytest

from backdraft.kernel import hashing
from backdraft.kernel.claims import parse_claims
from backdraft.kernel.model import Anchor, BindReport, Citation, CitationStatus, Receipt
from backdraft.kernel.tokens import parse_locator
from backdraft.render import math
from backdraft.render.html import page
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


# ---- in a rendered artifact -------------------------------------------------
#
# Everything above tests the two markdown entry points. These test the page, and
# they are the tests the feature was missing: `page.render` is where the one
# collector is shared between a claim's text and the document body, and where a
# conversion failure becomes a note the reader can act on — neither of which the
# markdown-level tests reach.


MATH_DOC = """# Coverage

The property clears its covenant at a
[DSCR of $\\frac{NOI}{D} = 1.42$](bd:t12:p8.c3:f3e4), which is the ratio below.

$$\\mathrm{DSCR} = \\frac{\\mathrm{NOI}}{\\mathrm{Debt\\ service}}$$

Reserves run $250 per unit per year against $1.2M of debt.
"""


def _report(doc: str) -> BindReport:
    """The document above, bound: one claim, one resolved citation, one snippet.

    The snippet deliberately carries `$1.42$` — evidence that looks like math is
    how the "off for evidence" promise gets tested rather than asserted.
    """
    claims = parse_claims(doc)
    snippet = "Coverage is $1.42$ against a floor of $1.20$."
    citation = Citation(
        token="bd:t12:p8.c3:f3e4",
        status=CitationStatus.RESOLVED,
        anchor=Anchor(
            slug="t12",
            locator=parse_locator("p8.c3"),
            receipt=Receipt(snippet=snippet, snippet_sha256=hashing.snippet_hash(snippet)),
            token="bd:t12:p8.c3:f3e4",
            page_number=8,
        ),
    )
    return BindReport(
        doc_path="memo.md",
        mode="frontwalk",
        bound_at="2026-08-28T00:00:00Z",
        claims=tuple(
            dataclasses.replace(claim, citations=(citation,) if index == 0 else ())
            for index, claim in enumerate(claims)
        ),
    )


def _document(out: str) -> str:
    """The rendered page without its record island.

    The island carries every claim's text *as authored*, TeX and all — that is
    the record doing its job — so an assertion that a formula stopped being TeX
    has to be made about the part a reader looks at.
    """
    body, _, _ = out.partition('<script type="application/json"')
    return body


def test_an_artifact_renders_math_in_the_body_and_inside_a_claim() -> None:
    """The one collector, end to end: a formula in a claim and one in the body."""
    pytest.importorskip("latex2mathml", reason="[math] extra not installed")
    out = _document(page.render(MATH_DOC, _report(MATH_DOC)))
    assert out.count("<math") >= 2, "the claim's formula and the display block"
    assert 'display="block"' in out, "the $$...$$ paragraph is a block"
    assert "\\frac{NOI}{D}" not in out, "the claim's TeX became math, not text"


def test_an_artifacts_currency_survives_the_math_pass() -> None:
    """`$250 per unit ... $1.2M` is the hazard the whole guard exists for."""
    out = _document(page.render(MATH_DOC, _report(MATH_DOC)))
    assert "$250 per unit per year against $1.2M" in out


def test_a_receipts_snippet_is_never_rendered_as_math() -> None:
    """Evidence reads as it was extracted. The snippet here looks exactly like math.

    Read off the document rather than the whole page: the record island quotes
    the snippet too, and a check that the *card* left it alone must not be able
    to pass on the island's copy.
    """
    out = _document(page.render(MATH_DOC, _report(MATH_DOC)))
    assert "Coverage is $1.42$ against a floor of $1.20$." in out
    assert "<math" not in out.split("Coverage is $1.42$")[0].rsplit("<li", 1)[-1]


def test_a_formula_that_will_not_convert_earns_a_note_in_the_artifact() -> None:
    """The failure path at page level: a wavy mark where it stands, a note here.

    `_math_note` is the only thing on the page that explains why one run of text
    is not typeset like the rest, so it carries the reason and links both ways.
    """
    pytest.importorskip("latex2mathml", reason="[math] extra not installed")
    broken = "# Broken\n\nA formula \\[ \\begin{bmatrix} a \\] mid-sentence.\n"
    out = _document(page.render(broken, _report(broken)))
    assert 'class="math math-error" id="bd-math-1"' in out, "marked where it stands"
    assert 'id="bd-math-1-note"' in out, "and explained in the notes"
    assert "could not be rendered as math (missing end)" in out
    assert 'href="#bd-math-1"' in out, "the note links back to the formula"


def test_an_artifact_without_math_gains_no_math_note() -> None:
    """Success is silent: a document with no formulas says nothing about math."""
    plain = "# Plain\n\nReserves run $250 per unit against $1.2M of debt.\n"
    out = _document(page.render(plain, _report(plain)))
    assert "could not be rendered as math" not in out
    assert "bd-math-" not in out
