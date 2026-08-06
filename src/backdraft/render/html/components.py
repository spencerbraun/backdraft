"""HTML components: cards, citations, evidence plates, notes, the sources index.

Each function emits one fragment of the artifact. The disclosure layering
(document → footnote → record) is structural here: `_card` is the footnote a
claim opens, `_record_block` is the deliberate step into the machine layer,
`_note` is the script-free baseline the Notes section keeps.
"""

from __future__ import annotations

import re

from ...kernel.model import SHEET_MEDIA_TYPES, Citation
from ..placement import Placement
from .fmt import _is_number, _style_attr, _width_px, fmt_cell
from .text import (
    _STATUS_SENTENCE,
    _drift_block,
    _esc,
    CELL_RE,
    PAGE_RE,
    humanize_sheet,
    humanize_verdict,
    location,
    md_html,
    origin,
    short_loc,
    source_title,
    table_heavy,
)


def _source_line(anchor, docs: dict) -> str:
    """A receipt's source: what it is, where in it, and — for a page fetched
    from the web — the URL it came from and the date it was taken.

    The card and the script-free note both open with this, so it lives here
    once: the two layers are the same receipt at different depths, and a
    provenance line that appeared in only one of them would be missing exactly
    where a reader without JavaScript is left.
    """
    url_html, when = origin(anchor.slug, docs)
    trailer = ""
    if url_html:
        asof = f'<span class="asof">fetched {when}</span>' if when else ""
        trailer = f'<span class="from">{url_html}{asof}</span>'
    return (
        f'<p class="src"><span class="doc">{_esc(source_title(anchor.slug, docs))}</span>'
        f'<span class="loc">{location(anchor, docs)}</span>{trailer}</p>'
    )


def _page_plate(anchor, page: dict, docs: dict, store: dict[str, dict]) -> str:
    match = PAGE_RE.match(str(anchor.locator))
    key = f"ev-{anchor.slug}-p{match['page']}"
    store[key] = page
    caption = f"{_esc(source_title(anchor.slug, docs))}, page {match['page']}"
    return (
        f'<figure class="plate"><img data-ev="{key}" alt="{caption}" '
        f'width="{int(page["width"])}" height="{int(page["height"])}">'
        f"<figcaption><span>{caption}</span>"
        f'<span class="hintcap">click to enlarge</span></figcaption></figure>'
    )


def _page_store_html(store: dict[str, dict]) -> str:
    images = "".join(
        f'<img id="{key}" '
        f'src="data:image/{page["format"]};base64,{page["data"]}" alt="">'
        for key, page in store.items()
    )
    return f'<div id="store" hidden aria-hidden="true">{images}</div>'


def _window_table(window: dict, slug: str) -> str:
    cited = window.get("cited")
    cited_col = re.match(r"[A-Z]+", cited).group() if cited else None
    cited_row = re.search(r"\d+", cited).group() if cited else None
    styling = window.get("styles") or {}
    cell_styles = styling.get("cells") or {}
    widths = styling.get("widths") or {}
    head_cells = []
    for c in window["cols"]:
        klass = ' class="citedcol"' if c == cited_col else ""
        width = f' style="min-width:{_width_px(widths[c])}px"' if c in widths else ""
        head_cells.append(f"<th{klass}{width}>{c}</th>")
    head = "".join(head_cells)
    rows = []
    for row in window["rows"]:
        cells = []
        for column in window["cols"]:
            raw = row["cells"].get(column, "")
            ref = f"{column}{row['n']}"
            style = cell_styles.get(ref)
            classes = []
            if ref == cited:
                classes.append("cited")
            if _is_number(raw):
                classes.append("num")
            klass = f' class="{" ".join(classes)}"' if classes else ""
            inline = _style_attr(style, cited=ref == cited)
            shown = fmt_cell(raw, style.get("fmt") if style else None)
            tip = f' title="{_esc(raw)}"' if raw != shown else ""
            cells.append(f"<td{klass}{inline}{tip}>{_esc(shown)}</td>")
        row_class = ' class="citedrow"' if str(row["n"]) == cited_row else ""
        rows.append(f'<tr{row_class}><th>{row["n"]}</th>{"".join(cells)}</tr>')
    caption = humanize_sheet(window["sheet"]) + (f", {cited}" if cited else "")
    sheet_key = f"{slug}:{window['sheet']}"
    return (
        f'<figure class="plate grid" data-sheet="{_esc(sheet_key)}" '
        f'data-cited="{_esc(cited or "")}" role="button" tabindex="0" '
        f'aria-label="Open full sheet"><div class="gridwrap"><table>'
        f"<thead><tr><th></th>{head}</tr></thead><tbody>{''.join(rows)}</tbody>"
        f"</table></div><figcaption><span>{_esc(caption)}</span>"
        f'<span class="hintcap">click to open the sheet</span></figcaption></figure>'
    )


def _tabs(source_pane: str, text_pane: str, source_label: str) -> str:
    return (
        '<div class="evidence"><div class="tabs" role="tablist">'
        f'<button class="tab on" data-pane="src">{source_label}</button>'
        '<button class="tab" data-pane="text">Extracted text</button></div>'
        f'<div class="pane on" data-pane="src">{source_pane}</div>'
        f'<div class="pane" data-pane="text">{text_pane}</div></div>'
    )


def _record_block(citation: Citation) -> str:
    rows = [
        f'<div class="rr"><span>token</span><code>{_esc(citation.token)}</code></div>'
    ]
    if citation.anchor is not None:
        rows.append(
            f'<div class="rr"><span>sha256</span>'
            f"<code>{_esc(citation.anchor.receipt.snippet_sha256)}</code></div>"
        )
    if citation.error:
        rows.append(
            f'<div class="rr"><span>error</span><code>{_esc(citation.error)}</code></div>'
        )
    for verdict in citation.verdicts:
        label, sentence = humanize_verdict(verdict)
        rows.append(
            f'<div class="rr verdict v-{verdict.status}"><span>{_esc(label)}</span>'
            f'<code class="vs">{_esc(str(verdict.status))}</code> {_esc(sentence)}</div>'
        )
    return f'<details class="record"><summary>Record</summary>{"".join(rows)}</details>'


def _status_sentence(citation: Citation) -> str:
    sentence = _STATUS_SENTENCE.get(citation.status)
    return f'<p class="alarm">{sentence}</p>' if sentence else ""


def _citation(
    citation: Citation, docs: dict, evidence: dict,
    store: dict[str, dict], *, index: int, on: bool,
) -> str:
    wrap = f'<div class="cite{" on" if on else ""}" data-cite="{index}">'
    if citation.anchor is None:
        return f"{wrap}{_status_sentence(citation)}{_record_block(citation)}</div>"
    anchor = citation.anchor
    locator = str(anchor.locator)
    parts = [
        wrap,
        _source_line(anchor, docs),
        _status_sentence(citation),
        _drift_block(citation),
    ]

    cell = CELL_RE.match(locator)
    page_m = PAGE_RE.match(locator)
    is_sheet_doc = docs.get(anchor.slug, {}).get("media_type") in SHEET_MEDIA_TYPES
    raw = f'<pre class="rawtext">{_esc(anchor.receipt.snippet[:4000])}</pre>'
    if cell:
        window = evidence.get("windows", {}).get(f"{anchor.slug}:{locator}")
        if window:
            parts.append(_tabs(_window_table(window, anchor.slug), raw, "Cells"))
        else:
            parts.append(raw)
    elif page_m and not is_sheet_doc:
        heavy = table_heavy(anchor.receipt.snippet)
        if not heavy:
            parts.append(
                f'<blockquote class="quote">{md_html(anchor.receipt.snippet)}</blockquote>'
            )
        page = evidence.get("pages", {}).get(f"{anchor.slug}:p{page_m['page']}")
        pagetext = evidence.get("pagetexts", {}).get(f"{anchor.slug}:p{page_m['page']}")
        text_pane = (
            f'<div class="pagetext">{md_html(pagetext)}</div>' if pagetext else raw
        )
        if page:
            parts.append(_tabs(_page_plate(anchor, page, docs, store), text_pane, "Page"))
        elif heavy:
            # No page image and a snippet the quote suppressed: the evidence
            # must still be visible — the page text, or the verbatim snippet.
            parts.append(text_pane)
    elif page_m:  # a whole-sheet citation
        window = evidence.get("windows", {}).get(f"{anchor.slug}:p{page_m['page']}")
        if window:
            parts.append(_tabs(_window_table(window, anchor.slug), raw, "Cells"))
        else:
            parts.append(raw)

    parts.append(_record_block(citation))
    parts.append("</div>")
    return "".join(parts)


_TYPE_LABEL = {
    "xlsx": "Excel",
    "xls": "Excel",
    "csv": "CSV",
    "pdf": "PDF",
    "docx": "Word",
    "pptx": "Slides",
    "image": "Image",
    "text": "Text",
}


def _card(placement: Placement, docs: dict, evidence: dict, store: dict[str, dict]) -> str:
    citations = placement.claim.citations
    selector = ""
    if len(citations) > 1:
        locs = [short_loc(c.anchor, docs) for c in citations]
        buttons = []
        for index, citation in enumerate(citations):
            label = _esc(locs[index])
            if locs.count(locs[index]) > 1 and citation.anchor is not None:
                media = docs.get(citation.anchor.slug, {}).get("media_type", "")
                label = f"{label} &middot; {_TYPE_LABEL.get(media, media)}"
            media = (
                docs.get(citation.anchor.slug, {}).get("media_type", "")
                if citation.anchor
                else ""
            )
            kind = {
                "xlsx": "excel", "xls": "excel", "csv": "excel",
                "pdf": "pdf", "image": "pdf", "docx": "pdf", "pptx": "pdf",
            }.get(media, "")
            buttons.append(
                f'<button class="{"on " if index == 0 else ""}{kind}" '
                f'data-cite="{index}">{label}</button>'
            )
        selector = (
            f'<p class="srccount">{len(citations)} sources</p>'
            f'<div class="srcsel">{"".join(buttons)}</div>'
        )
    if citations:
        inner = "".join(
            _citation(c, docs, evidence, store, index=i, on=(i == 0))
            for i, c in enumerate(citations)
        )
    else:
        inner = (
            '<div class="cite on"><p class="alarm">This claim carries no citation '
            "and no evidence.</p></div>"
        )
    return (
        f'<article class="card" id="card-{placement.number}" hidden>'
        f'<header><span class="cardno">Reference {placement.number}</span>'
        f'<button class="close" data-close aria-label="Close">&times;</button></header>'
        f"{selector}{inner}</article>"
    )


def _note(placement: Placement, docs: dict) -> str:
    parts = []
    if placement.claim.unmatched or not placement.claim.citations:
        parts.append(
            '<p class="alarm">This claim carries no citation and no evidence.</p>'
            f'<blockquote class="quote">{_esc(placement.claim.text[:200])}</blockquote>'
        )
    if not placement.placed:
        parts.append(
            '<p class="alarm">This claim is in the record but its words are not '
            "in the document as rendered.</p>"
            f'<blockquote class="quote">{_esc(placement.claim.text[:200])}</blockquote>'
        )
    for citation in placement.claim.citations:
        if citation.anchor is None:
            parts.append(_status_sentence(citation) + _record_block(citation))
            continue
        snippet = citation.anchor.receipt.snippet
        quote_html = ""
        if not table_heavy(snippet):
            short = snippet if len(snippet) <= 360 else snippet[:360].rsplit(" ", 1)[0] + " …"
            short = short.replace("**", "").replace("*", "")
            quote_html = f'<blockquote class="quote">{md_html(short)}</blockquote>'
        parts.append(
            f"{_source_line(citation.anchor, docs)}"
            f"{_status_sentence(citation)}{_drift_block(citation)}"
            f"{quote_html}{_record_block(citation)}"
        )
    return (
        f'<li class="note" id="note-{placement.number}">'
        f'<a class="backref" href="#claim-{placement.number}" '
        f'title="Back to the claim">{placement.number}</a>'
        f'<div>{"".join(parts)}</div></li>'
    )


def _sources_index(placements: list[Placement], docs: dict) -> str:
    counts: dict[str, int] = {}
    for placement in placements:
        for citation in placement.claim.citations:
            if citation.anchor is not None:
                counts[citation.anchor.slug] = counts.get(citation.anchor.slug, 0) + 1
    items = []
    for slug, count in sorted(counts.items(), key=lambda item: -item[1]):
        entry = docs.get(slug, {})
        url_html, when = origin(slug, docs)
        # A fetched page's filename is a staging artifact — `q4-2025.html` names
        # nothing on anyone's disk — so where there is an origin URL it stands
        # in the filename's place rather than beside it.
        meta = [url_html] if url_html else [_esc(entry.get("filename", slug))]
        if when:
            meta.append(f"fetched {when}")
        meta.append(f"{count} citation{'s' if count != 1 else ''}")
        items.append(
            f'<li><span class="doc">{_esc(source_title(slug, docs))}</span>'
            f'<span class="filemeta">{" &middot; ".join(meta)}</span></li>'
        )
    return "".join(items)
