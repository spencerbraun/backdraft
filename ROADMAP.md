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

### 1. What this install can do, said before a verb needs it

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

### 2. `bind` never says which ledger it judged `not_shown` against

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
`gate.reader.DEFAULT_SESSION_NOTE` — imported, not re-written, which is the
whole point of the item: two wordings for one cost is how the `session show`
note and this one drift apart. Keyed on the resolved id rather than on which
rule supplied it, exactly as `session show` keys it, so an explicit
`--session default` is named too. Then say it in the format: `spec/artifact.md`'s
`session_id` row and the legend's `not_shown` line must tell a reader what a
default session means for the status, since the record travels and the CLI does
not. That is a legend change, so goldens and the demo regenerate — the
2026-08-24 trade, taken twice before. Not what `bind --json` (2026-09-14)
settled: the record it prints already carries `session_id`, and what neither it
nor the report says is what a default session means for the statuses beside it.

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

### 3. A withdrawn source is invisible, including to the person looking for it

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

### 4. `--slug` is dropped without a word when the document is already there

**Intent.** `Registry.ingest`'s docstring says "`slug` is honoured only when the
document is new — a slug is stable once assigned", which is the right rule and is
stated nowhere a caller reads. `backdraft ingest report.pdf --slug q4-report`
against a `report.pdf` already in the registry prints the old slug, exits 0, and
never mentions that the flag did nothing; the same is true of a URL re-fetch,
where the fallback slug the docs warn about is exactly what the caller was trying
to replace. This is the one input `ingest` accepts and does not report on, in the
week it learned to report everything else it did — `unchanged`, `new generation`,
`restored`, thin extractions, and every source that never landed. It is not
`ingest --dry-run`, which predicts what a source would be called *before* the
ingest and already says there that `--slug` would not rename a document that has
one; this is the ingest itself saying what it did with the flag it was handed.

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

### 5. `verify` cannot re-check the one status only the ledger can settle

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
already carries `session_id`, and `Registry.was_shown(session_id, token)`
already answers the question one token at a time — that is the call `bind`
makes, so a status printed here stays the status a re-bind would print. The
standing objection is in the docstring and must be answered rather than
overridden: "read-only, it opens no session and mints nothing, which is what
separates it from `backdraft show`". Reading a ledger is not minting into one,
and the session read is the one the record names rather than one verify chose —
so `ensure_session` must not be called, a session id absent from the registry is
reported as absent rather than created, and a `session_id` of `null` is reported
as a run that had none. Nothing about `show`'s minting changes. The `sources:`
line gains the status, and so do `--json`'s `sources.by_status` and `findings` —
one set of findings, two presenters (2026-09-14); the existing counts must keep
meaning what they mean.

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

### 6. `bind` and `verify` name the failure and not the move

**Intent.** 2026-09-01 made `ingest`'s failures say what to do as well as what
went wrong, on the argument that a calling agent reads the reason and acts on it.
`bind` and `verify` are the two commands whose output *is* the product, and
neither says a next step anywhere: `! not_shown: <token> — <claim> @<offset>` is
a complete diagnosis and a blank instruction. The move differs sharply per status
and is not guessable — `not_shown` clears by showing the token, `unresolved`
needs a search and a new token or an uncited claim, `drifted` needs `locate`
and, where the text did not simply move, both snippets read and a judgement,
`malformed` is an href to fix, and a `receipt:` finding means the artifact was
edited rather than the sources moved. Today that mapping
lives only in `skills/backdraft/SKILL.md`, which means it works for an agent
running the skill and for nobody else — a hook, a CI job, a person, or any agent
that reached the command another way.

**Shape.** A closing block on both commands, one line per status actually
present, naming the exact command that addresses it — the shape `ingest`'s
grouped notes already use, and never a hint appended to each of eighteen line
items. One owner for the mapping, imported by `bind/cli.py` and `render/cli.py`
rather than written twice; the status set is the artifact format's and closed,
so the mapping is total and a test asserts every `CitationStatus` has a line.
`verify` adds the `receipt` case, which is not a citation status and is the
finding that means something categorically different. Display only: no exit code
moves, no status moves, no record field is added — a run that came out clean
prints exactly what it prints today. Not `--json` (2026-09-14), which gave the
same two commands a machine-readable payload; that serves a caller that parses,
this one serves the caller that reads, and both are wanted because the human
report is what gets relayed to the user.

**Acceptance.** In `demo/`, `backdraft bind memo.md --session s-bridgeview
--check value-trace,overlap` closes by naming `backdraft search` for its one
`unresolved`, and says nothing about the statuses it did not produce. A bind that
comes out clean is byte-identical to today, as is a clean `verify` — pin both. A
test enumerates `CitationStatus` and asserts each has a line and a command that
`backdraft --help` lists. `verify` on an artifact with one edited snippet says
the file was changed rather than the sources. `demo/walkthrough.md`'s bind and
verify blocks show the real output. DESIGN row.

**Size.** Two days.

### 7. A chunk the table of contents lists is a chunk no read can ask for

**Intent.** Since 2026-09-07 `backdraft read <slug>` on a one-page source lists
that page's chunks — `p1.c9  From Wikipedia, the free encyclopedia...` — and the
walkthrough tells the reader the list is how to find where an article starts.
It then offers one way in: `backdraft read franklin-county p1`, which begins at
the site's navigation menu and, under the 2026-09-08 budget, spends 12,000
characters to reach `c25`. The locator the list just printed is not something
`read` accepts. `backdraft read franklin-county p1.c9` exits 1 with `no page or
sheet named 'p1.c9'; sheets: Franklin County, Ohio - Wikipedia`, which is wrong
twice: the selector is refused, and a web page's title is called a sheet. So an
agent that did the right thing and read the map is left to compute a character
`--offset` it has no way to derive, or to search for words it has not seen yet.

**Shape.** The gate's selector grammar, not the token grammar: `p1.c9` is a
locator `spec/tokens.md` already defines, and this only lets `select_pages`
accept `pN.cM` and `pN.cM-cK` as *read* selectors (SPEC § Gate lists the forms).
A chunk selection is a `Selection` that also carries an ordinal range, and
`render_page_read` shows exactly those chunks through `_Window`, so the budget,
the whole-chunk rule and the continuation line — with its `--limit` and typed
`--session` — keep working, and the continuation names a command in the same
selector form. Minting is the gate's rule unchanged: what is printed is minted
and nothing else. Only `page`-kind pages take a chunk selector; on a sheet it is
refused with a message saying a sheet is read by name or page and cited by cell.
Cell *ranges* are Parked's "Excel region maps and range reads" and stay there
with their objection. A backwards range, or one naming no chunk, is a
`GateError` naming the page's chunk span in `_what_exists`'s shape. Fix
`_what_exists` while there: it prints `sheets:` whenever every page has a name,
which is true of every titled web page, so key it on `kind`. The one-page
table of contents' `[Read one: …]` hint stays `p1`, which keeps every existing
TOC byte-identical; the walkthrough's paragraph about finding `p1.c9` gains the
command that reads from there.

**Acceptance.** In `demo/`, `backdraft read franklin-county p1.c9` prints `c9`
alone under its own token and the ledger gains that one anchor and no other;
`p1.c9-c14` prints six chunks; `p1.c14-c9` and `p1.c99` exit 1 naming the page's
chunk span. A chunk range longer than the budget closes with a continuation that,
followed, walks the range exactly once — drive it with
`tests/continuation_util.py`. `backdraft read underwriting-model p1.c1` exits 1
saying how a sheet is read and cited. A titled web page's unknown-selector error
no longer says `sheets:`. Every existing selector form prints byte for byte what
it does today, pinned by the existing goldens. SPEC § Gate, `site/docs.html`,
`site/llms.txt`, `skills/backdraft/SKILL.md` and `demo/walkthrough.md` name the
form.

**Size.** Two days.

### 8. A search hit's excerpt can leave out the words that matched

**Intent.** `search` prints each hit's first 160 characters, and
`gate.reader.excerpt`'s NOTE says so on purpose: the cut is from the start rather
than centred on the match, because FTS5 decides what matched and the gate
re-derives nothing the registry owns. The walkthrough's own step 11 shows the
cost. `backdraft search "replacement reserve"` returns
`bd:t12-summary:p3.c4:6f0f` over an excerpt about capital expenditures that never
contains the phrase — the sentence that does starts past character 200 — and
the walkthrough can say "that is the snippet that actually says it" only because
it ran `show` next. An agent choosing among twenty hits does not run `show` on
each; it picks by excerpts that, for any chunk longer than a couple of lines, are
the chunk's opening rather than its evidence. Web pages, whose chunks run to a
thousand characters, made that the common case.

**Shape.** Answer the NOTE rather than override it: ask the registry, which does
own what matched. The `search` table in `registry/schema.sql` is a
content-storing FTS5 table, so `Registry.search` can return FTS5's own window
for each hit — `snippet()`, or match offsets out of `highlight()` markers — and
`SearchHit` gains that field. The gate then renders the window it was handed,
which is the rule the NOTE protects, and `Registry.search` stays the only place
an FTS5 function is called. Display only: token, anchor and receipt are
untouched, and the excerpt stays one line of at most `EXCERPT_CHARS` with an
elision mark at whichever end was cut. Keep byte-identity where it is free: a
hit whose match already falls inside the first `EXCERPT_CHARS` prints exactly
today's excerpt, so only the hits that were hiding their evidence change, and
most documented `search` blocks do not move. A phrase-fallback retry windows on
the phrase that actually ran. The DESIGN row says what replaced the NOTE and why
the registry, not the gate, computes the window.

**Acceptance.** In `demo/`, `backdraft search "replacement reserve"` shows the
`p3.c4` excerpt containing "replacement reserve", opening with an elision mark.
`backdraft search "24850000"` and every other `search` block in
`demo/walkthrough.md` and `README.md` whose match lies in the first 160
characters is byte-identical, pinned. A query that matches only late in a long
chunk, and a query run through the phrase fallback, each window on what FTS5
matched, asserted by test. No `registry-v1` export field changes. SPEC § Gate's
`search` line follows. DESIGN row.

**Size.** Two days.

### 9. A small table is marked a shell, and the skill says not to cite it

**Intent.** The thin-source mark (2026-08-20, carried onto every list
2026-09-09) is a character count under `THIN_SOURCE_CHARS`, and for prose that
is a fair proxy: a login wall and a scanned PDF both extract almost nothing. For
a table it is not. A three-row `rates.csv` — a going-in and an exit cap rate —
ingests at 188 characters, and ingest says `note: little text extracted` and
tells the agent to "tell the user the source came back thin rather than citing
the shell of it"; `ls` ends its row `little text: 188 chars`; and
`skills/backdraft/SKILL.md` says a row carrying that mark "is a source to read
and report on, not one to cite". The heuristic built to stop an agent citing an
empty page now stops it citing a correct, complete rate table, and has it tell
the user something false about the source. Sheets are where small and complete
is normal: an assumptions tab, a rate card, a cap table.

**Shape.** `gate.thin_mark` owns the rule and is the only place it changes;
`ingest`'s grouped note and all three list surfaces follow, which is what the
2026-09-09 single owner was for (and what Friday's cleanup made true of `ingest`,
which had kept a private copy of the threshold). Decide by page kind, not by
extension: an extraction whose pages are sheets is thin when it holds no
non-empty cell values at all — `Registry.pages` already returns sheet pages with
their `cells` — because a sheet's shell is a workbook of charts, images or pivot
caches, not a short table, and the rendered text's pipes and `[B10]` prefixes
make a character count meaningless there anyway. Prose keeps the character
threshold exactly. `cli._THIN_CAUSE` gains the sheet cause. The DESIGN row
amends 2026-08-20 rather than contradicting it: still display only, still exit
0, still no token, anchor or status derived from it. A registry's output changes
only on the table rows this exists to unmark and on sheet sources that hold no
values at all.

**Acceptance.** `backdraft ingest rates.csv` for a three-row table prints no
thin note, and `ls`, `backdraft read` and its table of contents carry no mark. A
workbook whose only sheet holds no cell values is still marked and gets the
sheet cause. A 27-character HTML login wall, a zero-page PDF and every existing
thin-source test are unchanged, and the demo's three sources print byte for byte
what they do today. `skills/backdraft/SKILL.md`,
`skills/backdraft-backfill/SKILL.md`, `site/llms.txt` and `README.md` say what the
mark means for a table. DESIGN row.

**Size.** One day.

### 10. `ingest --dry-run` names the source and not the run

**Intent.** The dry run (2026-09-10) answers what a source would be called, and
`tests/test_dry_run.py` pins that the prediction equals the outcome — for the
name. The rest of the command it predicts is unchecked:
`backdraft ingest report.pdf --dry-run --extractor bogus` and
`--config nonsense=1` both exit 0 with a clean line, while the real ingest fails
that source on the unknown extractor or on a key the chosen extractor never
reads. And the dry run is silent on the fact an agent most needs before a PDF
batch: whether `auto` will send the pages to the vision model, which spends
against `BACKDRAFT_VLM_API_KEY`, or read the text layer for free. That choice is
`extract_base.select`'s, made from the media type and `vlm_ready` with no bytes
and no network, so it is as knowable in advance as the slug.

**Shape.** One owner for "which extractor, with which settings", shared by
`Registry.ingest` and `Registry.naming`: lift the `select`/`get` and
`check_config` lines at the top of `ingest` into one registry method both call,
so the prediction cannot drift from the run — the argument that already put
`_find_document` behind both. `Naming` gains the extractor's name. A failure to
choose, or a rejected key, becomes that source's `!` line in the existing
failure report exactly as under the real ingest, and the dry run exits 1 for it.
Where the extractor goes on the line is the decision to write down:
`_report_naming` promises the dry run's line reads like `ingest`'s, and
`ingest`'s line does not name its extractor. Prefer a trailing mark in
`_naming_note`'s shape (`would extract with vlm`) over widening both lines,
which would move every documented ingest block. For a URL the media type is
provisional, so the extractor is too, and the existing note says both rather
than adding a note. A source already ingested reports its current generation's
extractor. `vlm_ready` answers presence and nothing else; no key value reaches
output. Not the ground of "What this install can do, said before a verb needs
it", which reports the machine; this reports what one command will do to one
source. `demo/walkthrough.md`'s dry-run block moves and is regenerated, not
hand-edited.

**Acceptance.** `backdraft ingest demo/sources/t12-summary.pdf --dry-run` names
`pdf-text` with no key configured and `vlm` with `BACKDRAFT_VLM_API_KEY=fake`
set, with no model call and no network request in either case — blocked
structurally, the way `tests/test_dry_run.py` already blocks `fetch.fetch`. The
fake key's value appears nowhere in the output, pinned by a test that greps for
it. `--extractor bogus` and `--config nonsense=1` fail the dry run with the same
reason text the real ingest's `!` line gives, asserted by comparing the two. For
every source in the prediction-equals-outcome tests, the extractor the dry run
names is the one the ingest records in its extraction. `README.md`,
`site/docs.html`, `site/llms.txt` and `skills/backdraft/SKILL.md` say the dry run
shows which extractor will run, and that `vlm` is a model call per page. DESIGN
row.

**Size.** Two days.

### 11. `session show` counts what was read and cannot say what was not

**Intent.** `session show` (2026-08-31) answers "have I read enough to write
this yet?" with a count per document. Since the page-read budget (2026-09-08) a
long page arrives in windows, and an agent that read the first window of a
57-chunk article, lost its context to compaction and came back has
`franklin-county  25` and nothing else: it cannot tell whether those 25 are the
navigation menu or the demographics section, and the only way to find what is
left is to re-read from the top, re-spending the context the budget was meant to
save. The ledger holds exactly the answer — which anchors this session was shown
— and no surface prints it by locator. A count is coverage for a report; a
writer needs coverage it can take a next step from.

**Shape.** `session show --in <slug>`, the flag `search` already uses to mean one
document. Under it, per page of the current extraction, the chunk locators
shown and not shown, compressed into ranges (`p1  shown c1-c25  not shown
c26-c57`); a sheet page reports whether its page anchor was shown and a count of
cells shown rather than enumerating cells. It emits no tokens and mints nothing
— locators are addresses, the stance `render_toc`'s chunk list already takes —
so it stays the one gate command that takes `--session` without minting into
it. Read it in `registry/ledger.py` beside `shown_by_document`, as one query
joining the ledger to the current extraction's anchors; anchors shown from a
superseded generation count the way `shown_by_document` counts them, and the
DESIGN row says which way that is. The closing hint names the read that covers
the first unshown range — in the chunk-selector form if "A chunk the table of
contents lists is a chunk no read can ask for" has landed, otherwise as the page
read with its `--offset` — carrying a typed `--session` through
`gate.reader.session_argument`. A withdrawn or unknown slug is refused in
`require_document`'s words, as `search --in` refuses it. Without `--in`,
`session show` is byte-identical, pinned.

**Acceptance.** In a copy of `demo/`'s registry, under a fresh session,
`backdraft read franklin-county p1` then `backdraft session show --in
franklin-county` reports `c1-c25` shown and `c26-c57` not shown, and its hint,
run, shows `c26` first. After `backdraft read t12-summary p1`, `--in
t12-summary` reports `p1` wholly shown, `p2` shown `c1` — the chunk that read
names across the page break (2026-09-16) — and not shown `c2-c7`, and `p3` not
shown. The ledger's row count is identical before and after the command.
`session show` with no `--in` prints exactly what `demo/walkthrough.md` shows.
`README.md`, `site/llms.txt` and `skills/backdraft/SKILL.md` tell the agent to
ask it after a context loss rather than re-reading from the top. DESIGN row.

**Size.** Two days.

### 12. An artifact word-diffs a drifted citation against whatever now stands at its old address

**Intent.** The artifact's drift block (`render/html/text.py`'s `_drift_block`)
shows `as cited` and `now`, word-diffed with `<del>` and `<ins>`, where `now` is
`anchor.snippet`: what stands at the cited locator in the current generation.
The 2026-09-17 row established that after a paragraph is inserted above, that is
a *different* paragraph, and the cited words stand unchanged one chunk down. So
the person the artifact is for sees every word of the cited sentence struck
through and an unrelated paragraph marked as inserted, which reads as "the source
rewrote this passage" and is false. `locate` knows better, but only a writer
holding the draft and the registry ever runs it; the artifact goes out with the
misleading diff, and since this Friday the artifact skill has had to tell a
recipient to spot "unrelated text" by eye. The footnotes projection quotes the
same two snippets side by side and has the same blind spot.

**Shape.** Bind already has what it needs: it resolves every token against the
registry at bind time, and `registry.current_with` answers where the cited text
stands now. Move `locate`'s outcome rule (`cli._Located.outcome`, `_PROSE`,
`MOVED`/`AMBIGUOUS`/`GONE`) down beside `current_with` in `registry/store.py` so
bind and `locate` share one owner, since bind may not import `cli`. When a
citation comes back `drifted` and the rule says `moved`, the record carries an
optional citation key (`moved_to`, say) naming the token that now holds the
text. `Citation.to_dict` writes it only when present, so every record without
drift is byte-identical. The status stays `drifted`: the set is closed, and a
moved citation still names a superseded snippet, which is what drift means.
`spec/artifact.md`'s citation table gains the key and the legend's `drifted`
sentence says what it means; the format string stays `artifact-v1`, which
§ Versioning's unknown-key rule and the 2026-09-07 `title` precedent both allow,
and the DESIGN row says so rather than leaving it implied. When `moved_to` is
present, the drift block says the cited words stand unchanged at that token and
shows them once, instead of diffing them against the paragraph now at the old
address; without it, today's diff. The footnotes projection says the same.
`verify`'s receipt checks are untouched, since the token still hashes against
`drifted_from`. A legend change regenerates the goldens, and
`demo/memo.backdraft.html` and `site/demo.html` together; the demo has no
drifted citation, so only the legend string and `bound_at` should move, checked
structurally. If "`locate` calls intact words `gone` when an insertion merged or
split their chunk" has landed, bind reads the rule it widened.

**Acceptance.** In a scratch project modelled on `tests/test_locate.py`'s
fixtures, bind a memo citing three paragraphs, insert one above them, re-ingest
and re-bind: all three citations are `drifted` and carry a `moved_to` equal to
the token `backdraft locate` prints for each, and the rendered cards say the text
stands unchanged at those tokens and contain no `<del>`. A sentence edited in
place still renders today's word diff. A citation whose text stands in two places
carries no `moved_to`, and a cell citation never does. `backdraft verify` on the
new artifact exits as before, every receipt holding. A record with no drifted
citation is byte-identical to today apart from the legend, pinned by the golden.
DESIGN row.

**Size.** Three days.

### 13. `locate` leaves the fix to hand edits of tokens, which the skill forbids

**Intent.** `locate` prints `moved: <old> — now at <new>` and closes by telling
the writer to put each moved token in place of the old one, while the writing
skill's first rule for tokens is "Never construct, guess, or edit a token by
hand. Copy it from the output that produced it." Three citations is a careful
paste. A thirty-citation memo, after a source gained a paragraph on page 1, is
thirty find-and-replace edits made with an agent's own text tools, and one wrong
paste — the new token dropped into the wrong claim, a hash truncated — is a
citation that binds `resolved` to the wrong text or `unresolved` for no reason.
`locate` already knows every replacement exactly, by claim and by offset.

**Shape.** `locate --apply` rewrites hrefs for `moved` lines only: each old token
replaced by its new one inside the claims `locate` reported, located by
`kernel.claims.parse_claims`' spans rather than by string search, so a token that
also appears outside a link is left alone and every byte outside those hrefs is
unchanged. `ambiguous` and `gone` lines are never touched. The 2026-09-17 row
made `locate` read-only, and the objection must be answered rather than
overridden: its reason was the ledger — "a command that proposes should not write
the ledger it proposes against" — and `--apply` still writes no ledger row, no
session and no record. The tokens it writes are still unshown, so its closing
line is the same `backdraft show … --session` the plain run names, and `bind`
still judges them. What it writes is the author's document, which is why it is a
flag and never the default, why it refuses a document whose bytes changed
between the parse and the write, and why it writes through a temporary file and
a rename so an interrupted run leaves the old document whole. It reports in
`locate`'s line shape (`applied: <old> → <new> — <claim> @<offset>`) so the
report stays one list. The skill's `drifted` bullet and `site/llms.txt` change
the next step from "put each moved token in place" to `--apply` and then the
named `show`.

**Acceptance.** In `tests/test_locate.py`'s scenario of three citations pushed
down by a new paragraph, `locate --apply --session s1` rewrites exactly the three
hrefs, a diff of the document before and after touches nothing else, and
following the closing line's `show` and re-binding exits 0. A copy of an old
token written in the document's prose outside any link is unchanged, as are the
tokens on `ambiguous` and `gone` lines. Without `--apply`, output and document
are byte-identical to today. A document edited between the parse and the write
(simulate it by patching the write step) is refused at exit 1 and left
unchanged. Ledger, session and bindings counts are identical before and after,
as `test_nothing_is_written_to_the_registry_the_ledger_or_the_record` already
pins for the plain run. DESIGN row.

**Size.** Two days.

### 14. `locate` calls intact words `gone` when an insertion merged or split their chunk

**Intent.** `locate` matches the cited snippet's hash exactly, and the 2026-09-17
row named the price: "a chunk that an insertion under 200 characters merged into"
comes back `gone`. Chunking rule 2 merges a segment under `MIN_CHARS` forward
into the one after it, so a short heading or one-line note inserted directly
above a cited paragraph becomes part of that paragraph's chunk and changes its
hash. Rule 3 does the reverse: a cited paragraph that grows past `MAX_CHARS` is
cut near a 1,200-character multiple, and the cited words can end up straddling
the cut. Either way the cited words are intact, character for character, and the
command that exists to find them says they were edited or removed, so the writer
goes searching again for text that never changed. A heading added above a
paragraph is the commonest edit a revised PDF gets, and a short heading is
exactly what rule 2 merges.

**Shape.** Still exact, never resemblance; the objection 2026-09-17 raised against
near matches stands. When the hash lookup finds nothing, look for the cited
snippet's normalized text (`kernel.hashing.normalize`) as a contiguous substring
of one current chunk of the same document, and then of two adjoining chunks
joined the way normalization joins them — adjoining by the rule
`gate.reader.adjoining` already uses (same page with no blank line between, or
across a page break), since that is where a rule 3 cut lands. Read the chunks off
the current generation one document at a time, with no new index. Containment in
one chunk proposes that chunk's token; containment across two proposes both,
`;`-separated, the form the skill already teaches for a claim that spans two
chunks. The line says which case it is — the words stand whole inside a chunk
that now holds more, or across two — rather than calling it `moved` silently,
and the DESIGN row decides whether that is `moved` with a qualifier or a fourth
outcome; the outcome set is `locate`'s own and not the artifact's, so either is
a display change. Several containing places stay `ambiguous`. Cells never match
this way: a value found inside a longer string proves nothing. If "An artifact
word-diffs a drifted citation against whatever now stands at its old address"
has landed, the rule lives in `registry`, bind reads the widened rule too, and
the row says whether a contained match records `moved_to`.

**Acceptance.** In a scratch project, cite three paragraphs of over 200
characters each, insert a 60-character heading line directly above the second,
and re-ingest: the first and third citations are not drifted at all, and where
today the second is `gone`, `locate` now proposes the chunk holding the heading
and the paragraph together; applying it and following the closing `show` binds
clean. Cite a 2,000-character paragraph, append enough to take it past 2,400 and
re-ingest: it is cut near 1,200, and the citation proposes the two adjoining
tokens. A sentence edited by one figure is still `gone`, pinned as today, and
every existing `tests/test_locate.py` expectation is unchanged. SPEC Addendum B's
`locate` paragraph and README's "When a source changes" follow. DESIGN row.

**Size.** Two days.

### 15. A draft outside its project is told there is no registry, about the wrong directory

**Intent.** `bind` and `locate` find the registry from the document's directory
(SPEC § CLI), and when that walk finds nothing `cli_context.open_registry`
refuses with `no .backdraft/ found in this directory or any parent; run backdraft
init` — where "this directory" reads as cwd. Checked on 2026-09-18: from inside
the demo project, `backdraft bind ../elsewhere/memo.md`, a draft kept beside the
project in a common layout, says there is no registry in the one directory that
visibly has one. The advice is wrong twice over. `init` in cwd reports the
registry that already exists, and `init` beside the draft makes an empty one,
after which every citation binds `unresolved` and the agent concludes its tokens
are bad.

**Shape.** `open_registry(start)` owns the wording. When the walk started
somewhere other than cwd, the refusal names that directory and the document it
came from. When the walk from cwd would have found a registry, it says so and
names the two ways to connect them — move the draft under that project, or run
with `BACKDRAFT_HOME=<root>` — and drops `backdraft init`, which is the wrong fix
there. It never falls back to cwd's registry: discovery infers nothing
(2026-09-15), and a registry the draft is not under is exactly the case to
refuse. `backdraft init` stays where no walk found anything, the fresh-project
case it was written for, and every refusal whose walk started at cwd — every gate
command — prints what it prints today, pinned. Not a `bind --against`: whether
`bind` should take a named registry the way `verify` does is a separate decision,
and the DESIGN row says why the environment variable is enough for now or queues
the flag.

**Acceptance.** From inside `demo/`, `backdraft bind ../elsewhere/memo.md` and
`backdraft locate ../elsewhere/memo.md` exit 1 naming the directory they searched
from, naming the demo project's root as a registry that does not cover the draft,
and naming `BACKDRAFT_HOME`, without mentioning `backdraft init`; with
`BACKDRAFT_HOME` set to the demo, the same bind runs. From a directory with no
registry anywhere above it, `backdraft read` and `backdraft bind memo.md` print
today's message byte for byte. None of these runs creates a `.backdraft/`
anywhere, asserted. `skills/backdraft/SKILL.md` and `site/llms.txt` say a draft
must live under its project or name it with `BACKDRAFT_HOME`. DESIGN row.

**Size.** One day.

### 16. After a re-ingest, nothing says which drafts cite the source that moved

**Intent.** `ingest`'s new-generation note says citations "may now report
`drifted`", that `bind` on a document citing the source says which, and names
`backdraft locate <document>` — without ever saying which documents. The project
holds the answer: every rooted bind writes its record under `.backdraft/records/`,
mirroring the draft's path relative to the project root
(`kernel.artifact.record_path`), and each record lists every token it cited. An
agent that ingests the revised T12 a user just dropped into a project with six
memos is told drift may have happened somewhere, and is left to re-bind all six
or guess. `show`'s `DRIFT_HINT` (2026-09-18) has the same gap from the other side:
it names `backdraft locate <doc.md>` with a placeholder, because `show` is handed
a token and never a document.

**Shape.** One reader in `registry/`, over `record_path`'s layout, since the
kernel is pure and `gate` may not import `cli`. It walks `.backdraft/records/`,
reads the slug of every token under each record's `claims[].citations[]` (parsing
only what it needs), maps each record back to its draft — directory and stem from
the record's location, suffix from its `doc_path` — keeps only drafts that still
exist, and skips and counts a malformed record rather than failing on it, since
failures are data. The registry's `bindings` rows are the alternative, and the
2026-09-17 row already rejected them for `locate` because they key on the path as
typed. `ingest`'s note then names each draft citing a regenerated source with the
exact `backdraft locate <draft>` to run, a count past a handful, and nothing new
when no draft cites it; `show`'s `DRIFT_HINT` names the drafts citing the drifted
token's slug and keeps the placeholder when none do. Display only: the exit codes
do not move and nothing is written.

**Acceptance.** In a scratch project with two memos, one citing `notes` and one
citing only another source, re-ingesting a changed `notes.md` names the first
memo and its `locate` command and not the second. Re-ingesting an unchanged
source prints exactly today's output, as does a registry with no records. A
record file holding invalid JSON does not break the ingest. `show` on a drifted
token names the citing memo's `locate` command. The walkthrough's
regenerated-corpus `ingest` block is re-captured from a scratch copy with no key
present, since the demo memo cites both regenerated sources and the note now
names it. README's "When a source changes" and `skills/backdraft/SKILL.md` say
the note names the drafts. DESIGN row.

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
  (generations, `drifted`, the word-diff, and `locate` for where a cited
  passage went) all exist; the missing piece is a diff-shaped report and a
  demo.
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
