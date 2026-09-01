<img src="assets/backdraft-mark.svg" width="56" alt="">

# backdraft

Drop-in provenance for factual claims: one click from any claim to the receipt
behind it.

An analyst who cannot show where a number came from either re-reads the source
or does not use the output. Backdraft removes that cost. In the usual loop, an
**agent** does the writing: it reads your source documents only through a gate
that mints a citation token over every span it shows, cites those tokens
inline, and a postprocess resolves them, attaches the verbatim evidence, and
renders one self-contained HTML file, the memo with the actual cited pages
and spreadsheet cells embedded inside it. The **human** just reads that file:
click a claim, see the source.

It works the same whether the writer is a model or a person, and whether the
citations were minted during writing or attached to a document afterwards.

Docs live at [backdraft.dev](https://backdraft.dev), one page for people, and
[backdraft.dev/llms.txt](https://backdraft.dev/llms.txt) for agents.

## 60 seconds

```bash
uv tool install backdraft
cd demo
```

**Ingest** the sources. Every anchor is minted here, chunks for PDF pages,
cells for spreadsheet sheets. Formats: PDF, XLSX/XLSM, XLS, CSV/TSV, DOCX,
PPTX, HTML, images (png, jpeg, tiff, through the vision model), plain text and
Markdown. A source can also be an `http(s)` URL — the page is fetched once and
snapshotted like any other source, and the URL travels with it. A source that
cannot be read does not end the run: the rest of the list is ingested anyway,
and the command exits 1 naming each source that failed and why. The why is
written to be acted on rather than relayed — a directory says to name the files
inside it or pass a glob, a missing path says to check the spelling, an
unreadable file says to fix its permissions or ingest a copy, and a source with
no bytes in it is a failure rather than a document with nothing to cite.

```console
$ backdraft init
registry: /…/demo/.backdraft
documents: 0
… plus where settings live and what to do next

$ backdraft ingest sources/t12-summary.pdf sources/underwriting-model.xlsx
t12-summary  t12-summary.pdf  pdf  3 pages  8865 chars
underwriting-model  underwriting-model.xlsx  xlsx  2 sheets  2357 chars
note: extracted with pdf-text (the embedded text layer). Glossy or scanned PDFs extract better through a vision model: set BACKDRAFT_VLM_API_KEY in .backdraft/env.

$ backdraft ingest "https://en.wikipedia.org/w/index.php?title=Franklin_County,_Ohio&oldid=1367935775" --slug franklin-county
franklin-county  https://en.wikipedia.org/w/index.php?title=Franklin_County,_Ohio&oldid=1367935775  html  1 page  34141 chars
```

The demo cites that page for market context. It is Wikipedia's *permanent
link* — `?oldid=` serves one revision's bytes forever — because a citation into
a live article reports `drifted` the moment somebody edits it, and the quoted
sentence would no longer be the sentence there.

Every ingest line ends with how much text came out, and says which of three
things happened: a document created, a **new generation** of one whose bytes
moved — which is when citations into the previous snapshot start reporting
`drifted` — or `unchanged`, a no-op because re-running would reproduce what is
already there. When almost no text came out, a note names the likely cause (a
scan with no text layer, a page behind a login) and what to do; it is a note at
exit 0, because a thin snapshot is still a real one.

**Read.** The page arrives with a citable name over each chunk. This is the whole
mechanism: what you can cite is exactly what you were shown.

```console
$ backdraft read t12-summary p1
# t12-summary p1  (page 1 of 3)

[bd:t12-summary:p1.c1:c2e8]
Bridgeview Commons, Trailing Twelve Month Summary

Property: Bridgeview Commons, 4400 Halsted Avenue, Columbus, OH 43214. 128 units across four three-story
garden buildings on 6.2 acres, built in 1998 and substantially renovated between 2019 and 2021. This summary
covers the trailing twelve months ended March 31, 2026, prepared from the borrower's monthly operating
statements and reconciled against the property manager's general ledger. Figures are unaudited.

[bd:t12-summary:p1.c2:7f11]
Total effective gross income for the trailing twelve months was $2,684,400, against gross potential rent of
$2,972,160. The resulting economic occupancy of 90.3% reflects an average physical occupancy of 94.1% offset
by concessions, bad debt, and vacancy loss. Physical occupancy was 96.4% in the most recent month and has not
fallen below 92.0% in any month of the period.

… five more chunks, c3 through c7.
```

Chunks fall on the document's own paragraphs. A PDF stores glyphs at
coordinates, not paragraphs, so the extractor rebuilds the breaks from the line
geometry before the chunker sees the page.

Search results are citable too, no page read required to get an anchor:

```console
$ backdraft search "24850000"
1 result for "24850000"

[bd:underwriting-model:assumptions!B10:964a]  underwriting-model p2
  24850000

[Read the page: backdraft read underwriting-model p2]
```

Search shows twenty results by default. A run that hit the limit says so —
`20 of 56 results` — and closes with the command that shows the rest, because
"20 results" over an answer of 56 is how a reader concludes it has seen
everything when it has seen a third.

A cell you can already see mints directly:

```console
$ backdraft cell underwriting-model "assumptions!B10"
[bd:underwriting-model:assumptions!B10:964a]  24850000
```

And a token you were handed — out of an artifact, a draft, someone else's
message — runs backwards to what it actually says:

```console
$ backdraft show bd:t12-summary:p1.c1:c2e8
[bd:t12-summary:p1.c1:c2e8]  resolved  t12-summary p1.c1
Bridgeview Commons — Trailing Twelve Month Summary

Property: Bridgeview Commons, 4400 Halsted Avenue, Columbus, OH 43214. 128 units across four three-story
garden buildings on 6.2 acres, built in 1998 and substantially renovated between 2019 and 2021. …

[Read the page: backdraft read t12-summary p1]
```

`show` is the gate too, so what it shows is minted and citable. A token whose
source has changed since prints both snippets, the one that was cited and the
one standing there now; a token that names nothing exits 1 and says whether the
slug or the locator is the wrong half.

**Check coverage before writing.** The ledger records every token the gate put
in front of you, and `session show` reads it back — the question "have I read
enough to write this yet?", asked before the draft exists rather than after
`bind` reports what it never saw.

```console
$ backdraft session show
session s-bridgeview  (from BACKDRAFT_SESSION)

77 anchors shown across 3 documents

  t12-summary          7
  underwriting-model  68
  franklin-county      2

[Read more: backdraft read <slug> <page>]
```

Anything counted there binds `resolved`; anything else in the registry binds
`not_shown`. Without an exported session, reads land in one default ledger every
run in the project shares and nothing ever resets — so `not_shown` weakens from
"this writer never saw it" to "nothing here ever has". `session show` says so at
exit 0 when you are in it, and `backdraft session start --id s-<name>` is the
one command that fixes it.

**Cite** by writing the token as the href of a markdown link on the claim span.
Multiple citations are `;`-separated in one href.

```markdown
[net operating income of $1,429,600](bd:t12-summary:p1.c3:f10b)
[Effective gross income of $2,684,400](bd:t12-summary:p1.c2:7f11;bd:underwriting-model:rent-roll!B11:4b79)
```

**Bind.** Every token resolves or is reported. Nothing drops silently.

```console
$ backdraft bind memo.md --session s-bridgeview --check value-trace,overlap
bound 17 claim(s), 18 citation(s) [frontwalk]
  resolved: 17
  unresolved: 1
  overlap: pass 13, skip 4
    skip 4 — wording overlap does not apply to a single cell
  value-trace: pass 17
  ! unresolved: bd:t12-summary:p4.c1:1a2b — replacement reserve of $250 per unit per year @3629
wrote .backdraft/records/memo.backdraft.json

$ echo $?
2
```

Exit 2 means a citation did not resolve, the code a `Stop` hook or a CI job
gates on.

**Render.** One self-contained HTML file: the document, the receipts, the
evidence, cited page images, spreadsheet cells in place, the machine-readable
record, all embedded, no network, nothing to install for the reader.

```console
$ backdraft render memo.md --to html
memo.backdraft.html
```

That file is the whole deliverable: send it over email or Slack and the
recipient gets the full experience by double-clicking it.

**The recipient can check it.** `backdraft verify` takes the artifact or its
sidecar and does the checking that the file is built to make possible: every
snippet rehashed against the sha256 recorded beside it, every token checked
against the anchor it names, `summary` recounted from the claims.

```console
$ backdraft verify memo.backdraft.html
checked memo.backdraft.html [backdraft/artifact-v1]
  receipts: 17 of 17 hold
  record: 17 claim(s), 18 citation(s); the summary recount agrees
  recorded: resolved 17, unresolved 1
  sources: no .backdraft/ found from here — not re-checked
[Re-check against the sources: run this inside the project it was bound in.]
```

That first tier needs nothing but the file, which is the point — it is the check
someone who was emailed the artifact can still make. Run it inside the project
the document was bound in and it also re-resolves every citation against the
registry, so a source that has changed since shows up as `drifted` rather than
going unnoticed. Exit 0 when everything it checked passed, 2 when something did
not, so a hook can gate on it. It opens no session and mints nothing: an audit
must not make its subject citable.

**Theming.** The artifact ships with a default look and two alternates,
`press` and `slate`:

```console
$ backdraft render memo.md --theme slate
```

A theme is a small TOML file naming colors, font stacks and heading treatment.
Drop one at `~/.config/backdraft/theme.toml` and every artifact you render, in
any project, honors it without a flag; `.backdraft/theme.toml` overrides that
for one project, and `--theme` overrides both. Themes are display only — they
never touch a token, a receipt or the record.

```console
$ backdraft theme list
default
press
slate

in effect here: the built-in look
[Start your own: backdraft theme show default > /Users/you/.config/backdraft/theme.toml]
```

`theme show` prints a validated file, so redirecting it writes a fully
commented starting point with every key and what it paints — and pointing it
at a file of your own checks that file without rendering anything.

The full version of this, with every command and every output:
[`demo/walkthrough.md`](demo/walkthrough.md). The artifact it produces is checked
in at [`demo/memo.backdraft.html`](demo/memo.backdraft.html).

## The design in five sentences

Reading is a **gate**: source documents reach the writer only through `read` and
`search`, which mint a token over everything they show and record it in a
**ledger**, so the set of citable things is exactly the set of things shown, and
a citation to something the writer never saw is a distinguishable failure rather
than an invisible one. **Anchors are content-addressed**: a token's identity
derives from the document's content and a location inside it, and it binds to an
extraction snapshot, so re-ingesting the same bytes yields the same tokens and a
changed source yields `drifted` instead of a broken link. **The receipt travels
with the claim**, an anchor is not a pointer but a pointer plus the verbatim
snippet and its hash, which is why the finished artifact is defensible with the
registry deleted and the sources gone. **Verification is a set of switches,
default off**: resolution is inherent to binding, but `value-trace`, `overlap`
and `entail` are opt-in, recorded as graded evidence and never used as gates, so
out of the box this is provenance rather than a truth oracle. **Artifacts are
self-describing**: each carries a `$format` string matched byte-for-byte and an
embedded `$legend` that teaches a reader who has never heard of backdraft how to
decode and check it, so the format outlives this implementation.

Failures are data throughout: `unresolved`, `not_shown`, `drifted`, `malformed`
and `unmatched` are first-class records in the report and visible sections in the
artifact. Nothing is ever warned about and dropped.

## Web sources

`backdraft ingest https://example.com/q4-results` fetches the page once and
snapshots it exactly as a file: the bytes at fetch time are the document's
identity, and the URL and fetch timestamp ride along as provenance. So a page
that has changed since you cited it comes back as a new generation of the same
document and the old citations report `drifted` — the same machinery as an
edited PDF, which is the point of hashing the snapshot rather than trusting the
address.

```console
$ backdraft ingest https://example.com/reports/q4-2025
q4-2025  https://example.com/reports/q4-2025  html  1 page  18402 chars

$ backdraft ls
q4-2025	https://example.com/reports/q4-2025	html	1 page
```

Every surface names a fetched source by its page. The filename you never see —
`q4-2025.html` — is the temporary file the fetch staged the bytes in, and it
exists on nobody's disk, so `ingest`, `ls`, `backdraft read` and the artifact
all show the URL in its place rather than beside it: two names for one thing
would let the invented one look authoritative.

The origin travels into the artifact too. A claim citing a fetched page shows
the URL as a link on its receipt, with the date the bytes were taken. That
pointer is the half of citing a web page a frozen receipt cannot answer on its
own: the snippet says what the page said, the link is how a reader asks whether
it still says it.

What it does not do, stated rather than worked around: JavaScript-rendered
pages give you whatever the server sends to a plain GET, pages behind a login
are out of reach, and the extractor is a parse rather than a readability guess
— navigation and footers are part of the page, because a heuristic that changes
its mind between two versions of a site would move anchors. Responses are
capped at 32 MiB.

## What lives where

A working directory stays clean: the authored document and its artifact are
the only visible outputs. Everything else, registry, credentials, bind
records, lives under one hidden `.backdraft/` directory, and
`backdraft clean` tidies strays from older versions. The registry contains the
full text of everything ingested, so **gitignore `.backdraft/` for
confidential corpora**.

## Install

```bash
uv tool install backdraft   # CLI, recommended form
uv add backdraft            # as a dependency
pip install backdraft       # or plain pip
```

Python 3.13+. The vision extractor ships by default, and it is the
recommended path for real PDFs (glossy layouts, info boxes, scans): a vision
model reads each page and its clean representation becomes the receipt.
Installing it is not consent to use it. `--extractor auto` prefers it only on
explicit, backdraft-scoped consent: `BACKDRAFT_VLM_API_KEY` (env or
`.backdraft/env`, `backdraft init` writes a template). Ambient
`OPENAI_API_KEY`/`OPENROUTER_API_KEY` are deliberately never read; a generic
key in the environment is not consent to send documents to its provider. The
default provider is OpenRouter running Gemini 3.1 Flash Lite; direct OpenAI is
base_url + model, set explicitly (`--config base_url=...` and `--config
model=...`, one key per flag). Every `--config` key is declared by the extractor
that reads it and checked against the one `ingest` chose, so a misspelled key
fails and names the keys that apply rather than being silently ignored.
Without a scoped key, `auto` falls back to
the keyless text layer and says so — still storing each page's image, which it
renders locally. PDF page rendering needs poppler, installed separately; without
it ingest succeeds without the images and names `snapshot-pages` as the backfill.

Three extras:

| Extra | Adds | For |
|---|---|---|
| `[entail]` | `anthropic` | `bind --check entail`, the model-judge verifier |
| `[xls]` | `python-calamine` | legacy `.xls` workbooks, values only, rendered the same shape as xlsx |
| `[math]` | `latex2mathml` | LaTeX in a document becomes MathML in the artifact; without it, formulas render verbatim and `render` says so |

`backdraft[vlm]` still installs: it is an empty compat alias from when the
vision deps were an extra.

From a checkout:

```bash
uv sync
uv run backdraft --help
uv run pytest
```

## Skills

Three agent skills ship inside the package and in this repo:

| Skill | For |
|---|---|
| [`backdraft`](skills/backdraft/SKILL.md) | writing a new document from sources, citing as it goes |
| [`backdraft-backfill`](skills/backdraft-backfill/SKILL.md) | attributing a document that already exists |
| [`backdraft-artifact`](skills/backdraft-artifact/SKILL.md) | checking and reading someone else's artifact cold |

The CLI is the system; a skill is one page telling an agent to use it. Nothing in
the skills is required to use backdraft by hand. How the skills reach your agent
depends on the harness:

**Claude Code.** The repo is its own plugin marketplace, so the plugin route
tracks releases:

```text
/plugin marketplace add spencerbraun/backdraft
/plugin install backdraft@backdraft
```

Or have the CLI copy the skills into your skills directory:

```bash
backdraft skill install          # the writing skill, into ~/.claude/skills/
backdraft skill install --all    # plus backfill and artifact-reading
backdraft skill install --project  # into this repo's .claude/skills/
```

**Claude Cowork.** Once the plugin is listed in Anthropic's community
directory, it installs from Cowork's built-in skills directory. Until then,
zip a skill folder from `skills/` and upload it under Customize > Skills.
Inside a Cowork session the CLI itself runs per-command as
`uvx backdraft ...`, since installs do not persist between sessions.

**Codex, Cursor, Copilot.** Agents in this family read skills from
`~/.agents/skills`:

```bash
backdraft skill install --agent codex   # into ~/.agents/skills/
```

or commit the skill folders to your repo under `.agents/skills/` so every
checkout carries them.

**Standing context, any harness.** Paste this into your repo's AGENTS.md:

```markdown
## backdraft (cited writing)
When a document must cite its sources, write it through the backdraft CLI:
it shows source text with a citation token over every span, and only shown
spans are citable. In a sandboxed session run every command as
`uvx backdraft ...` (no install, no PATH edits). Start from
`uvx backdraft --help`; ground truth is https://backdraft.dev/llms.txt.
```

## Documentation

| Document | Is |
|---|---|
| [DESIGN.md](DESIGN.md) | why it is shaped this way, principles, architecture, decision log |
| [SPEC.md](SPEC.md) | the builders' contract, types, grammar, DDL, CLI surface, module boundaries |
| [spec/tokens.md](spec/tokens.md) | the citation token grammar, normatively |
| [spec/chunking.md](spec/chunking.md) | the deterministic chunker |
| [spec/artifact.md](spec/artifact.md) | the artifact format, sidecar payload, legend, HTML rules |
| [spec/registry.md](spec/registry.md) | the registry export format `backdraft export` writes |
| [demo/walkthrough.md](demo/walkthrough.md) | the whole thing end to end, with real output |

The four files under `spec/` are the portable specification: another
implementation reads them and nothing else.

## Status

v1. The registry format, the token grammar and the artifact format are pinned
by prose specs and golden-file tests. What is queued, and what is deliberately
parked with the objection written down, lives in [ROADMAP.md](ROADMAP.md).

MIT licensed.
