# Bridgeview — T-12 review

**Recommendation:** proceed to term sheet. The property clears its covenant at a
DSCR of 1.42x[^bd1], on
NOI of $4.1M[^bd2][^bd3].

## What the file says

- Occupancy has been stable through the year[^bd4].
- The reserve balance[^bd5] is unchanged, per the *prior* memo.
- Across both files, the ratios tie[^bd6].

The underwriting rows come from the reserve schedule[^bd7]:

| Line | 2025 | 2024 |
|---|---:|---:|
| Revenue | 6,410,000 | 6,120,000 |
| Expenses | 2,310,000 | 2,260,000 |

> Underwriting is `unchanged` from the prior review.

See the [appendix](appendix.md) for the rent roll as extracted.

---

## Receipts

Bound from `memo.md` — frontwalk, session `s-bridgeview-01`, 2026-07-27T14:32:05Z. Machine-readable record: `memo.backdraft.json` (`backdraft/artifact-v1`).

[^bd1]: **t12-audit** · `p8.c3` · resolved

    > Debt service coverage for the trailing twelve months is 1.42x, against a covenant floor of 1.20x.

    Token `bd:t12-audit:p8.c3:f3e4` · sha256 `f3e4f7d7833bceb52f1591cae2b5f3530b3b53af3805b4f334f58394a9e805ce`

    Verdicts: value-trace pass — 1.42x occurs in the snippet; overlap partial — 0.62 of the claim's tokens

[^bd2]: **model** · `rent-roll!B10` · resolved

    > [B10] 4,100,000

    Token `bd:model:rent-roll!B10:27e9` · sha256 `27e90216cf24e79ee1a4ca3eb24726fb18be4966e291dc831042b75d41644e9d`

    Verdicts: value-trace pass — 4,100,000 == $4.1M at scale 1e6

[^bd3]: **t12-audit** · `p8` · drifted

    > Page 8 — Coverage
    >
    > Debt service coverage for the trailing twelve months is 1.42x, against a covenant floor of 1.20x.
    >
    > The covenant floor is unchanged from the prior review.

    Token `bd:t12-audit:p8:8f04` · sha256 `4c64381bf85d22aa26e96604179f35b112c63972b1c19920479eb4e0ef974b30`

    As cited, before the source changed:

    > Page 8 — Coverage
    >
    > Debt service coverage for the trailing twelve months is 1.31x, against a covenant floor of 1.20x.
    >
    > The covenant floor is unchanged from the prior review.

    Verdicts: value-trace fail — $4.1M does not occur in the page

[^bd4]: **t12-audit** · `p4.c1` · not_shown

    > Occupancy closed the year at 91.4%, down from 93.8%.

    Token `bd:t12-audit:p4.c1:ad01` · sha256 `ad01ed7a5e8f6ac9572eced97b030f57de9d949729440678a8798c9c6ce14f66`

    Verdicts: entail skip — judge not enabled for this run

[^bd5]: unanchored · unresolved

    Token `bd:t12-audit:p12.c2:0000`

    Verdicts: none run.

[^bd6]: unanchored · malformed

    Token `bd:calc(model:rent-roll!B10 / t12-audit:p4.c1)`

    Error: reserved derivation form 'bd:calc(...)' is not supported in v0: 'bd:calc(model:rent-roll!B10 / t12-audit:p4.c1)'

    Verdicts: none run.

[^bd7]: **model** · `rent-roll!B10:C12` · resolved

    > [B10] 4,100,000
    > [B11] 260,000
    > [C10] 3,980,000
    > [C11] 240,000

    Token `bd:model:rent-roll!B10:C12:3095` · sha256 `3095fb5e6a0f8dac929114bbe793412c986bd40ddcd30f4db0e0dfe0cb52ac15`

    Verdicts: overlap pass — exact substring for the quoted rows; entail partial — supports the rows, not the trend

## Unresolved

- **drifted** — `bd:t12-audit:p8:8f04` in claim 2, “NOI of $4.1M”: the source changed after this claim was written.
- **not_shown** — `bd:t12-audit:p4.c1:ad01` in claim 3, “has been stable through the year”: a valid anchor, but the writer was never shown it.
- **unresolved** — `bd:t12-audit:p12.c2:0000` in claim 4, “reserve balance”: no anchor for this token in any generation.
- **malformed** — `bd:calc(model:rent-roll!B10 / t12-audit:p4.c1)` in claim 5, “the ratios tie”: reserved derivation form 'bd:calc(...)' is not supported in v0: 'bd:calc(model:rent-roll!B10 / t12-audit:p4.c1)'.
