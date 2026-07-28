"""The Registry's surface, against a real SQLite file.

One test per behaviour the spec pins in Addendum A, plus the slug and sheetref
rules that ingest owns.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from backdraft.extract.base import ExtractedPage
from backdraft.kernel.tokens import parse as parse_token
from backdraft.registry import Registry, RegistryError, sanitize_sheet_name, slug_for
from backdraft.registry.store import DIRECTORY

from conftest_registry import sheet_page


def test_open_creates_the_registry_directory_and_schema(root: Path) -> None:
    with Registry.open(root) as registry:
        assert (root / DIRECTORY / "registry.db").is_file()
        assert registry.documents() == []


def test_open_is_idempotent(root: Path, note: Path) -> None:
    with Registry.open(root) as first:
        first.ingest(note)
    with Registry.open(root) as second:
        assert len(second.documents()) == 1


def test_ingest_records_the_document(registry: Registry, note: Path) -> None:
    document = registry.ingest(note)
    assert document.slug == "quarterly-notes"
    assert document.filename == "quarterly-notes.md"
    assert document.media_type == "text"
    assert len(document.sha256) == 64
    assert registry.document("quarterly-notes") == document


def test_documents_lists_everything_ingested(registry: Registry, note: Path, workbook: Path) -> None:
    registry.ingest(note)
    registry.ingest(workbook)
    assert [document.slug for document in registry.documents()] == ["quarterly-notes", "model"]


def test_document_returns_none_for_an_unknown_slug(registry: Registry) -> None:
    assert registry.document("nope") is None


def test_pages_returns_the_snapshot(registry: Registry, note: Path) -> None:
    document = registry.ingest(note)
    pages = registry.pages(document.slug)
    assert len(pages) == 1
    assert pages[0].number == 1
    assert pages[0].kind == "page"
    assert "1.42x" in pages[0].text


def test_pages_of_an_unknown_document_is_empty(registry: Registry) -> None:
    assert registry.pages("nope") == []


def test_page_addresses_one_page(registry: Registry, workbook: Path) -> None:
    registry.ingest(workbook)
    page = registry.page("model", 2)
    assert page is not None
    assert page.kind == "sheet"
    assert page.name == "summary"
    assert registry.page("model", 99) is None


def test_anchors_are_eager_and_ordered_page_first(registry: Registry, note: Path) -> None:
    registry.ingest(note)
    anchors = registry.anchors_for_page("quarterly-notes", 1)
    assert [anchor.kind for anchor in anchors] == ["page", "chunk", "chunk", "chunk"]
    assert [anchor.locator.format() for anchor in anchors[1:]] == ["p1.c1", "p1.c2", "p1.c3"]


def test_anchor_kind_is_derived_from_the_locator(registry: Registry, note: Path) -> None:
    registry.ingest(note)
    for anchor in registry.anchors_for_page("quarterly-notes", 1):
        assert anchor.kind == anchor.locator.kind


def test_anchors_carry_their_receipt(registry: Registry, note: Path) -> None:
    registry.ingest(note)
    anchor = registry.anchors_for_page("quarterly-notes", 1)[1]
    page = registry.page("quarterly-notes", 1)
    assert page is not None
    assert anchor.receipt.snippet == page.text[anchor.start : anchor.end]
    assert len(anchor.receipt.snippet_sha256) == 64


def test_tokens_name_their_anchors(registry: Registry, note: Path) -> None:
    registry.ingest(note)
    for anchor in registry.anchors_for_page("quarterly-notes", 1):
        token = parse_token(anchor.token)
        assert token.slug == "quarterly-notes"
        assert token.locator == anchor.locator
        assert anchor.receipt.snippet_sha256.startswith(token.hash)


def test_minted_hashes_are_four_hex_by_default(registry: Registry, note: Path) -> None:
    registry.ingest(note)
    for anchor in registry.anchors_for_page("quarterly-notes", 1):
        assert len(parse_token(anchor.token).hash) == 4


def test_resolve_finds_a_current_anchor(registry: Registry, note: Path) -> None:
    registry.ingest(note)
    anchor = registry.anchors_for_page("quarterly-notes", 1)[1]
    resolution = registry.resolve(anchor.token)
    assert resolution is not None
    assert resolution.current is True
    assert resolution.anchor.receipt == anchor.receipt


def test_resolve_returns_none_for_an_unknown_token(registry: Registry) -> None:
    assert registry.resolve("bd:nothing:p1:a7f3") is None


def test_resolve_returns_none_for_a_malformed_token(registry: Registry) -> None:
    assert registry.resolve("not a token") is None
    assert registry.resolve("bd:calc(a / b)") is None


def test_search_returns_mintable_anchors(registry: Registry, note: Path) -> None:
    registry.ingest(note)
    hits = registry.search("covenant")
    assert hits
    assert hits[0].slug == "quarterly-notes"
    assert hits[0].page_number == 1
    assert "covenant" in hits[0].anchor.receipt.snippet
    assert registry.resolve(hits[0].anchor.token) is not None


def test_search_can_be_scoped_to_one_document(registry: Registry, note: Path, workbook: Path) -> None:
    registry.ingest(note)
    registry.ingest(workbook)
    assert registry.search("Acme", slug="quarterly-notes") == []
    assert registry.search("Acme", slug="model")


def test_search_honours_its_limit(registry: Registry, note: Path) -> None:
    registry.ingest(note)
    assert len(registry.search("the", limit=1)) == 1


def test_search_does_not_return_whole_page_anchors(registry: Registry, note: Path) -> None:
    registry.ingest(note)
    assert all(hit.anchor.kind != "page" for hit in registry.search("covenant OR NOI"))


def test_search_accepts_punctuation_fts5_cannot_parse(registry: Registry, note: Path) -> None:
    """`1.42x` is a number an analyst types, not a syntax error."""
    registry.ingest(note)
    assert registry.search("1.42x")
    assert registry.search('unbalanced "quote') == []


def test_search_still_understands_fts5_operators(registry: Registry, note: Path) -> None:
    registry.ingest(note)
    assert len(registry.search("covenant OR anchor")) > 1


def test_a_phrase_retry_is_reported_on_the_results(registry: Registry, note: Path) -> None:
    """The retry asks a different question, so it is not allowed to be silent."""
    registry.ingest(note)
    assert registry.search("1.42x").phrase_fallback is True
    assert registry.search('unbalanced "quote').phrase_fallback is True


def test_a_query_fts5_parses_is_not_marked_as_retried(registry: Registry, note: Path) -> None:
    registry.ingest(note)
    assert registry.search("covenant OR anchor").phrase_fallback is False
    # An empty result is not a retry: the query parsed, nothing matched it.
    assert registry.search("zzznosuchterm") == []
    assert registry.search("zzznosuchterm").phrase_fallback is False


def test_search_results_are_still_a_plain_list(registry: Registry, note: Path) -> None:
    """Addendum A pins `list[SearchHit]`; the flag rides along, it does not replace."""
    registry.ingest(note)
    hits = registry.search("covenant")
    assert isinstance(hits, list)
    assert hits == list(hits)


def test_sessions_are_created_and_reused(registry: Registry) -> None:
    assert registry.ensure_session("s1") == "s1"
    assert registry.ensure_session("s1", "again") == "s1"
    generated = registry.ensure_session(None)
    assert generated and generated != "s1"


def test_the_ledger_records_what_was_shown(registry: Registry, note: Path) -> None:
    registry.ingest(note)
    anchor = registry.anchors_for_page("quarterly-notes", 1)[1]
    other = registry.anchors_for_page("quarterly-notes", 1)[2]
    session = registry.ensure_session("s1")
    registry.record_shown(session, [anchor.id])
    assert registry.was_shown(session, anchor.token) is True
    assert registry.was_shown(session, other.token) is False
    assert registry.was_shown("s2", anchor.token) is False


def test_recording_the_same_anchor_twice_is_harmless(registry: Registry, note: Path) -> None:
    registry.ingest(note)
    anchor = registry.anchors_for_page("quarterly-notes", 1)[0]
    session = registry.ensure_session("s1")
    registry.record_shown(session, [anchor.id, anchor.id])
    registry.record_shown(session, [anchor.id])
    assert registry.was_shown(session, anchor.token) is True


def test_save_binding_stores_the_report(registry: Registry) -> None:
    binding_id = registry.save_binding(
        doc_path="memo.md", session_id="s1", mode="frontwalk", report_json='{"claims": []}'
    )
    assert binding_id > 0
    exported = registry.export_json()
    assert exported["bindings"][0]["doc_path"] == "memo.md"
    assert exported["bindings"][0]["report"] == {"claims": []}


def test_export_json_covers_the_whole_registry(registry: Registry, note: Path) -> None:
    registry.ingest(note)
    anchor = registry.anchors_for_page("quarterly-notes", 1)[0]
    session = registry.ensure_session("s1", "demo")
    registry.record_shown(session, [anchor.id])
    exported = registry.export_json()

    assert exported["$format"] == "backdraft/registry-v1"
    document = exported["documents"][0]
    assert document["slug"] == "quarterly-notes"
    assert len(document["extractions"]) == 1
    assert document["extractions"][0]["is_current"] is True
    assert len(document["extractions"][0]["pages"]) == 1
    assert len(document["extractions"][0]["anchors"]) == 4
    assert exported["sessions"] == [
        {"id": session, "label": "demo", "started_at": exported["sessions"][0]["started_at"]}
    ]
    assert exported["ledger"][0]["token"] == anchor.token
    assert json.dumps(exported)  # JSON-able all the way down


def test_only_one_extraction_is_current(registry: Registry, note: Path) -> None:
    registry.ingest(note)
    note.write_text("changed entirely, and long enough to be its own chunk. " * 8, encoding="utf-8")
    registry.ingest(note)
    exported = registry.export_json()["documents"][0]["extractions"]
    assert [generation["is_current"] for generation in exported] == [False, True]


def test_the_partial_index_forbids_two_current_generations(root: Path, note: Path) -> None:
    with Registry.open(root) as registry:
        document = registry.ingest(note)
    connection = sqlite3.connect(root / DIRECTORY / "registry.db")
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            "INSERT INTO extractions (document_id, extractor, extractor_version, "
            "config_hash, deterministic, is_current, created_at) "
            "VALUES (?, 'text', '1', 'x', 1, 1, 'now')",
            (document.id,),
        )
    connection.close()


# ---- slugs ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        ("T12 Audit.pdf", "t12-audit"),
        ("Rent_Roll (2025).xlsx", "rent-roll-2025"),
        ("a.pdf", "a-doc"),
        ("___.txt", "doc"),
        ("Café Notes.md", "cafe-notes"),
        ("x" * 60 + ".pdf", "x" * 32),
    ],
)
def test_slug_for_kebabs_and_truncates(filename: str, expected: str) -> None:
    assert slug_for(filename) == expected


def test_slugs_are_deduped(registry: Registry, tmp_path: Path) -> None:
    slugs = []
    for index in range(3):
        directory = tmp_path / str(index)
        directory.mkdir()
        path = directory / "notes.md"
        path.write_text(f"body number {index}, distinct bytes", encoding="utf-8")
        slugs.append(registry.ingest(path).slug)
    assert slugs == ["notes", "notes-2", "notes-3"]


def test_an_explicit_slug_is_used(registry: Registry, note: Path) -> None:
    assert registry.ingest(note, slug="t12-audit").slug == "t12-audit"


def test_a_taken_explicit_slug_is_an_error(registry: Registry, note: Path, tmp_path: Path) -> None:
    registry.ingest(note, slug="t12-audit")
    other = tmp_path / "other.md"
    other.write_text("different bytes entirely", encoding="utf-8")
    with pytest.raises(RegistryError, match="already taken"):
        registry.ingest(other, slug="t12-audit")


def test_a_slug_survives_re_ingest(registry: Registry, note: Path) -> None:
    registry.ingest(note, slug="t12-audit")
    note.write_text("rewritten from scratch, several words long", encoding="utf-8")
    assert registry.ingest(note, slug="something-else").slug == "t12-audit"


# ---- sheetrefs --------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Rent Roll", "rent-roll"),
        ("Rent: Roll!", "rent-roll"),
        ("P&L (2025)", "p-l-2025"),
        ("a;b", "a-b"),
        ("   ", "sheet"),
    ],
)
def test_sheet_names_are_sanitized_to_the_sheetref_charset(name: str, expected: str) -> None:
    assert sanitize_sheet_name(name) == expected


def test_sheet_names_are_sanitized_at_ingest(registry: Registry, workbook: Path) -> None:
    registry.ingest(workbook)
    page = registry.page("model", 1)
    assert page is not None
    assert page.name == "rent-roll-2025"
    cell = next(a for a in registry.anchors_for_page("model", 1) if a.kind == "cell")
    assert cell.token.startswith("bd:model:rent-roll-2025!")


def test_colliding_sheet_names_are_deduped(
    registry: Registry, scripted: type, note: Path
) -> None:
    scripted(
        "twosheets",
        [
            sheet_page(1, "Rent Roll", "| Row | A |\n|---|---|\n| 1 | [A1] one |", [("A1", "one")]),
            sheet_page(2, "rent roll", "| Row | A |\n|---|---|\n| 1 | [A1] two |", [("A1", "two")]),
        ],
    )
    registry.ingest(note, extractor="twosheets")
    assert [page.name for page in registry.pages("quarterly-notes")] == [
        "rent-roll",
        "rent-roll-2",
    ]


def test_sheet_pages_carry_their_cells(registry: Registry, workbook: Path) -> None:
    registry.ingest(workbook)
    page = registry.page("model", 1)
    assert page is not None
    assert ("A1", "Unit") in [(cell.ref, cell.value) for cell in page.cells]
    assert ("C3", "1875.5") in [(cell.ref, cell.value) for cell in page.cells]


# ---- hash collisions --------------------------------------------------------


def test_a_colliding_hash_extends_to_six(registry: Registry, scripted: type, note: Path) -> None:
    """Two different snippets sharing a 4-hex prefix; the second extends.

    The snippets below are chosen so `sha256(normalize(text))` collides at four
    hex characters — the whole point of `TOKEN_HASH_LENGTHS`.
    """
    first, second = _four_hex_collision()
    scripted(
        "collide",
        [
            sheet_page(
                1,
                "s",
                "table",
                [("A1", first), ("A2", second)],
            )
        ],
    )
    registry.ingest(note, extractor="collide")
    cells = [a for a in registry.anchors_for_page("quarterly-notes", 1) if a.kind == "cell"]
    assert len(parse_token(cells[0].token).hash) == 4
    assert len(parse_token(cells[1].token).hash) == 6
    assert registry.resolve(cells[0].token) is not None
    assert registry.resolve(cells[1].token) is not None


def test_identical_snippets_share_a_hash_without_extending(
    registry: Registry, scripted: type, note: Path
) -> None:
    scripted("twins", [sheet_page(1, "s", "table", [("A1", "same"), ("B1", "same")])])
    registry.ingest(note, extractor="twins")
    cells = [a for a in registry.anchors_for_page("quarterly-notes", 1) if a.kind == "cell"]
    assert parse_token(cells[0].token).hash == parse_token(cells[1].token).hash
    assert cells[0].token != cells[1].token  # the locator still tells them apart


def _four_hex_collision() -> tuple[str, str]:
    """Two short strings whose normalized sha256 hexdigests share four hex chars."""
    from backdraft.kernel.hashing import snippet_hash

    seen: dict[str, str] = {}
    for index in range(200_000):
        text = f"v{index}"
        prefix = snippet_hash(text)[:4]
        if prefix in seen:
            return seen[prefix], text
        seen[prefix] = text
    raise AssertionError("no four-hex collision found")  # pragma: no cover


def test_a_page_kind_anchor_exists_even_for_a_blank_page(
    registry: Registry, scripted: type, note: Path
) -> None:
    scripted("blank", [ExtractedPage(number=1, kind="page", text="   \n\n  ")])
    registry.ingest(note, extractor="blank")
    anchors = registry.anchors_for_page("quarterly-notes", 1)
    assert [anchor.kind for anchor in anchors] == ["page"]
    assert registry.resolve(anchors[0].token) is not None


# --- page image snapshots ----------------------------------------------------


def test_page_images_round_trip_through_ingest(registry, tmp_path) -> None:
    from backdraft.extract.base import ExtractedPage, PageImage, register

    class Snapshotting:
        name = "snapshotting"
        version = "1"
        deterministic = True

        def can_handle(self, path, media_type):
            return path.suffix == ".snap"

        def extract(self, path, config):
            yield ExtractedPage(
                number=1, kind="page", text="Page one.",
                image=PageImage(data=b"WEBPBYTES", format="webp", width=10, height=8),
            )
            yield ExtractedPage(number=2, kind="page", text="Page two, no image.")

    register(Snapshotting())
    path = tmp_path / "doc.snap"
    path.write_text("irrelevant", encoding="utf-8")
    document = registry.ingest(path, extractor="snapshotting")

    stored = registry.page_image(document.slug, 1)
    assert stored is not None
    assert (stored.data, stored.format, stored.width, stored.height) == (
        b"WEBPBYTES", "webp", 10, 8,
    )
    assert registry.page_image(document.slug, 2) is None


def test_save_page_image_backfills_and_replaces(registry, note) -> None:
    document = registry.ingest(note)
    extraction_id = registry.current_extraction_id(document.slug)
    registry.save_page_image(
        extraction_id, 1, data=b"ONE", format="webp", width=1, height=1
    )
    registry.save_page_image(
        extraction_id, 1, data=b"TWO", format="webp", width=2, height=2
    )
    stored = registry.page_image(document.slug, 1)
    assert stored.data == b"TWO" and stored.width == 2
