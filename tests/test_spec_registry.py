"""`spec/registry.md` against the export it specifies.

The export is the only complete, portable representation of a registry, so it is
what a second implementation, a migration or an audit reads. That makes an
undocumented key a real defect rather than an untidiness: a reader holding the
spec would not know the key existed, and `$format` promises there is nothing to
know beyond the spec.

So the spec is the pin, mechanically. This module parses `spec/registry.md`'s key
tables, exports a registry built to exercise every branch the export has, and
requires the two to agree in both directions — a key the spec does not name fails
here, and so does a key the spec names that nothing emits. There is deliberately
no golden file beside it: the spec file *is* the golden, it lives in the diff a
reviewer reads, and a second copy of the same key set would only be a second
thing to forget to update.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from backdraft.kernel.hashing import snippet_hash
from backdraft.kernel.tokens import parse as parse_token
from backdraft.registry import EXPORT_FORMAT, Registry

SPEC = Path(__file__).resolve().parent.parent / "spec" / "registry.md"

KEY_TABLE = "| Key | Type | Is |"
"""The header of a table this module reads. Other tables in the spec — identity,
what each anchor kind carries — describe rather than enumerate, and are skipped
by having a different header."""

DELEGATED = frozenset({"bindings[].report"})
"""Paths the walk stops at because another spec owns them.

`bindings[].report` is the artifact sidecar's payload, specified in
spec/artifact.md; registry.md says so and deliberately does not restate it, since
one format with two specifications is one specification too many.
"""


# ---- reading the spec -------------------------------------------------------


def _specified() -> dict[str, list[str]]:
    """JSON path -> the keys `spec/registry.md` names there, in table order.

    A section heading carrying a backticked path (`` ### `documents[]` ``) labels
    the table under it; the one heading without a path labels the root object.
    Order is kept because the spec's *Encoding* section promises it.
    """
    tables: dict[str, list[str]] = {}
    path = None
    reading = False
    for line in SPEC.read_text(encoding="utf-8").split("\n"):
        if line.startswith("### "):
            heading = re.search(r"`([^`]+)`", line)
            path, reading = (heading.group(1) if heading else ""), False
            continue
        if line.startswith(KEY_TABLE):
            assert path is not None, "a key table sits above the first section heading"
            reading = True
            tables.setdefault(path, [])
            continue
        if not reading:
            continue
        if not line.startswith("|"):
            reading = False
            continue
        if line.startswith("|---"):
            continue
        # A row may name two keys sharing one description, as `start`/`end` do.
        cell = line.split("|")[1]
        keys = re.findall(r"`([^`]+)`", cell)
        assert keys, f"a row in the {path or 'root'} table names no key: {line}"
        tables[path].extend(keys)
    return tables


# ---- reading the export -----------------------------------------------------


def _instances(node: object, path: str = "", found: list[tuple[str, list[str]]] | None = None):
    """Every object in the export, as (path, its keys in the order they appear).

    The one walk of the payload: key coverage folds it into sets, key order reads
    it instance by instance.
    """
    found = [] if found is None else found
    if isinstance(node, dict):
        found.append((path, list(node)))
        for key, value in node.items():
            child = f"{path}.{key}" if path else key
            if child not in DELEGATED:
                _instances(value, child, found)
    elif isinstance(node, list):
        for item in node:
            _instances(item, path + "[]", found)
    return found


def _emitted(payload: dict) -> dict[str, set[str]]:
    """JSON path -> the keys the export carries there.

    Unions across every instance at a path, so a conditional key present on one
    document and absent on another is still counted as emitted.
    """
    found: dict[str, set[str]] = {}
    for path, keys in _instances(payload):
        found.setdefault(path, set()).update(keys)
    return found


# ---- a registry with one of everything in it --------------------------------


REPORT = {
    "doc_path": "memo.md",
    "mode": "frontwalk",
    "session_id": "s-labelled",
    "bound_at": "2026-08-25T00:00:00Z",
    "claims": [],
    "summary": {"claims": 0, "citations": 0, "by_status": {}, "by_method": {}},
}


@pytest.fixture
def whole(root: Path, note: Path, workbook: Path, tmp_path: Path) -> dict:
    """An export exercising every branch the format has.

    Both media shapes (prose pages with chunk anchors, sheets with cell anchors),
    both document shapes (a file, and a page fetched from the web with its
    provenance `meta`), a withdrawn document beside the documents on offer, two
    generations of one document so `is_current` is exercised both ways, a
    labelled session and an unlabelled one, a ledger row, and a binding.
    """
    page = tmp_path / "index.html"
    page.write_text("<h1>Franklin County</h1><p>Population 1,326,063 in 2020.</p>", "utf-8")
    with Registry.open(root) as registry:
        registry.ingest(note)
        registry.ingest(workbook)
        registry.ingest(
            page,
            url="https://example.org/franklin",
            fetched_at="2026-08-25T00:00:00Z",
        )
        note.write_text("Entirely different prose, long enough to chunk. " * 8, "utf-8")
        registry.ingest(note)
        # Withdrawn, and still exported whole: the export is what a migration
        # rebuilds a registry from, and dropping it would strand every token
        # minted from it.
        registry.forget("model")

        anchors = registry.anchors_for_page("quarterly-notes", 1)
        labelled = registry.ensure_session("s-labelled", "the audit")
        registry.ensure_session("s-bare")
        registry.record_shown(labelled, [anchors[1].id])
        registry.save_binding(
            doc_path="memo.md",
            session_id=labelled,
            mode="frontwalk",
            report_json=json.dumps(REPORT),
        )
        return registry.export_json()


def test_the_fixture_exercises_the_conditional_keys(whole: dict) -> None:
    """Without every shape the coverage tests below would pass while blind to a
    key that appears only sometimes — `meta`, whose arrival is what made the spec
    necessary, and `withdrawn_at`, which appears only on a document `forget`
    took out of the readable set and which must appear in the export at all."""
    carries = [document for document in whole["documents"] if "meta" in document]
    assert len(carries) == 1, "expected exactly the fetched document to carry meta"
    assert len(whole["documents"]) == 3, "expected two file documents beside it"
    gone = [document for document in whole["documents"] if "withdrawn_at" in document]
    assert [document["slug"] for document in gone] == ["model"]
    assert gone[0]["extractions"][0]["anchors"], "a withdrawn document lost its anchors"
    generations = [
        extraction["is_current"]
        for document in whole["documents"]
        if document["slug"] == "quarterly-notes"
        for extraction in document["extractions"]
    ]
    assert generations == [False, True], "expected a superseded generation and a current one"


def test_the_spec_names_every_key_the_export_emits(whole: dict) -> None:
    emitted = _emitted(whole)
    specified = _specified()
    for path, keys in sorted(emitted.items()):
        unnamed = keys - set(specified.get(path, ()))
        assert not unnamed, (
            f"spec/registry.md does not name {sorted(unnamed)} under "
            f"{path or 'the top level'}; document them there or stop emitting them"
        )


def test_the_export_emits_every_key_the_spec_names(whole: dict) -> None:
    emitted = _emitted(whole)
    specified = _specified()
    for path, keys in sorted(specified.items()):
        missing = set(keys) - emitted.get(path, set())
        assert not missing, (
            f"spec/registry.md names {sorted(missing)} under {path or 'the top level'} "
            f"and the export emits no such key"
        )


def test_the_spec_and_the_export_describe_the_same_objects(whole: dict) -> None:
    """Not just the keys: the set of paths that have keys at all."""
    assert sorted(_specified()) == sorted(_emitted(whole))


def test_keys_appear_in_the_order_the_spec_lists_them(whole: dict) -> None:
    """The spec's *Encoding* section promises key order, which is what makes two
    exports of an unchanged registry identical bytes. Checked per object rather
    than per path, so a conditional key absent from one instance does not read as
    a reordering of the rest."""
    specified = _specified()
    for path, keys in _instances(whole):
        expected = [key for key in specified[path] if key in keys]
        assert keys == expected, (
            f"{path or 'the top level'} emits {keys}; spec/registry.md lists {expected}"
        )


# ---- the spec's own "Checking an export" list, run ---------------------------


def test_the_format_string_is_the_one_the_spec_names(whole: dict) -> None:
    assert whole["$format"] == EXPORT_FORMAT == "backdraft/registry-v1"


def test_every_anchor_is_its_own_receipt(whole: dict) -> None:
    """Check 2: the snippet hashes to `snippet_sha256`, and the token names it."""
    for document in whole["documents"]:
        for extraction in document["extractions"]:
            for anchor in extraction["anchors"]:
                digest = snippet_hash(anchor["snippet"])
                assert digest == anchor["snippet_sha256"]
                parsed = parse_token(anchor["token"])
                assert digest.startswith(parsed.hash)
                assert parsed.slug == document["slug"]
                assert parsed.locator.format() == anchor["locator"]


def test_every_anchor_quotes_the_page_it_sits_on(whole: dict) -> None:
    """Check 3, and the kinds table under it: the page anchor is the whole page,
    a chunk is the half-open slice its offsets name, a cell is the value the
    sheet rendering shows in-band, and only chunks carry offsets at all."""
    seen = set()
    for document in whole["documents"]:
        for extraction in document["extractions"]:
            pages = {page["number"]: page["text"] for page in extraction["pages"]}
            for anchor in extraction["anchors"]:
                text = pages[anchor["page_number"]]
                seen.add(anchor["kind"])
                assert anchor["snippet"] in text
                if anchor["kind"] == "chunk":
                    assert text[anchor["start"] : anchor["end"]] == anchor["snippet"]
                    continue
                assert anchor["start"] is None and anchor["end"] is None
                if anchor["kind"] == "page":
                    assert anchor["snippet"] == text
    assert seen == {"page", "chunk", "cell"}, seen


def test_a_sheets_name_is_the_sheet_half_of_its_cell_locators(whole: dict) -> None:
    """The one place `pages[].name` carries identity rather than display."""
    sheets = 0
    for document in whole["documents"]:
        for extraction in document["extractions"]:
            names = {
                page["number"]: page["name"]
                for page in extraction["pages"]
                if page["kind"] == "sheet"
            }
            for anchor in extraction["anchors"]:
                if anchor["kind"] != "cell":
                    continue
                sheets += 1
                sheet, _, _ = anchor["locator"].partition("!")
                assert sheet == names[anchor["page_number"]]
    assert sheets, "the fixture produced no cell anchors"


def test_one_generation_per_document_is_current_and_locators_are_unique(whole: dict) -> None:
    """Check 4."""
    for document in whole["documents"]:
        current = [e for e in document["extractions"] if e["is_current"]]
        assert len(current) == 1, document["slug"]
        for extraction in document["extractions"]:
            locators = [anchor["locator"] for anchor in extraction["anchors"]]
            assert len(locators) == len(set(locators))


def test_the_ledger_resolves_against_the_export_alone(whole: dict) -> None:
    """Check 5 — the property the ledger carries tokens rather than row ids for."""
    sessions = {session["id"] for session in whole["sessions"]}
    tokens = {
        anchor["token"]
        for document in whole["documents"]
        for extraction in document["extractions"]
        for anchor in extraction["anchors"]
    }
    assert whole["ledger"], "the fixture recorded no showing"
    for row in whole["ledger"]:
        assert row["session_id"] in sessions
        assert row["token"] in tokens


def test_an_empty_registry_still_emits_all_four_top_level_keys(root: Path) -> None:
    with Registry.open(root) as registry:
        exported = registry.export_json()
    assert exported == {
        "$format": EXPORT_FORMAT,
        "documents": [],
        "sessions": [],
        "ledger": [],
        "bindings": [],
    }


def test_a_file_only_registry_carries_no_meta_key_anywhere(root: Path, note: Path) -> None:
    """The compatibility promise the spec makes for the conditional key."""
    with Registry.open(root) as registry:
        registry.ingest(note)
        exported = registry.export_json()
    assert "meta" not in json.dumps(exported)
