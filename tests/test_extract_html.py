"""The `html` extractor: markup in, the readable text a claim gets traced to.

The representation is pinned rather than described, for the same reason the
xlsx one is: it is what receipts quote, so a change to it moves what a citation
says. `PAGE` is one document exercising every rule at once, and the golden
below is its whole snapshot.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from backdraft.extract import base
from backdraft.extract.html import decode, parse
from backdraft.registry import media_type_for

PAGE = """\
<!doctype html>
<html><head><meta charset="utf-8"><title>Bridgeview  Q4 &amp; Outlook</title>
<style>.masthead{color:red}</style>
<script>var trap = "<p>script text is not page text</p>";</script></head>
<body>
<nav><a href="/">Home</a> <a href="/about">About</a></nav>
<h1>Bridgeview Holdings</h1>
<p>Net operating income rose to <b>$4.2M</b> in Q4&nbsp;2025, up
   11% year over year.</p>
<ul><li>Occupancy: 94.1%</li><li>Replacement reserve:
<ol><li>funded at $250k</li><li>held in escrow</li></ol></li></ul>
<table>
<tr><th>Metric</th><th>Q3</th><th>Q4</th></tr>
<tr><td>NOI</td><td>$3.8M</td><td>$4.2M</td></tr>
</table>
<pre>  two spaces
  and a newline</pre>
<svg><g><path d="M0 0"/></g></svg>
<p>Text after the svg still lands.</p>
</body></html>
"""

SNAPSHOT = """\
Home About

Bridgeview Holdings

Net operating income rose to $4.2M in Q4 2025, up 11% year over year.

- Occupancy: 94.1%
- Replacement reserve:
  1. funded at $250k
  2. held in escrow

| Metric | Q3 | Q4 |
| --- | --- | --- |
| NOI | $3.8M | $4.2M |

  two spaces
  and a newline

Text after the svg still lands."""


def test_the_snapshot_is_exactly_this() -> None:
    """The golden. Every rule in the module docstring shows up here."""
    title, text = parse(PAGE)
    assert title == "Bridgeview Q4 & Outlook"
    assert text == SNAPSHOT


# ---- selection --------------------------------------------------------------


@pytest.mark.parametrize("name", ["page.html", "page.htm", "page.xhtml"])
def test_html_files_select_the_html_extractor(name: str) -> None:
    assert base.select(Path(name), media_type_for(Path(name))).name == "html"


def test_markdown_still_selects_the_text_extractor() -> None:
    """`html` sits above `text` in AUTO_ORDER and must not shadow it."""
    assert base.select(Path("notes.md"), "text").name == "text"


def test_the_extractor_yields_one_named_page(tmp_path: Path) -> None:
    path = tmp_path / "q4.html"
    path.write_bytes(PAGE.encode("utf-8"))
    pages = list(base.get("html").extract(path, {}))
    assert len(pages) == 1
    assert (pages[0].number, pages[0].kind) == (1, "page")
    assert pages[0].name == "Bridgeview Q4 & Outlook"


def test_a_page_without_a_title_takes_the_file_stem(tmp_path: Path) -> None:
    path = tmp_path / "untitled.html"
    path.write_bytes(b"<html><body><p>No title element here.</p></body></html>")
    assert list(base.get("html").extract(path, {}))[0].name == "untitled"


# ---- blocks, so the chunker has something to split on -----------------------


def test_block_elements_separate_and_inline_ones_do_not() -> None:
    _, text = parse("<p>One <em>whole</em> sentence.</p><p>Another.</p>")
    assert text == "One whole sentence.\n\nAnother."


def test_br_breaks_a_line_without_breaking_the_block() -> None:
    _, text = parse("<p>First line<br>second line</p>")
    assert text == "First line\nsecond line"


def test_a_list_is_one_block() -> None:
    """A list is one idea; splitting it would anchor half of it."""
    _, text = parse("<ul><li>alpha</li><li>beta</li></ul>")
    assert text == "- alpha\n- beta"


def test_ordered_lists_number_their_items() -> None:
    _, text = parse("<ol><li>first</li><li>second</li><li>third</li></ol>")
    assert text == "1. first\n2. second\n3. third"


def test_pre_keeps_its_own_whitespace() -> None:
    _, text = parse("<pre>a   b\n  c</pre>")
    assert text == "a   b\n  c"


def test_entities_are_resolved() -> None:
    _, text = parse("<p>1&nbsp;&amp;&nbsp;2 &lt;tag&gt; &#8212; done</p>")
    assert text == "1 & 2 <tag> — done"


# ---- tables -----------------------------------------------------------------


def test_a_table_renders_as_a_pipe_table() -> None:
    _, text = parse("<table><tr><th>A</th><th>B</th></tr><tr><td>1</td><td>2</td></tr></table>")
    assert text == "| A | B |\n| --- | --- |\n| 1 | 2 |"


def test_a_short_row_is_padded_to_the_table_width() -> None:
    _, text = parse("<table><tr><td>a</td><td>b</td></tr><tr><td>c</td></tr></table>")
    assert text.splitlines()[-1] == "| c |  |"


def test_a_pipe_inside_a_cell_is_escaped() -> None:
    _, text = parse("<table><tr><td>a|b</td></tr></table>")
    assert "a\\|b" in text


def test_an_empty_table_disappears_rather_than_emitting_a_header() -> None:
    _, text = parse("<p>before</p><table><tr></tr></table><p>after</p>")
    assert text == "before\n\nafter"


def test_a_nested_table_contributes_its_values_not_its_pipes() -> None:
    _, text = parse(
        "<table><tr><td>outer<table><tr><td>inner</td></tr></table></td>"
        "<td>right</td></tr></table>"
    )
    assert text == "| outer inner | right |\n| --- | --- |"


def test_markup_that_never_closes_its_table_still_renders_it() -> None:
    _, text = parse("<table><tr><td>a</td><td>b</td></tr>")
    assert text == "| a | b |\n| --- | --- |"


def test_block_elements_inside_a_cell_do_not_break_the_row() -> None:
    _, text = parse("<table><tr><td><p>one</p><p>two</p></td><td>three</td></tr></table>")
    assert text.splitlines()[0] == "| one two | three |"


# ---- what is not the page's text --------------------------------------------


@pytest.mark.parametrize("tag", ["script", "style", "noscript", "template", "svg"])
def test_non_text_elements_are_dropped_whole(tag: str) -> None:
    _, text = parse(f"<p>kept</p><{tag}>dropped</{tag}><p>also kept</p>")
    assert text == "kept\n\nalso kept"


def test_an_unclosed_tag_inside_a_dropped_element_does_not_eat_the_page() -> None:
    """Skipping tracks the tag that opened it, not a depth counter."""
    _, text = parse("<svg><g><path/></svg><p>survives</p>")
    assert text == "survives"


def test_nested_templates_close_at_the_right_depth() -> None:
    _, text = parse("<template><template>x</template>y</template><p>after</p>")
    assert text == "after"


# ---- decoding ---------------------------------------------------------------


def test_a_meta_charset_is_honoured() -> None:
    data = '<meta charset="iso-8859-1"><p>caf\xe9</p>'.encode("iso-8859-1")
    assert "café" in decode(data)


def test_a_bom_outranks_a_contradicting_meta_charset() -> None:
    data = b"\xef\xbb\xbf" + '<meta charset="iso-8859-1"><p>café</p>'.encode("utf-8")
    assert decode(data).endswith("<p>café</p>")


def test_an_unknown_charset_falls_back_to_utf8() -> None:
    """A charset nothing implements must not fail the ingest."""
    assert "café" in decode(b'<meta charset="x-not-a-codec"><p>caf\xc3\xa9</p>')


def test_undecodable_bytes_are_replaced_rather_than_raising() -> None:
    """As the text extractor does: a snapshot with a replacement character
    still anchors; a failed ingest anchors nothing."""
    assert "�" in decode(b"<p>\xfa\xfb not utf-8</p>")


# ---- degenerate input -------------------------------------------------------


def test_plain_text_with_no_markup_passes_through() -> None:
    """The staged fallback for an unlabelled URL is `.html`, so this is the
    shape a plain-text page takes when a server declared nothing."""
    assert parse("just a sentence") == ("", "just a sentence")


def test_an_empty_document_is_an_empty_page() -> None:
    assert parse("") == ("", "")
