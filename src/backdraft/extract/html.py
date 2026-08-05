"""HTML pages: markup in, one page of readable text out.

A web page has no pagination, so — like `text` — the whole document is page 1
and the chunker supplies the sub-page structure. What this extractor owes the
chunker is *blank lines*: markup carries structure in tags, the chunker splits
on blank lines, so every block-level element closes a block and blocks are
joined by one.

The rules, pinned by `tests/test_extract_html.py` because the representation is
what claims get traced against:

- `script`, `style`, `noscript`, `template` and `svg` are dropped whole. A
  page's script is not its text, and leaving it in would anchor citations to
  minified JavaScript.
- Block-level elements end a block; inline ones do not. Runs of whitespace
  collapse to one space, as a browser would render them; `pre` keeps its own.
- List items become `- item` lines (`1. item` inside `<ol>`), nested lists
  indent two spaces, and the whole list is one block — a list is one idea, and
  splitting it would anchor half of it.
- Tables become markdown pipe tables with the first row as the header, exactly
  as `docx` renders them, so the two read alike in a receipt. A nested table
  flattens into its containing cell.
- The page's name is its `<title>`, truncated; a page without one takes the
  file stem.

Coordinates live in-band (DESIGN principle 5), which is why the list markers
and pipes are in the snapshot rather than in a side channel: the snapshot is
the receipt, and a quote from a table row should still look like a table row.

Nothing here is a readability heuristic — no boilerplate stripping, no "main
content" guess. Navigation and footers are part of the page, a guess about
which parts matter is not deterministic across two versions of a site, and an
anchor that moved because a heuristic changed its mind is the failure mode this
whole system exists to avoid.

Decoding is a pure function of the bytes — BOM, then the document's own
`<meta charset>`, then UTF-8 with replacement. NOTE: a server's `Content-Type`
charset is deliberately *not* consulted, even for a fetched page: identity is
the bytes, so the same bytes must extract the same way whether they arrived
over the network or were saved to disk. The cost is a non-UTF-8 page that
declares its encoding only in the HTTP header; HTML5 requires the in-document
declaration, and mojibake in the snapshot is visible rather than silent.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterator

from .base import ExtractedPage, Extractor, register

__all__ = ["HtmlExtractor", "EXTRACTOR", "decode", "parse"]

_MEDIA_TYPES = frozenset({"html"})
_SUFFIXES = frozenset({".html", ".htm", ".xhtml"})

MAX_TITLE_CHARS = 80
"""A page's title is its `<title>`, truncated to this — as `docx` truncates."""

# Dropped whole: content that is not the page's text. `head` is not here — it
# holds the `<title>`, and everything else in it is void or already skipped.
_SKIPPED = frozenset({"script", "style", "noscript", "template", "svg"})

_BLOCKS = frozenset(
    {
        "address", "article", "aside", "blockquote", "body", "dd", "details",
        "dialog", "div", "dl", "dt", "fieldset", "figcaption", "figure",
        "footer", "form", "h1", "h2", "h3", "h4", "h5", "h6", "header",
        "hgroup", "hr", "main", "nav", "p", "pre", "section", "summary",
    }
)

_LISTS = frozenset({"ul", "ol"})
_CELLS = frozenset({"td", "th"})

_WHITESPACE = re.compile(r"\s+")
_CHARSET = re.compile(rb"""<meta[^>]*?charset\s*=\s*["']?\s*([-\w.]+)""", re.IGNORECASE)
_SNIFF_BYTES = 4096
"""How far into the bytes to look for a `<meta charset>`."""

_BOMS = (
    (b"\xef\xbb\xbf", "utf-8-sig"),
    (b"\xff\xfe", "utf-16"),
    (b"\xfe\xff", "utf-16"),
)


class HtmlExtractor:
    """HTML to readable text. Deterministic: it is a parse, with no heuristics."""

    name = "html"
    version = "1"
    deterministic = True

    def can_handle(self, path: Path, media_type: str) -> bool:
        return media_type in _MEDIA_TYPES or path.suffix.lower() in _SUFFIXES

    def extract(self, path: Path, config: dict) -> Iterator[ExtractedPage]:
        """The page's readable text as page 1, named by its `<title>`."""
        title, text = parse(decode(path.read_bytes()))
        yield ExtractedPage(number=1, kind="page", name=title or path.stem, text=text)


def decode(data: bytes) -> str:
    """Bytes to markup: BOM, then `<meta charset>`, then UTF-8 with replacement."""
    for bom, encoding in _BOMS:
        if data.startswith(bom):
            return data.decode(encoding, errors="replace")
    match = _CHARSET.search(data[:_SNIFF_BYTES])
    if match is not None:
        try:
            return data.decode(match.group(1).decode("ascii", "replace"), errors="replace")
        except LookupError:
            pass  # a charset nothing implements; UTF-8 with replacement is the floor
    return data.decode("utf-8", errors="replace")


def parse(markup: str) -> tuple[str, str]:
    """`(title, text)` — one pass, because `extract` needs both."""
    reader = _Reader()
    reader.feed(markup)
    reader.close()
    return _collapse(reader.title)[:MAX_TITLE_CHARS], reader.text()


class _Reader(HTMLParser):
    """One pass over the markup, accumulating blocks.

    Three nested places text can land, innermost first: an open table cell, the
    line being built, the block being built. Blocks are flushed at block-level
    boundaries and joined with blank lines at the end.

    Skipping tracks the *tag* that opened it rather than a depth counter, so an
    unclosed `<g>` inside an `<svg>` cannot swallow the rest of the document.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title = ""
        self._blocks: list[str] = []
        self._lines: list[str] = []  # lines of the block being built
        self._buffer: list[str] = []  # inline text of the line being built
        self._indent = ""  # leading whitespace the current line keeps
        self._skip: str | None = None  # the tag that opened the skipped region
        self._skip_depth = 0
        self._pre = 0
        self._in_title = False
        self._lists: list[int | None] = []  # None: <ul>; int: next <ol> number
        self._tables: list[list[list[str]]] = []  # stack of tables -> rows -> cells
        self._cells: list[list[str]] = []  # inline buffer per open cell
        self._depths: list[int] = []  # len(_cells) when each table opened

    # ---- output -------------------------------------------------------------

    def text(self) -> str:
        while self._tables:  # markup that never closed its tables
            self._close_table()
        self._end_block()
        return "\n\n".join(self._blocks)

    def _end_line(self) -> None:
        """Finish the line being built, keeping it if it carries any text."""
        raw = "".join(self._buffer)
        self._buffer.clear()
        line = raw.rstrip() if self._pre else self._indent + _collapse(raw)
        if line.strip():
            self._lines.append(line)

    def _end_block(self) -> None:
        self._end_line()
        self._indent = ""
        if self._lines:
            self._blocks.append("\n".join(self._lines))
            self._lines = []

    def _close_table(self) -> None:
        """Finish the innermost table: a block of its own, or text in its parent cell.

        A nested table contributes its cells' *values* to the containing cell,
        not its rendering — a row of `\\|`-escaped pipes inside one cell of an
        outer table is noise in every receipt that quotes it.
        """
        rows = self._tables.pop()
        del self._cells[self._depths.pop() :]  # cells the markup never closed
        if self._cells:
            values = " ".join(cell for row in rows for cell in row if cell)
            self._cells[-1].append(f" {values} ")
            return
        self._end_block()
        rendered = _pipe_table(rows)
        if rendered:
            self._blocks.append(rendered)

    # ---- parser callbacks ---------------------------------------------------

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if self._skip is not None:
            self._skip_depth += tag == self._skip
            return
        if tag in _SKIPPED:
            self._skip, self._skip_depth = tag, 1
            return
        if tag == "title":
            self._in_title = True
            return
        if tag == "table":
            if not self._tables:
                self._end_block()
            self._tables.append([])
            self._depths.append(len(self._cells))
            return
        if self._tables:
            self._open_in_table(tag)
            return
        if tag == "br":
            self._end_line()
            return
        if tag in _LISTS:
            self._end_block() if not self._lists else self._end_line()
            self._lists.append(1 if tag == "ol" else None)
            return
        if tag == "li":
            self._end_line()
            self._buffer.append(self._marker())
            return
        if tag in _BLOCKS:
            self._end_block()
        if tag == "pre":
            self._pre += 1

    def handle_endtag(self, tag: str) -> None:
        if self._skip is not None:
            if tag == self._skip:
                self._skip_depth -= 1
                if self._skip_depth <= 0:
                    self._skip = None
            return
        if tag == "title":
            self._in_title = False
            return
        if tag == "table" and self._tables:
            self._close_table()
            return
        if tag in _CELLS and self._cells:
            self._close_cell()
            return
        if self._tables:
            return
        if tag in _LISTS and self._lists:
            self._lists.pop()
            self._end_line()
            if not self._lists:
                self._end_block()
            return
        # Flush first, drop out of `pre` second: `pre` is itself a block, and
        # its closing tag has to be handled while its whitespace still counts.
        if tag in _BLOCKS:
            self._end_block()
        if tag == "pre":
            self._pre = max(0, self._pre - 1)

    def handle_startendtag(self, tag: str, attrs: list) -> None:
        # A self-closing tag changes no depth: `<svg/>` opens nothing to skip,
        # and `<path/>` inside one is already covered by the skip.
        if self._skip is None and tag not in _SKIPPED:
            self.handle_starttag(tag, attrs)

    def handle_data(self, data: str) -> None:
        if self._skip is not None:
            return
        if self._in_title:
            self.title += data
        elif self._cells:
            self._cells[-1].append(data)
        elif not self._tables:  # stray text between rows belongs to no cell
            self._buffer.append(data)

    # ---- helpers ------------------------------------------------------------

    def _open_in_table(self, tag: str) -> None:
        """Inside a table only rows and cells have structure; the rest is spacing."""
        if tag == "tr":
            self._tables[-1].append([])
        elif tag in _CELLS:
            if not self._tables[-1]:
                self._tables[-1].append([])  # a cell outside any row still lands
            self._cells.append([])
        elif self._cells and (tag in _BLOCKS or tag in _LISTS or tag in ("li", "br")):
            self._cells[-1].append(" ")

    def _close_cell(self) -> None:
        cell = _collapse("".join(self._cells.pop()))
        if self._tables and self._tables[-1]:
            self._tables[-1][-1].append(cell)

    def _marker(self) -> str:
        """The bullet or number a list item opens with; records its indent."""
        self._indent = "  " * max(0, len(self._lists) - 1)
        if not self._lists or self._lists[-1] is None:
            return "- "
        number = self._lists[-1]
        self._lists[-1] = number + 1
        return f"{number}. "


def _pipe_table(rows: list[list[str]]) -> str:
    """A markdown pipe table, first row as the header. `''` for an empty table."""
    filled = [row for row in rows if any(cell for cell in row)]
    if not filled:
        return ""
    width = max(len(row) for row in filled)
    padded = [[*row, *([""] * (width - len(row)))] for row in filled]
    header, *body = padded
    return "\n".join(
        [_pipe_row(header), _pipe_row(["---"] * width), *(_pipe_row(row) for row in body)]
    )


def _pipe_row(cells: list[str]) -> str:
    return "| " + " | ".join(cell.replace("|", "\\|") for cell in cells) + " |"


def _collapse(text: str) -> str:
    """Runs of whitespace to one space — what a browser renders."""
    return _WHITESPACE.sub(" ", text).strip()


EXTRACTOR: Extractor = HtmlExtractor()
register(EXTRACTOR)
