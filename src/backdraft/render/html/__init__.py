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

The package splits along the artifact's own seams — `fmt` (sheet-value
display), `text` (prose helpers), `components` (the fragments), `assets` (the
stylesheet and behavior script), `page` (assembly) — but its import surface is
the old module's: `from backdraft.render import html`, then `html.render(...)`.
Every helper keeps its old `html.<name>` spelling so display-layer edits stay
small.
"""

from __future__ import annotations

from .assets import (
    FLAME_PATH,
    SCRIPT,
    SCRIPT_MIN,
    STYLESHEET,
    STYLESHEET_MIN,
    _favicon,
)
from .components import (
    _TYPE_LABEL,
    _card,
    _citation,
    _note,
    _page_plate,
    _page_store_html,
    _record_block,
    _sources_index,
    _status_sentence,
    _tabs,
    _window_table,
)
from .fmt import _is_number, _style_attr, _width_px, fmt_cell, fmt_number
from .page import (
    ISLAND_ID,
    PAGE,
    SHEETS_ISLAND_ID,
    _escape_island,
    _island,
    _title,
    render,
)
from .text import (
    CELL_RE,
    IMAGE_TAG_RE,
    PAGE_RE,
    SUBTITLE_RE,
    _drift_block,
    _esc,
    _word_diff,
    humanize_sheet,
    humanize_verdict,
    location,
    md_html,
    short_loc,
    source_title,
    split_subtitle,
    table_heavy,
    worst_status,
)

__all__ = ["render", "ISLAND_ID", "SHEETS_ISLAND_ID", "STYLESHEET", "FLAME_PATH"]
