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

### 1. A small table is marked a shell, and the skill says not to cite it

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

### 2. `ingest --dry-run` names the source and not the run

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
output. Not the ground of `backdraft doctor`, which reports the machine; this
reports what one command will do to one source. `demo/walkthrough.md`'s dry-run block moves and is regenerated, not
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

### 3. `session show` counts what was read and cannot say what was not

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

### 4. An artifact word-diffs a drifted citation against whatever now stands at its old address

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

### 5. `locate` leaves the fix to hand edits of tokens, which the skill forbids

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

### 6. `locate` calls intact words `gone` when an insertion merged or split their chunk

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

### 7. A draft outside its project is told there is no registry, about the wrong directory

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

### 8. After a re-ingest, nothing says which drafts cite the source that moved

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

### 9. `render` ships a draft edited after `bind` as if the record had judged it

**Intent.** `render` reads two files, the draft and the record `bind` wrote for
it, and never checks that they still describe the same text. Checked on
2026-10-09 in a scratch project: bind a memo with one resolved citation, then add
a sentence citing `bd:notes:p1.c1:ffff` — a token no gate ever emitted — and
`backdraft render memo.md` writes the artifact at exit 0 with that claim in it
and not a word said. An agent's normal loop is draft, bind, fix a sentence,
render, so the commonest way to ship an unchecked citation is not to skip `bind`
but to edit after it, and the artifact — the file whose whole claim is that every
citation in it was checked — is the thing that carries it out.

**Shape.** `render/cli.py`, before anything is written: parse the draft with
`kernel.claims.parse_claims` and compare it against the record's `claims` on what
a claim is — its text, its tokens in order, and its `start`/`end`, since render
places each claim by offset and a shifted offset misplaces every highlight after
it. Any difference is a `UsageError` (exit 1, the code `render` already uses for a
record it cannot use) naming how many claims differ, the first one by offset, the
record's `bound_at`, and the one fix: `backdraft bind <doc>` then render again.
No artifact-format change — the comparison uses what the record already carries;
a content hash of the draft in the record is the alternative and is a format
change, so name it in the DESIGN row and say why it lost. Prose edits outside any
claim that move no offset render as today. `verify` is not touched: it checks an
artifact against itself, and the artifact embeds the draft it was rendered from.

**Acceptance.** The scratch repro above exits 1 with the message, and no
`memo.backdraft.html` is written or overwritten (assert the old file's bytes are
unchanged). Re-binding then rendering succeeds. An edit that changes no claim and
no offset (a typo fixed after the last claim) renders byte-identical to before.
`demo/`'s render is byte-identical. `render --help`, README's render section,
`site/docs.html`, `site/llms.txt` and `skills/backdraft/SKILL.md` say that render
refuses a draft edited since bind. DESIGN row.

**Size.** One to two days.

### 10. An older backdraft reads a newer registry as if what it does not know were not there

**Intent.** The registry travels with the project folder — the documented answer
to a sandbox that cannot reach the vision model is to ingest locally and hand the
folder over — so registries routinely meet a different backdraft than the one
that wrote them. The schema has grown by adding tables (`document_meta`,
`withdrawals`, `page_meta`) under idempotent `CREATE ... IF NOT EXISTS` DDL, and
nothing records which backdraft last wrote a registry. So a registry with a
`withdrawals` row, opened by a release from before `forget`, lists the withdrawn
source in `ls` and binds its citations `resolved`; the older binary cannot know
it is missing anything, and nothing tells it. The same will happen to every
table added from here on.

**Shape.** `registry/store.py`'s `Registry.open` and `schema.sql`. Give the
schema an integer version, stamped with `PRAGMA user_version` (SQLite's own slot,
no table needed), bumped by any change that adds meaning an older reader would
silently drop. `open` reads it after the DDL: a registry stamped lower is stamped
up (the DDL already made it current); one stamped higher than this build knows
raises `RegistryError` naming both numbers and the fix (upgrade backdraft), at
exit 1 through the guard, before anything is written. Releases from before the
stamp cannot be fixed by it, which the DESIGN row must say plainly: the guard
protects every pair of versions from this one on. `doctor`'s registry line shows
the schema version; `export` carries it. SPEC Addendum A and `spec/registry.md`
name the stamp, since another implementation opening the same file must honour
it.

**Acceptance.** A registry created by this build carries the current
`user_version`. An existing registry with `user_version` 0 opens and is stamped,
with every existing test unchanged. A registry whose `user_version` is set one
higher refuses every verb with the message and exits 1, and `doctor` reports it
as the registry's gap at exit 0; assert the file's bytes are unchanged after both.
DESIGN row.

**Size.** One to two days.

### 11. `ingest` reports per source in columns an agent has to scrape

**Intent.** `bind` and `verify` gained `--json` (2026-09-14) because their output
is read by agents and every wording fix silently broke a parser. `ingest` is the
other command an agent reads closely and acts on, and its line is two-space
separated fields whose name column is a URL or a filename that may hold spaces,
followed by marks that now come in five kinds — `unchanged`, `new generation`,
`restored`, `--slug not applied`, and the `!` failure lines after a count — with
the notes that explain them in prose below. An agent ingesting a folder has to
pull the slug of each source out of that to cite it, and tell a thin source, a
failed one and a renamed-refused one apart by matching sentences this repo
rewords most weeks.

**Shape.** `--json` on `ingest` in `cli.py`, printing one object instead of the
report, with the exit codes exactly where they are. Per source: `source` as
typed, `slug`, `name` (`source_name`), `media_type`, `pages`, `chars`, `outcome`
(`Ingested.outcome`'s values), `restored`, `slug_applied` (null when no `--slug`
was given), `thin` (bool, by `gate.THIN_SOURCE_CHARS`), `snapshots` (captured,
not captured with the reason, not applicable); failures as `{source, reason}` with
the reason string the `!` line prints. Run-level: the notes as an array of the
same strings the report prints, so one owner per wording still holds. Built from
the same values the report is built from — collect first, then present twice,
the 2026-09-14 shape — not a second walk. `--dry-run --json` is the same object
with `outcome: "would-ingest"` or the dry run's own marks, or is refused; decide
and say which in the row.

**Acceptance.** A test ingests a fresh file, an unchanged one, a changed one, a
withdrawn one and a missing path in one `--json` run and asserts each object's
fields and the exit code (1, for the missing path). The report without `--json`
is byte-identical, pinned. `site/llms.txt`, `skills/backdraft/SKILL.md`,
`site/docs.html` and SPEC § CLI name the flag and its object. DESIGN row.

**Size.** Two days.

### 12. `forget` asks for confirmation without saying which drafts it will break

**Intent.** `forget` is the one command that takes something away, so it asks
first, and what it says is general: a token already written into a draft still
shows its receipt, and `bind` will report it `unresolved` naming the withdrawal.
Whether any draft in this project cites the source — the one fact that decides
whether forgetting it is tidying or breaking a memo the user is about to send —
is not said, though every rooted bind wrote its record under
`.backdraft/records/` listing every token it cited. An agent removing what looks
like a duplicate source cannot tell from the prompt that the memo it bound
yesterday cites only the duplicate.

**Shape.** Depends on item 8's records reader in `registry/` (the walk over
`record_path`'s layout that maps each record back to a draft that still exists
and skips a malformed record); if 8 has not landed, land that reader here and
let 8 reuse it. `forget`'s description before the prompt names each draft whose
record cites the slug and how many citations each would turn `unresolved`, a
count past a handful, and nothing new when none does. `--yes` prints the same
lines before withdrawing, since an agent passing `--yes` is the caller most in
need of them in the output it reads afterwards. Display only: the prompt's
question, the exit codes and the withdrawal itself do not move. The records
reflect the last bind, not the draft's current text, and the wording must say
"as last bound".

**Acceptance.** In a scratch project with two bound memos, one citing `notes`
and one not, `backdraft forget notes --yes` names the first memo and its citation
count and not the second. A registry with no records prints exactly today's
output, pinned. A record file holding invalid JSON does not stop the forget. The
`forget` row in `site/docs.html` and the forget paragraph in README say it names
the drafts.

**Size.** One day, two if it lands the records reader.

### 13. `doctor` is read by agents and prints only columns

**Intent.** The writing skill's first instruction is now "Run `backdraft doctor`
before you promise anything" and plan from its `missing` lines. An agent does
that by scraping aligned columns whose third field is a sentence, whose
continuation lines are told apart by leading spaces, and whose summary is a
bracketed line — the shape `bind --json` and `verify --json` (2026-09-14) were
added to stop agents depending on. The capability set will grow; each new line
moves the column widths.

**Shape.** `--json` on `doctor` in `cli.py`, printing one object from the same
`_Capability` list the report is built from: per capability `name`, `ready`
(bool), `gap` (the verb's own string, or null), `costs` (null when ready),
`ready_detail`, and `key` as `{name, set}` where the capability spends one —
never a value. The registry's entry carries the root and document count as
fields. Exit 0 always, as today. Document the object in SPEC § CLI beside
`doctor`'s paragraph; it is not part of the artifact format and does not go in
`spec/`.

**Acceptance.** A test runs `doctor --json` with everything missing and with
everything ready (the existing fixtures), parses it, and asserts every field; a
test with a fake key set asserts its value appears nowhere in the output. The
report without `--json` is byte-identical, pinned. `skills/backdraft/SKILL.md`
tells an agent to read `doctor --json`; `site/llms.txt` and `site/docs.html`
name the flag.

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
