# Roadmap

Sequenced intent. DESIGN.md records what was *decided*; this file records what
is *queued*, so tabling something is an act of writing it down here rather than
losing it. Items graduate by getting built and deleted.

## How the queue runs

The Now section is an ordered queue written for an implementing agent with no
session context: each item carries its intent, its shape, and its acceptance
test. The working agreement is one item at a time, top first, shipped complete
— code, tests, docs, and a DESIGN.md decision row where the item calls for one
— then deleted from this file in the same commit. Releases cut Friday, so an
item that lands mid-week waits on PyPI until the release; nothing ships
half-done to make a release. An item that turns out bigger than its sizing
gets split here, not stretched silently.

The cadence is daily and the runner is an agent: one item each morning Monday
through Thursday, landing as a direct commit to `main` — this repo does not
use pull requests, so a week of commits is the only review surface there is.

Friday builds nothing new. It reads that week's diff instead — duplication,
drift from the repo's own idioms, branches that landed untested, help text and
error messages that confuse, commands the docs describe wrongly — and lands
the fixes. Then the release, and only if something landed since the last tag:
the version moves in both `pyproject.toml` and `.claude-plugin/plugin.json`,
and publishing the GitHub release is what ships to PyPI. Then this section is
refilled with five items for the week ahead, drawn against the core — the four
verbs, the registry, the grammar, the artifact — and against where an agent
using backdraft actually stumbles. What the maintenance pass just found is the
best evidence available for what those five should be.

## Now

### 1. `backdraft show <token>`: the inverse of minting

**Intent.** An agent handed a token — out of someone's artifact, a half-written
draft, a colleague's message — cannot ask what it says. The gate mints tokens
and `bind` resolves them, but only as part of binding a whole document, so
there is no way to answer "what is `bd:t12-summary:p1.c4:410d`?" without
reconstructing the slug and selector by hand and re-reading a whole page.
`skills/backdraft-artifact/SKILL.md` names exactly this gap when it says only
one check needs the outside world.

**Shape.** A new command in `gate/cli.py` — `show <token> [<token> ...]` —
because this is the gate showing source text and must mint what it shows,
exactly as `read` and `search` do; an anchor shown here is an anchor the writer
may cite, and `not_shown` stays true by construction. Parse with
`kernel.tokens`, resolve through the same path `bind` uses rather than a second
implementation of what a token means, and print the closed status set bind
reports: `resolved` (locator + verbatim snippet), `drifted` (the snippet then
and the snippet now), `unresolved`, `malformed`. Output follows the gate's
line-oriented shape and ends with the usual bracketed next-step hint.

**Acceptance.** In `demo/`, `backdraft show bd:t12-summary:p1.c1:c2e8` prints
the snippet, and a subsequent `bind` of a document citing it reports `resolved`
rather than `not_shown` — that is the test that proves it minted. A
well-formed token naming nothing exits 1 saying so; a malformed one names the
grammar. Several tokens in one invocation print in argument order. `README.md`,
the docs page's command table, `site/llms.txt` and
`skills/backdraft-artifact/SKILL.md` gain it.

**Size.** Two days.

### 2. Ingest finishes the list, then reports what it could not read

**Intent.** `backdraft ingest a.md broken.pdf c.md` ingests `a.md`, fails on
`broken.pdf`, and never attempts `c.md`. The registry is left half-built, the
message names only the first failure, and nothing says which files landed and
which were never tried — so an agent ingesting a folder must re-run and infer
the state. This is the same warn-and-drop shape the page-snapshot capture
already avoids: it collects failures, names them, and lets the rest of the run
stand.

**Shape.** `ingest` in `cli.py`. Move the per-file work inside a try that
catches `BackdraftError` and records `(path, reason)` instead of propagating,
so the loop always reaches the end of the list. After the loop, print one line
per failure naming the file and the reason, grouped the way the snapshot note
already groups by reason, and exit 1 if anything failed — the exit code is
unchanged, only the coverage and the reporting improve. Re-ingest is idempotent
for deterministic extractors, so re-running after a fix costs nothing, and the
message should say that rather than leaving the agent to guess. Keep the guard
in `cli_context` as the only place `BackdraftError` becomes an exit code:
ingest catches per file and re-raises nothing, printing failures as data.

**Acceptance.** The three-file example above ingests `a.md` and `c.md`, prints
one failure line for `broken.pdf` naming why, and exits 1; `backdraft ls`
afterwards shows both good documents. A run where every file fails still exits
1 and names each. A run where none fail is byte-identical to today's output.
Tests for all three.

**Size.** One day.

### 3. The demo cites a web page, so the feature is visible

**Intent.** URL sources ship complete — `ingest` fetches and snapshots, the
registry keeps `url` and `fetched_at`, and as of 2026-08-06 the artifact links
back to the page with its fetch date. None of it appears at
`backdraft.dev/demo.html`, because both demo sources are local files
(`t12-summary.pdf`, `underwriting-model.xlsx`). The one artifact anybody
actually looks at does not show the capability, and the byte-identity test that
proved the change was safe is the same fact that keeps it invisible. A reader
evaluating backdraft cannot see that a web citation is a citation like any
other.

**Shape.** Add a third source to `demo/`: the Wikipedia article for the county
the property sits in, cited for market context — population, median household
income, the kind of external figure a screening memo genuinely leans on and
cannot get from a T12. Bridgeview Commons is fictional and says so in its own
first line, so give it a real county and let the memo name it; one new
paragraph under "The asset" or a short "Market" section, with one or two
claims. Cite Wikipedia's **permanent link** (`?oldid=<rev>`), not the bare
article URL: an article is edited constantly, a citation into the live URL
would report `drifted` within days, and a front-page demo that permanently
shows drift teaches that the tool is broken rather than that the source moved.
An immutable revision plus the rendered "as of" date is also what a careful
analyst cites. Write the tradeoff as a DESIGN row, naming the thing given up —
the demo no longer shows a live page changing under a citation, which is the
better story and belongs in a `drifted` walkthrough, not the shop window.

Practical notes for whoever builds this: `demo/.backdraft/` is gitignored, so
the fetch happens once on the implementer's machine and the snapshot then
travels in the local registry; `demo/generate_sources.py` builds the two
fixture files and is *not* where this goes, since the page is fetched rather
than generated. Re-bind and re-render (`bind memo.md --session s-bridgeview
--check value-trace,overlap`, then `render memo.md --to html`), and copy the
result over `site/demo.html` — the two are byte-identical by convention.
`demo/walkthrough.md` shows real CLI output and its `ls` and `bind` blocks both
move.

**Acceptance.** `backdraft.dev/demo.html` shows three sources, one of them a
clickable Wikipedia link with a fetch date, on both the resting rail and the
end-matter list; the claim citing it opens a card whose source line carries the
same link. `demo/walkthrough.md` matches what the commands now print. A re-bind
some weeks later still reports `resolved`, not `drifted` — that is the check
that the permanent link did its job.

**Size.** One day.

### 4. The gate names a fetched source by its page, not by its staging filename

**Intent.** A fetched page's `filename` is `q4-2025.html`, a name invented by
`fetch.filename_for` for a temporary file that no longer exists. The
2026-08-06 decision row ruled on this for the artifact — the URL *replaces* the
filename there, because "showing both would give a reader two names for one
thing and let the fictional one look authoritative" — but the same fictional
name is still what `backdraft read` prints in its document list, what its table
of contents headline prints, and what `ls` prints in column two. The gate is
where a writing agent actually lives, and there it learns nothing about
provenance at all: `skills/backdraft/SKILL.md` has to send it to `ls` for a
fact the surface it is already using could tell it. One rule, applied in one
place, is the fix.

**Shape.** `gate/reader.py`'s `render_documents` and `_document_headline`, plus
`cli.py`'s `ls` (which now shares the gate's page-count vocabulary through
`gate.unit` and should share this too). For a document whose `meta` carries a
`url`, show the origin in place of the filename, exactly as the artifact's
source list does. The gate's output is a contract — its module docstring says
"stable enough to diff" — so keep it line-oriented and keep the column
alignment: a URL is long, so put it on the row rather than in the aligned
filename column if alignment would collapse, and say which choice you made in
the docstring. `Document.meta` is already carried by `Registry.documents()` and
`Registry.document()`, so no registry change is needed. Do not touch the slug,
the token, or anything a citation resolves through — this is display, and the
2026-08-05 row's "provenance, never identity" governs.

**Acceptance.** In a registry holding one file and one fetched page, `backdraft
read` shows the file by its filename and the page by its URL; `backdraft read
<slug>` for the fetched page carries the URL in its headline; `backdraft ls`
matches. A registry of files prints exactly what it printed before — pin that
as a test, the way the artifact's byte-identity is pinned. `README.md`, the
docs page and `skills/backdraft/SKILL.md` drop the detour through `ls` for a
fact `read` now carries.

**Size.** Two days.

### 5. A fetched page's slug is decided, not defaulted

**Intent.** DESIGN.md's Open list has carried "slug assignment/collision rules"
since the first field trial, and URL sources sharpened it into a real failure:
`fetch.filename_for` takes the URL's last path segment, so
`https://a.example/reports/2025/index.html` and
`https://b.example/docs/index.html` both stage as `index.html` and become slugs
`index` and `index-2`. An agent then cites `bd:index-2:p1.c3:...` with no way to
tell which site that is, and a slug is the handle every token in every authored
document carries — it is stable once assigned, so a bad one is permanent. The
same collapse hits any site whose pages are `index.html`, `page`, `view`, or a
bare numeric id.

**Shape.** `fetch.filename_for`, and a decision row that closes the Open
question for files and URLs together. For a URL, build the stem from enough of
the address to distinguish it — the host plus the last meaningful path segment
is the obvious candidate, with the registry's existing `slug_for` slugification
doing the rest — and keep `_dedupe`'s `-2` as the collision *backstop* rather
than the normal outcome. `store._assign_slug` and `_dedupe` do not need to
change; this is about giving them a stem worth deduping. Note the constraint
that makes this delicate: continuity across a re-fetch is matched on the URL
(see `_find_document`), not on the slug, so changing the stem rule does not
break an existing registry's documents — but it does mean two registries built
on either side of this change disagree about a page's slug, which is a
compatibility statement the decision row has to make out loud.

**Acceptance.** The two `index.html` URLs above ingest as two slugs that each
name their site. `https://example.com/reports/q4-2025` still ingests as
`q4-2025` — the common case does not get uglier to fix the collision case. A
URL with an empty path still falls back to the host. Tests for each, plus one
that two pages colliding even after the new rule still dedupe rather than
error. DESIGN.md gains the decision row and the Open list loses the line.

**Size.** Two days.

### 6. Ingest says what it did and what it got

**Intent.** Two things `ingest` knows and does not say. First, it prints the
same line whether it created a document, created a *new generation* of one
whose bytes changed, or did nothing at all because the bytes and config were
identical — so an agent re-ingesting after a fix cannot tell whether anything
happened, and the moment a new generation appears is exactly the moment
existing bindings may start reporting `drifted`. Second, it never says how much
text came out. `skills/backdraft/SKILL.md` instructs the agent that a
JavaScript-rendered page or one behind a login "will come back thin or empty,
and if it does, say so to the user rather than citing the shell of it" — and
gives it no signal to notice that with. A login wall extracts as a few dozen
characters, exits 0, and prints `1 page` like any success. The same silence
covers a scanned PDF with no text layer.

**Shape.** `ingest` in `cli.py`, output only — no registry or format change.
`Registry.ingest` already distinguishes the three outcomes internally
(`_find_document`, `_is_noop`, `_upsert_document`); surface which one happened
rather than re-deriving it in the CLI, which may mean returning it alongside
the `Document` or exposing it on the returned value. Print the extracted
character count beside the page count, and when it falls under a threshold the
module declares as a named constant, add one line naming the likely cause and
what to do — the shape the poppler and `pdf-text` notes already use, which is a
note at exit 0 and never a failure, because a thin page is still a real
snapshot and failures here are data. A new generation gets its own line saying
that citations into the previous one may now report `drifted`, and that `bind`
is what will say so.

**Acceptance.** Ingesting a file twice unchanged says so the second time;
editing it and re-ingesting says a new generation was made and names drift;
both still exit 0. A near-empty HTML file ingests, exits 0, and prints the thin
-source note; a normal source does not. `backdraft ingest` on a fresh document
prints what it prints today plus the character count. Tests for all five
branches. `demo/walkthrough.md`, `README.md` and `site/docs.html` show the real
new output, and `skills/backdraft/SKILL.md` points at the note instead of
asking the agent to judge thinness unaided.

**Size.** Two days.

### 7. `backdraft verify <artifact>`: checking a receipt without the registry

**Intent.** `skills/backdraft-artifact/SKILL.md` exists because there is no
command: it walks an agent through opening a `.backdraft.json` or
`.backdraft.html`, recomputing each `snippet_sha256`, and reporting claim
statuses by hand. That is a deterministic check over a self-describing file,
which is precisely the kind of thing that should not be a prose procedure an
agent re-implements every time — and doing it by hand is how a recipient's
check ends up weaker than the producer's. The artifact is the product; nothing in the
tool reads one back.

**Shape.** A new command in `render/cli.py` (which already owns the artifact's
reader half through `sidecar.read`), taking the artifact or its sidecar.
Two tiers, and the output must be explicit about which ran. Tier one needs
nothing but the file: parse it against `kernel/artifact.py`'s format, recompute
every `snippet_sha256` from the snippet the file carries, and confirm the
`$format` and the claim/citation counts — this is the check a recipient with
only the file can make, and it catches an edited artifact. Tier two runs only
when a registry is discoverable: re-resolve each token through the same path
`bind` uses and report the closed status set. Exit 0 when everything checked
passed, 1 on a usage error, and — matching `bind` — 2 when something did not
verify, so a hook can gate on it. Read-only: it opens no session and mints
nothing, which is what distinguishes it from `read` and from the queued
`backdraft show <token>` — a number here shifts every time an item lands, so
name the item, not its position.

**Acceptance.** `backdraft verify demo/memo.backdraft.html` from outside
`demo/` reports tier one passing and says plainly that no registry was found,
exiting 0. From inside `demo/` it also re-resolves and reports the one
unresolved citation, exiting 2. A file with one snippet byte changed fails by
naming the claim and the hash that did not match. A file that is not an
artifact exits 1 saying so. `skills/backdraft-artifact/SKILL.md` is rewritten
around the command, keeping the prose procedure only as the fallback for an
agent that has no backdraft install.

**Size.** Three days.

### 8. `spec/registry.md`: the export format is normative, or it is not a format

**Intent.** `backdraft export` writes `"$format": "backdraft/registry-v1"`, a
version string that promises a specification and does not have one. `spec/`
holds `artifact.md`, `tokens.md` and `chunking.md`, and the repo's own rule is
that another implementation reads those and nothing else — the export is the
only declared format outside that set. It is also the only complete, portable
representation of a registry, so it is what a second implementation, a
migration, or an audit would read. The gap is not theoretical: the 2026-08-05
work added a conditional `meta` key to every exported document, a format change
to a format with nothing to change.

**Shape.** A new `spec/registry.md` in the voice of `spec/artifact.md`:
normative prose, MUST/OPTIONAL where it means them, and written to be readable
without the code. Cover the top-level shape, the document entry including the
`meta` key and its `url`/`fetched_at` (OPTIONAL, present only for a fetched
source — the same conditional the artifact spec already states, for the same
compatibility reason), every extraction generation with `is_current`, pages
and cells, and anchors with their receipts. State what identity is and what it
is not, matching the concept table in `SPEC.md`. Say what a conforming reader
must do with a key it does not recognize. Pin it the way the artifact format is
pinned: a golden-file test over the demo registry's export, so the next
conditional key is a test failure rather than an undocumented change.

**Acceptance.** `spec/registry.md` describes every key `Registry.export`
actually emits — check that mechanically, with a test that walks the exported
JSON and fails on a key the spec does not name. `SPEC.md`'s file map and
`README.md`'s spec list gain it. Exporting the demo registry and reading only
the spec is enough to say what each field means.

**Size.** Two days.

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
  a decision row before code. The web-page half of this item shipped
  2026-08-05; `document_meta` is where an email's provenance would land.
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
