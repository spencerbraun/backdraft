"""The drift contract — the reason anchors are content-addressed at all.

Two invariants the spec names for every workstream:

* re-ingest of identical bytes with a deterministic extractor changes nothing;
* editing one page leaves every other page's tokens exactly where they were, and
  the tokens that *did* move still resolve, marked not-current.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest_registry import PAGE_BREAK

from backdraft.extract.base import ExtractedPage
from backdraft.registry import CREATED, GENERATION, Registry, UNCHANGED, current_at, current_with


def _tokens(registry: Registry, slug: str) -> dict[str, str]:
    """locator -> token across every page of the current extraction."""
    return {
        anchor.locator.format(): anchor.token
        for page in registry.pages(slug)
        for anchor in registry.anchors_for_page(slug, page.number)
    }


def _generations(registry: Registry, slug: str) -> list[dict]:
    document = next(d for d in registry.export_json()["documents"] if d["slug"] == slug)
    return document["extractions"]


# ---- identical bytes --------------------------------------------------------


def test_re_ingesting_identical_bytes_changes_nothing(registry: Registry, note: Path) -> None:
    first = registry.ingest(note)
    before = _tokens(registry, first.slug)

    second = registry.ingest(note)

    assert (second.slug, second.sha256, second.id) == (first.slug, first.sha256, first.id)
    assert _tokens(registry, first.slug) == before
    assert len(_generations(registry, first.slug)) == 1


def test_ingest_says_which_of_its_three_outcomes_happened(
    registry: Registry, note: Path
) -> None:
    """The registry knows; deriving it from outside means re-implementing `_is_noop`."""
    assert registry.ingest(note).outcome == CREATED
    assert registry.ingest(note).outcome == UNCHANGED
    note.write_text("Occupancy closed at 92.0% in Q3.\n", encoding="utf-8")
    assert registry.ingest(note).outcome == GENERATION


def test_identical_bytes_in_a_fresh_registry_mint_identical_tokens(
    tmp_path: Path, note: Path
) -> None:
    """Content-addressing, stated as a test: no registry state leaks into a token."""
    tokens = []
    for name in ("one", "two"):
        with Registry.open(tmp_path / name) as registry:
            registry.ingest(note)
            tokens.append(_tokens(registry, "quarterly-notes"))
    assert tokens[0] == tokens[1]


def test_a_workbook_re_ingests_identically(registry: Registry, workbook: Path) -> None:
    registry.ingest(workbook)
    before = _tokens(registry, "model")
    registry.ingest(workbook)
    assert _tokens(registry, "model") == before


def test_a_non_deterministic_extractor_always_makes_a_new_generation(
    registry: Registry, scripted: type, note: Path
) -> None:
    page = ExtractedPage(number=1, kind="page", text="a stable page of transcribed text")
    scripted("guessy", [page], deterministic=False)
    registry.ingest(note, extractor="guessy")
    registry.ingest(note, extractor="guessy")
    assert len(_generations(registry, "quarterly-notes")) == 2


def test_a_different_extractor_makes_a_new_generation(
    registry: Registry, scripted: type, note: Path
) -> None:
    scripted("other", [ExtractedPage(number=1, kind="page", text="a wholly different snapshot")])
    registry.ingest(note)
    registry.ingest(note, extractor="other")
    generations = _generations(registry, "quarterly-notes")
    assert [generation["extractor"] for generation in generations] == ["text", "other"]
    assert [generation["is_current"] for generation in generations] == [False, True]


def test_a_different_config_makes_a_new_generation(
    registry: Registry, note: Path, scripted: type
) -> None:
    scripted(
        "tunable",
        [ExtractedPage(number=1, kind="page", text="one page, however it was tuned")],
        config_keys={"mode": "how loudly to read"},
    )
    registry.ingest(note, extractor="tunable")
    registry.ingest(note, extractor="tunable", config={"mode": "loud"})
    assert len(_generations(registry, "quarterly-notes")) == 2


# ---- edited bytes -----------------------------------------------------------


PAGE_ONE = "Page one holds the covenant language and nothing else worth quoting here."
PAGE_TWO = "Page two carries the debt service coverage ratio of 1.42x for the quarter."
PAGE_THREE = "Page three is the rent roll summary, unchanged across both ingests here."
PAGE_TWO_EDITED = "Page two now carries a debt service coverage ratio of 1.19x instead."


@pytest.fixture
def book(tmp_path: Path, paged: object) -> Path:
    """A three-page file the `paged` extractor splits, editable between ingests."""
    path = tmp_path / "quarterly-notes.md"
    _write(path, [PAGE_ONE, PAGE_TWO, PAGE_THREE])
    return path


def _write(path: Path, pages: list[str]) -> None:
    path.write_text(PAGE_BREAK.join(pages), encoding="utf-8")


def test_editing_one_page_carries_the_other_pages_tokens_over(
    registry: Registry, book: Path
) -> None:
    registry.ingest(book, extractor="paged")
    before = _tokens(registry, "quarterly-notes")

    _write(book, [PAGE_ONE, PAGE_TWO_EDITED, PAGE_THREE])
    registry.ingest(book, extractor="paged")
    after = _tokens(registry, "quarterly-notes")

    unchanged = {"p1", "p1.c1", "p3", "p3.c1"}
    assert {locator: after[locator] for locator in unchanged} == {
        locator: before[locator] for locator in unchanged
    }
    assert after["p2"] != before["p2"]
    assert after["p2.c1"] != before["p2.c1"]


def test_a_carried_over_token_still_resolves_as_current(
    registry: Registry, book: Path
) -> None:
    registry.ingest(book, extractor="paged")
    token = _tokens(registry, "quarterly-notes")["p1.c1"]

    _write(book, [PAGE_ONE, PAGE_TWO_EDITED, PAGE_THREE])
    registry.ingest(book, extractor="paged")

    resolution = registry.resolve(token)
    assert resolution is not None
    assert resolution.current is True


def test_a_token_whose_page_changed_resolves_against_the_old_generation(
    registry: Registry, book: Path
) -> None:
    registry.ingest(book, extractor="paged")
    token = _tokens(registry, "quarterly-notes")["p2.c1"]

    _write(book, [PAGE_ONE, PAGE_TWO_EDITED, PAGE_THREE])
    registry.ingest(book, extractor="paged")

    resolution = registry.resolve(token)
    assert resolution is not None
    assert resolution.current is False
    assert "1.42x" in resolution.anchor.receipt.snippet  # what the writer saw


# ---- the other half of drift ------------------------------------------------
#
# `resolve` finds what the writer saw; `current_at` finds what stands at the same
# locator now. Both `bind` and the gate's `show` need the pair, and neither may
# import the other, so the lookup is the registry's and this is where it is
# pinned.


def test_current_at_finds_what_replaced_a_superseded_anchor(
    registry: Registry, book: Path
) -> None:
    registry.ingest(book, extractor="paged")
    token = _tokens(registry, "quarterly-notes")["p2.c1"]

    _write(book, [PAGE_ONE, PAGE_TWO_EDITED, PAGE_THREE])
    registry.ingest(book, extractor="paged")

    cited = registry.resolve(token).anchor
    standing = current_at(registry, cited)
    assert standing is not None
    assert standing.locator == cited.locator
    assert standing.token != cited.token
    assert "1.19x" in standing.receipt.snippet  # what stands there now


def test_current_at_is_the_anchor_itself_when_nothing_moved(
    registry: Registry, book: Path
) -> None:
    registry.ingest(book, extractor="paged")
    anchor = registry.anchors_for_page("quarterly-notes", 1)[0]
    assert current_at(registry, anchor) == anchor


def test_current_at_is_none_when_the_locator_is_gone(registry: Registry, book: Path) -> None:
    """A page deleted between ingests: drift with only one side to show."""
    registry.ingest(book, extractor="paged")
    token = _tokens(registry, "quarterly-notes")["p3.c1"]

    _write(book, [PAGE_ONE, PAGE_TWO])
    registry.ingest(book, extractor="paged")

    cited = registry.resolve(token).anchor
    assert current_at(registry, cited) is None


# ---- where the cited text went -----------------------------------------------
#
# `current_at` keeps the locator and asks what text stands there now;
# `current_with` keeps the text and asks which locators hold it. `backdraft
# locate` is its caller, and the lookup is pinned here beside its other half.


def test_current_with_follows_a_page_that_a_new_page_pushed_down(
    registry: Registry, book: Path
) -> None:
    registry.ingest(book, extractor="paged")
    token = _tokens(registry, "quarterly-notes")["p2.c1"]

    _write(book, [PAGE_ONE, PAGE_THREE, PAGE_TWO])
    registry.ingest(book, extractor="paged")

    cited = registry.resolve(token).anchor
    assert registry.resolve(token).current is False
    found = current_with(registry, cited)
    assert [anchor.locator.format() for anchor in found] == ["p3.c1"]
    assert found[0].receipt.snippet_sha256 == cited.receipt.snippet_sha256
    assert found[0].token == token.replace(":p2.c1:", ":p3.c1:")


def test_current_with_matches_a_chunk_to_a_chunk_and_never_to_its_page(
    registry: Registry, book: Path
) -> None:
    """A one-chunk page carries one hash on two anchors; each kind finds its own."""
    registry.ingest(book, extractor="paged")
    tokens = _tokens(registry, "quarterly-notes")

    _write(book, [PAGE_THREE, PAGE_ONE, PAGE_TWO])
    registry.ingest(book, extractor="paged")

    chunk = registry.resolve(tokens["p1.c1"]).anchor
    page = registry.resolve(tokens["p1"]).anchor
    assert chunk.receipt.snippet_sha256 == page.receipt.snippet_sha256
    assert [anchor.locator.format() for anchor in current_with(registry, chunk)] == ["p2.c1"]
    assert [anchor.locator.format() for anchor in current_with(registry, page)] == ["p2"]


def test_current_with_is_empty_when_the_text_changed_at_all(
    registry: Registry, book: Path
) -> None:
    """Exact only: one figure edited is not the text that was cited."""
    registry.ingest(book, extractor="paged")
    token = _tokens(registry, "quarterly-notes")["p2.c1"]

    _write(book, [PAGE_ONE, PAGE_TWO.replace("1.42x", "1.43x"), PAGE_THREE])
    registry.ingest(book, extractor="paged")

    assert current_with(registry, registry.resolve(token).anchor) == []


def test_current_with_names_every_place_in_document_order(
    registry: Registry, book: Path
) -> None:
    registry.ingest(book, extractor="paged")
    token = _tokens(registry, "quarterly-notes")["p2.c1"]

    _write(book, [PAGE_TWO, PAGE_ONE, PAGE_THREE, PAGE_TWO])
    registry.ingest(book, extractor="paged")

    found = current_with(registry, registry.resolve(token).anchor)
    assert [anchor.locator.format() for anchor in found] == ["p1.c1", "p4.c1"]


def test_the_snippet_lookup_reads_the_current_generation_only(
    registry: Registry, book: Path
) -> None:
    registry.ingest(book, extractor="paged")
    cited = next(
        anchor
        for anchor in registry.anchors_for_page("quarterly-notes", 2)
        if anchor.kind == "chunk"
    )

    _write(book, [PAGE_ONE, PAGE_TWO_EDITED, PAGE_THREE])
    registry.ingest(book, extractor="paged")

    assert registry.anchors_with_snippet("quarterly-notes", cited.receipt.snippet_sha256) == []
    assert registry.anchors_with_snippet("elsewhere", cited.receipt.snippet_sha256) == []


def test_the_snippet_lookup_is_indexed(registry: Registry) -> None:
    """One indexed query per cited snippet, on a registry opened before it existed too:
    the DDL runs on every open, so an older registry gains the index the first time."""
    names = {
        row[1] for row in registry._connection.execute("PRAGMA index_list(anchors)")
    }
    assert "idx_anchors_snippet" in names


def test_search_follows_the_current_generation(registry: Registry, book: Path) -> None:
    registry.ingest(book, extractor="paged")
    assert registry.search("1.42x")

    _write(book, [PAGE_ONE, PAGE_TWO_EDITED, PAGE_THREE])
    registry.ingest(book, extractor="paged")
    assert registry.search("1.42x") == []
    assert registry.search("1.19x")


def test_the_ledger_survives_a_re_ingest(registry: Registry, book: Path) -> None:
    """A token the writer was shown stays shown, even on a new anchor row."""
    registry.ingest(book, extractor="paged")
    token = _tokens(registry, "quarterly-notes")["p1.c1"]
    anchor = next(a for a in registry.anchors_for_page("quarterly-notes", 1) if a.token == token)
    session = registry.ensure_session("s1")
    registry.record_shown(session, [anchor.id])

    _write(book, [PAGE_ONE, PAGE_TWO_EDITED, PAGE_THREE])
    registry.ingest(book, extractor="paged")

    assert registry.was_shown(session, token) is True


def test_a_removed_page_leaves_its_tokens_resolvable_but_not_current(
    registry: Registry, book: Path
) -> None:
    registry.ingest(book, extractor="paged")
    token = _tokens(registry, "quarterly-notes")["p3.c1"]

    _write(book, [PAGE_ONE, PAGE_TWO])
    registry.ingest(book, extractor="paged")

    assert registry.page("quarterly-notes", 3) is None
    resolution = registry.resolve(token)
    assert resolution is not None
    assert resolution.current is False


def test_editing_the_file_itself_drifts_rather_than_forking_the_document(
    registry: Registry, note: Path
) -> None:
    """The same path with new bytes is the same document, one generation later."""
    document = registry.ingest(note)
    token = _tokens(registry, document.slug)["p1.c1"]

    note.write_text(note.read_text(encoding="utf-8").replace("1.42x", "1.19x"), encoding="utf-8")
    reingested = registry.ingest(note)

    assert reingested.slug == document.slug
    assert reingested.sha256 != document.sha256
    assert len(registry.documents()) == 1
    resolution = registry.resolve(token)
    assert resolution is not None
    assert resolution.current is False
