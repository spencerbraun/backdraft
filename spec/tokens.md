# Citation tokens — normative format

Status: v0, 2026-07-27. This file is the portable specification of the token
grammar. `src/backdraft/kernel/tokens.py` implements it; another implementation
(TypeScript, say) reads this file and nothing else. Where the two disagree, this
file and the tests in `tests/test_tokens.py` decide.

A **token** is the textual name of an **anchor** — an addressable location in an
extraction, carrying a verbatim snippet and that snippet's hash. A model
transcribes tokens; nothing else about the source travels in the authored text.

## Grammar

```
token       = "bd:" slug ":" locator ":" hash
slug        = alnum-lower (alnum-lower | "-"){1,31}   ; unique per registry
locator     = page-loc | chunk-loc | cell-loc
page-loc    = "p" int                                 ; whole page
chunk-loc   = "p" int "." "c" int                     ; chunk ordinal, 1-based
cell-loc    = sheetref "!" cell [":" cell]            ; cell or rectangular range
sheetref    = sheet name, no ":" "!" ";" "(" ")" or whitespace
cell        = column-letters row-int                  ; A1 notation, uppercase
hash        = lowercase-hex{4,8}                      ; prefix of snippet sha256
int         = "0" | [1-9] digit*                      ; canonical, no leading zeros
```

Examples:

| Token | Names |
|---|---|
| `bd:t12-audit:p8.c3:a7f3` | chunk 3 of page 8 |
| `bd:t12-audit:p8:c114` | all of page 8 |
| `bd:model:rent-roll!B10:9e2f` | one cell |
| `bd:model:rent-roll!B10:C12:9e2f` | a rectangular range |

Additional constraints, all enforced by the parser:

- A slug is 2–32 characters. It starts with a lowercase letter or digit; the rest
  may also contain `-`.
- Page numbers and chunk ordinals are 1-based, written without leading zeros.
- Cell columns are uppercase letters; cell rows are 1-based.
- The hash is 4–8 lowercase hex characters. Registries mint 4, extending to 6
  then 8 on collision within a document; parsers accept anything in the range.
- Parsing is strict. Surrounding whitespace is not tolerated, nothing is
  canonicalized, and formatting a parsed token reproduces the input exactly.

Parsing a token is unambiguous despite `:` appearing inside a range locator: the
slug is everything up to the first `:` after the prefix, the hash is everything
after the last `:`, and the locator is what remains.

## Wire form

A claim is a markdown link whose text is the claim span and whose href is one or
more tokens:

```markdown
The [DSCR of 1.42x](bd:t12-audit:p8.c3:a7f3) clears the covenant.
The [numbers tie](bd:model:rent-roll!B10:9e2f;bd:t12-audit:p4.c1:1b8e) exactly.
```

Multiple citations are separated by `;`. There is one grammar and no alternates:
no bare tokens, no footnote syntax, no display text. Doc names, page numbers,
quotes and footnotes are render-time projections of the anchor, added by `bind`
and `render`, never authored.

## Hashing

The hash segment is a prefix of `sha256(normalize(snippet))`, where `normalize`
is: Unicode NFC, then every whitespace run collapsed to a single space, then
strip. Case is preserved. This is the only normalization in the system.

## Reserved: derivations

`bd:calc(<expr over tokens>)` is reserved for declared derivations — a claim
whose value appears in no document, carrying its computation over other tokens.
The expression grammar is not specified in v0.

A v0 parser **must reject it cleanly and distinctly**: recognized, unsupported,
never a crash and never confused with a typo. In Python this is
`UnsupportedTokenError`; in a report the citation's status is `malformed` with an
error that names the form.

## Statuses

A citation resolved by `bind` carries exactly one status from this closed set:

| Status | Means |
|---|---|
| `resolved` | anchor found in the current extraction |
| `drifted` | anchor found only in a superseded extraction; the report carries both snippets |
| `not_shown` | valid anchor, absent from the session ledger (front-walk only) |
| `unresolved` | well-formed token, no anchor in any generation |
| `malformed` | the token text does not parse |

Every non-`resolved` status is a line item. Nothing is dropped silently.
