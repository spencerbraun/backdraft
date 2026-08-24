"""A small markdown subset, rendered to HTML with stdlib only.

The artifact must be one file with no dependency at read time and none at build
time either, so the document body goes through this renderer rather than a
markdown library. The subset is exactly what an authored memo uses: headings,
paragraphs, lists, tables, blockquotes, fenced code, thematic breaks, and the
inline forms bold / italic / code / link.

Claims are not parsed here. `to_html` takes the source ranges bind already
located and splices caller-supplied HTML into them, so the claim spans in the
artifact are the spans the report recorded — never a second, disagreeing parse.

NOTE (deliberate omissions, the spec is silent on all of them): reference links,
setext headings, HTML passthrough, footnote syntax, and autolinks are not
recognized and render as literal text. Intraword `_` is not a delimiter, per
CommonMark, so `snake_case_name` survives as written; `*` is unrestricted. Images render as their alt text: an
`<img>` would be an external request, which the artifact does not make.
"""

from __future__ import annotations

import html
import re
from collections.abc import Sequence
from dataclasses import dataclass

__all__ = ["Span", "to_html", "inline"]

_SPLICE = "\x00s{index}\x00"
_ESCAPED = "\x01e{index}\x01"

_HEADING_RE = re.compile(r"(?P<level>#{1,6})\s+(?P<text>.*?)\s*#*\s*$")
_RULE_RE = re.compile(r"(?:\*\s*){3,}|(?:-\s*){3,}|(?:_\s*){3,}")
_FENCE_RE = re.compile(r"(?P<indent>\s*)(?P<fence>```+|~~~+)(?P<info>.*)$")
_BULLET_RE = re.compile(r"(?P<indent>[ \t]*)(?P<marker>[-*+])[ \t]+(?P<text>.*)$")
_ORDERED_RE = re.compile(r"(?P<indent>[ \t]*)(?P<marker>\d{1,9})[.)][ \t]+(?P<text>.*)$")
_QUOTE_RE = re.compile(r"[ \t]*>[ \t]?(?P<text>.*)$")
_ALIGN_RE = re.compile(r":?-{1,}:?")
_BACKSLASH_RE = re.compile(r"\\([\\`*_{}\[\]()#+\-.!|>~])")
_SAFE_HREF_RE = re.compile(r"\s*javascript\s*:", re.IGNORECASE)

# CommonMark's flanking rule, in the one form this subset needs: a `_` run with a
# word character on either side is never a delimiter, which is why `_` and `*` are
# spelled as separate alternatives below. Without it `snake_case_name` renders as
# `snake<em>case</em>name` — authored text silently rewritten, which is the one
# thing a tool whose claim is that a document's text is checkable cannot do. The
# guard is `\w` rather than alphanumeric so that it also refuses to start or end
# inside a run of underscores, which is what keeps `snake__case__name` whole.
_INLINE_RE = re.compile(
    r"""
      (?P<fence>`+)(?P<code>.+?)(?P=fence)
    | !\[(?P<alt>[^\]]*)\]\([^)]*\)
    | \[(?P<label>(?:[^\[\]]|\[[^\]]*\])*)\]\((?P<href>[^)\s]*)(?:\s+"[^"]*")?\)
    | \*\*(?P<strong>.+?)\*\*
    | (?<!\w)__(?P<strong_us>.+?)__(?!\w)
    | \*(?P<em>.+?)\*
    | (?<!\w)_(?P<em_us>.+?)_(?!\w)
    """,
    re.VERBOSE | re.DOTALL,
)


@dataclass(frozen=True, slots=True)
class Span:
    """A source range whose rendered form the caller supplies.

    `start`/`end` are character offsets into the source; `html` replaces that
    range verbatim and is never escaped or re-parsed.
    """

    start: int
    end: int
    html: str


def to_html(source: str, spans: Sequence[Span] = ()) -> str:
    """Render `source` as HTML, splicing each span's HTML into its source range.

    Spans must not overlap; they are applied in source order.
    """
    masked, splices = _mask_spans(source, spans)
    rendered = _blocks(masked.expandtabs(4).splitlines())
    for index, markup in enumerate(splices):
        rendered = rendered.replace(_SPLICE.format(index=index), markup)
    return rendered


def inline(text: str) -> str:
    """Render one run of inline markdown — the form used inside a claim's text."""
    escapes: list[str] = []

    def stash(match: re.Match[str]) -> str:
        escapes.append(html.escape(match.group(1), quote=False))
        return _ESCAPED.format(index=len(escapes) - 1)

    rendered = _inline(_BACKSLASH_RE.sub(stash, text))
    for index, literal in enumerate(escapes):
        rendered = rendered.replace(_ESCAPED.format(index=index), literal)
    return rendered


def _mask_spans(source: str, spans: Sequence[Span]) -> tuple[str, list[str]]:
    """Replace each span's source range with a splice marker."""
    ordered = sorted(spans, key=lambda span: span.start)
    pieces: list[str] = []
    splices: list[str] = []
    cursor = 0
    for span in ordered:
        if span.start < cursor:
            raise ValueError(f"overlapping span at {span.start}")
        pieces.append(source[cursor : span.start])
        pieces.append(_SPLICE.format(index=len(splices)))
        splices.append(span.html)
        cursor = span.end
    pieces.append(source[cursor:])
    return "".join(pieces), splices


def _blocks(lines: Sequence[str]) -> str:
    """Render a sequence of lines as block-level HTML."""
    out: list[str] = []
    index = 0
    total = len(lines)
    while index < total:
        line = lines[index]
        if not line.strip():
            index += 1
            continue
        if fence := _FENCE_RE.fullmatch(line):
            index = _code_block(lines, index, fence, out)
            continue
        if heading := _HEADING_RE.fullmatch(line.strip()):
            level = len(heading["level"])
            out.append(f"<h{level}>{inline(heading['text'])}</h{level}>")
            index += 1
            continue
        if _RULE_RE.fullmatch(line.strip()):
            out.append("<hr>")
            index += 1
            continue
        if _QUOTE_RE.fullmatch(line):
            index = _quote_block(lines, index, out)
            continue
        if _BULLET_RE.fullmatch(line) or _ORDERED_RE.fullmatch(line):
            index = _list_block(lines, index, out)
            continue
        if index + 1 < total and _is_table_rule(lines[index + 1]) and "|" in line:
            index = _table_block(lines, index, out)
            continue
        index = _paragraph(lines, index, out)
    return "\n".join(out)


def _code_block(lines: Sequence[str], index: int, fence: re.Match[str], out: list[str]) -> int:
    """Consume a fenced code block. Its content is never inline-rendered."""
    marker = fence["fence"]
    body: list[str] = []
    index += 1
    while index < len(lines) and lines[index].strip() != marker:
        body.append(lines[index])
        index += 1
    escaped = html.escape("\n".join(body), quote=False)
    out.append(f"<pre><code>{escaped}</code></pre>")
    return index + 1 if index < len(lines) else index


def _quote_block(lines: Sequence[str], index: int, out: list[str]) -> int:
    body: list[str] = []
    while index < len(lines) and (match := _QUOTE_RE.fullmatch(lines[index])):
        body.append(match["text"])
        index += 1
    out.append(f"<blockquote>{_blocks(body)}</blockquote>")
    return index


def _list_block(lines: Sequence[str], index: int, out: list[str]) -> int:
    """Consume one list, including indented continuation lines and sublists."""
    ordered = _ORDERED_RE.fullmatch(lines[index]) is not None
    items: list[list[str]] = []
    loose = False
    pending_blank = False
    while index < len(lines):
        line = lines[index]
        item = _ORDERED_RE.fullmatch(line) if ordered else _BULLET_RE.fullmatch(line)
        if item is not None and len(item["indent"]) < 2:
            items.append([item["text"]])
            loose = loose or (pending_blank and len(items) > 1)
            pending_blank = False
            index += 1
            continue
        if not line.strip():
            if not items:
                break
            pending_blank = True
            index += 1
            continue
        if items and line.startswith("  "):
            if pending_blank:
                items[-1].append("")
                loose = True
                pending_blank = False
            items[-1].append(line[2:])
            index += 1
            continue
        break
    rendered = [f"<li>{_item(body, loose)}</li>" for body in items]
    tag = "ol" if ordered else "ul"
    out.append(f"<{tag}>{''.join(rendered)}</{tag}>")
    return index


def _item(body: Sequence[str], loose: bool) -> str:
    """One list item: bare inline when it is a single simple line, blocks otherwise."""
    if not loose and len(body) == 1:
        return inline(body[0])
    return _blocks(body)


def _table_block(lines: Sequence[str], index: int, out: list[str]) -> int:
    header = _row(lines[index])
    alignments = [_alignment(cell) for cell in _row(lines[index + 1])]
    index += 2
    rows: list[list[str]] = []
    while index < len(lines) and "|" in lines[index] and lines[index].strip():
        rows.append(_row(lines[index]))
        index += 1
    head = "".join(
        f"<th{_align_attr(alignments, column)}>{inline(cell)}</th>"
        for column, cell in enumerate(header)
    )
    body = "".join(
        "<tr>"
        + "".join(
            f"<td{_align_attr(alignments, column)}>{inline(cell)}</td>"
            for column, cell in enumerate(row)
        )
        + "</tr>"
        for row in rows
    )
    out.append(
        '<div class="table-wrap"><table>'
        f"<thead><tr>{head}</tr></thead><tbody>{body}</tbody>"
        "</table></div>"
    )
    return index


def _paragraph(lines: Sequence[str], index: int, out: list[str]) -> int:
    body: list[str] = []
    while index < len(lines) and lines[index].strip():
        line = lines[index]
        if body and (
            _HEADING_RE.fullmatch(line.strip())
            or _FENCE_RE.fullmatch(line)
            or _QUOTE_RE.fullmatch(line)
            or _BULLET_RE.fullmatch(line)
            or _ORDERED_RE.fullmatch(line)
        ):
            break
        body.append(line.strip())
        index += 1
    out.append(f"<p>{inline(' '.join(body))}</p>")
    return index


def _is_table_rule(line: str) -> bool:
    stripped = line.strip()
    if "-" not in stripped or not stripped:
        return False
    cells = _row(line)
    return bool(cells) and all(_ALIGN_RE.fullmatch(cell) for cell in cells)


def _row(line: str) -> list[str]:
    stripped = line.strip()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]
    return [cell.strip() for cell in stripped.split("|")]


def _alignment(cell: str) -> str:
    left, right = cell.startswith(":"), cell.endswith(":")
    if left and right:
        return "center"
    if right:
        return "right"
    return "left"


def _align_attr(alignments: Sequence[str], column: int) -> str:
    align = alignments[column] if column < len(alignments) else "left"
    return "" if align == "left" else f' class="t-{align}"'


def _inline(text: str) -> str:
    """Inline rendering over text whose backslash escapes are already stashed."""
    out: list[str] = []
    cursor = 0
    for match in _INLINE_RE.finditer(text):
        out.append(html.escape(text[cursor : match.start()], quote=False))
        out.append(_inline_match(match))
        cursor = match.end()
    out.append(html.escape(text[cursor:], quote=False))
    return "".join(out)


def _inline_match(match: re.Match[str]) -> str:
    if (code := match["code"]) is not None:
        return f"<code>{html.escape(code.strip(), quote=False)}</code>"
    if (alt := match["alt"]) is not None:
        # NOTE: images are not embedded in v0 (no page images, no external
        # requests), so an image renders as its alt text, marked as such.
        return f'<span class="bd-image" title="image omitted">{_inline(alt)}</span>'
    if (label := match["label"]) is not None:
        href = match["href"] or ""
        if _SAFE_HREF_RE.match(href):
            return _inline(label)
        return f'<a href="{html.escape(href, quote=True)}">{_inline(label)}</a>'
    if (strong := match["strong"] or match["strong_us"]) is not None:
        return f"<strong>{_inline(strong)}</strong>"
    return f"<em>{_inline(match['em'] or match['em_us'])}</em>"
