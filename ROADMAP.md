# Roadmap

Sequenced intent. DESIGN.md records what was *decided*; this file records what
is *queued*, so tabling something is an act of writing it down here rather than
losing it. Items graduate by getting built and deleted.

## How the queue runs

The Now section is an ordered queue written for an implementing agent with no
session context: each item carries its intent, its shape, and its acceptance
test. The working agreement is one item at a time, top first, shipped complete
— code, tests, docs, and a DESIGN.md decision row where the item calls for one
— then deleted from this file in the same commit. Releases cut weekly, so an
item that lands mid-week waits on PyPI until the release; nothing ships
half-done to make a release. An item that turns out bigger than its sizing
gets split here, not stretched silently.

## Now

### 1. Page snapshots at text-layer PDF ingest

**Intent.** VLM ingest stores each page's image, so artifacts show the cited
pages themselves; text-layer ingest stores none, so the keyless path produces
visually poorer receipts for no principled reason. The snapshots are local
renders through poppler — no model calls, nothing leaves the machine — and the
capability already exists as the manual `backdraft snapshot-pages` backfill.
Close the gap: capture page snapshots automatically when a PDF ingests through
`pdf-text`.

**Shape.** The `pdf-text` extractor stays `deterministic = True`, so its
output cannot vary with whether poppler happens to be installed — the hook
lives *after* extraction, in the ingest path, sharing the same internals
`snapshot-pages` uses (same `BACKDRAFT_SNAPSHOT_QUALITY` / `MAX_HEIGHT`
budget, same storage). When poppler is absent, ingest succeeds exactly as
today and prints a one-line note naming `snapshot-pages` as the later backfill.
Snapshots are display-only and never touch token identity.

**Acceptance.** On a machine with poppler, a text-layer PDF ingest followed by
bind + render produces an artifact whose cited-page images are
indistinguishable in shape from the VLM path's; tokens minted before and after
the change are identical. Without poppler, ingest exits clean with the note.
Tests cover both branches; `--lean` still opts out at bind. Skill and docs
drop the "or via the text layer" caveat where it no longer applies.

**Size.** One day.

### 2. Source card: contents resize with the card

**Intent.** The artifact's source card is user-resizable (`resize:vertical`,
`max-height:82vh` — assets.py) but its inner blocks hold their own fixed caps
— the quote scroller is pinned at `15rem`, and the sheet grid and page image
size themselves — so dragging the card taller yields whitespace, not more
evidence. Resizing should mean seeing more.

**Shape.** Make the card a flex column whose scrollable evidence region
(quote / drift / sheet / page image) flexes to fill the card's height, with the
header, source selector, and tabs as fixed rows. Audit every fixed
`max-height` inside `.card` and convert to flex-driven sizing. The mobile
card keeps `resize:none` and its current behavior. Python is the formatting
authority and this is CSS/JS only, so no fmt-parity surface is touched; the
minified asset budget should move only trivially.

**Acceptance.** Dragging the card taller visibly grows the quote, sheet, and
page-image viewports; dragging it short reintroduces inner scrolling rather
than clipping the header or tabs. Verified against a real artifact (the demo)
across the three evidence kinds, plus the mobile breakpoint. Node-side DOM
test if cheap; otherwise the existing render tests plus a manual screenshot
pass recorded in the PR.

**Size.** One day.

### 3. Theming: sticky user preferences, drop-in themes

**Intent.** The artifact's look is currently one hardcoded design. Let a user
set a theme once and have every artifact they render honor it, and let a theme
be a small file someone can drop in — fonts, colors, heading treatment at
minimum.

**Shape.** Two parts, in order:

- *Decision row first.* A theme is a named set of overrides for the CSS custom
  properties the stylesheet already exposes (`--paper`, `--ink`, `--sel`, the
  font stacks) plus a bounded set of typographic choices (heading family/case,
  maybe rule weight). A theme may not change layout, structure, or any
  verification affordance — display only, tokens and records untouched.
  Settle the file format (a flat TOML of variable names, or a raw CSS-variables
  block) and write the DESIGN.md row before code.
- *Then the loader.* Precedence: `render --theme <file-or-name>` >
  project `.backdraft/theme.*` > user-wide config (XDG,
  `~/.config/backdraft/theme.*`) > built-in default. The user-wide file is
  what makes preferences stick across projects. Bundled themes (the default
  plus one or two alternates) prove the format; the resolved theme is baked
  into the artifact at render time so the file stays self-contained.

**Acceptance.** Rendering with no config is byte-stable against today's
output. A theme file in the XDG location changes fonts/colors/headers on every
subsequent render in any project without flags; `--theme` overrides it; a
malformed theme fails with a clear message, never a half-styled artifact.
Docs page gains a short theming section with a sample theme file.

**Size.** Two days — decision row and variable audit, then loader, bundled
themes, docs.

### 4. URL sources: capture and link back

**Intent.** Diligence folders contain links, not just files. `backdraft ingest
<url>` should fetch a page, snapshot it into the registry like any other
source, and — the other half — artifacts should show a source's origin URL and
link back to it, so a claim cited to a web page carries both the frozen
receipt and the live pointer.

**Shape.** This is the graduation of the "HTML pages" question from Later, and
it needs its decision row: *the source's identity is the sha256 of the fetched
snapshot at ingest time*, same as a file — the URL is provenance metadata, not
identity. A page that changes later is a new generation; the existing drift
machinery already describes that. Capture: fetch (stdlib or the lightest
dependency that handles redirects and encodings), extract readable text into
the normal page/chunk structure, store the origin URL and fetch timestamp in
source meta. Render: sources carrying an origin URL show it in the resting
source list and the card, as a real link. Out of scope for this item:
JavaScript-rendered pages (note the limitation), authentication, and `.eml`
(stays in Later).

**Acceptance.** `ingest https://…` on a static page mints citable tokens;
`read`/`search`/`cell`-equivalents behave as for text sources; bind embeds the
receipt; the artifact's source entry links to the URL and the record JSON
carries url + fetched-at. Re-ingesting a changed page produces a new
generation and `drifted` behaves correctly. A network-free test suite (fixture
HTML served locally or loaded from disk); DESIGN.md row written; docs updated.

**Size.** Two to three days — decision row and capture first, render linkage
second.

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
- **Email (.eml)** — arrives in diligence folders alongside everything else;
  identity questions (headers vs. body, attachments as child sources) deserve
  a decision row before code. The web-page half of this item graduated to the
  Now queue as URL sources.
- **Anthropic-API provider for the VLM extractor** — Cowork's sandbox
  egress allowlist includes api.anthropic.com but not the OpenAI-compatible
  providers, so an Anthropic-native option would let sandboxed sessions
  ingest at full fidelity. Needs a client abstraction the vlm module
  currently doesn't have; the documented workaround (ingest locally, the
  registry travels with the folder) covers it meanwhile.
- **Distribution** — published on PyPI; the repo ships
  `.claude-plugin/plugin.json` and `marketplace.json`, so it installs as a
  Claude Code plugin and self-hosts its marketplace, and the AGENTS.md
  snippet is published in the README and site docs. The community-directory
  submission went in 2026-07-29 and is awaiting review — approval is what
  surfaces the skills in Cowork's directory.

## Someday

- **Hosted team features** — upload, access control, shared registries.
  Deliberately parked: the product's trust story is the self-contained file,
  and a hosted viewer inverts it. Revisit only as a distinct teams product.
- **Entail at scale** — the model-judge verifier is wired (`[entail]` extra)
  but has never been field-calibrated; needs a corpus and a rubric before it
  is recommended anywhere.
