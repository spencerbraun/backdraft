# Backdraft — Contracts

Status: v0 build spec, 2026-07-27. This is the builders' contract: types, grammar, DDL, CLI surface, module boundaries. Direction and rationale live in [DESIGN.md](DESIGN.md); do not re-litigate decisions recorded there. Python 3.13, uv, package `backdraft`.

Design stance: this is a small codebase built as a base platform. A pure kernel with few concepts, one stateful object (the Registry), three extension protocols (Extractor, Verifier, Renderer), and a prose-specified format that outlives the implementation. When in doubt, keep the kernel smaller.

## Concepts (the whole vocabulary)

| Concept | Is | Identity |
|---|---|---|
| **Document** | An ingested file, or a web page snapshotted at ingest | sha256 of bytes; human handle is a `slug`. A fetched page's origin URL is provenance metadata, never identity |
| **Extraction** | A snapshot of a document's content produced by one extractor run | (document, extractor, version, config); generations are kept, one is `current` |
| **Page** | Ordered unit within an extraction — a PDF page or a sheet | (extraction, number) |
| **Anchor** | An addressable location in an extraction, carrying its **receipt**: verbatim snippet + snippet hash | locator within extraction; named by its token |
| **Token** | The textual name of an anchor a model transcribes | `bd:slug:locator:hash` |
| **Session / Ledger** | A record of every token minted into a writer's context | session id |
| **Claim** | A span of authored text + its citation tokens | position in the authored doc |
| **Binding** | The postprocess: resolve claims against the registry, backfill surface forms, report | one run over one authored doc |
| **Verdict** | One verification method's finding for one (claim, citation) | (claim, token, method) |
| **Artifact** | Rendered self-contained deliverable (quotes + receipts embedded) | output file |

Nothing else gets a name. New nouns require a spec change.

## Repo layout

```
backdraft/
  pyproject.toml            # uv; extras: [vlm] (openai client + pdf2image), [entail] (anthropic)
  src/backdraft/
    kernel/                 # PURE. No I/O, no SQLite, no deps beyond stdlib.
      model.py              # frozen dataclasses: Document, Extraction, Page, Anchor, Receipt,
                            #   Claim, Citation, Verdict, BindReport
      tokens.py             # grammar: parse / format / validate  (EBNF below lives here)
      hashing.py            # normalization + hashing rules (below)
      chunking.py           # deterministic chunker: (page_text) -> [Chunk(ordinal, text, start, end)]
      claims.py             # extract claims + tokens from authored markdown
      artifact.py           # the artifact format: $format string, legend, sidecar payload —
                            #   bind writes it and render reads it, so neither owns it
      errors.py
    registry/
      schema.sql            # THE DDL. Single source of truth.
      store.py              # Registry: the only stateful object. Owns SQLite + FTS5.
      ledger.py
    extract/
      base.py               # Extractor protocol + registry of extractors
      pdf_text.py           # pdfplumber text-layer; paragraph breaks rebuilt from line geometry
      sheet.py              # the shared tabular representation: bounds caps, [B10] row rendering
      xlsx.py               # openpyxl → sheet representation + styling meta
      xls.py                # [xls] extra: calamine → sheet representation, values only
      csv.py                # sniffed-dialect csv/tsv → sheet representation
      docx.py               # python-docx; heading sections become pages
      pptx.py               # python-pptx; one page per slide, text floor
      text.py               # md/txt passthrough
      image.py              # an image is a one-page document; VLM transcription
      html.py               # html/htm → one page of readable text; a parse, not a readability guess
      vlm.py                # pdf→images→VLM per page (deps ship by default; key gates use)
      vlm_settings.py       # provider/model/base-url resolution; stdlib-only
    gate/
      reader.py             # ls / toc / read page-range → token-marked context; records ledger
      searcher.py           # FTS5 → minted snippet results; records ledger
      cli.py                # `read`, `search`, `session` — mounted by the top-level cli
    bind/
      binder.py             # resolve → verify (switches) → backfill → report
      cli.py                # `bind` + the exit-code contract — mounted by the top-level cli
      verify/
        base.py             # Verifier protocol
        value_trace.py  overlap.py  recompute.py  entail.py   # entail behind [entail]
    render/
      html/                 # single-file artifact, embedded viewer + legend
                            #   fmt.py text.py components.py assets.py page.py
                            #   fmt_vectors.py: one vector table drives fmt_cell (py) and fmtCell (js)
      markdown.py           # the authored document's markdown → HTML, stdlib only
      placement.py          # locating each claim's span in the document render was handed
      footnotes.py          # markdown projection
      sidecar.py            # sidecar reader/writer over kernel/artifact.py's format
      theme.py              # the artifact's look: TOML in, one CSS override block out
      themes/               # the bundled themes, as the same files a user would write
      _text.py              # presentation helpers both renderers share (status prose, elision)
      cli.py                # `render` — mounted by the top-level cli
    fetch.py                # the whole network surface: one bounded GET over http(s), stdlib only
    cli.py                  # typer entry; owns discovery, sessions, the network, and the mounts
  skills/
    backdraft/SKILL.md            # front-walk
    backdraft-backfill/SKILL.md
    backdraft-artifact/SKILL.md   # reader
  spec/                     # normative prose format specs (portable; other impls read these)
    tokens.md  chunking.md  artifact.md
  tests/                    # pytest; kernel tests are pure/golden-file
```

Dependency rule: `kernel` imports nothing from the package. `registry` imports kernel. Everything else imports kernel + registry. `cli` imports everything. No sideways imports between extract/gate/bind/render.

## Token grammar (kernel/tokens.py; normative copy in spec/tokens.md)

```
token       = "bd:" slug ":" locator ":" hash
slug        = alnum-lower (alnum-lower | "-"){1,31}          ; assigned at ingest, unique per registry
locator     = page-loc | chunk-loc | cell-loc
page-loc    = "p" int                                        ; whole page
chunk-loc   = "p" int "." "c" int                            ; chunk ordinal within page, 1-based
cell-loc    = sheetref "!" cell [":" cell]                   ; cell or rectangular range
sheetref    = slug-sanitized sheet name (no ":" "!" whitespace)
cell        = column-letters row-int                         ; A1 notation, uppercase
hash        = lowercase-hex{4,8}                             ; prefix of snippet sha256
```

Examples: `bd:t12-audit:p8.c3:a7f3` · `bd:model:rent-roll!B10:9e2f` · `bd:t12-audit:p8:c114`

- Wire form in authored text: markdown link on the claim span — `[claim text](bd:...)`. Multiple citations: `[claim](bd:...;bd:...)` (`;`-separated, one grammar, no alternates).
- Hash: first 4 hex chars of the snippet's sha256 (see hashing); registry extends to 6/8 on collision within a document. Parser accepts 4–8.
- Slug assignment: derived from filename (kebab, truncated), deduped with `-2`, `-3`. Stable once assigned; stored, never recomputed.
- Reserved, not implemented in v0: derivation form `bd:calc(<expr over tokens>)`. Grammar TBD in spec/tokens.md; parsers must reject it cleanly, not crash.

## Hashing & normalization (kernel/hashing.py)

- `normalize(text)`: Unicode NFC → collapse every whitespace run to a single space → strip. Case preserved. This is the only normalization in the system; value-trace defines its own value equivalences separately.
- `snippet_hash(text) = sha256(normalize(text).encode()).hexdigest()`; token uses its prefix.
- Document identity: sha256 of file bytes.
- Extraction config hash: sha256 of canonical-JSON extractor config.

## Chunking (kernel/chunking.py; normative copy in spec/chunking.md)

Deterministic, pure: `chunk(page_text) -> [Chunk(ordinal, text, start, end)]`.

1. Split on blank lines: regex `\n\s*\n`.
2. Merge forward: any segment < 200 chars merges into the following segment (the last merges backward).
3. Split long: any segment > 2400 chars splits at the sentence boundary nearest each 1200-char multiple (sentence = terminal `.!?` + space + uppercase/digit start; no abbreviation table in v0 — splitting slightly wrong is fine, it only shifts chunk boundaries deterministically). A final piece under 200 chars merges backward, since merging ran before splitting and could not see it; a chunk is therefore under 200 chars only when it is the only chunk on its page.
4. Ordinals `c1..cN` in order. No per-page rebalancing, no chunk-count caps (rebalancing causes tail-loss bugs; deliberately avoided).

Anchor identity for a chunk: (extraction, page number, ordinal). `start`/`end` are char offsets into the page text — stored, enabling future span/region features.

## Registry (registry/schema.sql)

```sql
CREATE TABLE documents (
  id INTEGER PRIMARY KEY,
  slug TEXT NOT NULL UNIQUE,
  sha256 TEXT NOT NULL UNIQUE,
  path TEXT NOT NULL,            -- as given at ingest; informational
  filename TEXT NOT NULL,
  media_type TEXT NOT NULL,      -- 'pdf' | 'xlsx' | 'xls' | 'csv' | 'docx' | 'pptx' | 'image' | 'html' | 'text'
  created_at TEXT NOT NULL       -- ISO-8601 UTC, everywhere
);

CREATE TABLE document_meta (
  document_id INTEGER PRIMARY KEY REFERENCES documents(id),
  meta TEXT NOT NULL             -- JSON provenance; a fetched page carries {url, fetched_at}. Never citation identity.
);

CREATE TABLE extractions (
  id INTEGER PRIMARY KEY,
  document_id INTEGER NOT NULL REFERENCES documents(id),
  extractor TEXT NOT NULL,       -- 'pdf-text' | 'xlsx' | 'text' | 'vlm' | ...
  extractor_version TEXT NOT NULL,
  config_hash TEXT NOT NULL,
  deterministic INTEGER NOT NULL,
  is_current INTEGER NOT NULL DEFAULT 1,   -- one current per document (partial unique index)
  created_at TEXT NOT NULL
);

CREATE TABLE pages (
  id INTEGER PRIMARY KEY,
  extraction_id INTEGER NOT NULL REFERENCES extractions(id),
  number INTEGER NOT NULL,       -- 1-based
  kind TEXT NOT NULL,            -- 'page' | 'sheet'
  name TEXT,                     -- sheet name for kind='sheet'
  text TEXT NOT NULL,            -- the snapshot; receipts quote THIS
  summary TEXT,                  -- optional, for TOC
  UNIQUE (extraction_id, number)
);

CREATE TABLE anchors (
  id INTEGER PRIMARY KEY,
  extraction_id INTEGER NOT NULL REFERENCES extractions(id),
  page_number INTEGER NOT NULL,
  kind TEXT NOT NULL,            -- 'chunk' | 'cell' | 'range' | 'page'
  locator TEXT NOT NULL,         -- exactly the token's locator segment
  snippet TEXT NOT NULL,         -- verbatim from the snapshot (the receipt)
  snippet_sha256 TEXT NOT NULL,
  token TEXT NOT NULL,           -- full bd:... string
  start_off INTEGER, end_off INTEGER,
  created_at TEXT NOT NULL,
  UNIQUE (extraction_id, locator)
);
CREATE INDEX idx_anchors_token ON anchors(token);   -- token repeats across generations when content unchanged

CREATE TABLE sessions (
  id TEXT PRIMARY KEY,           -- caller-supplied or generated
  label TEXT,
  started_at TEXT NOT NULL
);

CREATE TABLE ledger (
  session_id TEXT NOT NULL REFERENCES sessions(id),
  anchor_id INTEGER NOT NULL REFERENCES anchors(id),
  shown_at TEXT NOT NULL,
  PRIMARY KEY (session_id, anchor_id)
);

CREATE TABLE bindings (
  id INTEGER PRIMARY KEY,
  doc_path TEXT NOT NULL,
  session_id TEXT,
  mode TEXT NOT NULL,            -- 'frontwalk' | 'backfill'
  report_json TEXT NOT NULL,     -- full BindReport
  bound_at TEXT NOT NULL
);

CREATE VIRTUAL TABLE search USING fts5(snippet, token UNINDEXED, slug UNINDEXED, page UNINDEXED);
```

Anchor creation is **eager at ingest** for chunks and cells-with-content (they're cheap rows and make search/read/bind all hit the same table) — but this is an implementation choice inside `Registry`, not a contract; the contract is that any token the gate ever emitted resolves.

Re-ingest semantics (the drift contract):
1. New extraction row; old one keeps its anchors.
2. For each new anchor, if an anchor with the same locator and same snippet_sha256 exists in the prior current extraction, it carries the **same token** (hash identical by construction).
3. Old extraction's `is_current` → 0. Bind resolves tokens against all generations: hit on current = `resolved`; hit only on non-current = `drifted` (report carries both snippets); no hit = `unresolved`.

## Extractor protocol (extract/base.py)

```python
@dataclass(frozen=True)
class ExtractedPage:
    number: int
    kind: Literal["page", "sheet"]
    text: str                      # sheets: markdown table with in-band [B10] refs
    name: str | None = None        # sheet name
    cells: list[CellValue] | None = None   # sheets: (ref, value) pairs for cell anchors + value-trace

class Extractor(Protocol):
    name: str
    version: str
    deterministic: bool
    def can_handle(self, path: Path, media_type: str) -> bool: ...
    def extract(self, path: Path, config: dict) -> Iterator[ExtractedPage]: ...
```

Registered in a plain dict; `ingest --extractor auto` picks the first `can_handle`, built-ins ordered `xlsx, xls, csv, docx, pptx, pdf-text, image, html, text` (an extractor whose optional extra is missing is skipped, not fatal). `vlm` is pdf→images→VLM per page, OpenAI-compatible client, model configurable; its deps ship by default and the backdraft-scoped key gates use. **For PDFs, `auto` prefers `vlm` when it is ready (importable, key configured)** (glossy layouts and info boxes extract badly from the text layer, and the snapshot is the receipt); otherwise it falls back to `pdf-text` and prints a one-line nudge naming the VLM option. An explicit `--extractor` always wins. The sheet representation (shared by xlsx, xls, csv): `Row | A | B...` header, `[B10] value` prefixes, dimension caps, inflated-sheet placeholder pages; cell values are never rounded, since the snapshot is the receipt a claim is traced against. `docx` synthesizes pages from heading sections (the document's smallest present outline level among Heading 1–2 splits; no headings → one page), so locators stay `pN.cM`. `pptx` is one page per slide, text floor only; ingest notes that slide visuals need the PDF-export path. `pdf-text` reconstructs paragraph breaks from line geometry before handing the page over, so the chunker's blank-line rule has something to fire on. `html` is one page for the whole document, named by its `<title>`: block elements end a block so the chunker's blank-line rule fires, `script`/`style`/`noscript`/`template`/`svg` are dropped whole, lists become `- `/`1. ` lines in a single block, and tables become pipe tables as `docx` renders them. It is a parse and not a readability heuristic — no boilerplate stripping, since a guess that changes between two versions of a site moves anchors. Decoding is a pure function of the bytes (BOM, then `<meta charset>`, then UTF-8 with replacement), so a saved page and a fetched one extract identically.

## Gate (gate/)

CLI-facing behavior contract:
- `read` with no args → document list (slug, filename, media, pages). `read <slug>` → TOC (page/sheet, name, summary-or-first-120-chars). `read <slug> p3` / `p3-5` / `rent-roll` → token-marked content.
- PDF pages render as chunks: `[bd:slug:p3.c1:a7f3]` on its own line above each chunk's text. Sheets render the markdown table as-is with a header line carrying the page token; cell tokens are NOT inlined per-cell (the `[B10]` refs are already in-band; bind composes `bd:slug:sheet!B10:hash` from the registry).
- `search "<query>"` → FTS5 over anchors; each result: token, slug, page, snippet. Results are minted (ledger-recorded) — a searched snippet is citable without a page read.
- Every emitted token is recorded to the ledger under the session (`--session` flag or `BACKDRAFT_SESSION` env; auto-created default session otherwise).
- Long pages: `--offset/--limit` on chars for PDFs; sheets paginate by rows, never mid-row, header row repeated.

## Bind (bind/binder.py)

`bind <authored.md> [--session S] [--check m1,m2] [--mode frontwalk|backfill]`

Pipeline: parse claims (kernel/claims.py: link spans with `bd:` hrefs) → resolve each citation → run enabled verifiers → rewrite doc (tokens → readable citations: `[claim](#cite-n)` + generated References section with doc name, locator, quote) → write sidecar + report → store binding row.

References carry **one numbered entry per distinct token**; claims citing the same anchor share its number and its quote appears once. This is a rendering rule only — the report and sidecar still carry every citation individually. Backfill's proposals search on a query derived from the claim's distinctive terms, not the raw sentence (which FTS5 cannot parse).

Citation statuses (closed set): `resolved` | `drifted` | `not_shown` (valid anchor, absent from session ledger; frontwalk mode only) | `unresolved` | `malformed`. Backfill mode adds claim-level `unmatched` for claims it couldn't anchor. Every non-`resolved` status is a report line item; bind never edits a claim silently and never drops a citation.

BindReport (kernel/model.py; serialized into sidecar and `bindings.report_json`):

```
BindReport { doc_path, mode, session_id?, bound_at,
             claims: [ { text, start, end,
                         citations: [ { token, status, anchor?: {slug, locator, snippet, snippet_sha256},
                                        drifted_from?: snippet,
                                        verdicts: [ {method, status: pass|fail|partial|skip, detail} ] } ] } ],
             summary: { claims, citations, by_status: {…}, by_method: {…} } }
```

## Verifier protocol (bind/verify/base.py)

```python
class Verifier(Protocol):
    method: str                                   # 'value-trace' | 'overlap' | 'recompute' | 'entail'
    def applies(self, claim: Claim, citation: Citation) -> bool: ...
    def verify(self, claim: Claim, citation: Citation, anchor: Anchor) -> Verdict: ...
```

All switches **default off** (`--check` opts in). Verdicts are recorded evidence, never gates; off ⇒ no verdict rows (schema shape unchanged). v0 implementations: `value-trace` (normalized number/date/name occurs in snippet — unit/scale/format equivalences live here), `overlap` (report-only span overlap; exact substring for quoted text), `recompute` (stub until `bd:calc` lands, registered but `applies() = False`), `entail` ([entail] extra; batched judge calls, tiny closed prompt).

## Render (render/)

- `render <authored.md> --to html` → single self-contained file: the bound doc, click/hover per claim → receipt card (quote, doc, locator, hashes, verdicts, drift diff if any), unresolved list rendered as a visible section, embedded JSON island with the full sidecar + `$format` string + legend (subtext pattern: the artifact teaches its own decoding). No external requests; no page images in v0.
- `--to footnotes` → plain markdown projection. `--to json` → sidecar alone.
- `--theme <name|file>` restyles the html artifact — a TOML file of colors, font stacks and heading treatment, resolved by `render/theme.py` into one CSS block emitted *after* the stylesheet (so an unthemed render is byte-identical to one from before themes existed). Precedence: `--theme` > project `.backdraft/theme.toml` > XDG `~/.config/backdraft/theme.toml` > built-in. `backdraft theme list` names the bundled themes and which file is in effect; `theme show <name|file>` prints one, validated, so redirecting `show default` bootstraps a commented starting file and `show ./mine.toml` lints one. Display only: no token, receipt or record moves, and layout is outside the allowlist.
- Artifact format string: `backdraft/artifact-v1` (prose spec in spec/artifact.md).

## CLI (cli.py — typer)

```
backdraft init                      # create .backdraft/, print status
backdraft ingest <sources...> [--extractor auto] [--slug S] [--config k=v]
                                    # a source is a path or an http(s) URL
backdraft ls | backdraft read ...   # gate, above
backdraft search "<query>" [--in slug]
backdraft bind <doc.md> [--session S] [--check ...] [--mode ...]
backdraft render <doc.md> [--to html|footnotes|json] [-o out] [--theme name|file]
backdraft theme [list|show <name|file>]
backdraft export [--out registry.json]
backdraft session [start|show] 
```

Registry discovery: nearest `.backdraft/` walking up from cwd, `BACKDRAFT_HOME` override. Exit codes: 0 clean; 1 usage/env error; 2 bind completed with non-resolved citations (so hooks can gate on it).

## Skills

- `backdraft` (front-walk): the substitution instruction — source documents are read only through `backdraft read`/`search`; write claims as `[text](bd:...)`; finish with `bind` + `render`; surface the report. ~One page.
- `backdraft-backfill`: ingest sources, then per claim in an existing doc: search → propose anchors → bind `--mode backfill`; unmatched claims presented as an open list, never silently unattributed.
- `backdraft-artifact`: teach a cold agent to read an artifact/sidecar (mostly redundant with the embedded legend, by design).

## Workstreams (builders)

W0 is sequential and first; W1–W4 then run in parallel against this spec; W5 needs the CLI to exist.

| WS | Scope | Depends on |
|---|---|---|
| **W0 kernel** | `kernel/*` complete + exhaustive tests (grammar round-trip, chunker golden files, hashing vectors, claims parsing) | — |
| **W1 store+extract** | `registry/*`, `extract/*` (pdf-text, xlsx, text; vlm extra), `ingest`/`ls`/`export` CLI | W0 |
| **W2 gate** | `gate/*`, `read`/`search`/`session` CLI, ledger recording | W0 (+ registry interface as spec'd) |
| **W3 bind** | `bind/*`, verifiers, `bind` CLI, exit-code contract | W0 (+ registry interface) |
| **W4 render** | `render/*`, artifact + legend, `render` CLI | W0 (sidecar schema) |
| **W5 skills+demo** | three SKILL.mds, demo corpus (1 PDF + 1 xlsx + walkthrough), README | W1–W4 CLI |

Integration invariants (every workstream's tests must respect): any token the gate emits binds `resolved` in the same session; re-ingest of identical bytes with a deterministic extractor changes nothing (same tokens, same hashes); the artifact renders with the registry deleted.

## Addendum A — Registry API (pinned for the parallel build)

`registry/store.py` exposes exactly this surface. W1 implements it; W2/W3 consume it and MUST NOT implement anything under `registry/`; their tests use a lightweight fake implementing these names.

```python
class Registry:
    @classmethod
    def open(cls, root: Path) -> "Registry": ...   # root contains .backdraft/; discovery lives in the CLI, not here
    def close(self) -> None: ...

    # write side (W1)
    def ingest(self, path: Path, *, extractor: str | None = None,
               slug: str | None = None, config: dict | None = None,
               url: str | None = None, fetched_at: str | None = None) -> Document: ...
        # runs extractor → new extraction generation, pages, eager anchors, FTS rows.
        # Token carry-over per re-ingest semantics; hash-collision extension steps TOKEN_HASH_LENGTHS.
        # Sheet names sanitized to the sheetref charset here, at ingest.
        # `url` marks `path` as a snapshot staged from the web: the document records the
        # URL as its path, carries {url, fetched_at} as meta, and matches an earlier
        # fetch by URL rather than by the temporary file. Identity stays the bytes.
        # The registry never fetches; `fetch.py` does, and the CLI calls it.

    # read side (W1 implements; W2/W3 consume)
    def documents(self) -> list[Document]: ...
    def document(self, slug: str) -> Document | None: ...
    def pages(self, slug: str) -> list[Page]: ...                    # current extraction only
    def page(self, slug: str, number: int) -> Page | None: ...
    def anchors_for_page(self, slug: str, number: int) -> list[Anchor]: ...
    def resolve(self, token: str) -> Resolution | None: ...
        # Resolution(anchor, current: bool). Hit on current generation → current=True.
        # Hit only on an older generation → that anchor with current=False (its snippet is
        # what the writer saw; bind maps current=False → status `drifted`). No hit → None.
    def search(self, query: str, *, slug: str | None = None,
               limit: int = 20) -> list[SearchHit]: ...              # SearchHit(anchor, slug, page_number)
        # Concretely a `SearchResults` (a list subclass) carrying `phrase_fallback: bool` —
        # True when the query did not parse as FTS5 and was retried as a quoted phrase.
        # Consumers may ignore the flag; the gate renders it as a note line.

    # ledger (W2 writes, W3 reads)
    def ensure_session(self, session_id: str | None, label: str | None = None) -> str: ...
    def record_shown(self, session_id: str, anchor_ids: Sequence[int]) -> None: ...
    def was_shown(self, session_id: str, token: str) -> bool: ...

    # page snapshots (v0.2: evidence for the artifact)
    def page_image(self, slug: str, number: int) -> PageImage | None: ...
        # The stored visual snapshot of a current-extraction page: what the VLM
        # extractor was shown (WebP q85), the local poppler render the CLI
        # captures after a text-layer PDF ingest, or a `snapshot-pages`
        # backfill. None for non-PDFs, and for PDFs ingested where poppler was
        # unavailable.
    def save_page_image(self, extraction_id: int, number: int, *, data: bytes,
                        format: str, width: int, height: int) -> None: ...
    def current_extraction_id(self, slug: str) -> int | None: ...    # for backfill tools

    # bind persistence (W3)
    def save_binding(self, *, doc_path: str, session_id: str | None,
                     mode: str, report_json: str) -> int: ...
        # report_json is the bare report WITHOUT the evidence block (heavy,
        # reproducible from the registry).
    def export_json(self) -> dict: ...
```

`Resolution` and `SearchHit` are small frozen dataclasses in `registry/store.py`; `SearchResults` is the `list[SearchHit]` subclass described above.

## Addendum B — CLI assembly

Top-level `cli.py` (W1) owns: typer app, registry discovery (nearest `.backdraft/` walking up from cwd; `BACKDRAFT_HOME` override), session resolution (`--session` flag > `BACKDRAFT_SESSION` env > default session), and the `init` / `ingest` / `ls` / `export` / `snapshot-pages` commands. After each ingest, `cli.py` captures page snapshots for any PDF whose extraction carries none — the text-layer path, since `vlm` stores its own — via `extract/snapshots.py` (poppler through pdf2image, `snapshot-pages`' internals). It sits outside the extractor so `pdf-text` stays deterministic regardless of whether poppler is installed, and it is best-effort: a `SnapshotError` leaves ingest at exit 0 with a one-line note naming `snapshot-pages` as the backfill. `cli.py` also owns the network for the same reason: an `ingest` argument with a scheme is fetched through `fetch.py` (stdlib `urllib`, http and https only, redirects followed, 32 MiB cap) and staged in a temporary file named for the content type the server declared — which is what selects the extractor — so extractors stay pure functions of bytes and the registry opens no sockets. It mounts sub-apps `gate/cli.py` (W2: `read`, `search`, `session`), `bind/cli.py` (W3: `bind`), `render/cli.py` (W4: `render`) — each exposes `app = typer.Typer()`; the top level mounts each inside a try/except ImportError so partial merges still run. The `backdraft` console script is declared by W1.
