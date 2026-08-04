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

### 1. URL sources: capture and link back

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

### 2. Bind's failure lines name the claim, not just the token

**Intent.** Exit 2 tells a calling agent that a citation did not resolve and
prints the token: `! unresolved: bd:t12-summary:p4.c1:1a2b`. It does not say
which sentence that token was on. `skills/backdraft/SKILL.md` then instructs
the agent to "tell the user which claim it belongs to" — the one fact the
report withheld — so the agent's next move is to grep its own document for a
token string. Meanwhile the `! unmatched:` line, three lines below, already
prints its claim text. The two line-items should carry the same weight.

**Shape.** `_print_report` in `bind/cli.py`, CLI output only — the record JSON
is a pinned format and already carries the claim/citation nesting, so nothing
in `spec/artifact.md` moves. `BindReport.claims` holds each claim's `text`,
`start` and `end` alongside its citations, so the mapping from a reported
citation back to its claim exists in memory; report the citation line as the
token, then the claim text truncated the way the `unmatched` line already
truncates it (80 chars), then the offset. Repeats matter here: the same token
cited on four claims currently prints four identical lines, which reads as four
problems — print one line per (token, claim) pair, which is what the offset
makes legible. Applies to every non-resolved status, `not_shown` and `drifted`
included, not only `unresolved`.

**Acceptance.** In `demo/`, `backdraft bind memo.md --session s-bridgeview
--check value-trace,overlap` prints the unresolved line with the replacement-
reserve claim text and its offset on it. A bind whose session was never read
into prints one line per distinct claim rather than one per citation
occurrence. Tests cover `unresolved`, `not_shown`, `drifted` and `malformed`.
Every doc that shows a bind report — `README.md`, `demo/walkthrough.md`,
`site/llms.txt`, `skills/backdraft/SKILL.md`,
`skills/backdraft-backfill/SKILL.md` — is updated to the real new output.

**Size.** One day.

### 3. `--config` keys are declared, validated, and listed

**Intent.** `backdraft ingest x.pdf --config dpy=300` exits 0, ingests, and
does nothing about the typo. No output names the mistake, and nothing anywhere
— help, docs, `llms.txt` — lists what keys exist; today the only way to learn
`dpi`, `model`, `base_url`, `api_key`, `snapshot_quality` or
`snapshot_max_height` is to read `extract/vlm.py` and `extract/snapshots.py`.
This repo's rule is that failures are data and never warn-and-drop, and the
config boundary is where that rule does not hold.

**Shape.** Give the `Extractor` protocol in `extract/base.py` a
`config_keys: Mapping[str, str]` (key → one-line meaning), defaulting to empty
so no extractor is forced to declare. `vlm` declares its provider and retry
keys; the page-render keys (`dpi`, `snapshot_quality`, `snapshot_max_height`)
are declared once by `extract/snapshots.py`, which already owns them, and are
accepted for every PDF path since both rasterize. `ingest` validates the parsed
config against the selected extractor's declared set *after* selection, since
`auto` picks per file, and raises `UsageError` in the shape the unknown-name
errors already use: `unknown config key 'dpy' for pdf-text; known: dpi,
snapshot_max_height, snapshot_quality`. A key that is valid for one extractor
and not another must fail only where it does not apply.

**Acceptance.** The typo above exits 1 and names both the key and the valid
ones; `--config dpi=300` still works on both the `vlm` and the text-layer path;
`--config model=...` fails on `pdf-text` and passes on `vlm`. Tests for each
branch, including a declaration-free extractor rejecting any key. The docs
page's `ingest` row and `site/llms.txt` list the keys.

**Size.** Two days.

### 4. `backdraft show <token>`: the inverse of minting

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

### 5. Ingest finishes the list, then reports what it could not read

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
