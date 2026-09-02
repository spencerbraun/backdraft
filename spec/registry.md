# The registry export — normative format

Status: v0, 2026-08-25. This file is the portable specification of
`backdraft/registry-v1`, the format `backdraft export` writes.
`src/backdraft/registry/store.py`'s `Registry.export_json` builds the payload and
`src/backdraft/cli.py` writes it out. Another implementation reads this file and
nothing else. Where they disagree, this file and the tests in
`tests/test_spec_registry.py` decide.

A **registry** is a project's accumulated sources: the documents ingested into
it, every extraction generation of each, the anchors those generations mint, the
ledger of what a writing session was shown, and the bind runs recorded against
it. It lives in one SQLite file under `.backdraft/` that nothing outside this
implementation should open. The **export** is that registry as one JSON
document — the portable form, and the only form specified.

It is what a second implementation reads, what a migration reads, and what an
audit reads. It is deliberately not a backup; see *What the export leaves out*.

## Writing one

```
backdraft export                      # to stdout
backdraft export --out registry.json  # to a file
```

## Encoding

UTF-8 JSON, one object. Two-space indent, non-ASCII preserved rather than
escaped, no key sorting; `--out` terminates the file with a newline. Keys appear
in the order the tables below list them and every array has a specified order, so
two exports of an unchanged registry are identical bytes and two exports across
an ingest diff to what the ingest did.

## Identity

Identity in an export is exactly what SPEC.md's concept table says it is, and
nothing in the JSON widens it:

| A | Is identified by | Not by |
|---|---|---|
| document | `sha256`, the hash of the ingested bytes | `slug`, `path`, `filename`, `meta.url`, `withdrawn_at` — a handle, an origin, a name, a provenance note, a registry's own state |
| extraction | (document, `extractor`, `extractor_version`, `config_hash`) | `id` |
| anchor | its `locator` within its extraction, named by its `token` | `id` |
| session | `id`, which is the caller's own string | `label` |

`id` on an extraction or an anchor is the registry's own row number. It is stable
within one export and meaningless outside it: nothing in this document references
an `id`, two registries holding the same document assign different ones, and a
reader MUST NOT treat one as identity or carry one across registries. The ledger,
which could have been written as anchor row numbers, carries tokens instead for
exactly that reason.

## The payload

```json
{
  "$format": "backdraft/registry-v1",
  "documents": [ … ],
  "sessions": [ … ],
  "ledger": [ … ],
  "bindings": [ … ]
}
```

### The top level

| Key | Type | Is |
|---|---|---|
| `$format` | string | `backdraft/registry-v1`, matched exactly. See *Versioning* |
| `documents` | array | every ingested document, oldest first |
| `sessions` | array | every session, oldest first |
| `ledger` | array | every showing of an anchor to a session, oldest first |
| `bindings` | array | every bind run recorded against this registry, oldest first |

An empty registry emits all four keys with empty arrays. There is no `$legend`
here: an artifact is read by whoever was handed the artifact, and carries its own
decoding; an export is read by an implementer holding this file.

### `documents[]`

| Key | Type | Is |
|---|---|---|
| `slug` | string | the human handle, unique in the registry, matching the token grammar's `slug` |
| `sha256` | string | the document's identity: sha256 of the ingested bytes, unnormalized, full 64 hex |
| `path` | string | the source as ingest was given it — a filesystem path, or the URL for a fetched page. Informational |
| `filename` | string | the file's name; for a fetched page, the name its staged snapshot took |
| `media_type` | string | one of `pdf`, `xlsx`, `xls`, `csv`, `docx`, `pptx`, `image`, `html`, `text` |
| `created_at` | string | ISO-8601 UTC, as every timestamp in backdraft |
| `withdrawn_at` | string | OPTIONAL. ISO-8601 UTC, when this document was withdrawn. See below |
| `meta` | object | OPTIONAL provenance. See below |
| `extractions` | array | every generation of this document, oldest first |

Documents are ordered by `created_at`, then by row number.

`withdrawn_at` is present only on a document that has been **withdrawn** — taken
out of the registry's readable set, which `backdraft forget` does. A reader must
conclude exactly two things from it, and neither is a deletion. The document is
no longer offered as a source: it is absent from listings, from tables of
contents, from page reads and from search results, and a producer MUST NOT serve
its text through any of those. And nothing about it is missing: its
`extractions`, `pages`, `anchors` and receipts are exported in full, every token
minted from it still names the anchor it named before, and a reader resolving a
token MUST resolve it as it would any other. What the withdrawal changes for such
a token is only what a *report* about it says — this implementation reports it
`unresolved` with a reason naming the withdrawal, so a document citing a
withdrawn source is not passed silently.

Withdrawal is not identity: a document's `sha256` is what it is, withdrawn or
not, and ingesting the same source again removes the key rather than creating a
second document.

`meta` is present only where there is provenance to carry, which today means a
source fetched from the web; a registry of files exports no `meta` key at all.
That is the same conditional the artifact format states, for the same reason: an
export of a file-only registry is byte-for-byte what it was before URL sources
existed, so a reader written against the earlier shape still reads it.
`withdrawn_at` follows the same rule: a registry nobody has withdrawn anything
in exports no such key.

### `documents[].meta`

| Key | Type | Is |
|---|---|---|
| `fetched_at` | string | ISO-8601 UTC, when the bytes were taken |
| `url` | string | the page they came from, after redirects |

The order above is alphabetical, and is the one place in this format where that
is the reason: `meta` is stored canonically, so two exports put provenance in the
same place whatever order a producer assembled it in. Every other object's keys
follow its table because its table follows the code.

Both keys are OPTIONAL, and a fetched source carries both. They are provenance,
never identity: documents whose bytes are identical are one document whatever
their URLs, and re-fetching one URL to different bytes is a new generation of the
same document rather than a second document. A reader MUST NOT resolve a citation
by `url`.

### `documents[].extractions[]`

| Key | Type | Is |
|---|---|---|
| `id` | int | the registry's row number. Not identity |
| `extractor` | string | the extractor's name — `pdf-text`, `xlsx`, `html`, `text`, `vlm` and others. Not a closed set |
| `extractor_version` | string | that extractor's version, bumped when its output moves |
| `config_hash` | string | sha256 of the canonical-JSON encoding of the config this run was given, full 64 hex |
| `deterministic` | bool | the extractor's own claim that identical bytes produce identical pages |
| `is_current` | bool | exactly one generation per document is `true` |
| `created_at` | string | ISO-8601 UTC |
| `pages` | array | the snapshot, in page order |
| `anchors` | array | every anchor this generation minted, in mint order |

Generations are ordered oldest first, by `created_at` then row number, and every
one is exported. A superseded generation's anchors are what make a drifted
citation explainable — they are the snippet the author actually saw — so an
export carrying only the current generation would lose the ability to say what a
claim was written against. Exactly one generation of a document has
`is_current: true`; a reader that finds two, or none, MUST refuse the export
rather than choose.

The same token appears in several generations of one document, and that is the
drift contract rather than a duplicate: a new generation's anchor keeps the prior
current generation's token wherever both the `locator` and the `snippet_sha256`
match. SPEC.md § Registry specifies the rule; it is what makes `token` a safe
name for an anchor across a whole export.

`deterministic` is a claim about the extractor, not a finding about this run.
Re-running a `false` extractor over the same bytes is not guaranteed to reproduce
this generation's pages, which is why `pages[].text` is the receipt and not a
cache: what the export carries is the snapshot a citation was minted from, and
for such an extraction there is no way back to it.

### `documents[].extractions[].pages[]`

| Key | Type | Is |
|---|---|---|
| `number` | int | 1-based, unique within the extraction |
| `kind` | `"page"` \| `"sheet"` | a document page, or a spreadsheet sheet |
| `name` | string \| null | what the extractor calls this page: a sheet's name, an HTML page's title, a `docx` section's heading, a slide's title. Null where the extractor has none |
| `text` | string | the snapshot: the page as a reader is shown it. Every receipt on this page is a verbatim substring of it |
| `summary` | string \| null | OPTIONAL one-line summary, for a table of contents |

Pages are ordered by `number`.

`text` is the substrate the rest of the system rests on. Every anchor on the page
quotes it verbatim — a page anchor is the whole of it, a chunk anchor is the
slice its offsets name, a cell anchor is the value the sheet rendering shows
in-band — the chunker is a pure function of it, and nothing downstream reopens
the original file.

`name` carries citation identity for a sheet and nothing but display anywhere
else. A sheet's name is sanitized at ingest to the token grammar's `sheetref`
charset, so it is exactly the `<sheet>` half of that sheet's cell locators; every
other kind of name is free text a producer chose, and a reader MUST NOT build a
locator out of one.

`summary` is reserved. No extractor in this implementation sets it, so it is
always null here and a reader must handle both.

### `documents[].extractions[].anchors[]`

| Key | Type | Is |
|---|---|---|
| `id` | int | the registry's row number. Not identity |
| `page_number` | int | the page this anchor is on, matching a `pages[].number` |
| `kind` | string | `page`, `chunk`, `cell` or `range` |
| `locator` | string | exactly the token's locator segment |
| `snippet` | string | the receipt: the verbatim evidence, a substring of that page's `text` |
| `snippet_sha256` | string | `sha256(normalize(snippet))`, full 64 hex |
| `token` | string | the full `bd:slug:locator:hash` string |
| `start` | int \| null | the offset of `snippet` in the page's `text` |
| `end` | int \| null | the end of that half-open range |
| `created_at` | string | ISO-8601 UTC |

Anchors are ordered as the generation minted them: for each page in order, the
page's own anchor first, then that page's chunks or cells.

An anchor is a location plus its receipt, and the receipt is what makes it
citable when the source is gone. `normalize` is Unicode NFC, then every
whitespace run collapsed to one space, then strip; case is preserved, and this is
the only normalization in the system. The `hash` segment of `token` is a
4-to-8-char prefix of `snippet_sha256`. The token grammar and its locator forms
are specified in [tokens.md](tokens.md); the chunker that produces `p<N>.c<M>`
locators is specified in [chunking.md](chunking.md).

`locator` is unique within its extraction — it is the anchor's identity there —
and it MUST equal `token`'s locator segment, with `token`'s slug segment equal to
the document's `slug`.

What each kind carries:

| `kind` | `locator` | `snippet` | `start`, `end` |
|---|---|---|---|
| `page` | `p<N>` | the whole page's `text` | null |
| `chunk` | `p<N>.c<M>` | one chunk of the page | ints; `text[start:end]` equals `snippet` |
| `cell` | `<sheet>!<A1>` | the cell's rendered value | null |

`range` is a fourth kind in the token grammar. This implementation mints anchors
eagerly at ingest — one per page, one per chunk, one per populated cell — and
mints no ranges, so no exported anchor carries the kind. A reader MUST accept it
from a producer that does.

### `sessions[]`

| Key | Type | Is |
|---|---|---|
| `id` | string | the session's identity: caller-supplied, or generated at first use |
| `label` | string \| null | OPTIONAL human label |
| `started_at` | string | ISO-8601 UTC |

Ordered oldest first, by `started_at` then `id`. The session called `default` is
the one a caller who named none was given, and it accumulates across every run in
the registry — a fact a reader needs before concluding from `ledger` what any one
writer saw.

### `ledger[]`

| Key | Type | Is |
|---|---|---|
| `session_id` | string | a `sessions[].id` |
| `token` | string | the token of the anchor that was shown |
| `shown_at` | string | ISO-8601 UTC, the first showing |

Ordered oldest first, by `shown_at` then the anchor's row number. One row per
(session, anchor): showing the same anchor twice in a session keeps the first
`shown_at`, because what bind asks is whether the writer ever saw it.

The ledger is the mechanism the `not_shown` status rests on — the set of citable
tokens is exactly the set the gate emitted into a writer's context — which makes
it the half of the export an audit reads. It carries `token` rather than an
anchor row number so that "was this citation shown?" is answerable from the
export alone.

### `bindings[]`

| Key | Type | Is |
|---|---|---|
| `id` | int | the registry's row number |
| `doc_path` | string | the authored document that run bound, as bind was given it |
| `session_id` | string \| null | the ledger session, when the run had one |
| `mode` | `"frontwalk"` \| `"backfill"` | how the citations were produced |
| `report` | object | the bind report, specified elsewhere. See below |
| `bound_at` | string | ISO-8601 UTC |

Ordered oldest first, by row number.

`report` is a bind report, and this file does not specify it. It is the artifact
sidecar's payload without the two reserved keys — `doc_path`, `mode`,
`session_id`, `bound_at`, `claims`, `summary` — and [artifact.md](artifact.md) is
where a reader reads it. It is stored without the `evidence` block, which is
heavy and reproducible from the registry. Treat the object as opaque at this
level: the artifact format owns its shape, and re-specifying it here would give
one format two specifications that can disagree.

## What the export leaves out

An export is the registry's content, not its bytes. Three things in the SQLite
file are deliberately not in it:

- **Page images** — a PDF page's visual snapshot, which for a vision-model
  extraction is the page as the model was shown it. Megabytes of base64 per
  document, and an artifact that needs them already embeds the ones it cites.
- **Sheet styling** — the presentation metadata an `xlsx` extraction captures:
  bold, fills, number formats, column widths, merges, frozen panes. Display
  context, never citation identity, as it is everywhere else it appears.
- **The full-text index** — derived from `anchors[].snippet`, and rebuildable
  from it.

So an export round-trips every citation and every receipt, and does not
round-trip a registry. A reader MUST NOT conclude from an absent page image that
a document has none. A tool that rebuilds a registry from an export produces one
whose tokens all resolve and whose artifacts render without page evidence; that
is the honest limit of the format, and widening it means a new format string.

## Versioning

`$format` is an opaque string, compared byte for byte. The rule is the artifact
format's, for the reason it is the artifact format's: a reader that guesses is
worse than a reader that stops.

- A reader that recognizes `backdraft/registry-v1` reads the payload as specified
  here.
- A reader that does not recognize the exact string MUST refuse the payload
  rather than interpret it. There is no compatibility range, no minor version, no
  negotiation, and no partial read.
- A later version gets a new string. It may reuse these field names with other
  meanings; that is exactly why guessing is forbidden.
- Unknown keys inside a recognized payload are preserved on copy and otherwise
  ignored. This is the only forward-compatibility affordance.

An OPTIONAL key that appears only where it applies — `documents[].meta` today —
is not a new version, and a reader that ignores it still reads the payload
correctly. A key a conforming reader must understand is.

## Checking an export

Given only the file:

1. `$format` equals `backdraft/registry-v1`.
2. For every anchor, `sha256(normalize(snippet))` equals `snippet_sha256`, and
   `token`'s hash segment is a prefix of it. `token`'s slug and locator segments
   equal the document's `slug` and the anchor's `locator`.
3. For every chunk anchor, on the page `page_number` names,
   `text[start:end]` equals `snippet`.
4. Exactly one generation per document has `is_current: true`, and `locator` is
   unique within each generation.
5. Every `ledger[].session_id` names a session, and every `ledger[].token` names
   an anchor in some generation.

Only one check needs the world outside the file: re-reading each document's
`path` and confirming its bytes still hash to `sha256`. Everything else is
internal, which is what makes an export auditable long after the sources moved.
