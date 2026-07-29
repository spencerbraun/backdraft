# Roadmap

Sequenced intent. DESIGN.md records what was *decided*; this file records what
is *queued*, so tabling something is an act of writing it down here rather than
losing it. Items graduate by getting built and deleted.

## Now

Formats and structural cleanup: make what exists better before adding views.
Each format is one Extractor implementing the existing protocol — pages out,
receipts quotable, nothing downstream changes. Each cleanup item is
behavior-preserving and guarded by the golden-file tests.

- **DOCX** — deterministic extraction from the XML via python-docx:
  paragraphs and tables (rendered as markdown) in document order. A DOCX has
  no pages, so heading sections become pages: a paragraph at the document's
  smallest present outline level (Heading 1, else Heading 2) starts a new
  section; content before the first heading is section 1; a document with no
  headings is one section. Locators stay `pN.cM` — no grammar change. No
  rendering dependency, ever: converting to PDF needs a layout engine
  (LibreOffice), and pagination would then depend on the converter's fonts
  and version, which breaks content-addressed locator stability.
- **PPTX** — deterministic slide text via python-pptx: one page per slide,
  title, body text, tables as markdown, speaker notes. The ingest note tells
  the calling agent that charts and images on slides are not captured, and
  that a PDF export of the deck ingested through the vision extractor
  captures them — the agent passes that along when it matters. No LibreOffice
  here either; the person with the deck has the real renderer.
- **XLS** — legacy workbooks via python-calamine behind an `[xls]` extra;
  rides the shared sheet helpers. Values only, no styling meta.
- **Decompose the HTML renderer** — `render/html.py` is 1,300 lines holding
  four different things: the Python component functions, the stylesheet
  string, the script string, and the page template. Split into a
  `render/html/` package so each is findable and diffable. While in there,
  pin the deliberate duplication: `fmt_cell` (Python, server-rendered
  windows) and `fmtCell` (JS, overlay) must format identically, so drive
  both from one shared table of test vectors instead of trusting parallel
  edits.
- **A shared sheet-extraction module** — the CSV extractor imports `_bounds`,
  `_render`, `_title` privately from the XLSX extractor. Hoist the common
  tabular helpers into one module with public names; XLS is the third
  consumer, DOCX tables the fourth.
- **Artifact weight** — the demo artifact is 523 KB: 68% embedded page
  images, and of the 170 KB of markup about 45 KB is indentation whitespace
  plus unminified CSS/JS. Only cited pages are embedded and `--lean` already
  drops images entirely, so the remaining levers are: (1) emit minified
  markup and assets, cheap and behavior-free; (2) tune the page-image
  snapshot budget (WebP quality and max height) at ingest. The constraint:
  the artifact stays self-describing, so the `$legend` and the sidecar
  payload stay readable in view-source even after minification.

## Parked

Deliberately not queued, each with the reason, so picking one up starts from
the objection rather than rediscovering it.

- **Exhibits view** — the evidence-first inversion. Risk: it grows the
  artifact and pollutes a design whose strength is restraint. Needs a
  deliberate design pass and a real audience before any code; not a
  weekend-feature shape.
- **Excel region maps and range reads** — the research notes exist, but no
  confidence the deterministic detection cascade lands well on the first
  try. Revisit when large-sheet navigation hurts in a real corpus, with
  test workbooks in hand.
- **`bd:calc` derivations** — reserved in the grammar and parsed as
  malformed-on-purpose, which is enough for now. Full support complicates
  binding and verification for one field-trial case.
- **Merged-cell and frozen-pane rendering** — ingest captures `merged` and
  `frozen` in sheet meta and keeps them (cheap, and capture is the part you
  cannot backfill). Frozen-pane rendering is cut; merged-cell rendering
  waits for a real sheet that renders wrong without it.

## Later

- **Living documents** — re-ingest, re-bind, and a drift-first report: "these
  claims cite figures that changed; cited-then vs. now." The primitives
  (generations, `drifted`, the word-diff) all exist; the missing piece is a
  diff-shaped report and a demo.
- **Substrates beyond the CLI** — SDK middleware for pipelines (the exit-code
  and `--to json` contracts are already shaped for it), and a client-side
  drag-drop viewer page (no upload — the file never leaves the reader's
  machine).
- **HTML pages and email (.eml)** — both arrive in diligence folders, both
  have messy identity questions (what is "the source" of a web page?) that
  deserve a decision row before code.
- **Distribution** — published on PyPI; still queued: a skills-registry
  listing when one becomes the standard channel.

## Someday

- **Hosted team features** — upload, access control, shared registries.
  Deliberately parked: the product's trust story is the self-contained file,
  and a hosted viewer inverts it. Revisit only as a distinct teams product.
- **Entail at scale** — the model-judge verifier is wired (`[entail]` extra)
  but has never been field-calibrated; needs a corpus and a rubric before it
  is recommended anywhere.
