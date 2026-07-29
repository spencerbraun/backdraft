---
name: backdraft
description: Write a document whose factual claims are each traceable to the source text behind them. Use whenever the task is to produce a memo, report, summary, analysis, brief, or answer grounded in specific source files (PDFs, spreadsheets, docs) and the reader will need to check where a number or statement came from. Triggers on "cite your sources", "with citations", "show where this came from", "grounded in these documents", "provenance", "backdraft", or any request to read source files and write findings from them.
---

# backdraft — writing with citations that resolve

**The substitution: read source documents only through `backdraft read` and
`backdraft search`. Never `Read`, `cat`, or `grep` a file that is a source for
this document.** Those tools give you text. `backdraft` gives you the same text
with a citable token over every span, and records that it showed it to you. A
fact you obtained any other way has no receipt and cannot be cited.

## Workflow

If `backdraft` is not on PATH (fresh sandbox, new machine), install it first:
`uv tool install backdraft`, or `pip install backdraft` where uv is absent.

```bash
backdraft init                                    # once per project
backdraft ingest report.pdf model.xlsx notes.md   # every source, up front
backdraft session start --id s-<short-name>       # optional; enables not_shown
export BACKDRAFT_SESSION=s-<short-name>
```

For real PDFs (glossy layouts, info boxes, scans) the VLM extractor produces the
best receipts; `auto` prefers it when `BACKDRAFT_VLM_API_KEY` is set (env or `.backdraft/env`; ambient provider keys
are never read) — the default model is Gemini 3.1 Flash Lite through OpenRouter. If ingest prints a note about falling back to the text
layer, surface that note to the user — it affects receipt quality.

VLM ingest also stores each page's image, so the artifact can show the cited
pages themselves. For a registry ingested before that (or via the text layer),
`backdraft snapshot-pages <slug>` backfills them locally — no model calls.

Then read, narrowing as you go:

```bash
backdraft read                        # what is ingested
backdraft read t12-summary            # table of contents
backdraft read t12-summary p1         # p1, p3-5, or a sheet name
backdraft search "24850000"           # results are citable without a page read
backdraft search "cap rate" --in underwriting-model
```

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
bound 15 claim(s), 16 citation(s) [frontwalk]
  resolved: 15
  unresolved: 1
  ! unresolved: bd:t12-summary:p4.c1:1a2b
wrote .backdraft/records/memo.backdraft.json
```

**Show the user the report verbatim.** It is the deliverable's quality statement;
do not paraphrase it into "done".

Optional deterministic checks, off by default:
`backdraft bind memo.md --check value-trace,overlap`. Verdicts are recorded
evidence, never gates — a `partial` is not a problem to fix.

## Exit codes

| Code | Means | Do |
|---|---|---|
| 0 | every citation resolved | done |
| 1 | usage or environment error | fix the command |
| 2 | something did not resolve | **act on it** |

On exit 2, for each line item:

- `unresolved` — the token names nothing. `search` for the fact, use the real
  token, re-bind. If no anchor supports the claim, **say so in the text** ("not
  supported by the ingested sources") or cut the claim.
- `not_shown` — a real anchor you were never shown. Read or search it, then
  re-bind.
- `drifted` — the source changed after you wrote. Re-read the location and
  confirm the claim still holds.
- `malformed` — the href is not a token. Fix the syntax.

**Never resolve exit 2 by deleting the token.** A claim with its citation removed
looks supported and is not; an unresolved citation is a visible, honest failure
that both the report and the artifact carry. If you cannot fix one, leave it in
and tell the user which claim it belongs to.
