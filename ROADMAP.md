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

### 1. `spec/registry.md`: the export format is normative, or it is not a format

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

### 2. `search` says when it stopped short

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

### 3. The bind report says why a verifier skipped

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

### 4. `session show` says what the ledger holds

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

### 5. An unreadable source says what to do, not what errno it was

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

### 6. A registry can forget a source

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

### 7. Bind's markdown names a fetched source by a file nobody has

**Intent.** The 2026-08-18 row made `gate.source_name` the one owner of what a
source is called and named the one surface it could not reach — bind, because
`bind` → `gate` is a sideways import SPEC forbids. The exception is larger than
that row said. `binder.py`'s `_doc_name` returns `document.filename`, and it
feeds both the generated `## References` section of `bind --bound` and the
proposals in the unmatched-claims section, so the markdown projection — the
form that travels into a pull request or an email, where the HTML artifact
cannot follow — calls the demo's Wikipedia article `index.html`. Bind the demo
with `--mode backfill --bound` and `memo.bound.md` says
`**[2]** index.html — p1.c11 — resolved` for a source that `render --to
footnotes` names `**franklin-county** · <https://en.wikipedia.org/…>` and the
artifact names `Franklin County`. Two of backdraft's own output formats
disagree about what a source is, and the one that disagrees is the one a reader
gets without a browser.

**Shape.** Answer the dependency objection rather than working around it.
`source_name` is a pure function of a `Document`, and `Document` lives in
`kernel/model.py`, which `gate` and `bind` both import *downward* from — so the
kernel is the owner the rule was always looking for, and it stays stdlib-pure
there. Decide and write down whether `gate.source_name` becomes a redirect or
whether callers move to the kernel path, remembering that kernel API in this
repo is module paths rather than flat re-exports, and that `cli.py` imports
`gate.source_name` today and SPEC § Gate names it. Leave the render side alone:
`render/html/text.source_title` and `render/footnotes._origin` read a `url` off
the *artifact's* `docs` dict, a different shape from a `Document`, and they are
already correct — say so in the row rather than letting the next reader think
they were missed.

**Acceptance.** Add an uncited claim to a copy of `demo/memo.md`, run `bind
memo.md --mode backfill --bound`, and `memo.bound.md` contains no `index.html`
and names the URL in both its References entries and its unmatched proposals.
A References entry for a *file* source is byte-identical to today's — pin it,
the way the file rows of the gate's list are pinned. `render --to footnotes` is
unchanged. SPEC's dependency rule and § Gate are updated, and the 2026-08-18
row gains its correction: the exception it accepted is now closed and the row
should say how.

**Size.** Two days.

### 8. A web page has a name, and `read` shows it the navigation menu instead

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

### 9. A page read has no budget and no closing line

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

### 10. The thin-source signal exists only in the ingest that printed it

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

### 11. What a URL will be called, before the answer is permanent

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

### 12. Math in a document renders as math, or says it could not

**Intent.** An agent writing a memo about coverage, a rate, or a model's output
writes what any author would write — `$\mathrm{DSCR} = \frac{NOI}{D}$` — and the
artifact hands the reader raw TeX. At worst it hands them corrupted TeX: today
`$x_1$ and $x_2$` renders as `$x<em>1$ and $x</em>2$`, because the two
subscripts pair into markdown emphasis, and `\(a^2+b^2=c^2\)` renders as
`(a^2 + b^2 = c^2)` because `_BACKSLASH_RE` eats the delimiters as escapes. Both
failures are silent and both are data-dependent — `$x_1$` alone survives, so the
corruption appears only in the real document. A document nobody can read is not
a lesser artifact, it is a broken one, and unrendered TeX is not a destination:
forbidding math outright would be better than shipping it.

**Shape.** `render/markdown.py`. Math spans get masked the way code spans
already are — `_INLINE_RE` and the `stash`/`_mask_spans` machinery is the
existing mechanism — for `$...$`, `$$...$$`, `\(...\)` and `\[...\]`, so nothing
inside a math span is ever seen by the emphasis or backslash-escape passes.
Conversion is `latex2mathml` (pure Python, zero dependencies, 312 KB installed,
MIT), declared as an optional extra `[math]` in the mould of `[vlm]` and
`[entail]`. The output is MathML: static markup that browsers lay out natively,
so there is no script, no font file and no external request, and artifact rules
1 and 2 hold by construction rather than by promise — this is the whole reason
not to inline KaTeX, which would cost roughly a megabyte of fonts on every
artifact whether or not it contains math. This is display-only: the sidecar
keeps the authored source text, and no token, snippet or hash moves.

Failures are data here too, and the boundary is uneven, so pin it. `latex2mathml`
raises typed errors for some malformed input (`}{` and the empty string raise
`NoAvailableTokensError`, `\begin{bmatrix} a` raises `MissingEndError`) and
silently degrades for the rest (`\notacommand{x}` becomes `<mi>\notacommand</mi>`,
`\frac{a` becomes a one-argument `mfrac`). A raise is a failure the artifact must
show at the claim in rule 6's shape, not a warn-and-drop and not a traceback. The
silent class cannot be caught and must be named as a known limit rather than
papered over. Without the extra installed, math must still never be *corrupted*:
the span stays masked and is emitted verbatim in a `.math` span — the degradation
path, not the goal.

**Acceptance.** Render a document carrying inline math, display math and both
delimiter styles, once with the extra and once without. With it, the artifact
contains `<math>` elements and no `$`-delimited source; without it, the artifact
contains the TeX verbatim with no `<em>` anywhere inside a math span. In both,
the `default-src 'none'` meta tag is intact and the file renders from `file://`
with the network down. Malformed math surfaces at the claim and in the Notes with
a reason. Mint the demo's tokens before and after and diff them: unchanged.
Update `spec/artifact.md` where it enumerates what the HTML form may contain, and
`skills/backdraft/SKILL.md` so an agent knows math is allowed and what happens
without the extra.

**DESIGN row.** MathML over a bundled renderer: why (self-containment survives,
no fonts, no script) and the tradeoff that makes it non-obvious — MathML leans on
a system math font, so two readers of one artifact may see different glyph
quality, which is the one soft spot in the "fixed at render" promise of rule 7.

**Size.** Two days.

### 13. Prose with two snake_case names is silently corrupted

**Intent.** `the snake_case_name field` renders as `the
snake<em>case</em>name field`, and `call foo_bar and baz_qux` as `call
foo<em>bar and baz</em>qux`. CommonMark forbids intraword `_` emphasis — that is
the entire reason `_` and `*` have different delimiter rules in the spec — and
`render/markdown.py` does not implement the rule, so any memo naming two
snake_case identifiers in one paragraph has its text quietly rewritten. This is
independent of math and worse than the math case, because nothing signals it:
the author sees prose, the reader sees prose, and the two are not the same
prose. A tool whose whole claim is that a document's text is checkable cannot
silently alter that text.

**Shape.** `_INLINE_RE` in `render/markdown.py`. Implement CommonMark's
left/right-flanking delimiter run rule for `_`: a `_` flanked by alphanumerics on
both sides is never a delimiter. `*` is unaffected and its behavior must not
move. Nothing currently pins the deviating behavior — `tests/test_render_markdown.py:27`
pins `__bold__` and `_italic_`, both of which must keep working — so this is a
fix, not a format change; note in the commit that no golden file moves.

**Acceptance.** `snake_case_name`, `foo_bar and baz_qux` and `a_b_c` survive
verbatim through `inline` and `to_html`; `_italic_`, `__bold__` and `*em*` are
unchanged; the emphasis cases in `tests/test_render_markdown.py` pass untouched;
`uv run backdraft render` over `demo/memo.md` produces a byte-identical artifact,
since the demo contains no `<em>` today and none should appear.

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
