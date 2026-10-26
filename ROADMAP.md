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

### 1. A draft outside its project is told there is no registry, about the wrong directory

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

### 2. After a re-ingest, nothing says which drafts cite the source that moved

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

### 3. `render` ships a draft edited after `bind` as if the record had judged it

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

### 4. An older backdraft reads a newer registry as if what it does not know were not there

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

### 5. `ingest` reports per source in columns an agent has to scrape

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

### 6. `forget` asks for confirmation without saying which drafts it will break

**Intent.** `forget` is the one command that takes something away, so it asks
first, and what it says is general: a token already written into a draft still
shows its receipt, and `bind` will report it `unresolved` naming the withdrawal.
Whether any draft in this project cites the source — the one fact that decides
whether forgetting it is tidying or breaking a memo the user is about to send —
is not said, though every rooted bind wrote its record under
`.backdraft/records/` listing every token it cited. An agent removing what looks
like a duplicate source cannot tell from the prompt that the memo it bound
yesterday cites only the duplicate.

**Shape.** Depends on the records reader in `registry/` that "After a re-ingest,
nothing says which drafts cite the source that moved" adds (the walk over
`record_path`'s layout that maps each record back to a draft that still exists
and skips a malformed record); if that item has not landed, land that reader here and
let that item reuse it. `forget`'s description before the prompt names each draft whose
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

### 7. `doctor` is read by agents and prints only columns

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

### 8. A `not_shown` cleared by `show` after `bind` reads like a citation read before writing

**Intent.** `not_shown` is the one status that says the author cited a passage
they never read, and it clears by being shown: `bind` flags it, the agent runs
the `backdraft show` the `next:` line names, re-binds, and the second report
says `resolved` with nothing to tell it from a citation read before the claim
was written. Friday 2026-10-16 tightened the wording (read the snippet, keep the
citation only where it says what the claim says), but wording is all that stands
between the check and an agent that shows every flagged token to make the run
green; and the record, the artifact and `verify` all carry the laundered
`resolved` onward. The project already holds the evidence: the previous bind's
record sits at `kernel.artifact.record_path`, and it names every citation it
flagged.

**Shape.** In `bind/cli.py`, before the record is overwritten, read the previous
record for the same document (front-walk only; a missing, unreadable or
backfill record means nothing to compare, and is skipped, not failed). A
citation — keyed by token and claim offset, the pair the report already uses to
tell line items apart — that the previous record called `not_shown` and this
run resolves is a *cleared* one. The report prints one `cleared:` line per such
citation, in the `! status:` line's shape but without the `!`, closing with how
long after the flagging bind its anchor was shown (the ledger's `shown_at`
against the previous record's `bound_at`), and one `next:`-style line saying the
claim was written before its evidence was read and stands only if the snippet
`show` printed says what it says. Display only: the status stays `resolved`, the
exit code and the record format do not move, and `--json` is untouched — the
DESIGN row should say why carrying "cleared" in the record was rejected (it
would be a fact about two runs written into a record of one, and a format
change). A first bind, and a re-bind with nothing cleared, are byte-identical to
today, pinned.

**Acceptance.** In a scratch project, bind a memo citing a chunk the session
never read (exit 2, `not_shown`), run the `show` the `next:` line names, and
re-bind: exit 0, and the report carries one `cleared:` line naming that token and
claim. Re-binding a third time prints no `cleared:` line (the previous record
now says `resolved`). A memo bound clean the first time, and `demo/`'s bind,
print exactly today's output. A previous record holding invalid JSON does not
break the bind. `skills/backdraft/SKILL.md`'s `not_shown` bullet names the line
and says to re-judge each claim it lists. DESIGN row.

**Size.** One to two days.

### 9. `verify`'s `next: not_shown` tells an auditor to mint into the author's session

**Intent.** Since 2026-10-14 `verify` re-checks `not_shown` against the session
the record names, and its report closes with `cli_context.NEXT_MOVES`' line for
it — `backdraft show <token> --session <the author's session>`. `verify` is the
recipient's command: the artifact skill tells an auditor to relay `next:` lines
rather than run them, but the line itself is an instruction, and anyone holding
the registry who follows it mints the token into the author's ledger, so the next
`verify` comes back clean. The audit's own report tells its reader how to erase
its finding. The same table is right for `bind`, whose reader is the author.

**Shape.** `NEXT_MOVES` stays the one owner, keyed now by the reader as well as
the kind: `bind`'s moves are today's, and `verify` gets its own wording for the
statuses where the author's move and the auditor's differ — `not_shown` above
all ("the author cited this without reading it; it is theirs to re-read and
re-bind — showing it here would clear the finding without answering it"), and
`drifted`/`unresolved`, whose fixes are re-binds of a document the recipient may
not hold. `receipt` and `recount` are already verify-only. Decide the key shape
(a `(reader, kind)` pair, or a second table checked total by the same test) and
write it down; the test that holds the table total and every command it names
real covers both readers. Display only, and `verify --json` does not move.

**Acceptance.** `verify` on an artifact whose record carries a `not_shown` the
ledger confirms closes with a `next: not_shown` line that names no `backdraft
show` and no `--session`; `bind` on the same draft still names the `show`.
`tests/test_next_moves.py` asserts both readers' tables are total over the
closed status set plus their own extra kinds. The demo's verify block, which
prints only `unresolved`, is regenerated if its wording moved and otherwise
byte-identical. `skills/backdraft-artifact/SKILL.md` stops having to say "rather
than running them" for this case. DESIGN row amending 2026-10-14's.

**Size.** One day.

### 10. `verify --json` carries the finding and not the move

**Intent.** `bind` and `verify` reports end with `next:` lines (2026-10-14), and
both `--json` forms carry none of it, by design for `bind`, whose `--json` is
the record's own bytes. `verify --json` is not the record: it is a
`verify-v1` object an agent reads instead of the report, and that agent — the
one running the artifact skill, or a CI step that posts an audit — gets the
`kind` of each finding and has to rediscover what to do about it from the
skill. The move is the part a parser most needs and the part the wording-churn
argument for `--json` was about.

**Shape.** `verify --json` gains a top-level `next` array, one object per kind of
finding present, `{kind, move}`, in table order — the same strings the report
prints, from the same `next_moves` call, so there is one owner and one ordering.
Additive under `verify-v1`'s unknown-keys rule, which 2026-10-14's `ledger` key
already relied on; the row says so. `bind --json` stays the record, and the row
says why its caller reads the move from `verify --json` or the report instead of
from a record field. If "`verify`'s `next: not_shown` tells an auditor to mint
into the author's session" has landed, the array carries verify's own wording.

**Acceptance.** `verify --json` on the demo artifact carries exactly one `next`
entry, `kind: "unresolved"`, whose `move` equals the report's `next:` line after
its `next: unresolved — ` prefix; an artifact with an edited receipt carries a
`receipt` entry first; a clean artifact carries `next: []`. Every other key of
the object is byte-identical, pinned against the existing JSON tests. SPEC
§ CLI's `verify-v1` paragraph, `spec/artifact.md` if it documents the object,
`site/llms.txt` and the artifact skill name the key.

**Size.** One day.

### 11. A search hit on a long page points at the whole page

**Intent.** Every search result block closes with `[Read the page: backdraft
read <slug> p<n>]`, and `show` does the same. On a 57-chunk web page that is
three windows starting at the navigation menu, when the agent wanted the
paragraph around one hit — which is exactly what the week's chunk selector
(`p1.c9-c14`, 2026-10-14) exists for and what nothing yet points at. The
walkthrough's own `search "renter-occupied"` hit is `p1.c24`, and the hint
sends the reader to `p1` from the top.

**Shape.** `gate/searcher.py` (the `seen` list behind the hint) and the
matching hint in `gate/reader.py`'s `show`. On a `page`-kind page with more
chunks than fit one default read window, the hint names the chunk range around
each hit — the hit's ordinal plus `READ_AROUND_CHUNKS` either side, clipped to
the page, merged where two hits' ranges touch — as `[Read around it: backdraft
read <slug> p1.c23-c25]`, carrying `--session` as today. A page that fits one
window keeps `[Read the page: …]` byte for byte, so every documented search on
the PDF and the workbook is unchanged; a sheet never gets the chunk form. The
hint is advice and mints nothing; the read it names mints what it prints, as
any chunk read does. Name the constant's value and the "fits one window" test in
the DESIGN row.

**Acceptance.** In a copy of `demo/`'s registry, `backdraft search
"renter-occupied"` closes with a `Read around it` hint naming a range that
contains `p1.c24`, and running that hint prints `p1.c24` and does not print
`p1.c1`. `backdraft search "24850000"` and every search block in
`demo/walkthrough.md` on `t12-summary` or `underwriting-model` is byte-identical.
`show bd:franklin-county:p1.c24:5678` names the same range. The walkthrough's
franklin-county search blocks are regenerated in a scratch copy, not
hand-edited, and `skills/backdraft/SKILL.md`'s long-page paragraph names the
hint. DESIGN row.

**Size.** One day.

### 12. A web page saved by hand ingests as a file and loses the address it came from

**Intent.** The 2026-08-05 row made a URL provenance, not identity: a fetched
page is identified by its snapshot and named everywhere by its URL. An agent
whose sandbox cannot reach the site, a page behind a login the user can open in
their own browser, and the walkthrough's own Wikipedia source — whose pinned
revision fetched on 2026-10-16 came back at 33,841 characters against the
34,141 the walkthrough documents, because the site's chrome moved around an
unchanged article — all have the same answer available: the user saves the
page, and `backdraft ingest saved.html` cites it as `saved.html`. The URL the
reader of the artifact needs is gone, and nothing can put it back, since no
command renames a source.

**Shape.** `ingest <file> --origin <url>` in `cli.py`, one source only (as
`--slug`), for a file the `html` extractor handles. Identity is the file's
bytes, exactly as for any file; `document_meta` records the `url` as the fetch
path does, with `saved_at` in place of `fetched_at` and an `asserted: true`
flag, because the tool did not fetch it and must not say it did. Every surface
that names a fetched source by its URL (`source_name`, `ls`, the gate's list,
`## References`) names this one by it too, and the artifact's source line says
"saved copy of <url>" rather than "fetched", so a reader can tell the two
provenances apart. The slug comes from the URL as the fetch path derives it,
unless `--slug` is given. Re-ingesting the same bytes with the same origin is
`unchanged`; a different origin on an ingested source is refused in
`--slug not applied`'s shape, since provenance is set once. If the artifact
format must carry `asserted`, that is a format change to `spec/artifact.md`,
and the row says whether it is additive under `artifact-v1`.

**Acceptance.** Fetch nothing: ingest a checked-in HTML fixture with `--origin
https://example.org/report`, and `ls`, `read`, `bind --bound`'s References and
the rendered artifact all name the URL, the artifact saying it is a saved copy.
The same fixture without `--origin` ingests exactly as today. `--origin` on a
PDF, on two sources, or with an `ftp://` value exits 1 naming why. Tokens minted
from the fixture are identical with and without `--origin`, diffed. SPEC
§ CLI, `spec/registry.md` for the meta key, README's web-page section,
`site/llms.txt` and the writing skill's sandbox paragraph follow. DESIGN row.

**Size.** Two to three days.

### 13. `show` on a drifted token prints the passage that took over its address as `now`, and never says the cited words only moved

**Intent.** `backdraft show <token>` is the first command an agent reaches for
when `bind` says `drifted`, and its block prints `cited:` then `now [<token>]:`
with whatever stands at the old locator in the current extraction — minting
that token, which reads as "cite this instead" — and closes with `DRIFT_HINT`
sending the reader to `locate`. Since 2026-10-21 the registry knows the
difference: `registry.relocate` says when the cited words
stand unchanged at exactly one new place, `bind` writes it as `moved_to`, and
the artifact's card stopped diffing the words against the unrelated passage.
`show` still shows that diff, so the one surface built to answer "what did this
token say, and what stands there now" is the one that has not learned the
answer, and the writer is sent to a second command for a fact the first one
had in hand.

**Shape.** `gate/reader.py`: in `show`'s drifted branch, beside the `current_at`
lookup `_drift_block` already takes, ask `relocate` (imported from
`registry`, as `current_at` is; a contained match carries `locate`'s qualifier). When the outcome is `moved`, the
block gains a line between `cited:` and `now`: `moved: the cited words stand
unchanged at <new token>`, and the `now` label says `now at that address (a
different passage) [<token>]:` so the second snippet is never read as an edit
of the first. Mint the moved token as the `now` token is minted: `show` mints
what it prints, and the snippet printed under `cited:` *is* the moved anchor's
snippet verbatim, so the session has been shown it — which is what lets a
writer go `show` → `locate --apply` → `bind` clean with no further `show`. The
DESIGN row says so, and says why `ambiguous` and `gone` add nothing (several
places is a choice `locate` lays out; nowhere is today's block exactly). The
`DRIFT_HINT` keeps its `<doc.md>` placeholder — item 2 in this queue is what
replaces it — but when every drifted token the run printed carried a move, the
hint names `locate <doc.md> --apply`. A sentence edited in place, and every
cell citation, print today's block byte for byte. Exit codes do not move.

**Acceptance.** In a scratch project shaped like `tests/test_locate.py`'s (three
paragraphs over 200 characters, one inserted above, re-ingest), `show` on the
second paragraph's old token prints the `moved:` line naming the token that
`locate` proposes for it, labels the `now` snippet as a different passage, and
leaves the new token in the session's ledger — asserted by `locate --apply`
then `bind` under the same session exiting 0 with no `not_shown`. `show` on a
token whose sentence was edited by one figure prints exactly today's block;
so does a cell token whose value stands in two cells. SPEC § CLI's `show`
paragraph, `site/docs.html`'s `show` row and the writing skill's `drifted`
bullet say what the line means. DESIGN row.

**Size.** One day.

### 14. `bind` knows which drifted citations only moved and reports none of it

**Intent.** Since 2026-10-21 `citation_for` writes `moved_to` on every drifted
citation whose words stand unchanged at one place, so the record knows, the
artifact says it, and `verify` carries it. The `bind` report that an agent
reads in the terminal still prints `! drifted: <token> — <claim> @<offset>` for
all of them alike, and its `next: drifted` line sends the caller to `backdraft
locate <doc>`, which recomputes exactly what `bind` just wrote and prints the
same list in its own shape. Thirty citations after a paragraph went in above
are thirty `drifted` lines, a `locate` run that says `moved: 30`, and then the
`--apply` — where the first report could have said the move and named the
command that makes it.

**Shape.** `bind/cli.py`'s line item, in `locate`'s own words: `! drifted: <old>
— now at <new> — <claim> @<offset>` when the citation carries `moved_to`, and
today's line when it does not. The `— now at` fragment has two owners then
(`cli.py`'s `_located_line` and the bind report) and `bind` may not import
`cli`, so the fragment moves to `cli_context` and both read it. The `next:`
line is `cli_context.NEXT_MOVES`' and stays one table: add a display kind
`drifted:moved` beside `unmatched`, `receipt` and `recount`, which `bind`
reports in place of `drifted` when *every* drifted citation present carried
`moved_to`, with the move `backdraft locate <doc> --apply{session}` then the
`show` the closing line of `locate` will name; a run with one drifted citation
edited in place keeps today's `next: drifted`. `tests/test_next_moves.py`'s
totality test gains the kind. `verify`'s source tier prints its line items
through the same path and gains the `now at` fragment too; its `next:` wording
is item 9's, not this one's. Display only: the record, `--json`, exit codes
and the statuses do not move, and a report with no drift is byte-identical.

**Acceptance.** In the scratch project of item 13, `bind` after the re-ingest
prints three `! drifted` lines each ending `— now at <new token>` before the
claim, and closes with `next: drifted:moved — … backdraft locate memo.md --apply
--session s1 …`; running that command and the `show` it names, then re-binding,
exits 0. Edit one cited sentence in place instead and the report's `next:` line
is today's `next: drifted` byte for byte, with that line item carrying no `now
at`. `bind --json` on both is unchanged against the current output, and
`demo/`'s bind prints exactly what it does. `skills/backdraft/SKILL.md`'s
`drifted` bullet names the line. DESIGN row amending 2026-10-13.

**Size.** One day.

### 15. `ingest --dry-run` says a PDF would go to the vision model and not how many pages that is

**Intent.** The 2026-10-19 row put the extractor on the dry run's line because
it is the one fact there that can cost money, and the note says `vlm` is a
model call per page. The number of pages is the cost, and the line does not
carry it: a two-page letter and a four-hundred-page appraisal print the same
`would extract with vlm`. An agent deciding whether to ask the user before
spending — the writing skill's first rule — has to open the PDF itself to find
out, and the ingest's own line, which does print the page count, prints it
after the money is spent. The count is local: `pdf-text` already opens every
PDF through pdfplumber without a model, and `len(pdf.pages)` costs nothing.

**Shape.** `Naming` (`registry/store.py`) gains `pages: int | None`: for a PDF
on disk, the count from a new `extract.pdf_text.page_count(path)` that opens
the file with pdfplumber and reads nothing else; for an image, 1; for a source
already ingested, its current generation's page count from `pages()`, which is
also what a re-extraction would send; `None` for every other media type and
for a URL, whose bytes are not here. A PDF pdfplumber cannot open is what the
ingest would fail on, so it is the dry run's `!` line with `pdf-text`'s own
reason, compared against the ingest's in a test as the 2026-10-19 row did. The
line's mark becomes `would extract with vlm, 12 pages` only where a count
exists, so every non-PDF line is byte for byte what it was; the vision note
closes with the sum, `12 pages → 12 model calls`, over the lines that would
spend. `VISION_EXTRACTORS` stays where it is. No key value can reach the
output; the existing canary test covers the new lines.

**Acceptance.** In a scratch project, the dry run on the test suite's PDF
fixture reads `would extract with pdf-text, N pages` with no key present and
`would extract with vlm, N pages` with a fake one, and the note then ends `N
pages → N model calls`; the key's value appears nowhere in either output. A
Markdown source, a workbook and a URL print exactly today's lines. A corrupt
PDF fixture is a `!` line whose reason equals the ingest's for the same file.
README's dry-run paragraph, `site/llms.txt`, `site/docs.html`'s `ingest` row
and the walkthrough's prose after its dry-run block (whose source is HTML, so
its captured output does not move) say the count is on the line. DESIGN row
amending 2026-10-19.

**Size.** One day.

### 16. A source re-ingested from where it moved to keeps the registry's old path, and every hint that names the path names a file that is gone

**Intent.** Identity is the bytes (2026-08-05), so re-ingesting an unchanged
file from a new path is a no-op: `Registry.ingest` finds the document by
`sha256`, `_is_noop` says nothing would change, and `_touch_meta` records only
a URL's re-fetch — `documents.path` keeps the old location. Everything that
names the path then names a file that is not there: `forget`'s and `ls
--withdrawn`'s way-back hint (`WITHDRAWN_HINT`, `backdraft ingest <old path>`),
the gate's refusal of a withdrawn slug, and `snapshot-pages`, which says the
source was not found and to pass `--file`. Renaming `drafts/` to `sources/` is
an ordinary afternoon in a diligence folder, and the user did the one thing
the docs say fixes it — ingested again — and was told `unchanged`.

**Shape.** The no-op branch of `Registry.ingest`: when the source is a file and
its path differs from the stored one, update `path` and `filename` in the same
transaction, and say so — `Ingested` gains `moved_from: str | None`, and the
line's mark reads `unchanged, was at <old path>` so a caller who did not know
the file had moved learns it here. `filename` feeds `source_name`, so `ls`, the
gate's list and `## References` follow by themselves; the slug does not move,
so no token does, which the test asserts by diffing tokens minted before and
after. A URL source is untouched (its stored path is the URL, and `_touch_meta`
already owns re-fetches). The same bytes present at two paths at once is the
case to decide and write down: the last ingest wins and the line says what it
replaced, because two documents for one set of bytes is what 2026-08-05 ruled
out. `spec/registry.md` says `path` is where the bytes were last ingested from.
Re-ingesting from the stored path prints exactly today's line.

**Acceptance.** In a scratch project, ingest `a/notes.md`, read it under a
session, move the file to `b/notes.md` and ingest again: the line says
`unchanged, was at a/notes.md`; `forget notes --yes`'s closing hint names
`b/notes.md`; `ls --withdrawn` names it; for a moved PDF, `snapshot-pages`
finds the file without `--file`. Tokens minted from `b/notes.md` after the move
equal those minted from `a/notes.md` before it. A re-ingest from the stored
path, and the demo's re-ingest of its unchanged sources, print byte for byte
what they print today. README's "Forgetting a source" paragraph says the hint
names where the file was last seen. DESIGN row.

**Size.** One day.

### 17. `search` and the table of contents never say which hits or chunks this session was already shown

**Intent.** `session show --in` (2026-10-20) answers coverage per document, but
the moment an agent actually chooses what to read next is a `search` block of
twenty hits or a fifty-seven-chunk table of contents, and neither marks what
the session has already been shown. So the agent `show`s a token it already
holds, or re-reads the chunk it read an hour ago, spending the budget the
chunk selector exists to save — or asks `session show --in` for every slug in
the list before every read. The ledger has the answer and the gate holds the
session: `was_shown` is one query, and both commands mint into that session
already.

**Shape.** `gate/searcher.py` and `render_toc` in `gate/reader.py`: a hit, and a
chunk row, whose token the session was shown *before this run* — asked before
`record_shown`, or the run marks everything it prints — carries a trailing
`shown` mark in `thin_mark`'s stance: a mark only on the rows that have one, so
a fresh session, and every documented block captured under one, prints byte
for byte what it does. Matched by token, as every ledger read is, so a chunk
that survived a re-ingest is marked and one whose text changed is not. The
default session marks against the shared ledger, which its existing note
already explains; the mark adds no note. Display only — minting, tokens, exit
codes and the hint lines do not move — and `show` is not marked: its caller
already holds the token.

**Acceptance.** In a copy of `demo/`'s registry under a fresh session,
`backdraft search "renter-occupied"` and `backdraft read franklin-county` print
exactly today's blocks; after `backdraft read franklin-county p1` under that
session, the same search marks its `p1.c24` hit `shown` and the table of
contents marks `c1`–`c25` and not `c26`–`c57`. The walkthrough's blocks are
checked in sequence in a scratch copy: a block whose hits an earlier block in
the walkthrough had shown is re-captured there, not hand-edited, and every
other block is byte-identical. `skills/backdraft/SKILL.md`'s search paragraph
says what the mark means. DESIGN row.

**Size.** One to two days.

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
