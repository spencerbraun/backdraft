"""value-trace: does the claim's value occur at the cited location?

The deterministic check. A claim says "$1.4M"; the snippet says "1,400,000".
Those are the same value, and a verifier that cannot see that is useless on real
documents, so the unit/scale/format equivalences live here — and *only* here.
`kernel.hashing.normalize` is whitespace and Unicode form; this module is the
system's one authority on when two written values are the same value.

Equivalences implemented (both directions — the side carrying the marker is the
side that expands):

* **Thousands separators / currency / whitespace** — `$1,400,000` ≡ `1400000`.
* **Scale suffixes** — `K` `M` `MM` `B` `BN` `T` attached, and the words
  `thousand` `million` `billion` `trillion` spaced: `$1.4M` ≡ `1.4 million` ≡
  `1,400,000`.
* **Percent** — `12%` and `12 percent` each stand for both `12` and `0.12`, so a
  percent on either side matches a bare decimal on the other. A bare `0.12` does
  *not* expand to `12`: that direction is the ambiguous one.
* **Multipliers** — `1.42x` ≡ `1.42` (the `x` is a unit, not a scale).
* **Accounting negatives** — `(1,234)` ≡ `-1234`.
* **Trailing zeros** — `4.10` ≡ `4.1` (values compare as numbers, not strings).
* **Dates** — `2025-03-31` ≡ `March 31, 2025` ≡ `Mar. 31 2025` ≡
  `31 March 2025` ≡ `3/31/2025`. A slash date whose first field could be either
  field expands to both readings; `2025-03` ≡ `March 2025`.

Rounding is a `partial`, never a `pass`: a claim written as `$1.4M` against a
snippet reading `1,412,000` is a rounded match — the claim's own precision sets
the quantum. A date written to month precision against a day-precision date in
the snippet is the same case.

Verdict rule: every value in the claim must be found in the snippet. Any value
with no match at all ⇒ `fail`, naming the values that were not found. All found,
at least one only by rounding ⇒ `partial`. All found exactly ⇒ `pass`.

NOTE: the spec's claim class for value-trace is "numbers, dates, names"; names
are not extracted here. A name is a span of words, which is what `overlap`
already measures, and a name extractor is a guessing machine this deterministic
check should not contain.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from ...kernel.hashing import normalize
from ...kernel.model import Anchor, Citation, Claim, Verdict, VerdictStatus
from .base import register

__all__ = ["ValueTrace", "value_trace"]

_SCALES: dict[str, Decimal] = {
    "k": Decimal(10) ** 3,
    "thousand": Decimal(10) ** 3,
    "m": Decimal(10) ** 6,
    "mm": Decimal(10) ** 6,
    "million": Decimal(10) ** 6,
    "b": Decimal(10) ** 9,
    "bn": Decimal(10) ** 9,
    "billion": Decimal(10) ** 9,
    "t": Decimal(10) ** 12,
    "trillion": Decimal(10) ** 12,
}

_CURRENCY = "$€£¥"

_MONTHS: dict[str, int] = {}
for _index, _name in enumerate(
    (
        "january",
        "february",
        "march",
        "april",
        "may",
        "june",
        "july",
        "august",
        "september",
        "october",
        "november",
        "december",
    ),
    start=1,
):
    _MONTHS[_name] = _index
    _MONTHS[_name[:3]] = _index
_MONTHS["sept"] = 9

_MONTH_NAMES = "|".join(sorted(_MONTHS, key=len, reverse=True))

# Dates are extracted first and their spans masked, so `2025-03-31` never
# decomposes into the numbers 2025, 3 and 31.
_DATE_PATTERNS = (
    re.compile(r"\b(?P<y>\d{4})-(?P<m>\d{1,2})-(?P<d>\d{1,2})\b"),
    re.compile(
        rf"\b(?P<mon>{_MONTH_NAMES})\.?\s+(?P<d>\d{{1,2}})(?:st|nd|rd|th)?,?\s+(?P<y>\d{{4}})\b",
        re.IGNORECASE,
    ),
    re.compile(
        rf"\b(?P<d>\d{{1,2}})(?:st|nd|rd|th)?\s+(?P<mon>{_MONTH_NAMES})\.?,?\s+(?P<y>\d{{4}})\b",
        re.IGNORECASE,
    ),
    re.compile(r"\b(?P<a>\d{1,2})/(?P<b>\d{1,2})/(?P<y>\d{4})\b"),
    re.compile(r"\b(?P<a>\d{1,2})/(?P<b>\d{1,2})/(?P<y2>\d{2})\b"),
    re.compile(rf"\b(?P<mon>{_MONTH_NAMES})\.?\s+(?P<y>\d{{4}})\b", re.IGNORECASE),
    re.compile(r"\b(?P<y>\d{4})-(?P<m>\d{1,2})\b"),
)

_DIGITS = r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?|\.\d+"
_ATTACHED_SCALE = r"MM|mm|[Bb][Nn]|[KkMmBbTt]"
_WORD_SCALE = r"thousand|million|billion|trillion"
_NUMBER = re.compile(
    rf"""
    (?P<open>\()?
    (?P<sign>-)?
    (?P<currency>[{_CURRENCY}])?\s?
    (?P<sign2>-)?
    (?P<digits>{_DIGITS})
    (?:
        (?P<percent>\s?%|\s+percent\b)
      | (?P<multiplier>[xX×](?![A-Za-z0-9]))
      | (?P<attached>(?:{_ATTACHED_SCALE})(?![A-Za-z0-9]))
      | \s(?P<word>{_WORD_SCALE})\b
    )?
    (?P<close>\))?
    """,
    re.VERBOSE | re.IGNORECASE,
)

_WORD = re.compile(r"[A-Za-z0-9]")

_ORDINAL_LABEL = re.compile(
    r"\b(?:year|yr|quarter|qtr|month|week|day|phase|tier|fy|q)[\s\-#]{0,2}\d{1,2}\b",
    re.IGNORECASE,
)
"""Structural labels, not claimed values: the `1` in `Year 1 debt yield` names a
column, and hunting for a bare `1` in the source produced false fails on every
proforma claim. Masked like dates, before number extraction, on both sides."""


@dataclass(frozen=True, slots=True)
class _Reading:
    """One numeric reading of a written value: the number and its precision.

    `quantum` is the size of the last written digit — `1.4M` is precise to
    100000, `1,412,000` to 1 — and is what rounding comparisons round to.
    """

    number: Decimal
    quantum: Decimal


@dataclass(frozen=True, slots=True)
class _Value:
    """One value as written, with every reading it could stand for."""

    text: str
    kind: str
    readings: tuple[_Reading, ...] = ()
    dates: tuple[tuple[int, int, int | None], ...] = ()


def extract_values(text: str) -> list[_Value]:
    """Every number and date written in `text`, in order.

    Dates are matched first and their spans removed from number scanning, so a
    date's fields are never also read as three separate numbers.
    """
    source = normalize(text)
    masked = list(source)
    values: list[_Value] = []
    spans: list[tuple[int, int, _Value]] = []
    for match in _ORDINAL_LABEL.finditer(source):
        for index in range(match.start(), match.end()):
            masked[index] = "\x00"
    for pattern in _DATE_PATTERNS:
        for match in pattern.finditer(source):
            if any(masked[index] == "\x00" for index in range(match.start(), match.end())):
                continue
            date = _read_date(match)
            if date is None:
                continue
            for index in range(match.start(), match.end()):
                masked[index] = "\x00"
            spans.append((match.start(), match.end(), date))
    remainder = "".join(masked)
    for match in _NUMBER.finditer(remainder):
        if "\x00" in match.group(0):
            continue
        number = _read_number(match)
        if number is not None:
            spans.append((match.start(), match.end(), number))
    for _start, _end, value in sorted(spans, key=lambda item: item[0]):
        values.append(value)
    return values


def _read_number(match: re.Match[str]) -> _Value | None:
    """One `_Value` from a number match, or None if the digits do not parse."""
    digits = match["digits"].replace(",", "")
    try:
        magnitude = Decimal(digits)
    except InvalidOperation:  # pragma: no cover - the regex admits only numerals
        return None
    exponent = -magnitude.as_tuple().exponent
    quantum = Decimal(1).scaleb(-exponent)  # type: ignore[operator]
    negative = bool(match["sign"] or match["sign2"]) or bool(match["open"] and match["close"])
    scale = Decimal(1)
    if match["attached"]:
        scale = _SCALES[match["attached"].lower()]
    elif match["word"]:
        scale = _SCALES[match["word"].lower()]
    value = magnitude * scale
    quantum = quantum * scale
    if negative:
        value = -value
    readings = [_Reading(number=value, quantum=quantum)]
    if match["percent"]:
        readings.append(_Reading(number=value / 100, quantum=quantum / 100))
    return _Value(text=match.group(0).strip(), kind="number", readings=tuple(readings))


def _read_date(match: re.Match[str]) -> _Value | None:
    """One `_Value` from a date match, or None if the fields are not a date."""
    groups = match.groupdict()
    candidates: list[tuple[int, int, int | None]] = []
    if "mon" in groups and groups.get("mon"):
        month = _MONTHS[groups["mon"].lower().rstrip(".")]
        year = int(groups["y"])
        day = int(groups["d"]) if groups.get("d") else None
        if day is not None and not 1 <= day <= 31:
            return None
        candidates.append((year, month, day))
    elif groups.get("a") is not None:
        first, second = int(groups["a"]), int(groups["b"])
        year = int(groups["y"]) if groups.get("y") else 2000 + int(groups["y2"])
        # NOTE: month-first is the primary reading; the day-first reading is
        # added whenever both fields could be a month, so an ambiguous slash
        # date matches either convention rather than half of them.
        if 1 <= first <= 12 and 1 <= second <= 31:
            candidates.append((year, first, second))
        if 1 <= second <= 12 and 1 <= first <= 31 and (year, second, first) not in candidates:
            candidates.append((year, second, first))
    else:
        year = int(groups["y"])
        month = int(groups["m"])
        day = int(groups["d"]) if groups.get("d") else None
        if not 1 <= month <= 12:
            return None
        if day is not None and not 1 <= day <= 31:
            return None
        candidates.append((year, month, day))
    if not candidates:
        return None
    return _Value(text=match.group(0).strip(), kind="date", dates=tuple(candidates))


def matches(claimed: _Value, found: _Value) -> str | None:
    """`"exact"`, `"rounded"`, or None — how `found` satisfies `claimed`."""
    if claimed.kind != found.kind:
        return None
    if claimed.kind == "date":
        return _match_dates(claimed, found)
    for reading in claimed.readings:
        for other in found.readings:
            if reading.number == other.number:
                return "exact"
    for reading in claimed.readings:
        for other in found.readings:
            if _rounds_to(other.number, reading) or _rounds_to(reading.number, other):
                return "rounded"
    return None


def _match_dates(claimed: _Value, found: _Value) -> str | None:
    if set(claimed.dates) & set(found.dates):
        return "exact"
    for year, month, day in claimed.dates:
        for other_year, other_month, other_day in found.dates:
            if (year, month) != (other_year, other_month):
                continue
            if day is None or other_day is None:
                return "rounded"
    return None


def _rounds_to(number: Decimal, target: _Reading) -> bool:
    """True when `number` rounds to `target` at `target`'s written precision.

    A zero target is excluded: everything small "rounds to 0" at an integer's
    precision, which once matched every percentage in a claim against a bare
    `0` in a proforma row and reported `7.6% ~ 0`. Nothing nonzero is evidence
    for zero.
    """
    if target.quantum <= 0:
        return False  # pragma: no cover - quanta are powers of ten
    if target.number == 0 and number != 0:
        return False
    steps = (number / target.quantum).quantize(Decimal(1))
    return steps * target.quantum == target.number


class ValueTrace:
    """Deterministic value equivalence between a claim and its anchor snippet."""

    method = "value-trace"

    def applies(self, claim: Claim, citation: Citation) -> bool:
        """True when the claim text contains at least one number or date."""
        return bool(extract_values(claim.text))

    def verify(self, claim: Claim, citation: Citation, anchor: Anchor) -> Verdict:
        """Every claimed value, sought in the anchor's verbatim snippet."""
        claimed = extract_values(claim.text)
        found = extract_values(anchor.receipt.snippet)
        missing: list[str] = []
        rounded: list[str] = []
        for value in claimed:
            outcome = None
            partner = None
            for candidate in found:
                result = matches(value, candidate)
                if result == "exact":
                    outcome, partner = result, candidate
                    break
                if result == "rounded" and outcome is None:
                    outcome, partner = result, candidate
            if outcome is None:
                missing.append(value.text)
            elif outcome == "rounded" and partner is not None:
                rounded.append(f"{value.text} ~ {partner.text}")
        if missing:
            return Verdict(
                method=self.method,
                status=VerdictStatus.FAIL,
                detail="not found in snippet: " + ", ".join(missing),
            )
        if rounded:
            return Verdict(
                method=self.method,
                status=VerdictStatus.PARTIAL,
                detail="rounded match: " + ", ".join(rounded),
            )
        return Verdict(
            method=self.method,
            status=VerdictStatus.PASS,
            detail=f"{len(claimed)} value(s) found in snippet",
        )


value_trace = register(ValueTrace())
