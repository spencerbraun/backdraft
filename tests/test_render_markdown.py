"""The markdown subset: what the artifact's document body supports, and no more."""

from __future__ import annotations

from backdraft.render import markdown


def render(source: str) -> str:
    return markdown.to_html(source)


def test_headings() -> None:
    assert render("# One") == "<h1>One</h1>"
    assert render("###### Six") == "<h6>Six</h6>"
    assert render("## Closed ##") == "<h2>Closed</h2>"
    assert render("#NoSpace") == "<p>#NoSpace</p>"


def test_paragraphs_join_wrapped_lines() -> None:
    assert render("one\ntwo\n\nthree") == "<p>one two</p>\n<p>three</p>"


def test_inline_forms() -> None:
    assert render("**bold** and *italic* and `code`") == (
        "<p><strong>bold</strong> and <em>italic</em> and <code>code</code></p>"
    )
    assert render("__bold__ and _italic_") == "<p><strong>bold</strong> and <em>italic</em></p>"


def test_links() -> None:
    assert render("[text](notes.md)") == '<p><a href="notes.md">text</a></p>'
    assert render('[text](notes.md "why")') == '<p><a href="notes.md">text</a></p>'


def test_script_hrefs_are_neutralized() -> None:
    rendered = render("[click](javascript:void)")
    assert "javascript:" not in rendered
    assert rendered == "<p>click</p>"


def test_images_render_as_alt_text() -> None:
    rendered = render("![a chart](chart.png)")
    assert "<img" not in rendered
    assert "chart.png" not in rendered
    assert "a chart" in rendered


def test_html_is_escaped() -> None:
    assert render("a < b & c") == "<p>a &lt; b &amp; c</p>"
    assert render("`<script>`") == "<p><code>&lt;script&gt;</code></p>"


def test_backslash_escapes() -> None:
    assert render(r"not \*italic\*") == "<p>not *italic*</p>"


def test_unordered_and_ordered_lists() -> None:
    assert render("- one\n- two") == "<ul><li>one</li><li>two</li></ul>"
    assert render("1. one\n2. two") == "<ol><li>one</li><li>two</li></ol>"


def test_nested_lists() -> None:
    rendered = render("- one\n  - inner\n- two")
    assert rendered == (
        "<ul><li><p>one</p>\n<ul><li>inner</li></ul></li><li>two</li></ul>"
    )


def test_blockquote() -> None:
    assert render("> quoted\n> lines") == "<blockquote><p>quoted lines</p></blockquote>"


def test_fenced_code_is_not_inline_rendered() -> None:
    rendered = render("```\n**not bold** <tag>\n```")
    assert rendered == "<pre><code>**not bold** &lt;tag&gt;</code></pre>"


def test_thematic_break() -> None:
    assert render("one\n\n---\n\ntwo") == "<p>one</p>\n<hr>\n<p>two</p>"


def test_tables_with_alignment() -> None:
    rendered = render("| a | b | c |\n|---|:-:|--:|\n| 1 | 2 | 3 |")
    assert '<div class="table-wrap"><table>' in rendered
    assert "<th>a</th>" in rendered
    assert '<th class="t-center">b</th>' in rendered
    assert '<td class="t-right">3</td>' in rendered


def test_a_table_needs_its_rule() -> None:
    assert "<table>" not in render("| a | b |\n| 1 | 2 |")


def test_spans_are_spliced_verbatim() -> None:
    source = "The [DSCR](bd:x:p1:0000) holds."
    span = markdown.Span(start=4, end=24, html="<mark>DSCR</mark>")
    assert markdown.to_html(source, [span]) == "<p>The <mark>DSCR</mark> holds.</p>"


def test_spliced_html_is_not_escaped_inside_a_table() -> None:
    source = "| a |\n|---|\n| x |\n"
    cell = source.index("| x |") + 2
    span = markdown.Span(start=cell, end=cell + 1, html="<b>x</b>")
    assert "<td><b>x</b></td>" in markdown.to_html(source, [span])


def test_overlapping_spans_are_refused() -> None:
    source = "abcdef"
    spans = [markdown.Span(0, 4, "<i>"), markdown.Span(2, 6, "<b>")]
    try:
        markdown.to_html(source, spans)
    except ValueError as error:
        assert "overlapping" in str(error)
    else:  # pragma: no cover - the assertion above is the test
        raise AssertionError("overlapping spans must be refused")


def test_inline_renders_a_claims_own_formatting() -> None:
    assert markdown.inline("**DSCR** of `1.42x`") == (
        "<strong>DSCR</strong> of <code>1.42x</code>"
    )
