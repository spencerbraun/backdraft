# Backdraft — Design

Status: v0 design, 2026-07-27. Decisions below are made unless marked open.

## The point

Drop-in provenance for factual claims: one click from any claim to the evidence behind it. The working problem statement is **verification cost** — an analyst who can't show where a number came from either re-reads the document or doesn't use the output, and both outcomes destroy the value of extraction.

Designed from first principles against the failure modes that kill citation systems in practice: random anchor ids, competing citation grammars, duplicated resolvers, silent failure, anchors that die on reprocessing.

## Principles

1. **Gate, don't verify.** The structure of how information reaches the model determines what it can cite. Reading happens through a tool that mints citation tokens; the set of citable things is exactly the set of things shown. Verification (below) is a separate, optional layer — not the correctness story.
2. **Content-addressed everything.** Anchors derive their identity from document content + location, not from a run. Reprocessing the same bytes yields the same anchors; citations survive.
3. **The receipt travels with the claim.** An anchor is not a pointer — it is a pointer plus captured evidence: verbatim snippet, content hash, location. Defensible without reopening the source.
4. **Failures are data.** Unresolvable tokens, drifted sources, unmatched claims are first-class records in reports and artifacts — never warn-and-drop.
5. **Coordinates live in-band.** Sub-page attribution works when markers like `[B10]` sit in the text the model reads. Human-readable location in the token; side-channel geometry rots (a bbox plumbed through six layers ends up read by nothing).
6. **The format is the product.** Substrates (skill, CLI, SDK, viewer) are thin shells over one spec + one library. Artifacts are self-describing and outlive any substrate (subtext's `$format` + embedded legend pattern).

## Architecture: three layers

### 1. The spec
- **Citation token grammar** — one grammar, typed, shared parser (Python + TS).
- **Anchor schema** — pointer + receipt.
- **Artifact format** — self-describing annotated document: versioned format string, embedded legend, claims with citation lists, sources map, provenance slot (filled — `author_type: human|agent`, model, run; the field subtext specified and left empty), verification records, unresolved list.

### 2. The library / CLI (the system)
Four verbs:
- **`ingest`** — deterministically anchor source documents (PDF/xlsx/md/…) into the registry: extract, locate, snapshot snippets, hash.
- **`read` / `search`** — the gate. Emit token-marked context for a model. Search results are themselves mintable evidence (search that returns nothing citable forces a page read purely to obtain an anchor).
- **`bind`** — postprocess a written document: resolve tokens, run enabled verification switches, backfill surface forms (doc names, pages, quotes), emit sidecar claims file + binding report.
- **`render`** — produce the clickable artifact.

### 3. Substrates (sequenced)
1. **Skill + CLI, together** (first release). The CLI is the system; the skill is ~a page instructing an agent to use it. Ships both the agent-native wedge and the zero-integration backfill demo.
2. **SDK middleware** — wrap a model call: minted context in, bound citations out. The drop-in for application developers.
3. **Viewer** — the artifact carries its own single-file viewer; a component version for embedding comes later.

## The registry

**SQLite**, in `.backdraft/` per project. JSON export command for portability and diffing.

Tables (shape, not final DDL):
- `documents` — path, display name, **slug**, content sha256, media type, ingest metadata.
- `anchors` — token, document, locator, verbatim snippet, snippet sha256, created-by (ingest run).
- `ledger` — session id, token, when shown. Records every token minted into context. Bind distinguishes "cited what you saw" from "cited a valid token you were never shown" — a caught hallucination class most systems cannot express.
- `claims` (written at bind) — claim span text, source doc, citation tokens, verification records.

FTS5 backs `search`. No server, no tenancy — single-analyst/single-project scope; multi-user is a substrate concern, not a registry concern.

## Token grammar

**`bd:<slug>:<locator>:<hash>`** — compound, human-readable location, content-hash suffix.

- `slug` — short kebab doc identifier assigned at ingest, unique per registry (`t12-audit`, `rent-roll-2025`).
- `locator` — media-native:
  - PDF/text: `p8` (page), `p8.c3` (chunk ordinal within page; chunking is deterministic with an explicit within-page ordinal)
  - Excel: `Rent!B10`, `Rent!B10:C12` (sheet + cell/range, spreadsheet-native)
  - Prose files: heading-path or line-range forms (open detail)
- `hash` — first 4+ hex of sha256 of the normalized snippet. Catches transcription typos, detects drift after re-ingest, and makes the token content-addressed. Registry extends length on collision.

Examples: `[DSCR of 1.42x](bd:t12-audit:p8.c3:a7f3)` · `[NOI of $4.1M](bd:model:Rent!B10:9e2f)`

Reserved extension — **declared derivations**: a claim whose value appears in no document carries its computation over multiple tokens (`bd:calc(model:Rent!B10 / t12-audit:p4.c1)` — sketch, grammar open). This is what makes "the numbers tie" a deterministic check instead of a slogan; only possible because we own the grammar.

## The gate (context construction)

The read tool's shape:
- Unified dispatch: list docs → per-doc TOC of page/sheet summaries → page/range read → batch read. Short slugs everywhere.
- Progressive disclosure with continuation, plus search hints.
- **Excel**: sheet-per-page markdown table with `Row | A | B | …` headers and `[B10] value` cell prefixes — the representation that makes cell-level attribution work. Hardening: dimension caps, inflated-sheet placeholders, trimming.
- Search mints citable snippet tokens; Excel long-context gets structural navigation (detected regions/ranges) rather than char-offset slicing (open design area).

The skill's core instruction is a substitution: for source documents, use `backdraft read`/`search`, not raw Read/Grep.

## Wire format

The writer emits inline tokens on the claim span — `[claim text](bd:…)` — and nothing else: no doc names, no footnotes, no display text. Span binding (which words the anchor supports) is captured at write time because it can never be recovered later and can always be projected away. Footnotes, endnote lists, hover cards are all render-time projections.

## Bind

Runs after writing (in Claude Code: enforceable as a Stop/PostToolUse hook so unbound tokens can't ship).

1. **Resolve** every token: parses → registry hit → ledger hit → snippet hash matches current source. Resolution is inherent to bind (an unresolvable token can't be backfilled) — it is not a switch.
2. **Verify** per enabled switches (below).
3. **Backfill** surface forms: tokens become readable citations (doc name, page/cell, quote) in the output doc.
4. **Report**: sidecar claims file + binding report. Every failure is a line item: `unresolved`, `not-shown`, `drifted`, `unmatched` (backfill mode). Nothing drops silently.

## Verification — switches, default off

Independent checks per citation, recorded as graded evidence, never gating generation. The record says which methods ran and what each found; switches off ⇒ record says unchecked. Grade schema is stable regardless of which switches are on.

| # | Switch | Method | Claim class |
|---|---|---|---|
| 1 | `value-trace` | Deterministic: normalized value (units/scale/format) occurs at the cited location | numbers, dates, names |
| 2 | `overlap` | Heuristic span overlap / exact substring for quotes — report-only signal | quotes, paraphrase |
| 3 | `entail` | Model judge: does snippet support claim — tiny closed question, batchable, async | qualitative |
| 4 | `recompute` | Deterministic re-execution of declared derivations | derived values |

Rationale for default-off: out of the box this is pure provenance (one click to the receipt); verification is opt-in per claim class. Rung-pass rates aggregated per run/model double as an eval substrate.

## Modes

- **Front-walk** — citations minted during generation; bind resolves against the session ledger. The high-quality integrated path.
- **Backfill** — an existing document + ingested sources; for each claim: search → propose anchors → bind via the fuzzier strategies (overlap, value-trace, structured lookup). Unmatched claims land in an explicit unresolved list, not silent non-attribution. Zero integration required — the demo wedge.

Same anchors, same bind, same artifact out.

## The artifact

Self-contained HTML (plus the machine-readable sidecar): **quotes + receipts + evidence embedded** — verbatim snippets, hashes, locations, verification grades, and the evidence itself: cited pages as images, cited cells in mini-grid windows. Bounded by what is cited, never the corpus; `--lean` drops images. Small and portable; defensible with sources absent. Designed in three disclosure layers (document → footnote → record) with success silent and failure loud — see the 2026-07-28 decision rows.

## Decision log

| Date | Decision |
|---|---|
| 2026-07-27 | Rewrite, not port; ideas only |
| 2026-07-27 | Gate-over-verify: read path mints citable tokens; ledger records what was shown |
| 2026-07-27 | Receipt (snippet + hash + location) is part of the anchor primitive |
| 2026-07-27 | Registry: SQLite in `.backdraft/`, JSON export |
| 2026-07-27 | Token grammar: compound `bd:slug:loc:hash` |
| 2026-07-27 | Verification: independent switches, default off; resolution is inherent to bind, not a switch |
| 2026-07-27 | First substrate: skill + CLI together; SDK middleware and viewer follow |
| 2026-07-27 | Artifact: quotes + receipts embedded, no page images in v0 |
| 2026-07-27 | VLM extraction is the recommended primary path for real PDFs (glossy layouts, info boxes — the snapshot is the receipt, and model reading beats scrambled text-layer order). Text-layer is the keyless floor and CI path, not "the default." `ingest --extractor auto` picks VLM when an API key is configured, else text-layer with a printed nudge. Known tradeoff, accepted: re-extraction under a non-deterministic extractor drifts all citations; generations + drift reporting carry that honestly. |
| 2026-07-27 | Kernel API is module paths (`backdraft.kernel.tokens.parse`); no flat re-export surface. Package `__init__`s export exactly what outside consumers import. |
| 2026-07-27 | CLI unified on the gate's patterns: shared `cli_context` (constants, discovery, sessions, one error guard mapping `BackdraftError` → exit 1), `Annotated` params, relative imports. Test fakes renamed so the real and fake registries cannot be confused. |
| 2026-07-27 | File naming is part of the artifact format, owned by `kernel/artifact.py`: `<stem>.bound.md`, `<stem>.backdraft.json`, `<stem>.backdraft.html`, `<stem>.footnotes.md`. |
| 2026-07-27 | `bind --check entail` without the extra records `skip` verdicts carrying the reason — verifiers never gate, including at the CLI layer. |
| 2026-07-27 | **Supersedes "VLM when key present":** credentials are explicit. Ambient provider keys (`OPENAI_API_KEY`, `OPENROUTER_API_KEY`, `ANTHROPIC_API_KEY`) are never read; a credential reaches backdraft only via `--config`, a `BACKDRAFT_*` variable, or `.backdraft/env` (`init` writes a template). `vlm_ready` — the `auto` gate — is therefore equivalent to consent. Decided after a real unapproved-spend incident during the first field trial: presence of a generic key in the environment is not consent to spend it or send documents to its provider. |
| 2026-07-28 | **Reader doctrine (supersedes "no script"):** the artifact is designed for two readers — the writer verifying the AI's work, and a normal person the document is sent to — in three disclosure layers: the document (editorial typography, quiet marks), the footnote (click a claim → the source's own words, named and paged — no tokens, no hashes, no jargon), and the record (one deliberate step to the full machine-readable layer). **Success is silent; only failure speaks**: a fully-resolved artifact looks like a well-made document, while unresolved citations announce themselves before the reader invests belief. The load-bearing constraint is *no network, single file* — enforced by a CSP `meta` tag (`default-src 'none'`) — not *no script*: inline JS is allowed as progressive enhancement over a CSS-only baseline that survives script-stripping. Decided after field use: the v1 artifact rendered success and failure at equal volume and read as machinery, not a document. |
| 2026-07-28 | **Evidence embeds in the artifact (supersedes "no page images in v0"):** the footnote layer carries the evidence itself, not just the quote — the cited page as an image, the cited cell in a mini-grid window (neighbors, row labels, column headers). Bounded by *what is cited*, never the corpus, so a memo citing ten pages costs ~2–3 MB; `--lean` skips images. Evidence is assembled at **bind** (the step that has the registry) and travels in the sidecar; render stays registry-blind and the artifact stays reproducible from the two files a reader was handed. For the VLM path, the page image the model was shown is stored at **ingest** — for a non-deterministic extractor the input pixels are the only reproducible snapshot, so the image completes the receipt chain (claim → quote → page). Reference shapes: WebP quality 85 for pages; sheet windows as compact JSON with typed cell values and column-letter headers. |
| 2026-07-28 | **Exhibits: the evidence-first inversion.** The artifact carries a second reading mode: every source document with the data points cited from it, each with its evidence context and backlinks to the claims that lean on it — "this memo rests on N data points across M documents." Ranking is deterministic in v1 (an anchor cited by three claims outranks one cited once); model-judged importance is a later switch. This is the skeptical reader's entry point and the writer's spot-check checklist. *(2026-07-29: parked in ROADMAP — file-size and design-restraint concerns; needs a deliberate design pass and a real audience first.)* |
| 2026-07-29 | **Office formats extract natively, never through conversion.** DOCX and PPTX are read straight from their XML (python-docx / python-pptx, core deps). Converting to PDF was rejected on principle: conversion is rendering, so it needs a layout engine (LibreOffice, MS Office, or a cloud API — a 700MB dependency, a platform lock, or documents leaving the machine), and converter-dependent pagination would break content-addressed locator stability. DOCX pages are heading sections: the split level is the smallest outline level present among {Heading 1, Heading 2}; preamble is section 1; no headings → one section — locators stay `pN.cM`, no grammar change. PPTX pages are slides (slide N is slide N in every renderer). The text floor deliberately misses slide visuals; the ingest note says so and names the path that captures them — the user exporting the deck to PDF with the real renderer they already have, ingested through the vision extractor — so a calling agent can relay it. |
| 2026-07-29 | **The vision extractor ships by default (supersedes "[vlm] as extra").** `openai` + `pdf2image` moved into core dependencies; `[vlm]` remains as an empty compat alias. Rationale: the VLM path is the recommended path for real PDFs, and an extra made the recommended path opt-in. The consent boundary does not move — installing deps was never consent; the backdraft-scoped `BACKDRAFT_VLM_API_KEY` is, and ambient provider keys stay unread. There is no slim install: pip extras can only add, never subtract; a separate core distribution is possible later if anyone asks. poppler stays a runtime capability check. |
| 2026-07-29 | **Renderer decomposed; Python is the formatting authority.** `render/html.py` (1,300 lines) became the `render/html/` package (fmt, text, components, assets, page), byte-identical at the seam. The deliberate `fmt_cell` (Python) / `fmtCell` (JS) duplication is now pinned by one shared vector table driving both tests, with the JS run under node when available. The JS was found diverging on exact rounding ties (`toFixed` rounds half-up; Python rounds half-to-even on the double's value) and was rewritten to round exactly — Python defines correct, JS matches it. The artifact emits minified CSS/JS and unindented markup; the `$legend` and sidecar JSON stay readable in view-source (spec constraint). Snapshot budget knobs `BACKDRAFT_SNAPSHOT_QUALITY`/`BACKDRAFT_SNAPSHOT_MAX_HEIGHT` tune page-image weight at ingest — display only, tokens never derive from pixels. |
| 2026-07-30 | **Every PDF ingest captures page images, not just the VLM path's.** The text-layer route stored none, so the keyless path produced visually poorer artifacts for no principled reason — the pages render locally through poppler, no model calls, and the capability already existed as the `snapshot-pages` backfill. The capture is a step *after* extraction, owned by `cli.py` over `extract/snapshots.py`, deliberately **not** inside `pdf-text`: an extractor whose output varied with whether poppler happened to be installed would not be `deterministic = True`, and the same bytes must extract identically on every machine. Because snapshots only ever write `page_images` — a table no token, chunk, or receipt path reads — capture is safe to make best-effort: no poppler means ingest still exits 0, with a one-line note naming `snapshot-pages` as the backfill, rather than failing over a display concern. Tradeoff accepted: PDF ingest is now slower by a local render per page (one poppler call per page rather than one per document, to bound peak memory on long PDFs), and a library caller using `Registry.ingest` directly gets no snapshots — the policy lives at the CLI, which is the substrate that has a user to notify. |
| 2026-08-03 | **The card divides its own height; nothing inside it is pinned.** The receipt card is user-resizable, so it is a flex column: header, source selector, source line and tabs are fixed rows that never scroll away, and the evidence region takes whatever is left — dragging the card taller grows the evidence rather than the whitespace under it. The caps that survive are relative (the card at `82vh` of the window; the quote, drift diff and record at `40%` of the card), and a `5rem` floor keeps the evidence from vanishing at the card's minimum, with the citation scrolling instead. Resizing means *more*, not *smaller*: the page image keeps its scale and the pane scrolls over it, because a page shrunk to fit a short card is a page you cannot read, while the sheet window — which has no scale to lose — grows to fill, matching the full-sheet overlay it opens into. Both sheet views now stick their headers from one rule. Display only, as ever: no token, receipt or record moves, and the phone card keeps `resize:none` and the fixed caps it always had, since there is no drag there for the evidence to follow. |
| 2026-08-04 | **A theme is an override block, not a stylesheet.** The artifact's look is themeable, and a theme is a small TOML file naming values for the CSS custom properties the stylesheet already exposes — the seventeen colors and the three font roles — plus four bounded heading knobs (family, case, weight, tracking) that the theme module compiles into one `.masthead h1,.doc h2` rule it owns. The built-in stylesheet is not edited and not replaced: the resolved theme is emitted as a block *after* it, so with nothing configured the artifact is byte-identical to an untheme'd build and theming is provably inert by default. A theme may not touch layout, structure, or any verification affordance, and never touches a token, receipt or record — `--rail-w` and `color-scheme` are deliberately outside the allowlist for that reason, and so is the artifact's refusal to follow the reader's system theme. Keys and values are both validated against declared allowlists, so `--colour` or `#GGG` fails by name before anything is written rather than producing a half-styled file; `url(...)` is rejected with the reason, since a font the file would have to fetch is exactly what the CSP forbids. Precedence is `--theme` > project `.backdraft/theme.toml` > XDG `~/.config/backdraft/theme.toml` > built-in, the user-wide file being what makes a preference stick across projects. The bundled `default.toml` restates today's values and is pinned by a test against the stylesheet's own `:root`, which makes it the audit as well as the reference sample. Tradeoff accepted: `--serif`/`--sans`/`--mono` name roles (body, UI, code) rather than classifications, so a sans-bodied theme sets `serif`. *(2026-08-04, follow-up: `--hl` was declared in `:root` and read by no rule, so it is deleted rather than left as a themeable key that paints nothing, and the `#fff` behind page images now tracks `--paper` — white there was coincidence, and every stored image is opaque RGB, so it was dead either way. The six constants that remain hardcoded — the card and rail shadows, the overlay scrim, the PDF tab accent, the `partial` verdict amber, sheet-header grey — were considered and deliberately left: each is near-neutral at any sane palette distance, and promoting them is a wider audit for churn rather than effect. Separately, `.doc h3` through `h6` had no rule at all — the markdown renderer emits every level and only two were styled, so a memo with `### ` fell to the browser's bold-Times default mid-page — and they are now a two-step scale that *brackets* the body rather than continuing down from `h2`, since the sheet sizes in `rem` while `body` sets 17px and a plain `1rem` heading lands under the text it heads. The theme's heading selector covers the whole scale for the same reason it exists: small-caps section heads above a body-face subsection read as a mistake, not a choice.)* |
| 2026-08-04 | **Failure speaks at the claim, not in the masthead (amends the 2026-07-28 reader doctrine).** The artifact no longer prints a failure summary under the title. "Success is silent; only failure speaks" stands, and so does the principle under it — failures are data, never warn-and-drop — but *where* it speaks moves: the wavy alarm-coloured mark on the affected claim, and that claim's note with the reason, both of which a reader meets in context. The line that went was a bare count, and a count is the one thing about a failed citation a reader cannot act on: whether `1 of 16 citations could not be traced` matters depends entirely on which claim it was, which the headline does not say and the mark and the note do. It was also aimed at the wrong reader — the writer verifying the work learns about failures from `bind`, which exits 2 and lists them, while the recipient got a number out of context before the first sentence. Nothing loses its last surface: an unmatched claim with no citations ranks `unresolved` and is marked in the body like any other failure, and a claim that is not in the document at all was already the Notes' job under artifact rule 4. This is a spec change — `spec/artifact.md` rule 6 is rewritten, and the summary is now explicitly *not* required of a conforming producer rather than merely unmentioned, so another implementation reads the same intent. |

| 2026-08-05 | **A web page's identity is the sha256 of the snapshot fetched at ingest time; the URL is provenance, not identity.** `ingest` accepts an http(s) URL alongside files (graduating the "HTML pages" question from Later). The fetched bytes are hashed and snapshotted exactly as a file's are, so everything downstream — anchors, the ledger, `bind`, generations — is unchanged, and a page that changed since the last fetch is a *new generation of the same document*, which is the machinery drift already describes. Continuity across a re-fetch follows the URL rather than the path, because the path is a temporary staging file; `documents.sha256` is UNIQUE, so bytes still win over origin when the same content arrives twice under two URLs. The URL and `fetched_at` live in a new `document_meta` table — a JSON sibling of `page_meta`, chosen over columns on `documents` so an existing registry needs no migration and so the next provenance question (`.eml` headers) needs no second one; `fetched_at` moves on a re-fetch that changed nothing, since "when was this last confirmed to say this" is the question a reader of an old citation actually has. Fetching is stdlib `urllib` and lives in `fetch.py`, *outside* `extract/`: an extractor stays a pure function of a file's bytes, which is what keeps `deterministic` honest and lets a saved `.html` file and a fetched page extract identically. The CLI owns the network the way it already owns page-snapshot capture. The new `html` extractor is a parse, not a readability heuristic — no boilerplate stripping, no main-content guess, because a heuristic that changes its mind moves anchors, which is the failure mode this system exists to prevent; navigation and footers are part of the page. Its representation follows `docx`: tables as markdown pipe tables, lists as `- `/`1. ` lines kept in one block, `<pre>` verbatim. Decoding is BOM, then the document's own `<meta charset>`, then UTF-8 with replacement — the server's `Content-Type` charset is deliberately *not* consulted, so the bytes alone determine the text. Known limitations, accepted and documented rather than worked around: JavaScript-rendered pages yield whatever the server sends, pages behind a login are out of reach, and a non-UTF-8 page that declares its encoding only in the HTTP header will render as mojibake in the snapshot — visibly, rather than silently. |
| 2026-08-06 | **A fetched source's origin travels into the artifact as a live link, dated.** The capture half of the row above stored `url` and `fetched_at` and stopped at the registry, so an artifact citing a web page named `q4-2025.html` — a staging filename that never existed on anyone's disk — and a reader holding the file had the frozen receipt with no way back to the page. `bind`'s evidence `documents` map now carries `url` and `fetched_at` through to the record, and both renderers show them: the receipt card, the script-free note, the source list and the rail all print the URL as a real `<a href>` with the fetch date beside it, and the markdown projection carries it as an autolink. This is an artifact-format change, so `spec/artifact.md` and the `$legend` name the two keys together, both OPTIONAL. The keys are emitted *only* where a document has a URL, which is what keeps an artifact built from files byte-identical to one built before this existed — the conditional is the compatibility guarantee, and it is a test rather than an intention. Linking does not weaken the self-containment rule: the CSP (`default-src 'none'`) forbids *fetching*, and an anchor fetches nothing until a reader chooses to follow it, so the file still renders identically offline. The href is allowlisted to `http`/`https` rather than merely screened for `javascript:`, since artifact rule 3 is a conformance requirement and an allowlist cannot be outflanked by a scheme nobody thought of; a URL under any other scheme is printed as plain text rather than dropped, because failures are data and provenance the reader must paste by hand still beats provenance withheld. In the source list the URL *replaces* the filename rather than joining it — showing both would give a reader two names for one thing and let the fictional one look authoritative. The date is the day, not the timestamp: "as of" is what makes a frozen quote from a live page defensible, and no reader needs the seconds. |

## Open

Queued and parked work lives in ROADMAP.md; this list is questions still
awaiting a decision:

- Re-bind/orphan pass on re-ingest of changed docs (chunk ordinal drift)
- Slug assignment/collision rules (the trailing-hyphen truncation from the
  first field trial lives here)
- Distribution: published to PyPI as `backdraft` 0.2.0 (2026-07-28); domain
  backdraft.dev acquired; still open: skill registration, deploying site/
- First external user (design-partner validation layer vs eval substrate vs
  open release feedback)
