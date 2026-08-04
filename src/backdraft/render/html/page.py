"""The page: `render` assembles the artifact from the package's parts.

This module owns the top of the document — the masthead and its alarm line,
claim placement and marking, the two JSON islands, and the PAGE template that
seats everything. The islands stay readable in view-source by design: the
record is the artifact's machine layer, and a reader who opens the file in an
editor should find it as legible as the prose.
"""

from __future__ import annotations

import json

from ...kernel.artifact import FORMAT, sidecar
from ...kernel.model import BindReport, CitationStatus
from .. import markdown
from ..placement import locate
from ..theme import Theme
from .assets import FLAME_PATH, SCRIPT_MIN, STYLESHEET_MIN, _favicon
from .components import _card, _note, _page_store_html, _sources_index
from .text import _esc, split_subtitle, worst_status

ISLAND_ID = "backdraft-artifact"
"""The id of the `<script type="application/json">` island holding the record."""

SHEETS_ISLAND_ID = "bd-sheets"
"""The id of the JSON island holding full cited-sheet values for the sheet view."""


def render(
    source: str,
    report: BindReport,
    *,
    title: str | None = None,
    theme: Theme | None = None,
) -> str:
    """Render the artifact: `source` as a document, `report` as its evidence.

    `title` overrides the page title, which otherwise comes from the document's
    first heading and falls back to the bound document's filename.

    `theme` restyles the artifact (see `render/theme.py`). It is emitted after
    the stylesheet rather than into it, so `theme=None` — the default, and what
    an unconfigured render passes — produces exactly the bytes this renderer
    produced before themes existed.
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

    # NOTE: the masthead carries no failure count. Failure still speaks, but in
    # context — the wavy mark on the claim it belongs to, and that claim's note
    # with the reason — rather than as a headline a reader meets before the
    # first sentence and cannot act on. See the DESIGN row of 2026-08-04.
    heading = title or _title(source, report)
    # the newline belongs to the subtitle, not the template: without it a
    # document that has no subtitle leaves a blank line inside the masthead
    subtitle_html = f'\n<p class="subtitle">{_esc(subtitle)}</p>' if subtitle else ""

    overrides = theme.css() if theme is not None else ""
    return PAGE.format(
        title=_esc(heading),
        favicon=_favicon(),
        css=f"{STYLESHEET_MIN}\n{overrides}" if overrides else STYLESHEET_MIN,
        js=SCRIPT_MIN,
        subtitle=subtitle_html,
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


# ---- the page ---------------------------------------------------------------

PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; img-src data:;">
<meta name="generator" content="{format}">
<link rel="icon" href="{favicon}">
<title>{title}</title>
<style>{css}</style>
</head>
<body>
<div class="frame">
<div class="pagecol">
<header class="masthead">
<h1>{title}</h1>{subtitle}
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
<div class="divider" role="separator" aria-orientation="vertical" aria-label="Resize the evidence rail" title="Drag to resize"></div>
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
<span class="namebox" aria-live="polite"></span>
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
