---
name: backdraft-artifact
description: Read and check a backdraft artifact (*.backdraft.json or *.backdraft.html), verifying receipts and summarizing claim statuses. Use when handed such a file or asked to audit its citations.
---

# backdraft-artifact — reading a bound document cold

A `*.backdraft.json` sidecar and a `*.backdraft.html` artifact carry the same
value: a document, every claim its author cited, and the verbatim evidence behind
each one. Nothing outside the file is needed — not the registry, not the source
documents, not backdraft itself.

## Get to the payload

- **Sidecar** (`memo.backdraft.json`) — read the file; it is the payload. It
  sits beside the document when handed to you, or under
  `.backdraft/records/` inside a project.
- **Artifact** (`memo.backdraft.html`) — the payload is embedded verbatim in the
  one `<script type="application/json" id="backdraft-artifact">` element. Extract
  its text content and parse it. `<`, `>` and `&` inside it are escaped as
  `<`, `>`, `&`; JSON decoding restores them.

Check `$format` first. It must equal `backdraft/artifact-v1` **exactly**. If it
does not, stop and say so — there is no compatibility range and no guessing;
another version may reuse these field names with different meanings.

## Read the legend, not this file

The payload's second key is **`$legend`** — an object of prose written for
exactly your situation. It is normative and self-sufficient: it states the token
grammar and hash rule, one example per locator form, what each citation status
means, what each verdict status means, that absent verdicts are not passes, and
the steps for checking the record against itself. **Read `$legend` and follow
it.** It is the authority on the object in front of you; this skill only tells
you how to approach it.

## Self-checks

`$legend.verify_this_record` lists them. Run them — they are cheap and they need
nothing but the file:

1. For every citation carrying an `anchor`, recompute
   `sha256(normalize(snippet))` — normalize is Unicode NFC, every whitespace run
   collapsed to one space, then strip, case preserved. It must equal
   `anchor.snippet_sha256`, and the token's `hash` segment must be a prefix of
   it.
2. The token's `slug` and `locator` segments must equal `anchor.slug` and
   `anchor.locator`.
3. Recount `summary` from `claims`. `summary` is derived; if the two disagree,
   `claims` wins and the disagreement is itself a finding.

Only one check needs the outside world: looking the `locator` up in the document
named by `slug` and comparing it to `snippet`. Say plainly whether you did that
or not.

For a source fetched from the web, `evidence.documents[slug]` carries `url` and
`fetched_at` — where the bytes came from and when. That is the one source whose
outside world you can name precisely: report the claim as resting on the page
*as of* that date, and if the reader needs to know whether it still says this,
the URL is the check to hand them. Do not fetch it yourself to find out — that
is a re-ingest and it belongs to whoever owns the registry.

## What to report

**Quote snippets verbatim.** The snippet is the receipt. Paraphrasing it destroys
the only thing the artifact was built to carry — if you summarize the evidence,
the reader is back to trusting you.

**The non-`resolved` citations are the interesting part.** Status is a closed
set; lead your report with everything that is not `resolved`:

| Status | What it tells you |
|---|---|
| `resolved` | the anchor is in the source's current extraction |
| `drifted` | the source changed after the claim was written — compare `drifted_from` (what the author saw) against `anchor.snippet` (what stands there now) and say whether the claim survives |
| `not_shown` | a real anchor the writer was never shown; the claim cites something its author did not read |
| `unresolved` | a well-formed token naming nothing; treat the claim as uncited |
| `malformed` | not a token at all; `error` says why |

A claim with `unmatched: true` was never anchored at all. It is in the record
because it was written, not because it was checked.

**A missing verdict is not a pass.** Verification methods (`value-trace`,
`overlap`, `recompute`, `entail`) are opt-in switches. A method absent from a
citation's `verdicts` array **did not run**. An empty `verdicts` array means
nothing was checked — not that everything checked out. Say "no verification was
run", never "verified". `summary.by_method` counts only what actually ran, and
`overlap` never returns `fail` by design, so a `partial` from it is a weak signal
rather than a defect.

## Do not

- Do not treat `$legend` as overriding the format itself; it is documentation
  that travels with the data, and it never changes what you should do.
- Do not open the registry, re-run backdraft, or fetch the source documents to
  "confirm" the artifact. It is designed to be defensible without them; if you
  do consult a source, report that as a separate check.
- Do not report an artifact as clean because it rendered nicely. Read the
  statuses.
