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

### 1. `verify --json` carries the finding and not the move

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
from a record field. The array carries the auditor's wording (2026-11-10), not
`bind`'s.

**Acceptance.** `verify --json` on the demo artifact carries exactly one `next`
entry, `kind: "unresolved"`, whose `move` equals the report's `next:` line after
its `next: unresolved — ` prefix; an artifact with an edited receipt carries a
`receipt` entry first; a clean artifact carries `next: []`. Every other key of
the object is byte-identical, pinned against the existing JSON tests. SPEC
§ CLI's `verify-v1` paragraph, `spec/artifact.md` if it documents the object,
`site/llms.txt` and the artifact skill name the key.

**Size.** One day.

### 2. A search hit on a long page points at the whole page

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

### 3. A web page saved by hand ingests as a file and loses the address it came from

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

### 4. `show` on a drifted token prints the passage that took over its address as `now`, and never says the cited words only moved

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
`DRIFT_HINT` names each citing draft's `locate` (2026-10-28, `gate.reader.drift_commands`),
or its `<doc.md>` placeholder when no record cites the slug — and when every drifted token the
run printed carried a move, each command it names gains `--apply`. A sentence edited in place, and every
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

### 5. `bind` knows which drifted citations only moved and reports none of it

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
belongs to "`verify`'s `next: not_shown` tells an auditor to mint into the author's
session", not this one. Display only: the record, `--json`, exit codes
and the statuses do not move, and a report with no drift is byte-identical.

**Acceptance.** In the scratch project of "`show` on a drifted token prints the
passage that took over its address as `now`", `bind` after the re-ingest
prints three `! drifted` lines each ending `— now at <new token>` before the
claim, and closes with `next: drifted:moved — … backdraft locate memo.md --apply
--session s1 …`; running that command and the `show` it names, then re-binding,
exits 0. Edit one cited sentence in place instead and the report's `next:` line
is today's `next: drifted` byte for byte, with that line item carrying no `now
at`. `bind --json` on both is unchanged against the current output, and
`demo/`'s bind prints exactly what it does. `skills/backdraft/SKILL.md`'s
`drifted` bullet names the line. DESIGN row amending 2026-10-13.

**Size.** One day.

### 6. `ingest --dry-run` says a PDF would go to the vision model and not how many pages that is

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

### 7. A source re-ingested from where it moved to keeps the registry's old path, and every hint that names the path names a file that is gone

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

### 8. `search` and the table of contents never say which hits or chunks this session was already shown

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

### 9. A drifted citation whose words now span two chunks has no `moved_to`, so its card diffs them against half a passage

**Intent.** Since 2026-10-26 `locate` proposes `a;b` when a cut now runs
through the cited words, and `--apply` writes the pair. `bind` does not record
it: `_moved_to` in `registry/store.py` writes none for a span, because
`moved_to` is one token in `spec/artifact.md`. So a reader of the artifact — or
an auditor following `skills/backdraft-artifact/SKILL.md`, which says "without
`moved_to` the words were edited, removed, or stand in several places" — is
told the claim may have failed, and the card word-diffs the cited words
against the first piece, when nothing changed but a cut. DESIGN.md's Open list
carries exactly this question; it should be decided rather than left there.

**Shape.** Decide for an additive optional key, not a second meaning of the
pinned one: a `drifted` citation may carry `moved_across`, a list of exactly
two tokens, the adjoining chunks that together hold the cited words, written
only when `relocate` returns `MOVED` with a two-anchor place — so `moved_to`
keeps its meaning and a consumer that does not know the new key reads today's
record. `Citation` in `kernel/model.py` gains the field and its `to_dict`/
`from_dict` round trip; `_moved_to`'s neighbour in `store.py` fills it; the
artifact card in `render/` treats it the way it treats `moved_to` (where the
words stand, no word-diff), naming both tokens; the footnotes projection
follows. `spec/artifact.md` gains the key in the citation table and the
`moved_to` paragraph, still `artifact-v1` because it is optional. The golden
record and artifact fixtures move only where a fixture holds a span — say so
in the commit. The artifact skill's `drifted` row learns the key. DESIGN row
closing the Open bullet.

**Acceptance.** `tests/test_locate.py`'s grown-paragraph case, bound after the
re-ingest: the record's citation carries `moved_across` equal to the two
tokens `locate` proposes and no `moved_to`; the rendered card says the words
stand across those two tokens and draws no diff. Every existing golden
artifact without a span is byte-identical. A record written before this change
renders exactly as it does today. `backdraft verify` on the new artifact exits
as before — the key is not part of the receipt checks.

**Size.** Two days.

### 10. The drafts named after a new generation may have been edited since their bind, and the note cannot tell which

**Intent.** `ingest`'s new-generation note and `show`'s drift hint name the
drafts whose records cite a source "as last bound", and the writing skill has
to warn the agent that "a draft you have edited since its last bind may cite
more or less than the note says". The repo can already tell: `render`'s
`_edited_since_bind` in `render/cli.py` compares a record's claims against the
draft on disk, with no format change. An agent with three drafts open learns
which records are stale only by running `render` on each and reading a
refusal.

**Shape.** Move `_edited_since_bind` and `_signature` out of `render/cli.py` to
one owner both the renderer and `registry/records.py` can import without
breaking the dependency rule — the kernel, since it is pure over a source
string and a `BindReport` (`kernel/claims.py` already holds `parse_claims`),
returning a small result (count and first differing claim) that `render`
formats into today's message byte for byte. `CitingDraft` gains `edited: bool`,
computed in `scan_records` only for drafts it is about to return (one read
and one parse per citing draft, not per record). `_citing_note` and
`drift_commands` append `(edited since)` to a draft's command when it is set.
No change when no draft is edited.

**Acceptance.** In `tests/test_citing_drafts.py`'s two-memo project, add a
claim to `memos/q3.md` after its bind and re-ingest `notes.md`: the note names
`` `backdraft locate memos/q3.md` (edited since) ``, and `show` on the drifted
token ends the same way; an unedited project prints exactly today's lines.
`render`'s refusal tests pass unchanged. The writing skill's sentence about
edited drafts is replaced by what the mark means.

**Size.** One day.

### 11. `bind` under a different session than the draft's last bind says nothing, and every citation turns `not_shown`

**Intent.** An agent that loses its context, or a fresh shell without
`BACKDRAFT_SESSION` exported, re-binds a draft with no `--session`: the run
judges against the shared `default` ledger, and every citation the writer
really read comes back `not_shown`. The report reads like the agent cited
things it never read, and the skill's response to `not_shown` is to go read
them again — budget spent recovering a ledger that was never lost. The
draft's previous record says which session it was bound under; `render`'s
refusal now names it (0.16.0), and `bind` itself is the place it matters most.

**Shape.** In `bind/cli.py`, after `resolve_session`, read the existing record
at `record_path` (or the sidecar fallback) for its `session_id` only — a
missing or unreadable record is silence. When it differs from the session
this run resolved, print one `note:` line before the report: the session it
was last bound under, the one this run uses, and the exact re-run with
`--session <previous>` (shell-quoted, `session_argument`'s style). A note, not
a refusal: switching sessions on purpose is legitimate, and verifiers never
gate. Exit codes do not move. No note when the sessions match or when there
is no previous record.

**Acceptance.** Bind `memo.md` under `--session s1`, then bind again with no
flag and no exported session: the note names `s1`, `default`, and
`backdraft bind memo.md --session s1`; the report's `not_shown` counts are
unchanged from today (the note explains, it does not alter). Re-binding
under `s1` prints exactly today's output. The demo's `bind` in
`demo/walkthrough.md` is byte-identical. The writing skill's `not_shown`
paragraph says to read the note before re-reading anything.

**Size.** One day.

### 12. A record the scan cannot read is counted, never named, so the "may be short" warning has no next step

**Intent.** `scan_records` skips a record that is not valid JSON or not a
record's shape and counts it; `ingest`'s note then says "1 record under
`.backdraft/records/` could not be read and was skipped, so this may be short"
and stops. The calling agent knows the list of affected drafts is incomplete
and has no way to find which draft is missing or what to do — the error
message says what went wrong and not what to do next. Records also outlive
their drafts silently: a renamed draft's record names a path that is gone and
is dropped without a word, so the note misses the draft at its new name until
it is re-bound.

**Shape.** `RecordScan` in `registry/records.py` gains `unreadable:
tuple[Path, ...]` (record paths, sorted) in place of a bare count — `skipped`
stays as a property for the callers that count — and `orphaned:
tuple[Path, ...]`, the drafts a readable record names that no longer exist.
`_citing_note` names the first unreadable record by its path relative to the
project and says the fix: re-bind the draft it was written for, or delete the
file if that draft is gone; past one, it counts the rest via `gate.reader.
handful`. Orphans are reported only when one of them cited a regenerated
slug — "a record for `old/memo.md`, which no longer exists, cites notes; if
the draft moved, bind it at its new path" — so an untouched project prints
nothing new.

**Acceptance.** In `tests/test_citing_drafts.py`: a broken record yields a
note naming `.backdraft/records/broken.backdraft.json` and the re-bind advice;
a draft renamed after its bind yields the orphan line naming the old path; a
project with neither prints exactly today's note. `scan_records`' existing
tests pass with `skipped` unchanged.

**Size.** One day.

### 13. `relocate` re-reads a whole document for every drifted chunk citation it cannot find exactly

**Intent.** `current_within` (2026-10-26) is a pass over every current chunk of
the cited document — `registry.pages` plus `anchors_for_page` per page, then a
normalize of every snippet — and `relocate` runs it once per drifted citation
whose exact snippet stands nowhere. `bind` calls it through `citation_for`,
and `locate` through `_drifted`, so a memo with thirty citations into a
four-hundred-page filing that just gained a generation re-reads and
re-normalizes that filing thirty times, inside `bind`, which agents run after
every edit. The cost is invisible until the corpus is real.

**Shape.** Keep `relocate(registry, cited)` as the public rule and give the
pass a per-document cache that lives for one run: a `DocumentChunks` value
(pages, ordered chunks, normalized texts) built once per slug, and
`current_within` taking it. The owner of the cache is the caller's loop —
`bind.binder` and `cli._drifted` — passed as an optional argument so a lone
call still works; no module-level state, no new index, no schema change. The
outcome of every relocation is unchanged, which the existing
`tests/test_reingest.py` and `tests/test_locate.py` cases pin.

**Acceptance.** A test with a counting wrapper around `Registry.pages` binds a
memo of ten drifted citations into one re-chunked source and asserts one
`pages` call for that slug, not ten; every existing relocate, locate and bind
test passes unchanged; `uv run backdraft bind memo.md` in `demo/` prints
byte-identical output.

**Size.** One day.

### 14. A link whose href is a token missing `bd:` binds as prose, and `bind` says `0 claim(s)` at exit 0

**Intent.** `kernel.tokens.is_token_href` counts a link as a citation only when
a piece starts with `bd:`, deliberately, so an ordinary URL is never judged. But
`search` prints every hit as `[bd:notes:p1.c1:2d79]` inside brackets, and an
agent pulling the token out of that line, or out of a `show` it ran, routinely
drops the scheme along with the bracket: `[Income rose eleven percent](notes:p1.c1:2d79)`.
That draft binds `bound 0 claim(s), 0 citation(s)` at exit 0, writes a record
that judged nothing, and renders an artifact whose claims are plain links. The
hook that gates on exit 2 passes it. Nothing in the output connects "0 claims"
to the cause, and a memo with a mix of both forms reports a lower count that
looks plausible. Found running the README's `forget` example during the
2026-11-06 maintenance pass.

**Shape.** Add `kernel.claims.bare_token_links(text) -> list[BareLink]` beside
`parse_claims`, stdlib-pure: every markdown link whose href is not a token href
but would be one with `bd:` prepended to a piece, by the strict
`kernel.tokens.validate` (so a URL, a relative path or `mailto:` never matches),
with its offset, line and link text. `bind/cli.py` prints one note under the
summary line when the list is non-empty: the count, up to `gate.reader.HANDFUL`
of them as `line N: [text](href)`, the corrected href for the first, and
`backdraft bind <doc>` to run after fixing. The note is display only. The
record, `parse_claims`, exit codes and `bind --json` stay as they are, because
what counts as a claim is `spec/tokens.md`'s grammar and the record is a
pinned format. The DESIGN row names the alternative and why it lost: parsing
these as `malformed` citations would surface them in the record and exit 2,
but it changes the portable grammar for a typo the report can name.
`backdraft render` prints the same note, since it is the last command before
the artifact leaves. Update `skills/backdraft/SKILL.md` and
`skills/backdraft-backfill/SKILL.md`, which should both say the href is the
whole `bd:` token.

**Acceptance.** A draft with one `bd:` citation and two bare-token links binds
`1 claim(s)` at exit 0 and prints the note naming both bare links with their
lines and the corrected href. A draft holding `[site](https://example.com/p1.c1)`,
`[x](./notes.md)` and `[y](notes)` prints no note. The first draft's record
carries exactly one claim and its `summary` reads as it did before the change,
so the note touched nothing written. `uv run backdraft bind memo.md` in `demo/`
prints byte-identical output.

**Size.** One day.

### 15. `locate` is the command an agent acts on token by token, and it has no `--json`

**Intent.** `locate` prints `moved`, `ambiguous` and `gone` as prose lines in
`bind`'s shape. An agent that wants to apply only some swaps, or pick among an
`ambiguous` citation's places, has to parse those lines: the places are cut at
three with `and N more`, the `contained` and `span` qualifiers are clauses
inside the sentence, and a span's proposal is two `;`-separated tokens. Every
other command an agent acts on (`bind`, `verify`, `ingest`, `doctor`) now
answers `--json`, so `locate` is the one where acting on a drifted citation
still means scraping the sentences this repo rewords most weeks.

**Shape.** `--json` on `cli.locate`, printing one `backdraft/locate-v1` object
through `cli_context.print_json` and specified in SPEC § CLI beside
`backdraft/ingest-v1`, for the same reason: it is command output, not the
artifact. Collect the rows `_drifted` already builds, then present them twice,
as `ingest` does (2026-11-03), so the report is byte-identical. Top level:
`format`, `document` (as typed), `applied` (bool, whether `--apply` ran),
`citations`, `next` (the closing commands as strings). Each citation:
`claim` as `{start, end, text}`, `token`, `status` (`moved`, `ambiguous` or
`gone`), `proposal` (the new token, a span's two `;`-joined, or null),
`match` (`exact`, `contained` or `span`, from `Relocation.contained` and the
span case; null for `gone`), `places` as every place `relocate` found, uncut,
each a list of tokens, and `applied` (bool). Exit codes do not move, and a run
that cannot start prints nothing on stdout. `--apply --json` reports what was
written in the same keys. Update README, `site/llms.txt`, `site/docs.html` and
`skills/backdraft/SKILL.md`.

**Acceptance.** A test project (reusing `tests/test_locate.py`'s fixtures)
with one each of exact `moved`, `contained`, `span`, `ambiguous` with four
places, and `gone` prints an object whose five entries carry those statuses
and matches, the ambiguous one listing all four places. `--apply --json` marks
the three moved entries `applied: true` and the draft holds their proposals.
The plain report is byte-identical against output captured before the change,
and no ledger, session or record row is written either way.

**Size.** Two days.

### 16. An agent takes its tokens out of `search`'s prose, and the snippet it sees is elided

**Intent.** `search` is how an agent finds what to cite, and its output is the
`N results for "..."` header, each hit as `[bd:slug:locator:hash]  slug pN`,
and a snippet cut to a line with `...`. The agent regexes the token out of the
bracket (the 2026-11-06 maintenance pass kept the closing `]` doing exactly
this), and cannot see the whole verbatim snippet it is about to cite without a
`show` per hit. The result list is the gate's main output and the least
parseable one.

**Shape.** `--json` on the gate's `search` command (`gate/cli.py`, rendering
in `gate/searcher.py`), one `backdraft/search-v1` object through
`cli_context.print_json`, specified in SPEC § CLI. It shows exactly what the
plain run shows and mints exactly the same ledger rows, because the ledger
records what the session was shown, so the two forms must not differ in what
counts as shown. Keys: `format`, `query`, `in` (slug or null), `session`,
`limit`, `truncated` (bool, the run hit `--limit`), `hits` (each `token`,
`slug`, `page`, `kind`, `snippet` as the anchor's full verbatim text, which the
session has now been shown, and `read`, the page-read command), and `notes`
(the report's own strings). The DESIGN row records that the full snippet in
`--json` does not widen what the ledger means: the anchor is minted to the
session whole either way, and the plain report elides only for width. If
ROADMAP item 8's shown-before marks land first, they become a `shown_before`
key here, and whichever lands second adds it.

**Acceptance.** For the same query in two fresh sessions, one plain and one
`--json`, the tokens are identical and in the same order, and `backdraft
session show` lists identical anchors for both sessions. Each hit's `snippet`
equals the snippet `backdraft show <token>` prints. `--limit 1` on a
two-hit query sets `truncated: true`. An unknown `--in` slug exits 1 with
stdout empty. The plain output is byte-identical to before.

**Size.** Two days.

### 17. The skills preview a withdrawal by running `forget` without `--yes` and counting on it to refuse

**Intent.** `forget` now names the drafts a withdrawal would break (2026-11-04),
and both skills tell the agent to see that list by running `backdraft forget
<slug>` without `--yes`, "where no terminal can answer", so the command exits
1 and withdraws nothing. That preview depends on `cli._interactive` finding no
TTY on stdin. An agent harness that runs commands under a pty (tmux,
`script`, several IDE terminals) gets the confirmation prompt instead, and
either hangs or, if something answers it, withdraws the source. Where it does
work, the preview exits 1, which an agent reasonably reads as failure. A
preview that only works by failing is not a preview.

**Shape.** `--dry-run` on `cli.forget`, the word `ingest` already uses for
"say what would happen, write nothing". It resolves the slug through
`_document_named` (an unknown slug still exits 1 with the existing message),
prints `_forget_citing_lines` and then `would forget <described>` with the
re-ingest line, never prompts, never calls `registry.forget`, and exits 0. An
already-withdrawn document prints today's `already withdrawn` lines at exit 0.
`--dry-run --yes` is a usage error naming both flags, since one says "do not"
and the other "do". Both `SKILL.md` files, the README's `forget` section,
`site/docs.html` and `site/llms.txt` switch the preview to `--dry-run` and drop
the "run it without `--yes`" instruction. The non-TTY refusal stays as it is.

**Acceptance.** With `cli._interactive` monkeypatched to return True, `forget
notes --dry-run` prints the citing lines and `would forget`, shows no prompt
(the runner's input is empty and the command still exits 0), and `ls` still
lists `notes`. `forget nope --dry-run` exits 1 naming the slugs that exist.
`forget notes --dry-run --yes` exits 1 and withdraws nothing. The existing
`tests/test_citing_drafts.py` forget tests pass unchanged.

**Size.** One day.

### 18. A `--json` run that cannot start leaves the caller one rewordable sentence on stderr

**Intent.** Every `--json` promises nothing on stdout at exit 1 when the run
cannot start: no registry, a registry stamped newer than this build, an
unknown slug, a malformed `--config`, a draft outside its project. That keeps
stdout clean, but the agent that asked for data is then left with `backdraft:
<sentence>` on stderr and has to scrape it to choose between `backdraft init`,
an upgrade, and fixing a flag. Those sentences are reworded most weeks, and
`RegistryError` alone covers both "no registry" and "newer schema", which need
opposite responses.

**Shape.** `cli_context.guard` and `fail` take `as_json: bool = False`. When it
is set, the error goes to stderr as one `backdraft/error-v1` object instead of
the line: `format`, `error` (the same message, declared rewordable), and
`code`, from a small enumerated set an agent branches on: `no_registry`,
`schema_newer`, `outside_project`, `unknown_slug`, `bad_config`,
`not_interactive`, and `other` for everything else. Codes are carried on the
raising exception as an optional `code` attribute on `BackdraftError`
(`kernel/errors.py`, stdlib-pure) and set only where those six are raised, in
`cli_context.open_registry`, `registry.store.Registry.open`,
`cli._document_named`, `cli._parse_config` and `cli._confirm`. Stdout keeps
its promise, and `ingest`'s failed-source exception (2026-11-03) is untouched.
The flag threads through `ingest`, `doctor`, `bind`, `verify`, and `locate`
and `search` when items 15 and 16 have landed. The DESIGN row records why
stderr and not stdout (the stdout promise), and why a code table and not
exception class names: class names are internal and move with refactors.
Specified in SPEC § CLI.

**Acceptance.** `ingest notes.md --json` with no registry exits 1 with empty
stdout and stderr parsing as `error-v1` with `code: no_registry`. `bind
memo.md --json` against a registry stamped `SCHEMA_VERSION + 1` gives
`schema_newer`, and `ingest a.md b.md --slug x --json` gives `other`. Without
`--json`, each of these prints byte-identical stderr to before, pinned. A test
walks every command with a `--json` option and asserts each threads the flag
into its guard.

**Size.** Two to three days.

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
