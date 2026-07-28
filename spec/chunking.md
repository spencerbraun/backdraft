# Chunking — normative format

Status: v0, 2026-07-27. This file is the portable specification of the chunker.
`src/backdraft/kernel/chunking.py` implements it and
`tests/golden/chunking/*.json` pins it. Where they disagree, this file and the
golden files decide.

A chunk's ordinal is half of an anchor's identity — `(extraction, page number,
ordinal)` — so chunking must be a pure function of the page text alone. Same
text in, same chunks out, on any machine, in any version. There is deliberately
no per-page rebalancing and no chunk-count cap: balancing schemes shift every
boundary on the page when one paragraph changes.

## Algorithm

Input: one page's text (a PDF page or a sheet, exactly as stored in the
extraction snapshot). Output: an ordered list of chunks, each with a 1-based
ordinal, its text, and the character offsets of that text in the page.

1. **Split on blank lines.** Separator: the regular expression `\n\s*\n`.
2. **Merge forward.** Scanning left to right, a segment shorter than **200**
   characters merges with the segment that follows it, repeatedly, until the
   accumulated region reaches 200 characters or the segments run out. If the
   final region is still under 200 characters and it is not the only one, it
   merges backward into its predecessor instead.
3. **Split long.** A region longer than **2400** characters is split at the
   sentence boundary nearest each multiple of **1200** characters. A sentence
   boundary is a terminal `.`, `!` or `?` followed by whitespace and then an
   uppercase letter or a digit; the boundary sits at that letter or digit. There
   is no abbreviation table: splitting slightly wrong only moves a boundary, and
   it moves it deterministically. Ties go to the earlier boundary. A region with
   no sentence boundary at all is left whole, oversize. If the final piece of a
   split is under **200** characters, it merges backward into the piece before
   it — the same backward merge rule 2 applies to a trailing short region.
4. **Number.** Ordinals `c1..cN` in order of appearance.

Chunking happens in that order: merging precedes splitting, so a short heading
followed by a long paragraph is one region that is then split by length. Because
merging cannot see pieces that do not exist yet, rule 3 carries the backward
merge itself; without it a 2500-character paragraph would leave a 100-character
chunk whose receipt is a sentence fragment. The consequence is worth stating
plainly: **a chunk is under 200 characters only when it is the only chunk on
its page.**

## Offsets

`start` and `end` are character offsets into the page text, and they are exact:

```
page_text[chunk.start : chunk.end] == chunk.text
```

A chunk's text is therefore the verbatim source region. Only the outer edges are
trimmed of whitespace, so a chunk never begins or ends with whitespace but does
contain any blank line that merging swallowed. Chunks are disjoint and ordered;
they need not cover the page, since trimmed whitespace falls between them.

Storing the offsets is what makes future span and region features possible; they
are not used for resolution, which goes through the locator.

## Empty pages

A page that is empty or contains only whitespace produces no chunks.
