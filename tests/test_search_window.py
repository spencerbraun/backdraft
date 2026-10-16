"""A search hit's excerpt shows the words that matched, over the real FTS5 index.

`search` used to print every hit's first `EXCERPT_CHARS` characters, which for a
long chunk is its opening rather than its evidence. The registry now hands back
what FTS5 matched (`SearchHit.matches`) and the gate windows on it — pinned
here end to end, because which words matched is FTS5's answer and only the real
store gives it.
"""

from __future__ import annotations

from pathlib import Path

from backdraft.gate.reader import EXCERPT_CHARS, excerpt
from backdraft.gate.searcher import PHRASE_FALLBACK_NOTE, search
from backdraft.kernel.hashing import normalize
from backdraft.registry import MATCH_CLOSE, MATCH_OPEN, Registry, unmark
from backdraft.registry.store import _match_spans

_OPENING = (
    "Capital expenditures were incurred outside the operating statement and are not "
    "deducted in arriving at net operating income for any period shown in this summary. "
)
_PARAGRAPH = (
    _OPENING
    + "The largest items were roof work on two buildings and parking lot resurfacing. "
    "A replacement reserve of $250 per unit per year would be customary here, and the "
    "debt yield of 9.1% on the 1.42x coverage stands apart from it entirely."
)


def _excerpt_of(output: str) -> str:
    """The first hit's excerpt line, as printed."""
    lines = output.split("\n")
    first = next(i for i, line in enumerate(lines) if line.startswith("[bd:"))
    return lines[first + 1].strip()


def _source(tmp_path: Path) -> Path:
    path = tmp_path / "capex.md"
    path.write_text(_PARAGRAPH + "\n", encoding="utf-8")
    return path


def test_a_late_match_is_shown_rather_than_the_opening(registry: Registry, tmp_path: Path) -> None:
    registry.ingest(_source(tmp_path))
    shown = _excerpt_of(search(registry, "replacement reserve", session="s"))
    assert shown.startswith("...")
    assert "replacement reserve" in shown
    assert len(shown.strip(".")) <= EXCERPT_CHARS


def test_an_early_match_prints_exactly_the_opening(registry: Registry, tmp_path: Path) -> None:
    """Byte-identity where it is free: the opening already shows the evidence."""
    registry.ingest(_source(tmp_path))
    shown = _excerpt_of(search(registry, "expenditures", session="s"))
    assert shown == normalize(_PARAGRAPH)[:EXCERPT_CHARS] + "..."


def test_a_phrase_fallback_windows_on_the_phrase_that_ran(
    registry: Registry, tmp_path: Path
) -> None:
    registry.ingest(_source(tmp_path))
    output = search(registry, "1.42x", session="s")
    assert PHRASE_FALLBACK_NOTE in output
    shown = _excerpt_of(output)
    assert shown.startswith("...")
    assert "1.42x" in shown


def test_the_window_never_runs_past_the_end(registry: Registry, tmp_path: Path) -> None:
    registry.ingest(_source(tmp_path))
    shown = _excerpt_of(search(registry, "entirely", session="s"))
    assert shown.startswith("...")
    assert shown.endswith("entirely.")
    assert len(shown) <= EXCERPT_CHARS + len("...")


def test_no_matches_cuts_from_the_start() -> None:
    assert excerpt(_PARAGRAPH) == normalize(_PARAGRAPH)[:EXCERPT_CHARS] + "..."


def test_a_short_snippet_is_shown_whole_whatever_matched() -> None:
    assert excerpt("Replacement   reserve", [(14, 21)]) == "Replacement reserve"


def test_spans_follow_the_whitespace_collapse() -> None:
    """Offsets are the raw snippet's; the excerpt is normalized; the window agrees."""
    raw = _PARAGRAPH.replace(" ", "  \n ")
    start = raw.index("replacement")
    shown = excerpt(raw, [(start, start + len("replacement"))])
    assert shown.startswith("...")
    assert "replacement reserve" in shown


def test_the_window_opens_at_a_word() -> None:
    start = _PARAGRAPH.index("replacement")
    shown = excerpt(_PARAGRAPH, [(start, start + len("replacement"))])
    text = normalize(_PARAGRAPH)
    assert shown.startswith("...") and shown.endswith("...")
    assert text[text.index(shown[3:-3]) - 1] == " "


def test_a_span_that_does_not_fit_the_snippet_is_ignored() -> None:
    assert excerpt(_PARAGRAPH, [(10_000, 10_005)]) == excerpt(_PARAGRAPH)


def test_the_window_holds_the_most_matches() -> None:
    """Two late matches close together beat one later still, whichever came first."""
    text = _OPENING + "alpha " + "x" * 200 + " beta gamma beta"
    spans = [(text.index("alpha"), text.index("alpha") + 5)]
    for word in ("beta", "gamma"):
        at = text.index(word)
        spans.append((at, at + len(word)))
    last = text.rindex("beta")
    spans.append((last, last + 4))
    spans.sort()
    shown = excerpt(text, spans)
    assert "beta gamma beta" in shown
    assert "alpha" not in shown


def test_unmark_drops_an_empty_or_unclosed_span() -> None:
    """A marker pair around nothing, and an opener never closed, mark no span;
    the text still comes out whole."""
    plain, spans = unmark(f"a{MATCH_OPEN}{MATCH_CLOSE}b{MATCH_OPEN}cd{MATCH_CLOSE}e{MATCH_OPEN}f")
    assert plain == "abcdef"
    assert spans == [(2, 4)]


def test_marked_text_that_disagrees_with_the_snippet_gives_no_spans() -> None:
    """Offsets into a different string would mislabel this one; none is better."""
    assert _match_spans(f"{MATCH_OPEN}rent{MATCH_CLOSE} roll", "rent roll") == ((0, 4),)
    assert _match_spans(f"{MATCH_OPEN}rent{MATCH_CLOSE} rolls", "rent roll") == ()
    assert _match_spans(None, "rent roll") == ()
