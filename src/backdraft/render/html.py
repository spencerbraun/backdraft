"""The artifact: one HTML file that carries the document, its receipts, and
its evidence.

Designed for two readers in three disclosure layers (DESIGN.md, 2026-07-28):

* **The document.** Editorial typography on plain paper; claims wear a faint
  underline and a small numbered mark. **Success is silent** — a fully-resolved
  artifact says nothing about citations on its face; failures earn one plain
  sentence under the title and a wavy underline on their claims.
* **The footnote.** Click a claim: its reference card opens in the evidence
  rail — the source's words rendered as prose, then the source itself: the
  actual page image, or the cited cell highlighted in a spreadsheet window that
  opens into the full sheet. Multiple citations sit behind a per-source
  selector. No tokens, no hashes, no jargon at this layer.
* **The record.** A `Record` disclosure per citation: token, sha256, and each
  verifier's verdict in plain words. The machine-readable record is the JSON
  island; `$legend` teaches a cold reader to decode it.

The load-bearing constraint is **no network, single file** — enforced by a CSP
`meta` tag (`default-src 'none'`), not promised. Inline JS is progressive
enhancement over a CSS-and-anchor baseline: with scripts stripped, claims
degrade to footnote jumps into the Notes section and every receipt is still
readable.

Evidence comes from `report.evidence` (assembled at bind, carried in the
sidecar); a report without evidence renders quotes alone. The island embeds the
sidecar payload minus `evidence.pages[*].data` — the same bytes are already in
the page as image elements, and `LEGEND["evidence"]` licenses the omission.
"""

from __future__ import annotations

import difflib
import html as html_module
import json
import re
import urllib.parse
from typing import Any

from ..kernel.artifact import FORMAT, sidecar
from ..kernel.model import BindReport, Citation, CitationStatus, Claim, Verdict
from . import markdown
from .placement import Placement, locate

__all__ = ["render", "ISLAND_ID", "SHEETS_ISLAND_ID", "STYLESHEET", "FLAME_PATH"]

ISLAND_ID = "backdraft-artifact"
"""The id of the `<script type="application/json">` island holding the record."""

SHEETS_ISLAND_ID = "bd-sheets"
"""The id of the JSON island holding full cited-sheet values for the sheet view."""

FLAME_PATH = (
    "M44 3 C38 8 30 10 26 16 C23.5 20 24.5 24 27 26.5 "
    "C20.5 28 14.5 33 14 41 C13.3 51.5 22 59.5 33 59.5 "
    "C44 59.5 51.5 51.5 51 41.5 C50.6 33.5 45 29 42.5 22.5 "
    "C40.8 18 42.5 9 44 3 Z "
    "M34 34 C38 38.5 39.5 43.5 37.5 47.5 C35 52 28.5 51.5 26.5 47 "
    "C25 43.5 27.5 40 30 38.5 C31.8 37.5 33.2 36 34 34 Z"
)
"""The backdraft mark: a flame swept backward by returning air. The canonical
vector is `assets/backdraft-mark.svg`; this is its in-code copy for the favicon
and the sign-off."""

CELL_RE = re.compile(r"^(?P<sheet>[^!]+)!(?P<ref>[A-Z]{1,3}\d+)$")
PAGE_RE = re.compile(r"^p(?P<page>\d+)(?:\.c\d+)?$")
IMAGE_TAG_RE = re.compile(r"\[(?:IMAGE|CHART|MAP):[^\]]*\]\s*")
SUBTITLE_RE = re.compile(r"^\*([^*].*?)\*\s*$")

_STATUS_RANK = {
    CitationStatus.RESOLVED: 0,
    CitationStatus.NOT_SHOWN: 1,
    CitationStatus.DRIFTED: 2,
    CitationStatus.UNRESOLVED: 3,
    CitationStatus.MALFORMED: 4,
}

_STATUS_SENTENCE = {
    CitationStatus.UNRESOLVED: (
        "This citation names nothing in the sources; the claim is untraced."
    ),
    CitationStatus.NOT_SHOWN: "The source exists, but the writer was never shown it.",
    CitationStatus.DRIFTED: "The source has changed since this was written.",
    CitationStatus.MALFORMED: "The citation is malformed and could not be checked.",
}


def _esc(value: Any) -> str:
    return html_module.escape(str(value), quote=True)


# ---- small text helpers -----------------------------------------------------


def split_subtitle(source: str) -> tuple[str, str | None]:
    """An italic line directly under the `# title` is the document's subtitle.

    Returns (source without that line, subtitle text or None). The subtitle is
    a fill-in slot the author owns; the masthead shows it under the title.
    """
    lines = source.splitlines(keepends=True)
    seen_title = False
    for index, line in enumerate(lines):
        if not line.strip():
            continue
        if line.startswith("# ") and not seen_title:
            seen_title = True
            continue
        if seen_title and (match := SUBTITLE_RE.match(line.strip())):
            return "".join(lines[:index] + lines[index + 1:]), match.group(1)
        break
    return source, None


def fmt_number(raw: str) -> str:
    """Sheet values display formatted; the record keeps the verbatim value."""
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return raw
    if value == int(value) and abs(value) < 1e15:
        return f"{int(value):,}"
    if 0 < abs(value) < 1:
        return f"{value:.4f}"
    return f"{value:,.0f}"


def _is_number(raw: str) -> bool:
    try:
        float(raw)
        return True
    except (TypeError, ValueError):
        return False


def humanize_sheet(slug: str) -> str:
    fixed = {"dy": "DY", "t12": "T12", "ttm": "TTM", "noi": "NOI"}
    return " ".join(
        fixed.get(word, word.capitalize()) for word in slug.replace("-", " ").split()
    )


def source_title(slug: str, docs: dict) -> str:
    """A human name for a source: its filename's stem, humanized.

    A slug-shaped stem (`t12-summary`, `underwriting-model`) reads as a
    machine identifier where a reader expects a name, so it is title-cased
    through the same fixed-caps table sheet names use. A stem with its own
    casing is somebody's chosen name and passes through untouched.
    """
    entry = docs.get(slug)
    base = (
        str(entry.get("filename", slug)).rsplit(".", 1)[0].replace("_", " ")
        if entry
        else slug
    )
    if re.fullmatch(r"[a-z0-9][a-z0-9 \-]*", base):
        return humanize_sheet(base.replace(" ", "-"))
    return base


def md_html(text: str) -> str:
    """Snippet or page text rendered as markdown for human display."""
    return markdown.to_html(IMAGE_TAG_RE.sub("", text), [])


def table_heavy(text: str) -> bool:
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        return False
    return sum(1 for line in lines if line.lstrip().startswith("|")) > len(lines) * 0.4


def worst_status(claim: Claim) -> CitationStatus:
    statuses = [citation.status for citation in claim.citations]
    if not statuses:
        return CitationStatus.UNRESOLVED
    return max(statuses, key=_STATUS_RANK.__getitem__)


def location(anchor, docs: dict) -> str:
    locator = str(anchor.locator)
    if match := CELL_RE.match(locator):
        return f"{_esc(humanize_sheet(match['sheet']))} &middot; {match['ref']}"
    if match := PAGE_RE.match(locator):
        if docs.get(anchor.slug, {}).get("media_type") == "xlsx":
            return "sheet"
        return f"Page {match['page']}"
    return _esc(locator)


def short_loc(anchor, docs: dict) -> str:
    """Compact label for the source selector: `Page 6`, `D24`, `Sheet`."""
    if anchor is None:
        return "untraced"
    locator = str(anchor.locator)
    if match := CELL_RE.match(locator):
        return match["ref"]
    if match := PAGE_RE.match(locator):
        if docs.get(anchor.slug, {}).get("media_type") == "xlsx":
            return "Sheet"
        return f"Page {match['page']}"
    return locator


# ---- verdict language -------------------------------------------------------

_VALUES_FOUND_RE = re.compile(r"^(\d+) value\(s\) found in snippet$")
_NOT_FOUND_RE = re.compile(r"^not found in snippet: (.+)$")
_ROUNDED_RE = re.compile(r"^rounded match: (.+)$")
_TOKENS_RE = re.compile(r"^(\d+)/(\d+) claim tokens in snippet")
_QUOTED_MISSING_RE = re.compile(r"^quoted span not in snippet: (.+)$")
_QUOTED_CASE_RE = re.compile(r"^quoted span differs in case: (.+)$")
_QUOTED_OK_RE = re.compile(r"^(\d+) quoted span\(s\) verbatim in snippet$")

_METHOD_LABEL = {
    "value-trace": "Figures",
    "overlap": "Wording",
    "entail": "Reading",
    "recompute": "Math",
}


def humanize_verdict(verdict: Verdict) -> tuple[str, str]:
    """(label, sentence) for the record layer. Debug strings become prose."""
    label = _METHOD_LABEL.get(verdict.method, verdict.method)
    detail = verdict.detail or ""
    if verdict.method == "value-trace":
        if match := _VALUES_FOUND_RE.match(detail):
            count = int(match.group(1))
            sentence = (
                "The figure in this claim appears in this source."
                if count == 1
                else f"All {count} figures in this claim appear in this source."
            )
        elif match := _NOT_FOUND_RE.match(detail):
            sentence = f"Not found in this source: {match.group(1)}."
        elif match := _ROUNDED_RE.match(detail):
            sentence = f"Matched only after rounding: {match.group(1)}."
        else:
            sentence = detail
        return label, sentence
    if verdict.method == "overlap":
        if match := _TOKENS_RE.match(detail):
            found, total = int(match.group(1)), int(match.group(2))
            sentence = (
                "None of the claim's wording appears in this source."
                if found == 0
                else f"{found} of the claim's {total} words appear in this source."
            )
        elif match := _QUOTED_MISSING_RE.match(detail):
            sentence = f"Quoted phrase not found verbatim in this source: {match.group(1)}."
        elif match := _QUOTED_CASE_RE.match(detail):
            sentence = f"Quoted phrase differs from this source in casing: {match.group(1)}."
        elif match := _QUOTED_OK_RE.match(detail):
            sentence = "Every quoted phrase appears verbatim in this source."
        else:
            sentence = detail
        return label, sentence
    return label, detail or str(verdict.status)


# ---- drift ------------------------------------------------------------------

_WORD_RE = re.compile(r"\s+|\S+")


def _word_diff(before: str, after: str) -> tuple[str, str]:
    """Escaped HTML for both snippets, with `<del>`/`<ins>` on what moved."""
    old_words = _WORD_RE.findall(before)
    new_words = _WORD_RE.findall(after)
    matcher = difflib.SequenceMatcher(a=old_words, b=new_words, autojunk=False)
    old: list[str] = []
    new: list[str] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        old_text = html_module.escape("".join(old_words[i1:i2]))
        new_text = html_module.escape("".join(new_words[j1:j2]))
        if tag == "equal":
            old.append(old_text)
            new.append(new_text)
            continue
        if old_text:
            old.append(f"<del>{old_text}</del>")
        if new_text:
            new.append(f"<ins>{new_text}</ins>")
    return "".join(old), "".join(new)


def _drift_block(citation: Citation) -> str:
    if citation.drifted_from is None:
        return ""
    now = citation.anchor.receipt.snippet if citation.anchor else ""
    old_html, new_html = _word_diff(citation.drifted_from, now)
    return (
        '<div class="drift">'
        f'<div class="drift-row"><span>as cited</span><p>{old_html}</p></div>'
        f'<div class="drift-row"><span>now</span><p>{new_html}</p></div>'
        "</div>"
    )


# ---- the renderer -----------------------------------------------------------


def render(source: str, report: BindReport, *, title: str | None = None) -> str:
    """Render the artifact: `source` as a document, `report` as its evidence.

    `title` overrides the page title, which otherwise comes from the document's
    first heading and falls back to the bound document's filename.
    """
    evidence = report.evidence or {}
    docs: dict = evidence.get("documents", {})
    source, subtitle = split_subtitle(source)

    placements = locate(source, report.claims)
    placed = [p for p in placements if p.placed]
    orphans = [p for p in placements if not p.placed]

    page_store: dict[str, dict] = {}

    spans = []
    for placement in placed:
        flag = "" if worst_status(placement.claim) is CitationStatus.RESOLVED else " flagged"
        text = markdown.inline(placement.claim.text)
        spans.append(markdown.Span(
            start=placement.start, end=placement.end,
            html=(
                f'<a class="claim{flag}" id="claim-{placement.number}" '
                f'href="#note-{placement.number}" data-claim="{placement.number}">'
                f'{text}<sup class="mark">{placement.number}</sup></a>'
            ),
        ))
    body = markdown.to_html(source, spans)

    cards = "\n".join(_card(p, docs, evidence, page_store) for p in placements)
    notes = "\n".join(_note(p, docs) for p in placements)

    failures = [
        (p, c)
        for p in placements
        for c in p.claim.citations
        if c.status is not CitationStatus.RESOLVED
    ]
    unmatched = [p for p in placements if p.claim.unmatched or not p.claim.citations]
    n_cites = sum(len(p.claim.citations) for p in placements)

    heading = title or _title(source, report)
    subtitle_html = f'<p class="subtitle">{_esc(subtitle)}</p>' if subtitle else ""
    alarm_bits: list[str] = []
    if failures:
        alarm_bits.append(
            f"{len(failures)} of {n_cites} citations could not be traced to a source"
        )
    if unmatched:
        alarm_bits.append(f"{len(unmatched)} claims carry no citation")
    if orphans:
        alarm_bits.append(f"{len(orphans)} recorded claims are not in this document")
    alarm_html = (
        f'<p class="alarmline">{_esc("; ".join(alarm_bits))} &mdash; see the notes.</p>'
        if alarm_bits
        else ""
    )

    return PAGE.format(
        title=_esc(heading),
        favicon=_favicon(),
        css=STYLESHEET,
        js=SCRIPT,
        subtitle=subtitle_html,
        alarm=alarm_html,
        body=body,
        cards=cards,
        notes=notes,
        sources=_sources_index(placements, docs),
        store=_page_store_html(page_store),
        mark_svg=(
            f'<svg class="bd-mark" width="14" height="14" viewBox="0 0 64 64">'
            f'<path fill="#676767" fill-rule="evenodd" d="{FLAME_PATH}"/></svg>'
        ),
        sheets_island_id=SHEETS_ISLAND_ID,
        sheets=_escape_island(json.dumps(evidence.get("sheets", {}), ensure_ascii=False)),
        island_id=ISLAND_ID,
        island=_island(report),
        format=FORMAT,
    )


def _title(source: str, report: BindReport) -> str:
    for line in source.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
        if line.strip():
            break
    return report.doc_path.rsplit("/", 1)[-1]


def _favicon() -> str:
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
        '<rect width="64" height="64" rx="13" fill="#FBFAF6"/>'
        '<g transform="translate(32 32) scale(0.82) translate(-32 -32)">'
        f'<path fill="#282828" fill-rule="evenodd" d="{FLAME_PATH}"/></g></svg>'
    )
    return "data:image/svg+xml," + urllib.parse.quote(svg)


def _escape_island(payload: str) -> str:
    """JSON escaped so no byte sequence can close the script element."""
    return payload.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def _island(report: BindReport) -> str:
    """The record island: the sidecar payload, minus embedded image bytes.

    `render --to json` carries the full evidence; the island omits
    `evidence.pages[*].data` because the identical bytes are in the document as
    image elements, and `$legend` documents the omission.
    """
    payload = sidecar(report)
    evidence = payload.get("evidence")
    if isinstance(evidence, dict) and isinstance(evidence.get("pages"), dict):
        evidence = dict(evidence)
        evidence["pages"] = {
            key: {k: v for k, v in entry.items() if k != "data"}
            for key, entry in evidence["pages"].items()
        }
        payload = {**payload, "evidence": evidence}
    return _escape_island(json.dumps(payload, indent=2, ensure_ascii=False))


# ---- evidence ---------------------------------------------------------------


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
    head = "".join(
        f'<th class="citedcol">{c}</th>' if c == cited_col else f"<th>{c}</th>"
        for c in window["cols"]
    )
    rows = []
    for row in window["rows"]:
        cells = []
        for column in window["cols"]:
            raw = row["cells"].get(column, "")
            ref = f"{column}{row['n']}"
            classes = []
            if ref == cited:
                classes.append("cited")
            if _is_number(raw):
                classes.append("num")
            klass = f' class="{" ".join(classes)}"' if classes else ""
            shown = fmt_number(raw)
            tip = f' title="{_esc(raw)}"' if raw != shown else ""
            cells.append(f"<td{klass}{tip}>{_esc(shown)}</td>")
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
        f'<p class="src"><span class="doc">{_esc(source_title(anchor.slug, docs))}</span>'
        f'<span class="loc">{location(anchor, docs)}</span></p>',
        _status_sentence(citation),
        _drift_block(citation),
    ]

    cell = CELL_RE.match(locator)
    page_m = PAGE_RE.match(locator)
    is_sheet_doc = docs.get(anchor.slug, {}).get("media_type") == "xlsx"
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


_TYPE_LABEL = {"xlsx": "Excel", "pdf": "PDF", "text": "Text"}


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
            kind = {"xlsx": "excel", "pdf": "pdf"}.get(media, "")
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
            f'<p class="src"><span class="doc">{_esc(source_title(citation.anchor.slug, docs))}</span>'
            f'<span class="loc">{location(citation.anchor, docs)}</span></p>'
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
        meta = _esc(entry.get("filename", slug))
        items.append(
            f'<li><span class="doc">{_esc(source_title(slug, docs))}</span>'
            f'<span class="filemeta">{meta} &middot; '
            f"{count} citation{'s' if count != 1 else ''}</span></li>"
        )
    return "".join(items)


# ---- the page ---------------------------------------------------------------

STYLESHEET = """
*,*::before,*::after{box-sizing:border-box}
:root{
  color-scheme:light;
  --paper:#FFFFFF; --ink:#282828; --muted:#676767; --faint:#A3A19A;
  --hover:rgba(40,40,40,.05); --active:rgba(40,40,40,.09);
  --underline:rgba(40,40,40,.16);
  --hairline:#E8E5DD; --hairline-strong:#D6D2C6;
  --notebook:#FBFAF6; --notebook-line:rgba(40,40,40,.05);
  --sel:#1F7244; --sel-soft:#EAF3EE;
  --excel-line:#E3E2DC; --excel-head:#F4F3EE;
  --hl:#F5E6AE;
  --alarm:#A63A2E;
  --serif:'Iowan Old Style','Iowan Old Style BT',Palatino,'Palatino Linotype',Georgia,serif;
  --sans:ui-sans-serif,system-ui,-apple-system,'Segoe UI',Helvetica,sans-serif;
  --mono:ui-monospace,'SF Mono',Menlo,Consolas,monospace;
  --rail-w:calc(50vw - 14px);
}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--notebook);color:var(--ink);
  font-family:var(--serif);font-size:17px;line-height:1.6;
  font-synthesis:none;text-rendering:optimizeLegibility}
.frame{display:grid;grid-template-columns:minmax(0,1fr) 28px var(--rail-w)}
.pagecol{grid-column:1;min-width:0;max-width:44rem;width:100%;
  padding:4rem 2.75rem 6rem;margin:0 auto}
.divider{grid-column:2;cursor:col-resize;touch-action:none}
.divider::before{content:'';display:block;position:sticky;top:12.5vh;height:75vh;
  width:1px;margin:0 auto;background:var(--hairline-strong);transition:background .15s}
.divider:hover::before,.divider.dragging::before{background:var(--ink);width:2px}
.railcol{grid-column:3;min-width:0;
  background:
    repeating-linear-gradient(0deg,var(--notebook-line) 0 1px,transparent 1px 18px),
    repeating-linear-gradient(90deg,var(--notebook-line) 0 1px,transparent 1px 18px),
    var(--notebook)}
.rail{position:sticky;top:0;max-height:100vh;overflow-y:auto;
  font-family:var(--sans);font-size:.84rem;line-height:1.55;
  padding:2.5rem 2.25rem}
a{color:inherit}

/* ---- masthead ---- */
.masthead{margin:0 0 3rem;text-align:center}
.masthead h1{font-size:1.85rem;line-height:1.35;margin:0 0 .55rem;font-weight:600}
.subtitle{font-family:var(--serif);font-size:.95rem;color:var(--muted);margin:0}
.alarmline{font-family:var(--sans);font-size:.78rem;color:var(--alarm);
  margin:.6rem 0 0}

/* ---- the document ---- */
.doc h1{display:none}
.doc h2{font-family:var(--serif);font-size:1.2rem;font-weight:600;
  margin:2.3rem 0 .7rem}
.doc p{margin:0 0 1.05rem}
.doc ul,.doc ol{margin:0 0 1.05rem;padding-left:1.4rem}
.doc blockquote{margin:1.1rem 0;padding:.1rem 0 .1rem 1rem;
  border-left:2px solid var(--hairline);color:var(--muted)}
.doc pre{font-family:var(--mono);font-size:.78rem;line-height:1.5;overflow-x:auto;
  background:var(--paper);border:1px solid var(--hairline);border-radius:3px;
  padding:.8rem .95rem;margin:0 0 1.05rem}
.doc code{font-family:var(--mono);font-size:.85em}
.table-wrap{overflow-x:auto;margin:0 0 1.1rem}
.doc table{border-collapse:collapse;font-family:var(--sans);font-size:.84rem}
.doc th,.doc td{padding:.35rem .65rem;border-bottom:1px solid var(--hairline);
  text-align:left}
.doc .t-right{text-align:right}
.doc .t-center{text-align:center}
.bd-image{color:var(--muted);font-style:italic}
.claim{color:inherit;cursor:pointer;
  text-decoration:underline;text-decoration-color:var(--underline);
  text-decoration-thickness:1px;text-underline-offset:3px;
  transition:background-color .15s,text-decoration-color .15s}
.claim:hover{background:var(--hover);text-decoration-color:var(--ink)}
.claim.active{background:var(--active);text-decoration-color:var(--ink)}
.claim.flagged{text-decoration-style:wavy;text-decoration-color:var(--alarm)}
.mark{font-family:var(--sans);font-size:.58em;font-weight:600;color:var(--muted);
  margin-left:.14em}
.claim:hover .mark,.claim.active .mark{color:var(--ink)}
.claim.flagged .mark{color:var(--alarm)}

/* ---- rail resting ---- */
.resting{background:var(--paper);border:1px solid var(--hairline);border-radius:3px;
  padding:1.2rem 1.35rem;box-shadow:0 1px 3px rgba(40,40,40,.05)}
.resting h2{font-size:.66rem;letter-spacing:.14em;text-transform:uppercase;
  margin:0 0 .9rem;color:var(--faint);font-weight:600}
.resting ul{list-style:none;margin:0;padding:0}
.resting li{margin:.75rem 0}
.resting .doc{display:block;color:var(--ink);font-weight:600;font-size:.84rem}
.resting .filemeta{display:block;font-size:.72rem;color:var(--muted);
  overflow-wrap:anywhere;margin-top:.15rem}
.resting .hint{margin:1.2rem 0 0;font-size:.74rem;color:var(--muted);line-height:1.5}

/* ---- the card ---- */
.card{background:var(--paper);border:1px solid var(--hairline);border-radius:3px;
  box-shadow:0 1px 3px rgba(40,40,40,.05),0 8px 24px rgba(40,40,40,.06);
  padding:1.05rem 1.35rem 1.15rem;animation:rise .16s ease;
  resize:vertical;overflow:auto;min-height:12rem;max-height:82vh}
@keyframes rise{from{opacity:0;transform:translateY(.35rem)}to{opacity:1;transform:none}}
.card header{display:flex;align-items:baseline;justify-content:space-between;
  padding:0 0 .2rem}
.cardno{font-family:var(--sans);font-size:.74rem;font-weight:600;color:var(--ink);
  letter-spacing:.02em}
.close{background:none;border:0;font-size:1.05rem;line-height:1;color:var(--faint);
  cursor:pointer;padding:.1rem .3rem}
.close:hover{color:var(--ink)}

/* source selector */
.srccount{font-family:var(--sans);font-size:.68rem;color:var(--faint);
  margin:.1rem 0 0}
.srcsel{display:flex;gap:1.3rem;border-bottom:1px solid var(--hairline);
  margin:.3rem 0 .95rem}
.srcsel button{font-family:var(--sans);font-size:.76rem;font-weight:500;
  color:var(--muted);background:none;border:0;padding:.45rem 0;cursor:pointer;
  border-bottom:2px solid transparent;margin-bottom:-1px;letter-spacing:.01em}
.srcsel button:hover{color:var(--ink)}
.srcsel button.on{color:var(--ink);font-weight:600;border-bottom-color:var(--ink)}
.srcsel button.on.excel{border-bottom-color:var(--sel)}
.srcsel button.on.pdf{border-bottom-color:#9E3B2F}

.cite{display:none;padding:.15rem 0}
.cite.on{display:block}
.src{margin:.2rem 0 .6rem;display:flex;align-items:baseline;gap:.6rem;flex-wrap:wrap}
.src .doc{font-weight:600;color:var(--ink);font-size:.88rem}
.src .loc{font-size:.72rem;color:var(--faint)}
.alarm{color:var(--alarm);font-size:.78rem;margin:.35rem 0}

.quote{margin:.35rem 0 .75rem;padding:.05rem 0 .05rem .9rem;
  border-left:2px solid var(--hairline-strong);font-family:var(--serif);
  font-size:.9rem;line-height:1.55;color:var(--ink);
  max-height:15rem;overflow-y:auto}
.quote p{margin:0 0 .5rem}.quote p:last-child{margin:0}
.quote h1,.quote h2,.quote h3,.quote h4{font-family:var(--sans);font-size:.64rem;
  letter-spacing:.1em;text-transform:uppercase;color:var(--faint);
  margin:.6rem 0 .3rem;font-weight:600}
.quote ul,.quote ol{margin:.2rem 0 .5rem;padding-left:1.2rem}
.quote strong{font-weight:600}
.quote .bd-image{display:none}

/* drift: the two snippets, word-diffed */
.drift{margin:.5rem 0 .7rem;font-size:.84rem}
.drift-row{display:flex;gap:.6rem;margin:.3rem 0}
.drift-row span{flex:0 0 3.6rem;font-family:var(--sans);font-size:.6rem;
  color:var(--faint);text-transform:uppercase;letter-spacing:.08em;padding-top:.2rem}
.drift-row p{margin:0;font-family:var(--serif);overflow-wrap:anywhere}
.drift del{text-decoration:line-through;text-decoration-thickness:1px;
  color:var(--alarm);background:rgba(166,58,46,.08)}
.drift ins{text-decoration:none;color:var(--sel);background:var(--sel-soft)}

/* view toggle */
.evidence{margin:.4rem 0 .3rem}
.tabs{display:flex;gap:.9rem;margin-bottom:.55rem}
.tab{font-family:var(--sans);font-size:.68rem;font-weight:500;color:var(--faint);
  background:none;border:0;padding:.15rem 0;cursor:pointer;
  border-bottom:1px solid transparent}
.tab:hover{color:var(--ink)}
.tab.on{color:var(--ink);border-bottom-color:var(--ink)}
.pane{display:none}
.pane.on{display:block}
.pagetext,.rawtext{border:1px solid var(--hairline);
  border-radius:2px;padding:.7rem .85rem;background:var(--paper)}
.pagetext{font-family:var(--serif);font-size:.86rem;line-height:1.55}
.pagetext h1,.pagetext h2,.pagetext h3{font-family:var(--sans);font-size:.64rem;
  letter-spacing:.1em;text-transform:uppercase;color:var(--faint);
  margin:.7rem 0 .35rem;font-weight:600}
.pagetext h1:first-child,.pagetext h2:first-child{margin-top:0}
.pagetext p{margin:0 0 .5rem}
.pagetext ul{margin:.2rem 0 .5rem;padding-left:1.2rem}
.pagetext .table-wrap{overflow-x:auto;margin:.4rem 0}
.pagetext table{border-collapse:collapse;font-family:var(--sans);font-size:.7rem;
  white-space:nowrap}
.pagetext th,.pagetext td{border:1px solid var(--hairline);padding:.2rem .5rem;
  text-align:left}
.pagetext th{background:var(--excel-head);font-weight:600}
.rawtext{font-family:var(--mono);font-size:.68rem;line-height:1.5;white-space:pre-wrap;
  overflow-wrap:anywhere;color:var(--ink);margin:.4rem 0}

/* evidence plates */
.plate{margin:.1rem 0 .3rem;cursor:zoom-in}
.plate img{display:block;width:100%;height:auto;border:1px solid var(--hairline);
  border-radius:2px;background:#fff}
.plate:hover img{border-color:var(--hairline-strong)}
.plate figcaption{font-family:var(--sans);font-size:.68rem;color:var(--muted);
  margin-top:.4rem;display:flex;justify-content:space-between;gap:.6rem}
.hintcap{color:var(--ink);opacity:0;transition:opacity .15s;white-space:nowrap}
.plate:hover .hintcap{opacity:.7}

/* the excel experience */
.grid{cursor:pointer}
.grid .gridwrap{overflow-x:auto;border:1px solid var(--excel-line);border-radius:2px;
  background:var(--paper)}
.grid table,.sheettable{border-collapse:separate;border-spacing:0;
  font-family:var(--sans);font-size:.72rem;line-height:1.6;min-width:100%;
  font-variant-numeric:tabular-nums}
.grid th,.sheettable th{font-weight:500;color:#6B6B66;background:var(--excel-head);
  padding:.1rem .55rem;text-align:center;
  border-bottom:1px solid var(--excel-line);border-right:1px solid var(--excel-line);
  font-size:.66rem}
.grid td,.sheettable td{padding:.1rem .55rem;
  border-bottom:1px solid var(--excel-line);border-right:1px solid var(--excel-line);
  white-space:nowrap;max-width:14rem;overflow:hidden;text-overflow:ellipsis;
  background:var(--paper);text-align:left}
.grid td.num,.sheettable td.num{text-align:right}
.grid td.cited,.sheettable td.cited{background:var(--sel-soft);
  box-shadow:inset 0 0 0 2px var(--sel);font-weight:600}
.grid tbody th{position:sticky;left:0}
tr.citedrow th{background:var(--sel-soft);color:var(--sel);font-weight:600}
th.citedcol{background:var(--sel-soft);color:var(--sel);font-weight:600}

/* the record layer */
.record{margin:.5rem 0 .1rem;font-size:.7rem}
.record summary{cursor:pointer;color:var(--faint);letter-spacing:.1em;
  text-transform:uppercase;font-size:.6rem;font-weight:600;list-style:none}
.record summary::before{content:'\\25B8';margin-right:.35rem;font-size:.55rem}
.record[open] summary::before{content:'\\25BE'}
.record[open] summary{margin-bottom:.35rem}
.rr{display:flex;gap:.55rem;margin:.22rem 0;color:var(--muted);overflow-wrap:anywhere}
.rr span{flex:0 0 4.4rem;text-transform:uppercase;letter-spacing:.08em;font-size:.58rem;
  padding-top:.1rem}
.rr code{font-family:var(--mono);font-size:.66rem;color:var(--ink)}
.rr.verdict code{text-transform:uppercase;letter-spacing:.05em}
.v-fail code{color:var(--alarm)} .v-partial code{color:#96690F}
.v-skip code{color:var(--faint)}

/* ---- end matter ---- */
.endmatter{margin-top:4rem;border-top:1px solid var(--hairline);padding-top:1.6rem;
  font-family:var(--sans)}
.endmatter h2{font-size:.66rem;letter-spacing:.14em;text-transform:uppercase;
  color:var(--faint);font-weight:600;margin:0 0 1rem}
.srclist{list-style:none;margin:0 0 2.2rem;padding:0;font-size:.8rem}
.srclist li{margin:.55rem 0}
.srclist .doc{font-weight:600}
.srclist .filemeta{display:block;color:var(--muted);font-size:.7rem}
.notes{list-style:none;margin:0;padding:0;font-size:.78rem}
.note{display:flex;gap:1rem;padding:.9rem 0;border-top:1px solid var(--hairline);
  cursor:pointer}
.note:hover{background:var(--hover)}
.note:target{background:var(--hover)}
.note > div{flex:1;min-width:0}
.backref{flex:0 0 1.4rem;font-family:var(--mono);font-size:.72rem;
  color:var(--faint);text-decoration:none;text-align:right;padding-top:.15rem}
.backref:hover{color:var(--ink)}
.note .quote{font-size:.84rem}
.colophon{margin-top:2.8rem;color:var(--muted);font-size:.72rem;
  line-height:1.55;display:flex;align-items:center;gap:.45rem}
.bd-mark{flex:0 0 auto}

/* ---- overlays ---- */
.overlay{position:fixed;inset:0;background:rgba(24,23,20,.85);z-index:90;
  display:none;align-items:center;justify-content:center;padding:1.5rem}
.overlay.open{display:flex}
.overlay > img{max-width:100%;max-height:100%;border-radius:2px;cursor:zoom-out;
  background:#fff}
.sheetbox{background:var(--paper);border-radius:4px;
  width:min(78rem,100%);height:auto;max-height:min(48rem,100%);
  display:flex;flex-direction:column;overflow:hidden}
.sheetbox header{display:flex;align-items:center;justify-content:space-between;
  font-family:var(--sans);font-size:.78rem;font-weight:600;
  padding:.7rem 1rem;border-bottom:1px solid var(--hairline)}
.sheetbox header .close{font-size:1.2rem}
.sheetscroll{overflow:auto;flex:1;background:var(--paper)}
.sheettable thead th{position:sticky;top:0;z-index:2}
.sheettable tbody th{position:sticky;left:0;z-index:1;min-width:2.6rem}
.sheettable thead th:first-child{left:0;z-index:3}
.sheettable td{max-width:18rem}

/* ---- responsive / print ---- */
@media (max-width:1140px){
  .frame{display:block}
  .divider{display:none}
  .pagecol{max-width:44rem;margin:0 auto;padding:2.5rem 1.25rem 4rem}
  .railcol{background:none}
  .rail{position:static;max-height:none;padding:0}
  .resting{display:none}
  .card{position:fixed;left:50%;transform:translateX(-50%);bottom:1rem;z-index:80;
    width:min(30rem,calc(100vw - 2rem));max-height:72vh;overflow-y:auto;resize:none}
  @keyframes rise{from{opacity:0;transform:translate(-50%,.5rem)}
    to{opacity:1;transform:translate(-50%,0)}}
  .overlay{padding:.6rem}
}
@media (prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}
@media print{
  .railcol,.divider,.overlay{display:none}
  .frame{display:block}
  .pagecol{max-width:none;padding:0}
  .note{break-inside:avoid}
  .claim{text-decoration:none}
}
:focus-visible{outline:2px solid var(--ink);outline-offset:2px}
"""

SCRIPT = """
(function () {
  var rail = document.querySelector('.rail');
  var resting = document.querySelector('.resting');
  var sheetsEl = document.getElementById('bd-sheets');
  var sheets = sheetsEl ? JSON.parse(sheetsEl.textContent || '{}') : {};
  var active = null, activeCard = null;

  function fmt(raw) {
    if (raw === '' || raw == null) return '';
    var v = Number(raw);
    if (isNaN(v)) return raw;
    if (v === Math.trunc(v) && Math.abs(v) < 1e15) return v.toLocaleString('en-US');
    if (Math.abs(v) < 1) return v.toFixed(4);
    return Math.round(v).toLocaleString('en-US');
  }
  function colName(n) {
    var s = '';
    while (n > 0) { var r = (n - 1) % 26; s = String.fromCharCode(65 + r) + s; n = (n - 1 - r) / 26; }
    return s;
  }

  function deactivate() {
    if (activeCard) activeCard.hidden = true;
    if (active) active.classList.remove('active');
    if (resting) resting.style.display = '';
    active = activeCard = null;
  }
  function activate(n, claim) {
    var card = document.getElementById('card-' + n);
    if (!card) return;
    deactivate();
    if (resting) resting.style.display = 'none';
    card.querySelectorAll('img[data-ev]').forEach(function (img) {
      if (!img.src) {
        var stored = document.getElementById(img.dataset.ev);
        if (stored) img.src = stored.src;
      }
    });
    card.hidden = false;
    if (claim) {
      claim.classList.add('active');
      active = claim;
    }
    activeCard = card;
    if (window.matchMedia('(min-width: 1141px)').matches) {
      rail.scrollTop = 0;
      if (claim) {
        var r = claim.getBoundingClientRect();
        if (r.top < 0 || r.bottom > innerHeight) claim.scrollIntoView({block: 'center'});
      }
    }
  }

  function openSheet(key, cited) {
    var data = sheets[key];
    if (!data) return;
    var box = document.getElementById('sheetoverlay');
    var scroll = box.querySelector('.sheetscroll');
    box.querySelector('.sheetname').textContent =
      data.name.replace(/-/g, ' ').replace(/\\b\\w/g, function (ch) { return ch.toUpperCase(); });
    var citedCol = cited ? cited.replace(/\\d+$/, '') : null;
    var citedRow = cited ? cited.replace(/^[A-Z]+/, '') : null;
    var h = '<table class="sheettable"><thead><tr><th></th>';
    for (var c = 1; c <= data.ncols; c++) {
      var cn = colName(c);
      h += '<th' + (cn === citedCol ? ' class="citedcol"' : '') + '>' + cn + '</th>';
    }
    h += '</tr></thead><tbody>';
    for (var r = 1; r <= data.nrows; r++) {
      h += '<tr' + (String(r) === citedRow ? ' class="citedrow"' : '') + '><th>' + r + '</th>';
      for (var c2 = 1; c2 <= data.ncols; c2++) {
        var raw = data.rows[r - 1][c2 - 1];
        var ref = colName(c2) + r;
        var cls = [];
        if (ref === cited) cls.push('cited');
        if (raw !== '' && raw != null && isFinite(Number(raw))) cls.push('num');
        h += '<td' + (cls.length ? ' class="' + cls.join(' ') + '"' : '') +
             ' title="' + String(raw).replace(/"/g, '&quot;') + '">' + fmt(raw) + '</td>';
      }
      h += '</tr>';
    }
    h += '</tbody></table>';
    scroll.innerHTML = h;
    box.classList.add('open');
    var hlCell = scroll.querySelector('td.cited');
    if (hlCell) {
      scroll.scrollTop = hlCell.offsetTop - scroll.clientHeight / 2;
      scroll.scrollLeft = hlCell.offsetLeft - scroll.clientWidth / 2;
    }
  }

  document.addEventListener('click', function (e) {
    var claim = e.target.closest('a.claim');
    if (claim) {
      e.preventDefault();
      if (active === claim) deactivate();
      else activate(claim.dataset.claim, claim);
      return;
    }
    if (e.target.closest('[data-close]')) {
      var over = e.target.closest('.overlay');
      if (over) { over.classList.remove('open'); return; }
      deactivate(); return;
    }
    var sel = e.target.closest('.srcsel button');
    if (sel) {
      var box = sel.closest('.card');
      box.querySelectorAll('.srcsel button').forEach(function (b) { b.classList.remove('on'); });
      box.querySelectorAll('.cite').forEach(function (ct) { ct.classList.remove('on'); });
      sel.classList.add('on');
      box.querySelector('.cite[data-cite="' + sel.dataset.cite + '"]').classList.add('on');
      return;
    }
    var tab = e.target.closest('.tab');
    if (tab) {
      var evd = tab.closest('.evidence');
      evd.querySelectorAll('.tab').forEach(function (t) { t.classList.remove('on'); });
      evd.querySelectorAll('.pane').forEach(function (p) { p.classList.remove('on'); });
      tab.classList.add('on');
      evd.querySelector('.pane[data-pane="' + tab.dataset.pane + '"]').classList.add('on');
      return;
    }
    var noteRow = e.target.closest('.note');
    if (noteRow && !e.target.closest('a') && !e.target.closest('summary')) {
      var noteN = noteRow.id.replace('note-', '');
      var noteClaim = document.getElementById('claim-' + noteN);
      if (noteClaim) {
        noteClaim.scrollIntoView({block: 'center'});
        activate(noteN, noteClaim);
      }
      return;
    }
    var grid = e.target.closest('.grid[data-sheet]');
    if (grid) { openSheet(grid.dataset.sheet, grid.dataset.cited); return; }
    var img = e.target.closest('.plate img');
    if (img && img.src) {
      var zoom = document.getElementById('zoom');
      zoom.querySelector('img').src = img.src;
      zoom.classList.add('open');
      return;
    }
    var overlay = e.target.closest('.overlay');
    if (overlay && (e.target === overlay || overlay.id === 'zoom')) {
      overlay.classList.remove('open');
    }
  });
  document.addEventListener('keydown', function (e) {
    if (e.key !== 'Escape') return;
    var open = document.querySelector('.overlay.open');
    if (open) open.classList.remove('open');
    else deactivate();
  });

  /* draggable divider */
  var divider = document.querySelector('.divider');
  if (divider) {
    var startX = 0, startW = 0;
    divider.addEventListener('pointerdown', function (e) {
      startX = e.clientX;
      startW = document.querySelector('.railcol').getBoundingClientRect().width;
      divider.classList.add('dragging');
      divider.setPointerCapture(e.pointerId);
    });
    divider.addEventListener('pointermove', function (e) {
      if (!divider.classList.contains('dragging')) return;
      var w = Math.min(Math.max(startW - (e.clientX - startX), 320), innerWidth - 420);
      document.documentElement.style.setProperty('--rail-w', w + 'px');
    });
    ['pointerup', 'pointercancel'].forEach(function (ev) {
      divider.addEventListener(ev, function () { divider.classList.remove('dragging'); });
    });
  }
})();
"""

PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy"
      content="default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; img-src data:;">
<meta name="generator" content="{format}">
<link rel="icon" href="{favicon}">
<title>{title}</title>
<style>{css}</style>
</head>
<body>
<div class="frame">
<div class="pagecol">
<header class="masthead">
<h1>{title}</h1>
{subtitle}{alarm}
</header>
<main class="doc">
{body}
</main>
<section class="endmatter">
<h2>Sources</h2>
<ul class="srclist">{sources}</ul>
<h2>Notes</h2>
<ol class="notes">
{notes}
</ol>
<p class="colophon">{mark_svg} Generated by Backdraft</p>
</section>
</div>
<div class="divider" role="separator" aria-orientation="vertical"
     aria-label="Resize the evidence rail" title="Drag to resize"></div>
<aside class="railcol">
<div class="rail">
<div class="resting">
<h2>Sources</h2>
<ul>{sources}</ul>
<p class="hint">Click any numbered claim to see the source behind it.</p>
</div>
{cards}
</div>
</aside>
</div>
<div class="overlay" id="zoom" role="dialog" aria-label="Enlarged page"><img alt=""></div>
<div class="overlay" id="sheetoverlay" role="dialog" aria-label="Full sheet">
<div class="sheetbox"><header><span class="sheetname"></span>
<button class="close" data-close aria-label="Close">&times;</button></header>
<div class="sheetscroll"></div></div></div>
{store}
<script type="application/json" id="{sheets_island_id}">
{sheets}
</script>
<script type="application/json" id="{island_id}">
{island}
</script>
<script>{js}</script>
</body>
</html>
"""
