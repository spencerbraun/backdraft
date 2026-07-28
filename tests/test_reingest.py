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
from backdraft.registry import Registry


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

    assert second == first
    assert _tokens(registry, first.slug) == before
    assert len(_generations(registry, first.slug)) == 1


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


def test_a_different_config_makes_a_new_generation(registry: Registry, note: Path) -> None:
    registry.ingest(note)
    registry.ingest(note, config={"mode": "loud"})
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
