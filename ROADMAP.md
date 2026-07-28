# Roadmap

Sequenced intent. DESIGN.md records what was *decided*; this file records what
is *queued*, so tabling something is an act of writing it down here rather than
losing it. Items graduate by getting built and deleted.

## Next

- **Exhibits view** — the evidence-first inversion (DESIGN 2026-07-28): a
  ranked section of the artifact listing the distinct data points a document
  rests on, each with its evidence context and backlinks to the claims that
  lean on it. Ranking v1 is deterministic — an anchor cited by three claims
  outranks one cited once. Pure renderer work; no new data needed. *Tabled
  2026-07-28 pending a real audience for it.*

- **Excel region maps and range reads** — navigation for large sheets. The
  research is done (notes kept privately): a
  deterministic detection cascade (declared tables → named ranges → print
  areas / freeze panes → merged-aware connected components) producing a
  table of contents per sheet. Two hard constraints from that research:
  regions are navigation metadata only, never citation identity; detection
  must be deterministic. Range reads (`read slug 'sheet!B10:C40'`) ride along.

## Formats

Today: PDF (VLM primary, text-layer floor), XLSX, plain text and Markdown.
Each new format is one Extractor implementing the existing protocol — pages
out, receipts quotable, nothing downstream changes.

- **Images (png, jpeg, tiff)** — a photographed or scanned page is a
  one-page document; the VLM extractor already is this pipeline minus the
  pdf2image step, and the source file is its own stored snapshot. Cheapest
  high-value addition.
- **CSV** — a workbook with one sheet; reuse the sheet representation (A1
  refs, cell anchors) wholesale. Deterministic, keyless, near-trivial.
- **DOCX** — leases, LOIs, agreements. Structured XML, so the deterministic
  path is the good path (paragraphs and tables straight out of the file, no
  OCR); tables render to markdown like sheets do.
- **PPTX** — offering memoranda that arrive as decks. Slide text is
  extractable deterministically as the floor; the faithful path renders
  slides to images through the VLM like PDF pages.
- **XLS / XLSM** — legacy and macro workbooks. openpyxl covers xlsm;
  xls wants python-calamine as the tolerant fallback.
- **Someday**: HTML pages, email (.eml) — both arrive in diligence folders,
  both have messy identity questions (what is "the source" of a web page?)
  that deserve a decision row before code.

## Later

- **`bd:calc` derivations** — the reserved token form for numbers the writer
  computed from cited inputs (the grammar already parses and binds it as
  malformed-on-purpose). The field-trial case: "about 4% of embedded
  loss-to-lease," derived from two cited cells, currently an honest
  value-trace fail with nowhere to point.
- **Sheet styling fidelity** — carry bold / fills / merges / column widths
  through ingest so sheet evidence looks like the workbook, not just its
  values. Carry `cell_styles`, `merged_ranges`, `column_widths` and
  `frozen_panes` in the sheet payload.
- **Living documents** — re-ingest, re-bind, and a drift-first report: "these
  claims cite figures that changed; cited-then vs. now." The primitives
  (generations, `drifted`, the word-diff) all exist; the missing piece is a
  diff-shaped report and a demo.
- **Substrates beyond the CLI** — SDK middleware for pipelines (the exit-code
  and `--to json` contracts are already shaped for it), and a client-side
  drag-drop viewer page (no upload — the file never leaves the reader's
  machine).
- **Distribution** — published on PyPI; still queued: a skills-registry
  listing when one becomes the standard channel.

## Someday

- **Hosted team features** — upload, access control, shared registries.
  Deliberately parked: the product's trust story is the self-contained file,
  and a hosted viewer inverts it. Revisit only as a distinct teams product.
- **Model-judged exhibit ranking** — importance scoring above the
  deterministic count. Only after the deterministic version proves the view.
- **Entail at scale** — the model-judge verifier is wired (`[entail]` extra)
  but has never been field-calibrated; needs a corpus and a rubric before it
  is recommended anywhere.
