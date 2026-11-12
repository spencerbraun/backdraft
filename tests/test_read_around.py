"""A hit on a long page closes with the chunk range around it, not the page.

`[Read the page: backdraft read <slug> p1]` on a 57-chunk web page is three
windows starting at the navigation menu. Where a page does not fit one default
read window, `search` and `show` name the hit's chunk with `READ_AROUND_CHUNKS`
either side instead — and a page that does fit keeps the page hint byte for
byte. Run over the real registry, because the test for "fits one window" is the
read's own window over the chunker's real chunks.
"""

from __future__ import annotations

import re
from pathlib import Path

from backdraft.gate.reader import (
    DEFAULT_BUDGET,
    READ_AROUND_CHUNKS,
    fits_one_window,
    read,
    read_around,
    read_hints,
    show,
)
from backdraft.gate.searcher import render_search, search
from backdraft.kernel.tokens import ChunkLocator
from backdraft.registry import Registry

_WORDS = [
    "alder", "birch", "cedar", "dogwood", "elm", "fir", "ginkgo", "hazel", "ironwood",
    "juniper", "katsura", "larch", "maple", "nutmeg", "oak", "pine", "quince", "rowan",
    "spruce", "tupelo", "upas", "viburnum", "willow", "xylosma", "yew", "zelkova",
    "apricot", "banyan", "cypress", "damson",
]  # fmt: skip


def _paragraph(word: str) -> str:
    """One paragraph of about 650 characters that only `word` distinguishes."""
    filler = "The survey recorded the stand in the usual way and found nothing to remark on. "
    return f"The {word} stand was measured first. " + filler * 8


def _long(tmp_path: Path, name: str = "survey.md") -> Path:
    """Thirty paragraphs, well past one default read window."""
    path = tmp_path / name
    path.write_text("\n\n".join(_paragraph(word) for word in _WORDS) + "\n", encoding="utf-8")
    return path


def _hints(output: str) -> list[str]:
    return [line for line in output.split("\n") if line.startswith("[Read ")]


def _ordinal(registry: Registry, slug: str, word: str) -> int:
    """The ordinal of the chunk that holds `word`, read off the page itself."""
    for anchor in registry.anchors_for_page(slug, 1):
        if not isinstance(anchor.locator, ChunkLocator):
            continue
        if f"The {word} stand" in anchor.receipt.snippet:
            return anchor.locator.ordinal
    raise AssertionError(word)


def _last(registry: Registry, slug: str) -> int:
    return max(
        anchor.locator.ordinal
        for anchor in registry.anchors_for_page(slug, 1)
        if isinstance(anchor.locator, ChunkLocator)
    )


def _span(first: int, last: int) -> str:
    return f"c{first}" if first == last else f"c{first}-c{last}"


def test_the_constant_is_one_chunk_either_side() -> None:
    """Pinned because the DESIGN row and the skill both name the value."""
    assert READ_AROUND_CHUNKS == 1


def test_a_hit_on_a_long_page_names_the_range_around_it(registry: Registry, tmp_path: Path) -> None:
    registry.ingest(_long(tmp_path))
    hit = _ordinal(registry, "survey", "maple")
    output = search(registry, "maple", session="s")

    wanted = _span(hit - READ_AROUND_CHUNKS, hit + READ_AROUND_CHUNKS)
    assert _hints(output) == [f"[Read around it: backdraft read survey p1.{wanted}]"]


def test_the_read_the_hint_names_shows_the_hit_and_not_the_top(
    registry: Registry, tmp_path: Path
) -> None:
    """The hint is a command that runs, and what it reads is what was asked for."""
    registry.ingest(_long(tmp_path))
    hint = _hints(search(registry, "maple", session="s"))[0]
    selector = re.fullmatch(r"\[Read around it: backdraft read survey (\S+)\]", hint)
    assert selector is not None

    page = read(registry, "survey", selector[1], session="s")
    hit = _ordinal(registry, "survey", "maple")
    assert f"[bd:survey:p1.c{hit}:" in page
    assert "[bd:survey:p1.c1:" not in page
    assert "Showing" not in page  # three chunks fit one window


def test_the_range_clips_to_the_page_at_both_ends(registry: Registry, tmp_path: Path) -> None:
    registry.ingest(_long(tmp_path))
    last = _last(registry, "survey")
    assert _ordinal(registry, "survey", _WORDS[0]) == 1
    assert _ordinal(registry, "survey", _WORDS[-1]) == last

    assert _hints(search(registry, _WORDS[0], session="s")) == [
        f"[Read around it: backdraft read survey p1.{_span(1, 1 + READ_AROUND_CHUNKS)}]"
    ]
    assert _hints(search(registry, _WORDS[-1], session="s")) == [
        f"[Read around it: backdraft read survey p1.{_span(last - READ_AROUND_CHUNKS, last)}]"
    ]


def test_ranges_that_touch_merge_and_ranges_that_do_not_stay_apart(
    registry: Registry, tmp_path: Path
) -> None:
    registry.ingest(_long(tmp_path))
    near_a, near_b = (_ordinal(registry, "survey", word) for word in ("cedar", "fir"))
    far = _ordinal(registry, "survey", "tupelo")
    # c2-c4 and c5-c7 share no chunk and still make one read: they touch.
    assert near_b - near_a == 2 * READ_AROUND_CHUNKS + 1

    output = search(registry, "cedar OR fir OR tupelo", session="s")
    assert _hints(output) == [
        "[Read around it: backdraft read survey "
        f"p1.{_span(near_a - READ_AROUND_CHUNKS, near_b + READ_AROUND_CHUNKS)}]",
        "[Read around it: backdraft read survey "
        f"p1.{_span(far - READ_AROUND_CHUNKS, far + READ_AROUND_CHUNKS)}]",
    ]


def test_the_range_hint_carries_a_typed_session(registry: Registry, tmp_path: Path) -> None:
    registry.ingest(_long(tmp_path))
    output = search(registry, "maple", session="s-deal", session_flag="s-deal")
    assert _hints(output)[0].endswith(" --session s-deal]")
    assert _hints(output)[0].startswith("[Read around it: ")


def test_a_page_that_fits_one_window_keeps_the_page_hint(
    registry: Registry, tmp_path: Path
) -> None:
    """The negative branch, and the byte-identity every documented block rests on."""
    path = tmp_path / "short.md"
    path.write_text("\n\n".join(_paragraph(word) for word in _WORDS[:4]) + "\n", encoding="utf-8")
    registry.ingest(path)

    output = search(registry, "cedar", session="s")
    assert _hints(output) == ["[Read the page: backdraft read short p1]"]
    assert read_around(registry, registry.anchors_for_page("short", 1)) == {}


def test_a_sheet_never_gets_the_chunk_form(registry: Registry, tmp_path: Path) -> None:
    """Long as it is: 400 rows is two default windows of a sheet."""
    path = tmp_path / "rates.csv"
    rows = ["unit,rent"] + [f"u{n},{1000 + n}" for n in range(400)]
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    registry.ingest(path)

    output = search(registry, "1217", session="s")
    assert _hints(output) == ["[Read the page: backdraft read rates p1]"]
    assert read_around(registry, registry.anchors_for_page("rates", 1)) == {}


def test_a_long_page_and_a_short_one_each_get_their_own_hint(
    registry: Registry, tmp_path: Path
) -> None:
    registry.ingest(_long(tmp_path))
    path = tmp_path / "short.md"
    path.write_text(_paragraph("maple") + "\n", encoding="utf-8")
    registry.ingest(path)

    hints = _hints(search(registry, "maple", session="s"))
    assert sorted(hint.split(":")[0] for hint in hints) == ["[Read around it", "[Read the page"]
    assert "[Read the page: backdraft read short p1]" in hints


def test_show_names_the_range_search_names(registry: Registry, tmp_path: Path) -> None:
    registry.ingest(_long(tmp_path))
    output = search(registry, "maple", session="s")
    token = re.search(r"^\[(bd:[^\]]+)\]", output, re.M)[1]  # type: ignore[index]

    shown = show(registry, [token], session="s", session_flag="s")
    assert shown.complete
    assert _hints(shown.text) == [hint[:-1] + " --session s]" for hint in _hints(output)]


def test_show_on_a_drifted_token_keeps_the_page_hint(registry: Registry, tmp_path: Path) -> None:
    """A superseded anchor's ordinal is an address in an extraction that is gone."""
    source = _long(tmp_path)
    registry.ingest(source)
    output = search(registry, "maple", session="s")
    token = re.search(r"^\[(bd:[^\]]+)\]", output, re.M)[1]  # type: ignore[index]

    text = source.read_text(encoding="utf-8")
    source.write_text(text.replace("The maple stand", "The mulberry stand"), encoding="utf-8")
    registry.ingest(source)

    shown = show(registry, [token], session="s")
    assert "drifted" in shown.text
    assert _hints(shown.text) == ["[Read the page: backdraft read survey p1]"]


def test_the_hint_mints_nothing(registry: Registry, tmp_path: Path) -> None:
    """Advice is not evidence: the neighbours it names are shown by the read, not by it."""
    registry.ingest(_long(tmp_path))
    hit = _ordinal(registry, "survey", "maple")
    search(registry, "maple", session="s")

    shown = registry.shown_in_current("s", "survey")
    by_id = {anchor.id: anchor for anchor in registry.anchors_for_page("survey", 1)}
    assert [by_id[i].locator.ordinal for i in shown] == [hit]  # type: ignore[union-attr]


def test_fits_one_window_is_the_reads_own_answer(registry: Registry, tmp_path: Path) -> None:
    """Soft budget: a lone chunk past the budget still arrives whole, so it fits."""
    registry.ingest(_long(tmp_path))
    chunks = [
        anchor
        for anchor in registry.anchors_for_page("survey", 1)
        if isinstance(anchor.locator, ChunkLocator)
    ]
    assert sum(len(chunk.receipt.snippet) for chunk in chunks) > DEFAULT_BUDGET["chars"]
    assert not fits_one_window(chunks)
    assert "Continue with" in read(registry, "survey", "p1", session="s")

    assert fits_one_window(chunks[:3])
    assert fits_one_window([])


def test_render_search_without_around_is_the_page_hint(registry: Registry, tmp_path: Path) -> None:
    """`around` is optional, so a caller that computes none prints what it did."""
    registry.ingest(_long(tmp_path))
    hits = registry.search("maple")
    assert _hints(render_search("maple", hits)) == ["[Read the page: backdraft read survey p1]"]


def test_read_hints_dedupes_and_keeps_first_seen_order() -> None:
    pages = [("b", 2), ("a", 1), ("b", 2), ("a", 1)]
    assert read_hints(pages, {("a", 1): [(4, 6), (9, 9)]}, " --session s") == [
        "[Read the page: backdraft read b p2 --session s]",
        "[Read around it: backdraft read a p1.c4-c6 --session s]",
        "[Read around it: backdraft read a p1.c9 --session s]",
    ]
