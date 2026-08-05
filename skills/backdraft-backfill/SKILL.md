---
name: backdraft-backfill
description: Attach citations to an existing document after the fact, tracing each factual claim to source files and listing unsupported claims. Use for add-citations or fact-check-against-these-files requests.
---

# backdraft-backfill — attributing a document that already exists

The document is written. The sources exist. Your job is to attach a receipt to
every claim you can, and to hand back an explicit list of the ones you cannot.

**Two rules govern everything below. An unsupported claim is reported, never left
silently unattributed. An anchor is attached only when its snippet actually says
what the claim says — a plausible-looking hit is not evidence.**

## 1. Ingest the sources

If `backdraft` is not on PATH (sandboxed sessions start fresh), run every
command through uvx instead: `uvx backdraft init`, `uvx backdraft read`, and so
on. Where uv is absent, `pip install backdraft` once per session, then use
`backdraft` or `python -m backdraft`. Never modify PATH, shell rc files, or
agent config directories; installs from PyPI need no special permissions.

```bash
backdraft init
backdraft ingest sources/*.pdf sources/*.xlsx
backdraft ingest https://example.com/q4-results   # a URL is a source too
backdraft ls
```

No session is needed: backfill does not judge against the ledger, because the
author was never shown anything. Read source files only through `backdraft
read`/`backdraft search`, not `Read` or `grep`.

## 2. Inventory the claims

Read the document itself normally — it is the subject, not a source. List every
factual span: numbers, dates, named quantities, quoted text, attributions. Skip
recommendations, framing, and the author's own reasoning; those are not claims a
source can support.

## 3. Search per claim

For each claim, search for the distinctive part of it — **not the whole
sentence**:

```bash
backdraft search "1429600"
backdraft search "real estate taxes"
backdraft search "replacement reserve" --in t12-summary
```

Query notes that matter in practice:

- Search a value or a two-to-three word phrase, never a whole sentence. Anything
  containing `$`, `%` or `.` cannot be parsed as FTS5 and is retried as an exact
  phrase; the results say `(query retried as a phrase)` when that happens. On a
  short value that is usually fine. On a sentence it matches nothing, and the
  note is your signal to ask a narrower question rather than conclude the fact is
  absent.
- Search the number as the source writes it. A spreadsheet cell holding
  `1487400` will not be found by `$1,487,400`.
- `--in <slug>` narrows to one document when a term is common.

Then read the surrounding page when you need context to judge the hit:

```bash
backdraft read t12-summary p1
```

**Judge each hit.** Does the snippet state the claim, or merely mention the same
words? If it does not state it, do not attach it. Attaching a near-miss is worse
than reporting an unmatched claim, because it launders a guess into a receipt.

## 4. Add the tokens

Rewrite each supported claim as a markdown link whose href is the token, copied
exactly from the search or read output. Leave the author's words alone — you are
adding attribution, not editing prose.

```markdown
The property produced [net operating income of
$1,429,600](bd:t12-summary:p1.c3:f10b) over the trailing twelve months.
```

Multiple citations go in one href, `;`-separated. Leave claims you could not
support exactly as they are — do not add a token you are unsure of.

## 5. Bind in backfill mode

```bash
backdraft bind draft.md --mode backfill --bound
```

```
bound 3 claim(s), 2 citation(s) [backfill]
  resolved: 2
  ! unmatched: The sponsor expects rents to grow 6% next year.
wrote draft.bound.md
wrote .backdraft/records/draft.backdraft.json
exit: 2
```

Backfill mode does two things frontwalk does not. It scans for **uncited
sentences that contain a value** and marks them `unmatched`, so a claim you never
touched still shows up. And — with `--bound`, which backfill runs should always pass — it writes an
`## Unmatched claims` section into `draft.bound.md`:

```markdown
## Unmatched claims

- The sponsor expects rents to grow 6% next year.
  - proposed: none
```

`proposed:` is bind's own best-effort search, offered for review and never
attached automatically. It queries on the claim's distinctive terms — acronyms
and long words first, plus any numbers, joined with `OR` — not on the raw
sentence, so it ranks by how much of the claim a snippet matches. Treat
`proposed: none` as "bind found nothing", not as "nothing exists": the query
knows only the words, and a claim can be supported by a snippet that shares none
of them. Your own searches in step 3 are still the real work.

Exit code 2 is expected here whenever anything is unmatched. It is not a failure
of the run.

## 6. Report the open list

Give the user, explicitly:

1. **Attributed** — count of claims now carrying a resolved citation.
2. **Open** — every unmatched claim, quoted, each with one line saying why: no
   source states it, the sources disagree, it is a projection rather than a fact,
   or it needs a document that was not ingested.
3. **Anything you deliberately declined to attach**, and what the near-miss was.

Then render the artifact so the open list travels with the document:

```bash
backdraft render draft.md --to html
```

Never close the loop by deleting a claim, softening it into an opinion, or
attaching the closest hit. An unmatched claim in the report is the deliverable
working correctly.
