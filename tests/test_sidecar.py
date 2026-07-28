"""The sidecar: the format string, the legend contract, and round-trip stability.

The golden file in `tests/golden/render/` is the contract for the bytes a sidecar
carries. Regenerate deliberately, never reflexively:

    BACKDRAFT_UPDATE_GOLDEN=1 uv run pytest tests/test_sidecar.py
"""

from __future__ import annotations

import json
import pathlib

import pytest

from backdraft.kernel.model import BindReport, CitationStatus, VerdictStatus
from backdraft.render import sidecar

from conftest_render import backfill_report, demo_report
from golden_util import assert_golden

GOLDEN = pathlib.Path(__file__).parent / "golden" / "render"

LEGEND_KEYS = [
    "what_this_is",
    "how_to_read",
    "token",
    "locator_forms",
    "citation_status",
    "verdict_status",
    "verdicts_are_evidence",
    "verify_this_record",
    "evidence",
    "version",
]


def test_format_string_is_exact() -> None:
    assert sidecar.FORMAT == "backdraft/artifact-v1"


def test_payload_leads_with_the_reserved_keys(demo: BindReport) -> None:
    payload = sidecar.sidecar(demo)
    assert list(payload) == [
        "$format",
        "$legend",
        "doc_path",
        "mode",
        "session_id",
        "bound_at",
        "claims",
        "summary",
    ]
    assert payload["$format"] == sidecar.FORMAT
    assert payload["$legend"] == sidecar.LEGEND


def test_payload_is_the_report_plus_the_reserved_keys(demo: BindReport) -> None:
    payload = sidecar.sidecar(demo)
    report = demo.to_dict()
    assert {key: value for key, value in payload.items() if not key.startswith("$")} == report


def test_legend_carries_the_specified_keys() -> None:
    assert list(sidecar.LEGEND) == LEGEND_KEYS


def test_legend_explains_every_citation_status() -> None:
    assert set(sidecar.LEGEND["citation_status"]) == {str(status) for status in CitationStatus}
    for text in sidecar.LEGEND["citation_status"].values():
        assert text and text[0].islower()


def test_legend_explains_every_verdict_status() -> None:
    assert set(sidecar.LEGEND["verdict_status"]) == {str(status) for status in VerdictStatus}


def test_legend_explains_every_locator_form() -> None:
    assert set(sidecar.LEGEND["locator_forms"]) == {
        "p8",
        "p8.c3",
        "rent-roll!B10",
        "rent-roll!B10:C12",
    }


def test_legend_states_the_exact_match_rule() -> None:
    assert "backdraft/artifact-v1" in sidecar.LEGEND["version"]
    assert "exact" in sidecar.LEGEND["version"]


def test_legend_says_absent_methods_did_not_run() -> None:
    assert "not run" in sidecar.LEGEND["verdicts_are_evidence"]


def test_legend_teaches_the_hash_rule() -> None:
    assert "sha256" in sidecar.LEGEND["token"]
    assert "NFC" in sidecar.LEGEND["token"]


def test_legend_is_json_and_prose_only() -> None:
    """Strings, lists of strings, and flat objects of strings. No nested schema."""
    for value in sidecar.LEGEND.values():
        assert isinstance(value, (str, list, dict))
        if isinstance(value, list):
            assert all(isinstance(item, str) for item in value)
        if isinstance(value, dict):
            assert all(isinstance(item, str) for item in value.values())


def test_dumps_is_deterministic_and_newline_terminated(demo: BindReport) -> None:
    first = sidecar.dumps(demo)
    assert first == sidecar.dumps(demo_report())
    assert first.endswith("\n")
    assert json.loads(first)["$format"] == sidecar.FORMAT


@pytest.mark.parametrize("build", [demo_report, backfill_report])
def test_payload_round_trip_is_stable(build) -> None:  # noqa: ANN001
    payload = sidecar.sidecar(build())
    assert sidecar.sidecar(sidecar.to_report(payload)) == payload


def test_round_trip_preserves_the_record(demo: BindReport) -> None:
    rebuilt = sidecar.to_report(sidecar.sidecar(demo))
    assert [claim.text for claim in rebuilt.claims] == [claim.text for claim in demo.claims]
    original = [
        citation for claim in demo.claims for citation in claim.citations
    ]
    restored = [citation for claim in rebuilt.claims for citation in claim.citations]
    assert [citation.status for citation in restored] == [
        citation.status for citation in original
    ]
    assert [citation.token for citation in restored] == [
        citation.token for citation in original
    ]
    assert [citation.verdicts for citation in restored] == [
        citation.verdicts for citation in original
    ]
    for before, after in zip(original, restored, strict=True):
        if before.anchor is None:
            assert after.anchor is None
            continue
        assert after.anchor is not None
        assert after.anchor.receipt == before.anchor.receipt
        assert str(after.anchor.locator) == str(before.anchor.locator)
        assert after.anchor.slug == before.anchor.slug


def test_round_trip_keeps_unmatched_claims(backfill: BindReport) -> None:
    rebuilt = sidecar.to_report(sidecar.sidecar(backfill))
    assert [claim.unmatched for claim in rebuilt.claims] == [False, True]
    assert rebuilt.session_id is None
    assert rebuilt.mode == "backfill"


def test_unknown_format_is_refused(demo: BindReport) -> None:
    payload = sidecar.sidecar(demo)
    payload["$format"] = "backdraft/artifact-v2"
    with pytest.raises(ValueError, match="unknown artifact format"):
        sidecar.to_report(payload)


def test_missing_format_is_refused(demo: BindReport) -> None:
    payload = {key: value for key, value in sidecar.sidecar(demo).items() if key != "$format"}
    with pytest.raises(ValueError, match="unknown artifact format"):
        sidecar.to_report(payload)


def test_non_object_payload_is_refused() -> None:
    with pytest.raises(ValueError, match="must be an object"):
        sidecar.to_report([])  # type: ignore[arg-type]


def test_write_and_read_round_trip(tmp_path: pathlib.Path, demo: BindReport) -> None:
    path = sidecar.write(demo, tmp_path / "memo.backdraft.json")
    assert path.read_text(encoding="utf-8") == sidecar.dumps(demo)
    assert sidecar.dumps(sidecar.read(path)) == sidecar.dumps(demo)


def test_sidecar_path_is_the_document_stem(tmp_path: pathlib.Path) -> None:
    assert sidecar.sidecar_path(tmp_path / "memo.md").name == "memo.backdraft.json"
    assert (
        sidecar.sidecar_path(tmp_path / "report.final.md").name == "report.final.backdraft.json"
    )


def test_find_sidecar_prefers_the_stem_form(tmp_path: pathlib.Path, demo: BindReport) -> None:
    doc = tmp_path / "memo.md"
    doc.write_text("# memo\n", encoding="utf-8")
    sidecar.write(demo, tmp_path / "memo.md.backdraft.json")
    assert sidecar.find_sidecar(doc) == tmp_path / "memo.md.backdraft.json"
    sidecar.write(demo, tmp_path / "memo.backdraft.json")
    assert sidecar.find_sidecar(doc) == tmp_path / "memo.backdraft.json"


def test_find_sidecar_returns_none_when_absent(tmp_path: pathlib.Path) -> None:
    doc = tmp_path / "memo.md"
    doc.write_text("# memo\n", encoding="utf-8")
    assert sidecar.find_sidecar(doc) is None


@pytest.mark.parametrize(
    ("name", "build"), [("demo", demo_report), ("backfill", backfill_report)]
)
def test_golden_sidecar(name: str, build) -> None:  # noqa: ANN001
    assert_golden(GOLDEN / f"{name}.sidecar.json", sidecar.dumps(build()))
