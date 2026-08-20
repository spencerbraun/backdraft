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

### 1. `backdraft verify <artifact>`: checking a receipt without the registry

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
nothing, which is what distinguishes it from `read` and from `backdraft show`
(landed 2026-08-12), whose whole point is that showing mints — an audit must not
make its subject citable.

**Acceptance.** `backdraft verify demo/memo.backdraft.html` from outside
`demo/` reports tier one passing and says plainly that no registry was found,
exiting 0. From inside `demo/` it also re-resolves and reports the one
unresolved citation, exiting 2. A file with one snippet byte changed fails by
naming the claim and the hash that did not match. A file that is not an
artifact exits 1 saying so. `skills/backdraft-artifact/SKILL.md` is rewritten
around the command, keeping the prose procedure only as the fallback for an
agent that has no backdraft install.

**Size.** Three days.

### 2. `spec/registry.md`: the export format is normative, or it is not a format

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

### 3. `search` says when it stopped short

**Intent.** `backdraft search "the"` prints `20 results for "the"` whether there
are twenty or two hundred: `--limit` defaults to 20, and the count line reports
the size of the *page*, not the size of the answer. Search is the discovery
surface an agent leans on hardest — it is how a claim finds its evidence — and
an agent that reads "20 results" reasonably concludes it has seen all of them,
picks the best of twenty, and never learns that the sentence it actually needed
was twenty-first. `--limit 2` says `2 results` with no hint anything was cut.
This is the silent-cap failure the repo rejects everywhere else: `read`
paginates and closes with `[Showing 0-464 of 3115 chars. Continue with: ...]`,
which is exactly the shape missing here.

**Shape.** `registry.store.Registry.search` and `gate/searcher.py`. The registry
needs to know the total before it truncates — count the FTS matches and carry
the number alongside the hits, on `SearchResults`, which is already a list
subclass carrying `phrase_fallback` for precisely this kind of out-of-band fact
(SPEC Addendum A pins that shape, so extending it is a spec change and Addendum
A must say so). Then `render_search` reports honestly: an uncapped run keeps the
line it prints today, byte for byte, because most runs are uncapped and their
output is a contract; a capped run says how many matched and how to see the
rest, in `read`'s continuation-hint voice and naming the real flag. Do not add
an offset to `search` for this — `--limit` already exists, the hint can name it,
and paging a relevance-ordered list is a different design question. Keep the
count cheap: a `COUNT(*)` over the same FTS query, not a fetch-everything-and-
slice, since a registry of a hundred documents is the case that matters.

**Acceptance.** In a registry with more matches than the limit, `backdraft
search <q> --limit 2` names the true total and tells the reader how to widen it;
with fewer matches than the limit, the output is byte-identical to what it
prints today — pin that as a test, the way the artifact's byte-identity is
pinned. `--in <slug>` scoping counts within the scope, not across the registry.
`site/llms.txt` and `skills/backdraft/SKILL.md` tell the agent to widen rather
than settle when the line says it was capped.

**Size.** One day.

### 4. The bind report says why a verifier skipped

**Intent.** A bind report prints `overlap: pass 11, skip 4` and stops. Four
citations were not checked and the report does not say why, so a reader cannot
tell a benign skip from a hole in the verification — and the reason exists
already: the record's verdicts carry `"detail": "wording overlap does not apply
to a single cell"` for every one of those four. This is the same gap the
2026-08-13 line-item work closed one level up, where the token was printed and
the claim it sat on was not: the record says it, nested, and the line a person
reads does not. `DESIGN.md` holds that verifiers are evidence and never gate,
which makes the reason *more* important, not less — a skip nobody can interpret
is the one way a non-gating verifier can still mislead.

**Shape.** `bind/cli.py`'s `_print_report`, output only; no verifier, record or
artifact change. Skips of one method cluster on one reason, so group by reason
the way `ingest`'s snapshot note groups (`cli.py`'s `unsnapshot` dict) rather
than listing one line per citation the way its unread-source report does — the
distinction is written down in the 2026-08-13 decision row and this is the
grouping case. Keep it under the method's existing summary line and keep it one
line per distinct reason. `fail` is not involved: a skip is not a failure, the
exit code does not move, and a run whose verifiers all passed prints exactly
what it prints today.

**Acceptance.** Binding the demo (`bind memo.md --session s-bridgeview --check
value-trace,overlap`) prints the four skips' reason under the `overlap` line;
exit code is still 2 for the unresolved citation and would be 0 without it. A
run with no skips is byte-identical to today's, pinned as a test. A method
skipping for two different reasons prints two lines. `demo/walkthrough.md`'s
bind blocks, `README.md`'s, and `skills/backdraft/SKILL.md`'s show the real new
output, and the skill says a skip with a reason is not a hole to fix.

**Size.** One day.

### 5. `session show` says what the ledger holds

**Intent.** The ledger is the mechanism the design rests on — the set of citable
tokens is exactly the set the gate emitted — and nothing reads it back.
`backdraft session show` prints `session default  (from default)` and stops, so
an agent cannot answer "have I read enough to write this yet?" except by binding
and reading the `not_shown` count, which means finding out after the draft
exists. Worse, the default session is documented as stable across invocations
*so reads accumulate*, which means an agent that never exported
`BACKDRAFT_SESSION` has its `not_shown` judged against everything ever read in
that registry by any previous run on any document — a real weakening of the
system's strongest check, currently invisible at every surface. `skills/
backdraft/SKILL.md` tells the agent to start a named session and calls it
optional; nothing shows it what optional costs.

**Shape.** `gate/cli.py`'s `session show` and `gate/reader.py` (the ledger is
the gate's, and `session start` already lives there). Report what the session
holds: how many anchors, across how many documents, and per document a slug and
a count — read off the `shown` rows the registry already keeps, which may need
one accessor on `Registry` beside `was_shown` (SPEC Addendum A, so state it
there). When the session is the default one, say plainly that it accumulates
across runs and that a named session is what makes `not_shown` mean "this
draft's author saw it" — the same voice the `--config` and poppler notes use, a
note at exit 0 and never a failure. An empty session says so and names
`backdraft read` rather than printing a bare zero.

**Acceptance.** After reading two pages of one document and searching another,
`backdraft session show` names both documents with their counts and a total; on
a fresh registry it says the session is empty and what to run. Running under
`BACKDRAFT_SESSION=s-x` shows `s-x` and no accumulation note; running with
nothing set shows the default and the note. `README.md`, `site/docs.html`,
`site/llms.txt` and `skills/backdraft/SKILL.md` point at it as the way to check
coverage before binding, and the skill's "optional" for `session start` becomes
a stated tradeoff.

**Size.** Two days.

### 6. An unreadable source says what to do, not what errno it was

**Intent.** `ingest` now finishes its list and names each failure (2026-08-13),
which turned the reason string into something a calling agent actually reads —
and the reason is Python. A directory says `cannot read adir: [Errno 21] Is a
directory: 'adir'`; a locked file says `[Errno 13] Permission denied`; a missing
one says `[Errno 2] No such file or directory`. Each names the source three
times, leaks an errno an agent must not have to know, and — the real cost —
says nothing about the fix, though the fix differs completely between the three
and is obvious in each case. A directory means "name the files inside it, or
glob"; the repo's own rule is that an error says what went wrong *and* what to
do next, and this is the boundary where an unattended agent meets it most.

**Shape.** Wherever the read failure is raised on the ingest path — `cli.py`'s
`_staged`, `registry/store.py`'s ingest read, and `fetch.py` for the URL half —
turn the `OSError` into a `BackdraftError` whose message is written for the
caller: what the source is, why it could not be read, what to do. Map the causes
worth distinguishing (missing, a directory, unreadable, empty, and the fetch
side's own) and let anything unmapped keep the underlying text rather than
guessing — an unknown cause reported plainly beats a wrong suggestion. Say the
source once: the `!` line already leads with it, so the reason should not repeat
it. This is *not* the queued "Ingest says what it did and what it got" item, which is about what a successful ingest says
(no-op, new generation, character count); this is the failure half, and the two
should not be merged.

**Acceptance.** `backdraft ingest <a-directory>` names the directory once and
says to pass the files inside it or a glob; a missing file, an unreadable file
and an empty file each get their own reason and their own next step; none of the
four prints `[Errno`. A URL that 404s keeps saying so. The count line and the
closing re-run line are unchanged, and the clean-run stdout byte-identity test
from 2026-08-13 still passes. `site/llms.txt` says the failure reasons are
actionable so an agent surfaces them to the user rather than paraphrasing.

**Size.** One day.

### 7. A registry can forget a source

**Intent.** Ingest is one-way. An agent working unattended over a folder — which
is now the normal case, since `ingest` finishes its list — will ingest something
it should not have: a scratch copy, a duplicate under two names, a file the user
did not mean to include. Nothing removes it. It stays in `backdraft read`'s list
forever, its anchors stay in `search` competing with the real source, and an
agent picking evidence can cite the wrong copy without anything looking wrong.
The only recovery is deleting `.backdraft/` and starting over, which throws away
every other document and the whole ledger.

**Shape.** Withdraw, do not delete — a new `backdraft forget <slug>` in `cli.py`
beside `ingest`, and the storage half in `registry/store.py`. A withdrawn
document disappears from `documents()`, from the gate's list and table of
contents, and from `search`; its anchors keep resolving, because a token already
written into somebody's draft or artifact must not silently become `unresolved`
— that is the failure mode this whole system exists to prevent, and the
2026-08-05 "provenance, never identity" row governs. So `Registry.resolve` still
finds it and `show` and `bind` report it, with the closed status set gaining
nothing: reuse `unresolved` and let the *reason* say withdrawn, since adding a
status is an artifact-format change and this does not need one. Storage is a
flag on `documents`, not a DELETE, for the same reason. Require confirmation or
an explicit flag, since this is the one command that takes something away.
Interacts with the queued `spec/registry.md` item: whichever lands second
documents the flag in the export.

**Acceptance.** Ingest two documents, `forget` one: `read`, `ls` and `search`
show only the other; a token minted from the forgotten one still resolves
through `backdraft show`, saying it was withdrawn and when; `bind` on a document
citing it reports it and does not crash. `forget` on an unknown slug exits 1
naming the known ones. Re-ingesting the same file after forgetting it brings it
back as a new generation of the same document rather than a second slug — pin
that, it is the case that decides whether the flag was the right storage.
`README.md`, `site/docs.html`, `site/llms.txt` and `SPEC.md`'s command list gain
it, and it earns a DESIGN.md row: withdraw-not-delete, with the tradeoff that a
registry never actually shrinks.

**Size.** Three days.

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
