---
name: backdraft-artifact
description: Read and check a backdraft artifact (*.backdraft.json or *.backdraft.html), verifying receipts and summarizing claim statuses. Use when handed such a file or asked to audit its citations.
---

# backdraft-artifact — reading a bound document cold

A `*.backdraft.json` sidecar and a `*.backdraft.html` artifact carry the same
value: a document, every claim its author cited, and the verbatim evidence behind
each one. Nothing outside the file is needed — not the registry, not the source
documents, not backdraft itself.

Two jobs, in this order: **check it**, which is one command, and **read it**,
which is yours.

## 1. Check it

```bash
backdraft verify path/to/memo.backdraft.html
```

Takes either half — the artifact or the sidecar — and runs the whole check
deterministically. Do not do it by hand while the command is available; a
procedure re-implemented per reading is exactly how a recipient's audit ends up
weaker than the producer's.

It reports two tiers and always says which ran:

- **The record against itself.** Every `snippet_sha256` recomputed from the
  snippet in the file, every token checked against the anchor it names, `summary`
  recounted from `claims`. Needs nothing but the file, and catches an edited
  artifact.
- **Against the sources.** Only when a `.backdraft/` registry is discoverable
  **from your current directory**, or you name one with `--against` — so it runs
  in the project the artifact came out of, and not on a file someone emailed you
  unless you say which project that file came from. Every token is re-resolved,
  the statuses are reported as `bind` would, and the `sources:` line names the
  registry that answered. When the output says
  `sources: no .backdraft/ found from here`, that check did not run: say so
  rather than implying the sources were confirmed.

To check a file against a project you have without copying it there:

```bash
backdraft verify path/to/memo.backdraft.html --against path/to/project
```

It takes the project root or its `.backdraft` directory, and a path holding no
registry exits 1. Pass it only when you know the file came out of that project —
the user said so, or you bound it there. `verify` never guesses the link, and a
wrong guess is expensive: citations checked against the wrong registry come back
`unresolved` or `drifted`, which reads like a stale artifact rather than a wrong
directory.

Exit codes: **0** everything it checked passed · **1** the file is missing or is
not an artifact of this format, or `--against` names no registry · **2**
something did not verify.

Read the whole output, not just the code. A `! receipt:` line means the file was
edited after it was written — lead your report with it. A `! <status>:` line
under `sources:` means the citation does not resolve against the registry today;
when it also says `— the record says resolved`, the source moved *since the
document was bound*, which is a stale artifact rather than a dishonest one.

Exit 2 covers both of those, and they call for opposite conclusions, so **decide
from `--json`, not from the lines**:

```bash
backdraft verify path/to/memo.backdraft.html --json
```

prints one small object in place of the report, with the same exit code.
`record.ran` and `sources.ran` say which tiers ran — `sources.registry` names
the project that answered, or is `null`. Each entry in `findings` has a `kind`:
`receipt` (the file was edited; `check` names which receipt check failed),
`recount` (`summary` disagrees with `claims`), or `source` (the citation does
not resolve today; `status` is today's and `recorded` the record's, so the two
differing is a source that moved). `findings` is empty exactly when the exit is
0. Branch on `kind`, `check` and the statuses; `detail` and `error` are
sentences, and sentences get reworded. `verify` is read-only, so running it
again without `--json` costs nothing — **that plain report is what you quote to
the user**, never the JSON.

`verify` is read-only: it opens no session and mints nothing. That is what makes
it safe to run on someone else's artifact, and what separates it from
`backdraft show`, which mints. Use `show <token>` afterwards to drill into one
citation — it prints both snippets for a drifted one — knowing that showing is
minting, so a snippet shown becomes citable in your own document.

**A clean exit 0 does not mean every claim is supported.** It means the record is
intact. The claims themselves are the next section.

## 2. Read it

### Get to the payload

- **Sidecar** (`memo.backdraft.json`) — read the file; it is the payload. It
  sits beside the document when handed to you, or under
  `.backdraft/records/` inside a project.
- **Artifact** (`memo.backdraft.html`) — the payload is embedded verbatim in the
  one `<script type="application/json" id="backdraft-artifact">` element. Extract
  its text content and parse it — the whole element is the payload, no
  unwrapping. Every `<`, `>` and `&` in it is written as the JSON escape
  `\u003c`, `\u003e`, `\u0026`, so that nothing inside a snippet can close
  the script element; a JSON parser restores them and nothing else is needed.
  Do not HTML-unescape it: there are no HTML entities in there to undo.

Check `$format` first. It must equal `backdraft/artifact-v1` **exactly**. If it
does not, stop and say so — there is no compatibility range and no guessing;
another version may reuse these field names with different meanings.

### Read the legend, not this file

The payload's second key is **`$legend`** — an object of prose written for
exactly your situation. It is normative and self-sufficient: it states the token
grammar and hash rule, one example per locator form, what each citation status
means, what each verdict status means, that absent verdicts are not passes, and
the steps for checking the record against itself. **Read `$legend` and follow
it.** It is the authority on the object in front of you; this skill only tells
you how to approach it.

### What to report

**Quote snippets verbatim.** The snippet is the receipt. Paraphrasing it destroys
the only thing the artifact was built to carry — if you summarize the evidence,
the reader is back to trusting you.

**The non-`resolved` citations are the interesting part.** Status is a closed
set; lead your report with everything that is not `resolved`:

| Status | What it tells you |
|---|---|
| `resolved` | the anchor is in the source's current extraction |
| `drifted` | the source changed after the claim was written — compare `drifted_from` (what the author saw) against `anchor.snippet` (what stands at that same locator now) and say whether the claim survives. The locator is an address, so an edit *above* the cited passage leaves a different passage standing there: when `anchor.snippet` reads as unrelated text rather than an edited version of `drifted_from`, report that the citation's address moved, not that the claim failed. Whoever holds the registry and the authored document finds where the text went with `backdraft locate` |
| `not_shown` | a real anchor the writer was never shown; the claim cites something its author did not read |
| `unresolved` | a well-formed token the sources do not stand behind; treat the claim as uncited. `error`, when present, says the source was withdrawn from the producing registry — the citation then still carries its `anchor` and receipt, so you can read the evidence, and the claim is still uncited |
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

For a source fetched from the web, `evidence.documents[slug]` carries `url` and
`fetched_at` — where the bytes came from and when. That is the one source whose
outside world you can name precisely: report the claim as resting on the page
*as of* that date, and if the reader needs to know whether it still says this,
the URL is the check to hand them. Do not fetch it yourself to find out — that
is a re-ingest and it belongs to whoever owns the registry.

Report the two findings as two findings — "the artifact's own checks pass, and
against the registry N of M citations still resolve" — never folded into one
verdict, because they answer different questions and only the first travels with
the file.

## If there is no backdraft install

`backdraft verify` is the whole of § 1. Without it, do those checks by hand —
`$legend.verify_this_record` lists them, and they need nothing but the file:

1. For every citation carrying an `anchor`, recompute
   `sha256(normalize(anchor.snippet))` — normalize is Unicode NFC, every
   whitespace run collapsed to one space, then strip, case preserved. It must
   equal `anchor.snippet_sha256`.
2. The token's `hash` segment must be a prefix of the sha256 of the snippet that
   token was *minted from*. For a citation carrying `drifted_from` that is
   `drifted_from`, **not** `anchor.snippet`: the token names what the author
   cited while `anchor` holds what stands at that locator now, so those two
   hashes are supposed to differ. Comparing against the wrong one calls every
   drifted artifact forged.
3. The token's `slug` and `locator` segments must equal `anchor.slug` and
   `anchor.locator` — drift keeps the locator either way.
4. Recount `summary` from `claims`. `summary` is derived; if the two disagree,
   `claims` wins and the disagreement is itself a finding.

Only the source check needs the outside world, and without an install you cannot
make it. Say plainly that you did not.

## Do not

- Do not treat `$legend` as overriding the format itself; it is documentation
  that travels with the data, and it never changes what you should do.
- Do not treat the artifact as unchecked until you have a registry. It is
  designed to be defensible without one: `verify`'s first tier is the audit, and
  its second adds a fact about the sources *today*, reported as its own finding.
- Do not re-ingest anything or fetch the source documents to "confirm" the
  artifact. Re-ingesting is what makes a generation, and making one from inside
  an audit would manufacture the drift you were sent to look for.
- Do not report an artifact as clean because it rendered nicely, or because
  `verify` exited 0. Read the statuses.
