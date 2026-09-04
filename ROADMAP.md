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

### 1. A web page has a name, and `read` shows it the navigation menu instead

**Intent.** `backdraft read franklin-county` — the demo's own web source —
prints `p1  Franklin County, Ohio - Wikipedia  Jump to content Main menu Main
menu move to sidebar hide Navigation - Main page - Contents - Current events -
Random art...`. The table-of-contents line is the one surface that tells an
agent what is on a page before it spends context reading it, and for every web
source it is site chrome. The page's real name is sitting in the extracted text
and in the markup's `<title>`, unused: a fetched page ingested without `--slug`
also titles itself `En Wikipedia Org Index` in the artifact's source list,
because `render/html/text.source_title` falls back to the slug and title-cases
it. Two surfaces need one fact nothing captures. Separately, an HTML source is
a single page, so its table of contents is that one line and does no
navigating at all — for a 34,000-character article the citable unit is the
chunk and nothing lists the chunks.

**Shape.** Capture the fact once, at extraction: `extract/html.py` already
parses the markup, so the document's `<title>` becomes page or document meta
there, and everything downstream reads it instead of guessing. Then
`gate/reader.py`'s TOC preview (`TOC_PREVIEW_CHARS`, `_preview`) prefers it,
and `render/html/text.source_title` prefers it over the slug fallback for a
document that has one. For the single-page case, `render_toc` lists the page's
chunks with their opening words, so a one-page source's table of contents is
one. **This is display only and must stay that way**: no chunk boundary moves,
no anchor moves, no token changes, and the slug is not derived from the title —
that is the admissibility argument the 2026-08-20 thin-source note made, and
this row must make it again, because the neighbouring rule ("no boilerplate
stripping: a heuristic that changes its mind moves anchors") is about
extraction and is not being touched. A page with no `<title>`, and every
non-HTML source, keeps exactly what it prints today.

**Acceptance.** In `demo/`, `backdraft read franklin-county` names the county
rather than "Jump to content", and lists the page's chunks. `backdraft read
t12-summary` and `backdraft read underwriting-model` are byte-identical to
today's — pin both. `backdraft bind memo.md --session s-bridgeview --check
value-trace,overlap` still reports 17 resolved and the same one unresolved,
with the same tokens: mint them before and after and diff. An HTML fixture with
no `<title>` falls back to what it prints now. `demo/walkthrough.md`'s read
blocks and `README.md`'s show the real output. DESIGN row.

**Size.** Three days.

### 2. A page read has no budget and no closing line

**Intent.** `backdraft read franklin-county p1` prints 36,442 characters and
stops, with nothing to say how much that was or whether it was all of it — it
ends mid-navigation on `49 languages Add topic`, which reads exactly like a
truncation and is not one. `--limit` defaults to "all of them", so the
continuation hint this repo is proud of — `[Showing 0-464 of 3115 chars.
Continue with: …]` — only ever appears to a caller who already knew to pass
`--limit`. The gate is the one surface an agent is *required* to use, which
makes the default the case that matters: one `read` can spend a large fraction
of a context window with no warning, and the agent cannot tell a complete page
from a cut one. `search` caps at 20 by default; `read` caps at nothing. This is
the same silent-cap family as the queued `search` item, from the other end — an
uncapped read that looks capped, rather than a capped search that looks
complete.

**Shape.** `gate/reader.py`'s page rendering and `gate/cli.py`'s `--limit`. The
decision to make and write down is a default budget versus staying unbounded
and always closing with the size and the continuation line; prefer whichever
keeps a small page byte-identical, since most pages are small and their output
is a contract. Whatever lands, a read that shows part of a page must close by
naming the exact command that continues it, as the existing hint does. One
constraint to state and test rather than discover: the window slices by
characters and a chunk token stands above its chunk, so a cut must not leave a
token over a chunk the reader only half received — either the window respects
chunk boundaries or the closing line says the last chunk is partial. Do not add
an offset story to `search` here; that is the queued item's ground.

**Acceptance.** `backdraft read t12-summary p1` in `demo/` is byte-identical to
what it prints today — pin it. `backdraft read franklin-county p1` closes by
saying how much of the page it showed and how to see the rest, and running the
command it names continues where it stopped. No read output ever shows a token
above a chunk it did not finish. `demo/walkthrough.md`, `README.md`,
`site/llms.txt` and `skills/backdraft/SKILL.md` show the real output and tell
the agent to continue rather than assume it saw the page. DESIGN row.

**Size.** Two days.

### 3. The thin-source signal exists only in the ingest that printed it

**Intent.** 2026-08-20 gave `ingest` a character count and a `note: little text
extracted` naming the likely cause — the signal that a source is a shell and
must not be cited. Both are printed once and then gone: nothing stores the
count, and `ls`, the gate's document list and a document's table of contents
say nothing about it. The agent that writes is usually not the process that
ingested — the skill says to ingest everything up front and then read, and a
registry travels with the project folder — so the one signal that matters is
the one an agent is least likely to be present for. Off `backdraft read`'s
list, a 34,000-character article and a 60-character login wall are the same
row.

**Shape.** The count is derivable from the current extraction
(`sum(len(page.text))`), so this is a reporting change rather than a storage
one unless measurement says otherwise. One owner, shared between `cli.py`'s
ingest line and `gate/reader.py`'s list and headline, the way `unit` and
`source_name` already are — the point of this item is that three surfaces give
one answer, so a second implementation of the count would defeat it. Display
only, as the ingest note is: no token, anchor or status derives from it. Hold
the byte-identity rule the source-naming work established — a registry of
ordinary sources must not gain a column for this, so mark only the sources that
are thin rather than annotating every row.

**Acceptance.** Ingest a login-wall HTML file beside a real source: `backdraft
read` and `backdraft ls` mark the thin one and say nothing new about the other,
and `backdraft read <thin-slug>` says it in the headline too. A registry with
no thin source prints what it prints today, byte for byte — pinned, including
`demo/`'s three sources. `THIN_SOURCE_CHARS` is read from one place.
`skills/backdraft/SKILL.md` and `site/llms.txt` tell the agent that the
document list is where it learns this, not only the ingest it may not have run.

**Size.** Two days.

### 4. What a URL will be called, before the answer is permanent

**Intent.** Three docs now tell an agent to pass `--slug` when it ingests a URL,
because a slug is permanent once tokens carry it and the default may name a
site rather than a page. None of them lets the agent find out what the default
would be. `fetch.filename_for` settles the answer from the address alone,
before any bytes exist — that is the 2026-08-19 row's own words — so the
question is cheap and answerable, and today the only way to ask it is to ingest
and live with the result. An agent that guesses wrong has written a name into
every token of the document, and the fix is re-ingesting under a new slug and
rewriting the draft.

**Shape.** Small and read-only. The natural home is beside the thing it
predicts: a flag on `ingest` that resolves each source to the slug and media
type it would take and prints them without fetching, writing or minting
anything, or a sibling command if a flag on a writing verb reads badly — pick
one and say why in the DESIGN row, since "a verb that does not do its verb" is
the objection to answer. For a URL the answer comes from `fetch.filename_for`
plus `registry.slug_for` and needs no network; the media type is the honest
gap, because only the served content type settles it, and the output must say
so rather than guessing. For a file, both are already knowable. Existing
collisions matter: a slug already taken must be reported as taken, since that is
what turns a predicted `index` into a real `index-2`.

**Acceptance.** Against `demo/`, asking about
`https://en.wikipedia.org/w/index.php?title=Franklin_County,_Ohio&oldid=1367935775`
prints `en-wikipedia-org-index` and does not create a document, open a socket,
or touch the ledger — check the registry's document count and `ls` before and
after. Asking about a path prints the slug the file would take. Asking about a
source whose slug is already in the registry says so. `README.md`,
`site/docs.html`, `site/llms.txt` and `skills/backdraft/SKILL.md` name it where
they currently say "pass `--slug`", so the advice comes with the way to check
it.

**Size.** One day.

### 5. A calling agent parses prose to find out what happened

**Intent.** `bind` and `verify` are the two commands whose *output* is the
product — the exit code says clean or not, and everything actionable is in the
lines. An agent is the primary caller of both, and today it must scrape them:
`! unresolved: <token> — <reason> — <claim words> @<start>`, or `! receipt:`,
or `receipts: 16 of 17 hold`. Every wording fix this repo lands — and it lands
them often, four this week alone — is a silent breaking change for anything
that scraped the last wording. Worse, the shapes collide: `verify` exits 2 both
for a receipt that did not hold, which means the file was edited, and for a
source that moved since binding, which means the file is honest and stale. Those
demand opposite responses and the exit code cannot tell them apart, so the agent
is pushed back to the prose to find out which it got.

**Shape.** `--json` on `bind` and on `verify`, writing one object to stdout and
nothing else, with the human report suppressed. For `bind` the object already
exists — it is the sidecar payload `render.sidecar.dumps` writes, which the
artifact spec already governs — so this is a flag choosing the existing
serialization, not a new format. `verify` needs a small one of its own, and it
belongs in `spec/artifact.md` § Checking an artifact beside the checks it
reports: the format string, the two tiers with a ran/not-ran flag each, per
citation the token and what failed, and a `findings` list whose entries carry a
kind (`receipt`, `source`, `recount`) so the two exit-2 causes are separable
without reading a sentence. Exit codes do not move — the codes are the contract
and a third one would break every hook written against 0/1/2; the distinction
lives in the payload, which is exactly what the payload is for. `--json` with
`-o -` on `render` is the precedent for writing structured output to stdout.

**Acceptance.** `backdraft bind memo.md --json` in `demo/` emits a single JSON
object, exits 2 as it does today, and prints no report lines; the object parses
and equals the sidecar it wrote. `backdraft verify memo.backdraft.html --json`
emits an object naming both tiers, and in `demo/` its `findings` carries one
entry of kind `source` and none of kind `receipt`; with a snippet edited by one
byte it carries a `receipt` entry. A test asserts the two kinds are
distinguishable without any string matching on prose. `spec/artifact.md`,
`site/llms.txt` and `skills/backdraft/SKILL.md` and
`skills/backdraft-artifact/SKILL.md` tell the agent to prefer `--json` and to
relay the human report to the user.

**Size.** Two to three days.

### 6. An artifact you were sent cannot be checked against a registry you have

**Intent.** `verify`'s second tier runs only where a `.backdraft/` is
discoverable from cwd, and the reason is good: an artifact is a file people
forward, so the folder it landed in says nothing about which registry produced
it (2026-08-24). But the rule leaves no way to say what the agent often knows —
"this artifact came out of *that* project" — so the only route to a source check
is to copy the artifact into the project directory first, which is a filesystem
move performed to change a discovery result. An agent auditing several
artifacts against one registry does this repeatedly, and a reviewer holding a
colleague's artifact next to a shared checkout cannot do it at all without
write access to that checkout.

**Shape.** One option on `verify`: a path naming the project root or the
`.backdraft` directory itself, accepted in both forms exactly as
`cli_context.find_root` accepts `BACKDRAFT_HOME`, and bypassing the cwd walk
when given. It answers rather than violates the 2026-08-24 objection, and the
DESIGN row must say so: discovery stays refusal-by-default and the flag is the
recipient asserting a link the tool must never infer, which is the same shape
as `--slug` overruling a derived name. The `sources:` line names the registry it
used either way, so a report never leaves which registry answered ambiguous.
`BACKDRAFT_HOME` already overrides discovery process-wide and must keep
working; the flag wins over it, and a test pins that order.

**Acceptance.** From a directory with no `.backdraft/` anywhere above it,
`backdraft verify memo.backdraft.html --against ../backdraft/demo` re-resolves
every citation and prints the same `sources:` line the in-project run prints,
naming that root. Pointing it at `demo/.backdraft` works identically. Pointing
it at a directory with no registry is a usage error naming what was expected,
not a silent fall back to tier one. Without the flag, behaviour is byte-identical
to today. `README.md`, `site/docs.html`, `site/llms.txt` and
`skills/backdraft-artifact/SKILL.md` name it where they currently say the check
runs only in the project it was bound in.

**Size.** One day.

### 7. A claim that straddles a chunk boundary gets one token instead of two

**Intent.** `skills/backdraft/SKILL.md` tells the writing agent that "a claim
that spans two chunks needs both tokens, not the nearest one" — a correct
instruction with no support behind it. The gate hands back chunks; whether the
sentence the agent is about to cite ends inside one is something the agent must
notice by eye, in the middle of drafting, against text it is reading for
meaning. When it misses, nothing downstream complains: one token resolves, the
receipt is real, the artifact renders clean, and the half of the claim living in
the next chunk is uncited while looking cited. That is the one failure mode this
product cannot detect and cannot afford — a claim whose evidence covers part of
it is worse than an unresolved one, because an unresolved one says so.

**Shape.** The gate's, and display-only: no token, anchor or receipt moves. A
search hit whose snippet begins or ends mid-sentence is at a boundary, and the
neighbour is `ordinal ± 1` on the same page, which `Registry.anchors_for_page`
already returns — so the hit can carry the neighbour's token and be rendered
with it, in `gate/searcher.py`'s existing line shape. Decide "mid-sentence" by
the chunk's own edges rather than by parsing prose: the chunker (spec/chunking.md)
splits on paragraph boundaries, so a chunk that does not end at one is the
signal, and the rule must be stated in the DESIGN row because a heuristic that
guesses at sentences would be the kind this repo refuses. Emitting the neighbour
is minting it, per the gate's own rule, so the ledger records it and the run says
so — that is a cost to name, not to hide. The same treatment belongs on a page
read's last chunk, where the next page's first chunk is the neighbour.

**Acceptance.** Ingest a source whose paragraph runs across a page break, search
for a phrase landing in the tail chunk, and the hit names the adjoining token on
its own line; the ledger shows both minted. A hit sitting wholly inside a
paragraph gains nothing and its output is byte-identical to today, pinned by a
test. `skills/backdraft/SKILL.md` replaces "needs both tokens, not the nearest
one" with the surface that now says which both are.

**Size.** Two to three days.

### 8. A re-ingested source strands citations one at a time

**Intent.** This is DESIGN.md's oldest Open line — "re-bind/orphan pass on
re-ingest of changed docs (chunk ordinal drift)" — and the week that taught
`ingest` to announce a `new generation` (2026-08-20) made it sharper rather than
smaller: the agent is now told the moment its citations may have moved, and
still has nothing to do about it but re-bind and read a list of failures. A
changed source re-chunks, so an edit near the top of a page shifts every ordinal
below it; citations that pointed at unchanged text come back `drifted` or
`unresolved` en masse, each one a separate manual hunt for where that sentence
went. The system knows both sides — the cited snippet and the current
extraction — and makes the human do the matching.

**Shape.** Read-only and advisory; it proposes, it never rewrites. A command
over one document that, for every citation in its bindings that no longer
resolves against the current generation, looks for the cited snippet in the
current extraction and reports what it found: the old token, the new token if
the text is there under a new locator, and plainly nothing when it is not.
Matching is on the normalized snippet hash first (`kernel.hashing`), which is
exact and is the only claim worth making automatically; a near match is a
different and harder question and must be left out, said out loud in the DESIGN
row, because a wrong proposal here rewrites provenance. The registry already
holds every generation and `registry.current_at` is the existing half of this —
so the new part is the reverse lookup by snippet hash within a document, which
is one indexed query, and the walk over `bindings` the registry already stores.
Output is the same line shape `bind` and `verify` use.

Not Later's "living documents", and the boundary is worth holding: that item is
a *presentation* — cited-then vs. now, diff-shaped, with a demo — and answers
"what changed". This one answers "where did it go", is the Open list's line
rather than Later's, and is the primitive the presentation would rest on.

**Acceptance.** Ingest a document, bind a memo citing three chunks, edit the
source so a paragraph is inserted above them, re-ingest, and the command reports
all three as moved with their new tokens; applying those tokens by hand and
re-binding gives a clean run. A citation whose text was deleted outright is
reported as gone, with no token proposed. A document with no new generation
reports nothing and exits 0. Nothing is written: the registry's document,
extraction and ledger counts are identical before and after.

**Size.** Three days.

### 9. What this install can do, said before a verb needs it

**Intent.** backdraft degrades rather than fails, which is right, and the price
is that its capabilities are discovered one at a time at the moment each is
missed: poppler tells you at ingest, the vision model tells you at ingest, a
thin extraction tells you after the fact, `[xls]` tells you when a workbook
arrives, and `[math]` now tells you at render — each a different note at a
different moment, none of them askable in advance. An agent planning a job
cannot say "this machine can ingest scanned PDFs" without attempting one, so it
either promises the user something it cannot deliver or hedges everything. The
notes are good; there is no way to read them before the work.

**Shape.** One read-only command reporting each optional capability, what it
affects in terms of the four verbs, and the exact command that installs it —
reusing the message each site already owns rather than writing a second copy of
any of them, which is the whole risk here. The sites are known:
`extract.snapshots`'s poppler check, `extract.vlm_settings.vlm_ready`, the
`[xls]`, `[entail]` and `[math]` imports, and the registry's own presence. Each
must be asked the way the real path asks it, so the report cannot say yes where
the verb would say no. Credentials are named as present or absent and **never
printed, echoed or logged**, per the credentials rule. Exit 0 always: a missing
optional capability is not an error, and gating on it would make the report a
second, worse failure surface.

**Acceptance.** On a machine without poppler, the command names it, says page
images will be missing and citations unaffected, and gives the install line —
matching what `ingest` prints when it actually happens, asserted against the
same constant. With `[math]` uninstalled it says formulas render verbatim; with
it installed it says nothing is missing. It exits 0 in both cases, and in a
directory with no registry it still runs and says the registry is the one thing
absent. No key value appears in the output under any state, pinned by a test
that sets a fake key and greps the output for it. `README.md`, `site/docs.html`,
`site/llms.txt` and `skills/backdraft/SKILL.md` name it as the first thing to
run in an unfamiliar environment.

**Size.** Two days.

### 10. `bind` never says which ledger it judged `not_shown` against

**Intent.** `bind`'s report names the mode, the claim and citation counts, every
status, every check that ran and every failure — everything except the one input
that decides `not_shown`. The session is resolved silently by
`cli_context.resolve_session` (flag, then `BACKDRAFT_SESSION`, then the default),
so `backdraft bind memo.md` in `demo/` with nothing exported reports `not_shown:
1` off the shared default ledger and says nothing about it. That is the weakest
form the check has: the 2026-08-31 row established that the default session
accumulates across every run in a registry, so a `resolved` there can mean "some
earlier run read that page" rather than "this writer did". The row fixed it at
`session show`, the command that reports the ledger, and left `bind`, the
command that acts on it. The recipient inherits the gap: the record carries
`session_id` and `spec/artifact.md` calls it "the ledger session, when the run
had one", so a reader holding a record that says `"session_id": "default"` has
the fact and no way to know it weakens every `not_shown` and every `resolved`
beside it.

**Shape.** `bind/cli.py`'s report header, and `spec/artifact.md`. Name the
session on the summary line, and where it is the default one, close with
`gate.reader.DEFAULT_SESSION_NOTE` — imported, not re-written, which is the whole
point of the item: two wordings for one cost is how the `session show` note and
this one drift apart. Keyed on the resolved id rather than on which rule supplied
it, exactly as `session show` keys it, so an explicit `--session default` is
named too. Then say it in the format: `spec/artifact.md`'s `session_id` row and
the legend's `not_shown` line must tell a reader what a default session means for
the status, since the record travels and the CLI does not. That is a legend
change, so goldens and the demo regenerate — the 2026-08-24 trade, taken twice
before. Not item 5's ground: that item makes the report machine-readable, this
one adds a fact the report does not currently carry in any form.

**Acceptance.** In `demo/`, `backdraft bind memo.md` with no session and no
`BACKDRAFT_SESSION` names `default` and prints the note; `--session s-bridgeview`
names that id and prints no note; `--session default` prints the note. Below the
header the two runs are byte-identical. A test asserts the printed note is
`gate.reader.DEFAULT_SESSION_NOTE` by constant rather than by substring, so a
second copy cannot pass. `backdraft verify` on a record bound in the default
session says so from the record alone, with no registry present. Golden sidecars
and `demo/memo.backdraft.html`/`site/demo.html` regenerate together and stay
byte-identical to each other. `README.md`, `site/llms.txt`,
`skills/backdraft/SKILL.md` and `skills/backdraft-artifact/SKILL.md` follow.
DESIGN row.

**Size.** Two days.

### 11. A withdrawn source is invisible, including to the person looking for it

**Intent.** `forget` withdraws a source from every surface that offers one, which
is right, and the result is that nothing lists what was withdrawn. `ls` says `no
documents ingested` in a registry holding two withdrawn documents — true about
sources, false about the registry, and the wording admits nothing. The three
places a withdrawn document still appears are `session show`'s mark, the JSON
export, and the unknown-slug error added 2026-09-04; none of them is where
somebody looks. So an agent handed a project, meeting a citation that binds
`unresolved — withdrawn from the registry on ...`, can learn that one source went
and cannot learn what else did. The documented undo makes it worse: re-ingesting
the file is the way back, and the path to re-ingest lives on the document, which
is exactly what no surface will show once it is out of the list.

**Shape.** `cli.list_documents`, off `documents(include_withdrawn=True)`, which
already exists. Reuse `registry.withdrawn_reason` for the date and
`gate.WITHDRAWN_HINT` for the way back — both are single owners and this must not
mint a fourth wording for a withdrawal. The decision to make and write down is
whether this is a flag on `ls` or a block printed under it when the registry has
any: the objection to answer is that `ls` is the readable set, so anything that
widens it must not make a withdrawn source look available — mark every row and
never sort a withdrawn one among the live ones. The gate's own document list is
out of scope and must not change: the gate serves sources, and a withdrawn source
is not one. Hold the byte-identity rule the source-naming work established — a
registry with nothing withdrawn prints exactly what it prints today, everywhere.

**Acceptance.** In a registry with two documents, one withdrawn, `ls`'s default
output is byte-identical to the same registry with only the live document — pin
it. The withdrawn view names the slug, the date it went and the exact `backdraft
ingest <path>` that brings it back, asserted against `WITHDRAWN_HINT` by
constant. A registry where everything has been withdrawn no longer reports itself
empty without qualification. `backdraft read` and the gate's list are unchanged,
pinned. `README.md`'s "Forgetting a source", `site/docs.html`, `site/llms.txt`
and `skills/backdraft/SKILL.md` say where to look. DESIGN row.

**Size.** One day.

### 12. `--slug` is dropped without a word when the document is already there

**Intent.** `Registry.ingest`'s docstring says "`slug` is honoured only when the
document is new — a slug is stable once assigned", which is the right rule and is
stated nowhere a caller reads. `backdraft ingest report.pdf --slug q4-report`
against a `report.pdf` already in the registry prints the old slug, exits 0, and
never mentions that the flag did nothing; the same is true of a URL re-fetch,
where the fallback slug the docs warn about is exactly what the caller was trying
to replace. This is the one input `ingest` accepts and does not report on, in the
week it learned to report everything else it did — `unchanged`, `new generation`,
`restored`, thin extractions, and every source that never landed. It is not item
4, which predicts what a source *not yet in the registry* would be called; this is
`ingest` saying what it did with a flag for a source that is.

**Shape.** `cli.ingest`, in the shape `_outcome_note` and the grouped notes
already use — a mark on the source's line or one grouped note, matching how
`restored` was added rather than inventing a third reporting shape. No schema
change and no registry change: the CLI holds the requested slug and the returned
`Ingested` carries the assigned one, so the comparison is a string equality in
the layer that already owns the reporting. Say the next step, which fd8d00f made
the rule for this command: the slug is permanent because every token carries it,
so the honest options are keep it, or `forget` the document and ingest the file
under the new slug as a *new* document — which strands every token minted under
the old one, and the note must name that cost rather than recommending it. Exit 0
throughout: getting back the document you already had is not a failure.

**Acceptance.** Ingest a file, then ingest it again with `--slug something-else`:
the run says the slug was not applied, names the slug the document actually has,
names what re-slugging would cost, and exits 0. Same for a URL re-fetched with a
`--slug` it did not have the first time. A `--slug` on a genuinely new document,
and every ingest with no `--slug` at all, is byte-identical to today — pin both,
including `demo/`'s three sources. `README.md`, `site/llms.txt` and
`skills/backdraft/SKILL.md` say a slug is permanent where they currently say to
pass `--slug`. DESIGN row.

**Size.** One day.

### 13. `verify` cannot re-check the one status only the ledger can settle

**Intent.** `verify`'s source tier re-resolves every token and reports the
statuses "as `bind` would", with one gap the code names out loud: `not_shown`
cannot appear, because it is a fact about a ledger session and verify opens none
(`render/cli.py`'s `_against_sources`). So a record that says a claim cited
something its author never read comes back `resolved` from the tier that is
supposed to be the stronger check, and the strongest claim this product makes —
that the set of citable tokens is exactly the set the gate emitted — is the one
claim a recipient holding the registry cannot re-check. That recipient is the
`backdraft-artifact` skill's whole case: they have the artifact, they have the
project, and the check they most want is the one that says the author read it.

**Shape.** `render/cli.py`'s source tier plus one registry read. The record
already carries `session_id`, and `Registry.was_shown(session_id, token)` already
answers the question one token at a time — that is the call `bind` makes, so a
status printed here stays the status a re-bind would print. The standing
objection is in the docstring and must be answered rather than overridden:
"read-only, it opens no session and mints nothing, which is what separates it
from `backdraft show`". Reading a ledger is not minting into one, and the session
read is the one the record names rather than one verify chose — so
`ensure_session` must not be called, a session id absent from the registry is
reported as absent rather than created, and a `session_id` of `null` is reported
as a run that had none. Nothing about `show`'s minting changes. The `sources:`
line gains the status; the existing counts must keep meaning what they mean.

**Acceptance.** In `demo/`, bind a memo under a session that was never shown one
of its citations, render, then `backdraft verify` in the project: the source tier
reports that citation `not_shown` and says which session it read. Verified from
outside the project, the tier does not run and the output is byte-identical to
today. A record whose `session_id` names no session in this registry says so and
does not create it — assert the registry's session count before and after. A
record with `session_id: null` says the run had no session. Every existing verify
output where the ledger agrees with the record is byte-identical, pinned,
including `demo/`'s. `spec/artifact.md` § Checking an artifact,
`skills/backdraft-artifact/SKILL.md`, `site/llms.txt` and `README.md` follow.
DESIGN row.

**Size.** Two to three days.

### 14. `bind` and `verify` name the failure and not the move

**Intent.** 2026-09-01 made `ingest`'s failures say what to do as well as what
went wrong, on the argument that a calling agent reads the reason and acts on it.
`bind` and `verify` are the two commands whose output *is* the product, and
neither says a next step anywhere: `! not_shown: <token> — <claim> @<offset>` is
a complete diagnosis and a blank instruction. The move differs sharply per status
and is not guessable — `not_shown` clears by showing the token, `unresolved`
needs a search and a new token or an uncited claim, `drifted` needs both snippets
read and a judgement, `malformed` is an href to fix, and a `receipt:` finding
means the artifact was edited rather than the sources moved. Today that mapping
lives only in `skills/backdraft/SKILL.md`, which means it works for an agent
running the skill and for nobody else — a hook, a CI job, a person, or any agent
that reached the command another way.

**Shape.** A closing block on both commands, one line per status actually
present, naming the exact command that addresses it — the shape `ingest`'s
grouped notes already use, and never a hint appended to each of eighteen line
items. One owner for the mapping, imported by `bind/cli.py` and
`render/cli.py` rather than written twice; the status set is the artifact
format's and closed, so the mapping is total and a test asserts every
`CitationStatus` has a line. `verify` adds the `receipt` case, which is not a
citation status and is the finding that means something categorically different.
Display only: no exit code moves, no status moves, no record field is added — a
run that came out clean prints exactly what it prints today. Not item 5, which
gives the same two commands a machine-readable payload; that item serves a caller
that parses, this one serves the caller that reads, and both are wanted because
the human report is what gets relayed to the user.

**Acceptance.** In `demo/`, `backdraft bind memo.md --session s-bridgeview
--check value-trace,overlap` closes by naming `backdraft search` for its one
`unresolved`, and says nothing about the statuses it did not produce. A bind that
comes out clean is byte-identical to today, as is a clean `verify` — pin both. A
test enumerates `CitationStatus` and asserts each has a line and a command that
`backdraft --help` lists. `verify` on an artifact with one edited snippet says
the file was changed rather than the sources. `demo/walkthrough.md`'s bind and
verify blocks show the real output. DESIGN row.

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
