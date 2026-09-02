# The artifact — normative format

Status: v0, 2026-07-27. This file is the portable specification of
`backdraft/artifact-v1`. `src/backdraft/kernel/artifact.py` implements the format
itself — the format string, the legend, and the payload writer, shared by bind
which writes it and render which reads it — and `src/backdraft/render/` implements
the renderers over it. Another implementation reads this file and nothing else.
Where they disagree, this file and the tests in `tests/test_sidecar.py` and
`tests/test_html.py` decide.

An **artifact** is a rendered, self-contained deliverable: an authored document
plus, for every claim in it, the verbatim evidence behind that claim. It exists
in two forms that carry the same value:

| Form | File | Is |
|---|---|---|
| **sidecar** | `<doc>.backdraft.json` | the record alone, as JSON |
| **artifact** | `<doc>.backdraft.html` | one HTML file: the document, its receipts, and the sidecar embedded verbatim |

There is also a lossy markdown projection (`--to footnotes`), described at the
end and not normative.

The point of the format is that it survives its producer. An artifact is
defensible with the registry deleted, the source documents gone, the tool
uninstalled and the network unavailable — because the evidence is inside it and
the file explains its own decoding.

## Naming

A document's record is named after the document's stem:

```
memo.md          ->  memo.backdraft.json
memo.md          ->  memo.backdraft.html
report.final.md  ->  report.final.backdraft.json
```

The record has two homes. **Beside the document** is the portable form — the
one a reader handed a document and its record uses, and the one a renderer
looks for first. **Inside the project** (`.backdraft/records/<document's path
relative to the project root>`) is where a bind run with a registry writes, so
the authored directory shows only the document and its artifact. A renderer
looks beside the document first (accepting `memo.md.backdraft.json` as a typed
variant on read, writing only the stem form), then in the records store of the
nearest ancestor directory containing `.backdraft/`. No registry is ever
opened: an artifact is reproducible from the document and its record.

## The payload

The sidecar file is UTF-8 JSON, one object, newline-terminated. Two reserved
keys come first, then the bind report:

```json
{
  "$format": "backdraft/artifact-v1",
  "$legend": { "…": "…" },
  "doc_path": "memo.md",
  "mode": "frontwalk",
  "session_id": "s-bridgeview-01",
  "bound_at": "2026-07-27T14:32:05Z",
  "claims": [ … ],
  "summary": { … },
  "evidence": { … }
}
```

`evidence` is OPTIONAL: context for the cited sources, assembled at bind and
bounded by what is cited — never the whole corpus. Its keys: `documents` maps
slug to `{filename, media_type}`, plus `url` and `fetched_at` for a source
fetched from the web — the page the bytes came from (after redirects) and when
they were taken, both OPTIONAL and both absent for a source read from a file;
they are provenance, never identity, so two documents differing only in `url`
are still distinct only if their bytes differ. `pages` maps `slug:pN` to a page image
`{format, width, height, data}` with `data` base64 (for a vision-model
extraction, the page as the model was shown it); `pagetexts` maps `slug:pN` to
that page's extracted text; `windows` maps `slug:<locator>` to a small cell
grid `{sheet, cited, cols, rows}` around a cited cell, with an OPTIONAL
`styles` object `{cells, widths}` carrying the workbook's presentation for
those cells; `sheets` maps `slug:<sheet>` to the full cited sheet's values
`{name, nrows, ncols, rows}`, with an OPTIONAL `meta` object
`{palette, cells, widths, merged, frozen}` — cell styling as indices into a
style palette (`b` bold, `fg`/`bg` six-hex colors, `fmt` the Excel number
format string), column widths in Excel character units, merged ranges as A1
ranges, and the frozen pane's top-left cell. Styling is display context and
never citation identity: snippets, hashes, and tokens are computed from
values alone, and a renderer that ignores `styles`/`meta` entirely is
conforming. A record without `evidence` is complete — evidence is context,
snippets are the proof.

| Key | Type | Is |
|---|---|---|
| `$format` | string | `backdraft/artifact-v1`, matched exactly. See *Versioning* |
| `$legend` | object | prose that teaches a reader to decode the payload. See *The legend* |
| `doc_path` | string | the authored document this run bound, as bind was given it |
| `mode` | `"frontwalk"` \| `"backfill"` | how the citations were produced |
| `session_id` | string \| null | the ledger session, when the run had one |
| `bound_at` | string | ISO-8601 UTC, as everywhere in backdraft |
| `claims` | array | every claim, in document order |
| `summary` | object | counts, derived from `claims` |

Keys appear in that order. Encoding is deterministic — two-space indent,
non-ASCII preserved rather than escaped, no key sorting — so that two runs over
the same report produce identical bytes and artifacts diff cleanly.

### `claims[]`

| Key | Type | Is |
|---|---|---|
| `text` | string | the words the citations support — the claim span |
| `start`, `end` | int | character offsets into the authored document, bounding the whole construct bind read |
| `unmatched` | bool | backfill outcome: bind could not anchor this claim |
| `citations` | array | the tokens the author attached, in the order written |

`text` is the link text alone; `start`/`end` bound the entire markdown link, so
`source[start:end]` is what bind rewrites. A consumer MUST NOT assume the
offsets still address the document it holds — bind may have rewritten it — and
MUST fall back to locating the claim by its `text`.

### `claims[].citations[]`

| Key | Type | Is |
|---|---|---|
| `token` | string | the citation exactly as authored, even when it does not parse |
| `status` | string | one of the five statuses below |
| `anchor` | object | present when an anchor was found |
| `drifted_from` | string | present when `status` is `drifted`: the snippet as cited |
| `error` | string | why the status happened, where the status alone does not say: a `malformed` token's parse failure, or an `unresolved` one whose source was withdrawn |
| `verdicts` | array | one entry per verification method that ran; always present, may be empty |

### `claims[].citations[].anchor`

| Key | Type | Is |
|---|---|---|
| `slug` | string | the source document's handle |
| `locator` | string | the location inside it — the token's locator segment |
| `snippet` | string | the verbatim evidence |
| `snippet_sha256` | string | `sha256(normalize(snippet))`, full 64 hex |

`normalize` is Unicode NFC, then every whitespace run collapsed to one space,
then strip; case is preserved. The `hash` segment of the token is a 4-to-8-char
prefix of `snippet_sha256`. Locator forms and the token grammar are specified in
[tokens.md](tokens.md).

The anchor deliberately carries no registry identifiers — no extraction id, no
row id, no offsets into the page. Those name rows in a database the reader does
not have.

### `claims[].citations[].verdicts[]`

| Key | Type | Is |
|---|---|---|
| `method` | string | `value-trace` \| `overlap` \| `recompute` \| `entail` |
| `status` | `pass` \| `fail` \| `partial` \| `skip` | the finding |
| `detail` | string | one line of evidence for the finding; may be empty |

Verification methods are opt-in switches and are never gates. A method absent
from `verdicts` was **not run** — that is not a pass.

### `summary`

`{"claims": int, "citations": int, "by_status": {status: count}, "by_method": {method: {verdict status: count}}}`,
derived from `claims`. A reader that finds the two disagreeing MUST prefer
`claims`.

### Statuses

Citation status is a closed set; every value other than `resolved` is a
first-class line item that a renderer MUST show:

| Status | Means |
|---|---|
| `resolved` | the anchor is in the source's current extraction |
| `drifted` | the anchor is only in a superseded extraction: the source changed after the claim was written |
| `not_shown` | a valid anchor the writer was never shown (front-walk only) |
| `unresolved` | a well-formed token the sources do not stand behind: no anchor in any generation, or a source withdrawn from the registry |
| `malformed` | the citation text is not a token; `error` says why |

For `drifted`, `drifted_from` is the snippet **as cited** — what the author saw
— and `anchor.snippet` is what stands at that locator **now**. A renderer shows
both; the difference is the finding.

`unresolved` covers two cases and `error` separates them. Where it is absent, the
token names no anchor anywhere and the citation carries none. Where it names a
**withdrawn** source, the producing registry still held the anchor and the
citation carries it with its receipt intact — the source was taken out of that
registry's readable set rather than lost, so the evidence is still checkable and
the claim is still uncited. A reader MUST NOT treat a withdrawn citation's
present `anchor` as making it `resolved`; the status is the finding.

## The legend

`$legend` is an object of prose, addressed to a reader who has never seen
backdraft — a person, or a model with no tools and no context. It is normative:
a conforming producer MUST emit it, and MUST emit text that says what the keys
below say. It is not a schema, not machine-parsed by anything, and not
extensible into a protocol; it is documentation that travels with the data.

| Key | Type | Must say |
|---|---|---|
| `what_this_is` | string | that this is a bound document, that the evidence is embedded, and that no other file is needed |
| `how_to_read` | array of strings | how `claims`, `citations`, `anchor` and `summary` relate; that non-`resolved` statuses are kept failures; that `summary` is derived |
| `token` | string | the token shape and the hash/normalization rule, so a reader can recompute it |
| `locator_forms` | object | one example per locator form, each mapped to what it names |
| `citation_status` | object | one entry per citation status, saying what the reader should conclude |
| `verdict_status` | object | one entry per verdict status |
| `verdicts_are_evidence` | string | that methods are opt-in and absent means not-run, not pass |
| `verify_this_record` | array of strings | the steps that check the record against itself, and the one check that needs the sources |
| `version` | string | the exact-match rule below, stated so a reader does not guess |

A consumer MUST NOT treat `$legend` as authoritative over this specification,
and MUST NOT change behavior based on its contents. It exists so that a reader
holding only the file can act correctly; this file exists so that an
implementer can.

## Versioning

`$format` is an opaque string, compared byte for byte.

- A reader that recognizes `backdraft/artifact-v1` reads the payload as specified
  here.
- A reader that does not recognize the exact string MUST refuse the payload
  rather than interpret it. There is no compatibility range, no minor version,
  no negotiation, and no partial read.
- A later version gets a new string. It may reuse these field names with other
  meanings; that is exactly why guessing is forbidden.
- Unknown keys inside a recognized payload are preserved on copy and otherwise
  ignored. This is the only forward-compatibility affordance.

## The HTML artifact

The HTML form MUST satisfy all of the following. They are what "self-contained"
means, and each is testable:

1. **One file, no network.** No external request of any kind: no stylesheet,
   font, script source, remote image or fetch to any origin. Every style is
   inline; every image is a `data:` URI. The constraint is enforced, not
   promised: a `Content-Security-Policy` meta tag with `default-src 'none'`
   makes the browser refuse any request the file might try. The file renders
   identically from `file://` with the network down. Mathematics, where a
   producer renders it, MUST be static markup for the same reason: MathML
   satisfies this, while a script-driven formula renderer or a downloaded math
   font does not. A producer that does not render math MUST leave the author's
   source visible rather than altering it.
2. **Script is enhancement, never substrate.** Inline behavior script is
   permitted (it is how the evidence rail, source selector and sheet view
   work) but the artifact MUST degrade to a readable document without it:
   every claim is an anchor link to its entry in a visible Notes section, and
   every receipt's text is present in static markup. No script `src`, no
   inline event-handler attributes, no `javascript:` URLs.
3. **The islands.** Exactly one `<script type="application/json"
   id="backdraft-artifact">` carrying the record: the sidecar payload, except
   that `evidence.pages[*].data` MAY be omitted when the identical bytes are
   present in the page as image elements (`$legend` documents the omission —
   `--to json` always writes the full record). A second data island
   (`id="bd-sheets"`) MAY carry full cited-sheet values for the sheet view.
   Producers MUST escape `<`, `>` and `&` inside every island as the JSON
   escapes `\u003c`, `\u003e` and `\u0026`, so no snippet can terminate the
   element early; JSON decoding restores them.
4. **Every claim.** Every claim in the payload is present in the rendered
   document, addressable by a stable fragment id, with a card and a note. A
   claim whose text cannot be found in the document body is kept visibly in
   the Notes section rather than dropped.
5. **Every receipt.** Each citation's verbatim evidence is reachable: the
   quote (or the cell grid / page evidence that carries it), the source, and —
   in a disclosure layer — its token, its `snippet_sha256`, and each verdict
   in plain language. A `drifted` citation renders both snippets as a diff.
6. **Success is silent; failure speaks in place.** A fully-resolved artifact
   says nothing about citations on its face. When a citation is not `resolved`
   or a claim is `unmatched`, the claim carrying it MUST be visibly marked
   where it stands in the document, and the failure MUST appear in the Notes
   with its reason. A claim not found in the document body is kept in the Notes
   (see 4), which is the whole of its showing. Nothing is warned about and
   dropped.

   Deliberately **not** required: a summary of failures in the masthead or
   anywhere else above the document. A count a reader meets before the first
   sentence — *"1 of 16 citations could not be traced"* — cannot be acted on,
   because whether that one matters is a question only the claim itself
   answers. Producers MUST NOT gate on this, and a producer that adds such a
   summary is still conforming; the requirement is that failure is impossible
   to miss *at the claim*, not that it is announced first.
7. **Print-aware, light-first, fixed at render.** The artifact is a paper
   document: it renders light, carries a print stylesheet, and never responds
   to the reader's environment — no `prefers-color-scheme` branch, no stored
   preference, no control that restyles it. Its appearance is whatever the
   producer chose when the file was written, which is what makes two readers
   of one artifact see one document. A producer MAY let an author pick that
   appearance (this implementation's `render --theme`); the choice is baked
   into the file, and may not change the structure, the disclosure layers, or
   anything a reader verifies by.

Nothing above forbids a viewer built on top of the islands. The rule is that
the artifact must be complete without one.

## Checking an artifact

Given only the file, in this order:

1. Parse the island (or read the sidecar). `$format` must equal
   `backdraft/artifact-v1`.
2. For every citation carrying an anchor, recompute `sha256(normalize(snippet))`
   and compare it to `snippet_sha256`.
3. For every such citation, check that the token's `hash` segment is a prefix of
   the sha256 of the snippet that token was **minted from**. For a citation
   carrying `drifted_from` that snippet is `drifted_from`, not `anchor.snippet`:
   the token names what the author cited, `anchor` carries what stands at that
   locator now, and the two hashes differing is precisely what `drifted` means.
   For every other citation it is `anchor.snippet`. Either way the token's
   `slug` and `locator` segments MUST equal the anchor's — drift holds the
   locator and moves the text.
4. Recount `summary` from `claims`.
5. Confirm the rendered document shows every non-`resolved` citation.

Only one check needs the world outside the file: looking `locator` up in the
document named by `slug` and comparing it to `snippet`. That is the check the
receipt exists to make rare.

`backdraft verify <artifact>` is this list, implemented: steps 1 to 4 from the
file alone, and — only where a registry is discoverable from the current
directory — the outside check as well, re-resolving every token and reporting
the statuses. It exits 0 when everything it checked passed, 1 when the file is
not an artifact of this format, and 2 when something did not verify. A record
that carries a non-`resolved` citation still passes: what the producer found is
data the record faithfully carries, not a defect in it.

## The markdown projection (informative)

`--to footnotes` renders the same report as plain markdown: each claim's
citations become footnote references (`[^bd1]`, numbered in document order), a
`## Receipts` section carries one footnote definition per citation — source
`slug`, locator, verbatim quote, token, `snippet_sha256`, verdicts — and a
`## Unresolved` section repeats every non-`resolved` citation and every
unmatched claim. It is a projection for places HTML cannot go; the sidecar
remains the record.
