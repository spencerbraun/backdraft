---
name: backdraft
description: Write documents whose factual claims each carry a checkable citation into source files. Use when producing a memo, report, or analysis from PDFs, spreadsheets, or docs with citations or provenance.
---

# backdraft — writing with citations that resolve

**The substitution: read source documents only through `backdraft read` and
`backdraft search`. Never `Read`, `cat`, or `grep` a file that is a source for
this document.** Those tools give you text. `backdraft` gives you the same text
with a citable token over every span, and records that it showed it to you. A
fact you obtained any other way has no receipt and cannot be cited.

## Workflow

If `backdraft` is not on PATH (sandboxed sessions start fresh), run every
command through uvx instead: `uvx backdraft init`, `uvx backdraft read`, and so
on. Where uv is absent, `pip install backdraft` once per session, then use
`backdraft` or `python -m backdraft`. Never modify PATH, shell rc files, or
agent config directories; installs from PyPI need no special permissions.

```bash
backdraft init                                    # once per project
backdraft ingest report.pdf model.xlsx notes.md   # every source, up front
backdraft ingest <url> --slug <name>              # a URL is a source too
backdraft session start --id s-<short-name>       # do this; see below
export BACKDRAFT_SESSION=s-<short-name>
```

**Start a session and export it.** It is skippable and skipping it costs the
system's strongest check. Without one, every run in the project reads into a
single shared ledger that is never reset, so `not_shown` stops meaning "this
draft's writer never saw this" and starts meaning "nothing in this folder has
ever read it" — a citation you invented can come back `resolved` because some
earlier run happened to read that page. `backdraft session show` says which
session you are in and warns when it is the shared one.

Name every source in one `ingest`; it attempts all of them. If one cannot be
read the command exits 1 and prints `N of M sources ingested` followed by one
`!` line per failure with its reason — everything not named there is in the
registry already. Each reason says what to do next as well as what went wrong:
a directory wants the files inside it or a glob, a missing path wants its
spelling checked, an unreadable file wants its permissions fixed, a source with
no bytes in it never became a snapshot at all. Do what the reason says where you
can, and where you cannot, give the user the `!` line as written — the next step
is the part a paraphrase drops. Then re-run the same command: one already
ingested and unchanged re-ingests as a no-op. Tell the user which sources are
missing before you write, rather than quietly writing around them.

Read each source's line: it ends with how much text came out, and with what
`ingest` did. `unchanged` is a no-op — the snapshot was already there and every
token into it still stands. `new generation` means the bytes moved since the
last ingest, so citations written against the previous snapshot may now be
`drifted`; re-bind and act on what it says, do not assume. A bare line is a
document that did not exist before. When almost no text came out, ingest prints
a `note: little text extracted` line naming the likely cause — that note, not
your own judgement, is the signal that a source came back as a shell.

If the list took in a source it should not have — a scratch copy, the same
report under two names, a file the user did not mean to include — say so and
offer `backdraft forget <slug> --yes`, which withdraws it from `read`, `search`
and `ls` while leaving every token already minted from it resolving. Do not run
it unasked: which copy is the real one is the user's call, not yours, and the
same file ingested again is the undo.

For real PDFs (glossy layouts, info boxes, scans) the VLM extractor produces the
best receipts; `auto` prefers it when `BACKDRAFT_VLM_API_KEY` is set (env or `.backdraft/env`; ambient provider keys
are never read) — the default model is Gemini 3.1 Flash Lite through OpenRouter. If ingest prints a note about falling back to the text
layer, surface that note to the user — it affects receipt quality. In a
sandbox that cannot reach the model provider, do not retry: continue with the
text layer, tell the user, and mention that a registry ingested with the
vision model on their own machine travels with the project folder
(`.backdraft/`) and needs no key at bind or render time.

If the user points you at a web page, ingest the URL rather than fetching it
yourself: text you fetched outside the gate has no receipt and cannot be cited.
The page is snapshotted at that moment and the URL is stored with it, and
every surface names the source by that URL — `backdraft read`'s list, its table
of contents, `ingest`'s own line and the References section `bind --bound`
writes all print the page rather than a filename, so you know which sources came
off the web without a second command. The artifact carries the origin itself: a
receipt on a fetched page links back to it with the fetch date, so you do not
need to repeat the URL in the prose for the reader to have it. What you get is
what a plain unauthenticated GET returns: a JavaScript-rendered page or one
behind a login comes back thin or empty. You do not have to judge that yourself
— ingest's own `note: little text extracted` line says so and names the cause.
When it appears, say so to the user rather than citing the shell of the page.

Two habits make a web citation last. **Ingest a fixed revision when the site
offers one** — Wikipedia's `?oldid=` permanent link, a DOI, an archived
snapshot — because a page that gets edited makes every citation into it report
`drifted`, which is true and unhelpful: the sentence quoted is no longer the
sentence there. **Pass `--slug` with the URL.** The default slug is the URL's
last path segment; when that segment names the site's plumbing rather than its
page — `/index.php`, `/view`, a bare number — the host goes in front of it
instead, so you get `en-wikipedia-org-index` rather than `index`. That names the
site and still not the page, and a slug is permanent once your tokens carry it.
Quote the URL in the shell — `&` in a query string backgrounds the command
otherwise.

Ingest also stores each PDF page's image — both paths, since the text-layer
path renders the pages locally through poppler — so the artifact can show the
cited pages themselves. If ingest prints a note that page images were not
captured, the machine has no poppler; ingest and citations are unaffected, and
`backdraft snapshot-pages <slug>` backfills the images later (also the fix for
a registry built before ingest did this). No model calls either way.

Then read, narrowing as you go:

```bash
backdraft read                        # what is ingested
backdraft read t12-summary            # table of contents
backdraft read t12-summary p1         # p1, p3-5, or a sheet name
backdraft search "24850000"           # results are citable without a page read
backdraft search "cap rate" --in underwriting-model
```

Before you write, ask what you have actually been shown:

```bash
backdraft session show
```

```
session s-deal  (from BACKDRAFT_SESSION)

24 anchors shown across 3 documents

  t12-summary          9
  underwriting-model  13
  franklin-county      2

[Read more: backdraft read <slug> <page>]
```

Everything counted there binds `resolved`; everything else in the registry binds
`not_shown`. A source you ingested and never read is missing from that list, and
finding that out here costs one command — finding it out from `bind` costs the
draft. `nothing shown yet` means no citation you write can bind cleanly.

Search shows 20 results by default. When the count line reads `2 of 56 results`,
`--limit` cut the rest and the last line names the command that shows them —
run it rather than picking the best of what you were shown, because relevance
order is not the same as the sentence you needed. A bare `56 results` is the
whole answer.

A page read arrives with a token over each chunk:

```
[bd:t12-summary:p1.c2:7f11]
Total effective gross income for the trailing twelve months was $2,684,400, against gross potential rent of
$2,972,160. The resulting economic occupancy of 90.3% …

[bd:t12-summary:p1.c3:f10b]
Total operating expenses were $1,254,800, or $9,803 per unit per year. …
Net operating income for the trailing twelve months was $1,429,600.
```

Chunks follow the source's paragraphs, so a claim usually sits inside one of
them. A claim that spans two chunks needs both tokens, not the nearest one.

A sheet read puts cell references in-band (`[B10] 24850000`) and mints the sheet
token in its header. To cite an individual cell you can see, mint its token
directly:

```bash
backdraft cell the-model "rent-roll!B10" "capitalization!D24"
```

Each line is the cell's token and verbatim value; `search` also works when you
know the value but not the cell.

Going the other way — you have a token and want to know what it says — is
`backdraft show`:

```bash
backdraft show bd:t12-summary:p1.c3:f10b
```

It prints the token's status, its locator and the verbatim snippet. This is the
gate as well, so a snippet it shows is minted and citable: a token copied out of
an existing artifact or an earlier draft becomes yours to cite by showing it.

## Write claims as links

Every factual span is a markdown link whose href is the token, copied exactly:

```markdown
[net operating income of $1,429,600](bd:t12-summary:p1.c3:f10b)
```

Multiple citations go in one href, `;`-separated:

```markdown
[Effective gross income of $2,684,400](bd:t12-summary:p1.c2:7f11;bd:underwriting-model:rent-roll!B11:4b79)
```

Rules:

- **Bind the span, not the sentence.** The link text is the words the anchor
  supports. That binding cannot be recovered later; footnotes and endnotes are
  render-time projections of it.
- **Cite only what you were shown.** Never construct, guess, or edit a token by
  hand. Copy it from the output that produced it.
- **Uncited prose is fine** for recommendations, framing, and your own reasoning.
  Cite facts, not opinions.

## Finish

A title convention the artifact honors: an *italic line* directly under the
`# title` becomes the document's subtitle on the rendered page.

Math is allowed: write LaTeX the ordinary way — `$...$` or `\(...\)` inline,
`$$...$$` or `\[...\]` for a display formula — and the artifact renders it as
math when the `[math]` extra is installed. Without the extra the formula shows
verbatim instead; it is never silently rewritten either way, so there is no
reason to avoid math or to spell a formula out in words. Currency (`$250`,
`$1.2M`) and shell variables in backticks are never read as math.

You do not have to guess which happened. When the extra is missing and the
document has formulas, `render` says so at exit 0 — `note: 2 formula(s) rendered
verbatim rather than as math` — and names the install. Relay that note to the
user rather than acting on it: installing packages is their call, and the
artifact is correct either way.

```bash
backdraft bind memo.md --session s-<short-name>
backdraft render memo.md --to html
```

Bind embeds the evidence behind every citation — cited page images, cell
windows, sheet values — into the record, and the artifact carries it all in
one file. The record lives under `.backdraft/records/`, so the working
directory shows only the document and its artifact; `backdraft clean` tidies
strays from older runs. `bind --lean` skips the page images when a small
artifact matters more.

```
bound 17 claim(s), 18 citation(s) [frontwalk]
  resolved: 17
  unresolved: 1
  ! unresolved: bd:t12-summary:p4.c1:1a2b — replacement reserve of $250 per unit per year @3629
wrote .backdraft/records/memo.backdraft.json
```

**Show the user the report verbatim.** It is the deliverable's quality statement;
do not paraphrase it into "done".

Optional deterministic checks, off by default:
`backdraft bind memo.md --check value-trace,overlap`. Verdicts are recorded
evidence, never gates — a `partial` is not a problem to fix.

```
  overlap: pass 13, skip 4
    skip 4 — wording overlap does not apply to a single cell
  value-trace: pass 17
```

A `skip` is the check declining to apply, and the line under it says why — most
often that a claim cites a single spreadsheet cell, where measuring wording
overlap against a bare number would mean nothing. **A skip with a reason is not
a hole to fix**: do not re-cite, re-word or drop a claim over one, and do not
report it to the user as a verification gap. Relay the reason as it is printed.

## Exit codes

| Code | Means | Do |
|---|---|---|
| 0 | every citation resolved | done |
| 1 | usage or environment error | fix the command |
| 2 | something did not resolve | **act on it** |

Each line item is `<status>: <token> — <the claim's own words> @<offset>`, so
the report already tells you which sentence to go fix and where it sits in the
document. Do not grep for the token; the offset is what distinguishes two line
items carrying the same one.

On exit 2, `backdraft show <token>` is the first move on any line item: it runs
the token back to what it names, and its answer is the same status bind just
printed, with the reason attached.

- `unresolved` — the token names nothing. `show` says which half is wrong: an
  unknown slug or a locator/hash that names no anchor. Then `search` for the
  fact, use the real token, re-bind. If no anchor supports the claim, **say so
  in the text** ("not supported by the ingested sources") or cut the claim.
  One `unresolved` is not that: when the line item's reason says the source was
  *withdrawn from the registry*, the token is fine and somebody took the source
  out on purpose (`backdraft forget`). `show` still prints its receipt, so you
  can read what it said, but the source is no longer on offer here — do not
  re-ingest it to make the error go away. Find the fact in a source that is
  still ingested, or leave the claim uncited and tell the user which source was
  withdrawn.
- `not_shown` — a real anchor you were never shown. `show` it (or read or search
  it) and re-bind: showing is minting, so that alone clears the status.
- `drifted` — the source changed after you wrote. `show` prints both snippets,
  the one you cited and the one standing at that locator now, plus the token for
  the new one. Confirm the claim still holds against the new text, and cite the
  new token if it does.
- `malformed` — the href is not a token. `show` names the segment that broke and
  the grammar. Fix the syntax.

**Never resolve exit 2 by deleting the token.** A claim with its citation removed
looks supported and is not; an unresolved citation is a visible, honest failure
that both the report and the artifact carry. If you cannot fix one, leave it in
and tell the user which claim it belongs to — the line item names it.
