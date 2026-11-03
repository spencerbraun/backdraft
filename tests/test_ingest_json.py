"""`ingest --json`: what each source became, for a caller that parses.

`ingest` is the command whose output an agent has to act on source by source —
which slug to cite, which source came back thin, which never landed — and its
report is worded for people and reworded most weeks. The object carries the same
values; these tests pin its keys, that the exit codes did not move, and that the
report it stands beside did not change by a byte.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from test_snapshots import _make_pdf, _Renderer, _set_renderer, _uninstalled
from typer.testing import CliRunner

from backdraft import cli
from backdraft.registry import Registry

runner = CliRunner()

pytest_plugins = ["test_fetch"]  # the `serve` fixture and its handler

NOTES = "# Notes\n\n" + (
    "Net operating income rose eleven percent across the suburban assets this year. " * 6
) + "\n"
GONE = "# Gone\n\n" + (
    "This source gets withdrawn and then restored by a second ingest of the same bytes. " * 5
) + "\n"
DECK = "# Deck\n\n" + (
    "A body of prose that will change between the two ingests in this scenario, on purpose. " * 5
) + "\n"

MISSING_REASON = (
    "nothing is at that path. Check the spelling, and that the path is relative "
    "to the directory you are running in."
)

RESTORED_NOTE = (
    "note: gone came back — withdrawn with `backdraft forget`, and ingesting the "
    "source again is the undo. Back in `backdraft read`, `search` and `ls`, with "
    "citations into them resolving again. Forget again if that was not the intent."
)
GENERATION_NOTE = (
    "note: new generation of deck — citations into the previous snapshot may now "
    "report `drifted`. A token whose locator and snippet both survived the change "
    "carries over untouched, so `backdraft bind` on a document citing it is what "
    "says which; `backdraft locate <document>` then finds where each drifted "
    "citation's text stands now, and names the new token wherever the text only "
    "moved."
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(cli.HOME_ENV, raising=False)
    monkeypatch.delenv(cli.SESSION_ENV, raising=False)


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    runner.invoke(cli.app, ["init"])
    return tmp_path


def _scenario(project: Path) -> None:
    """A registry holding `notes`, `gone` (withdrawn) and `deck`, whose file has since moved."""
    (project / "notes.md").write_text(NOTES)
    (project / "gone.md").write_text(GONE)
    (project / "deck.md").write_text(DECK)
    assert runner.invoke(cli.app, ["ingest", "notes.md", "gone.md", "deck.md"]).exit_code == 0
    assert runner.invoke(cli.app, ["forget", "gone", "--yes"]).exit_code == 0
    with (project / "deck.md").open("a") as handle:
        handle.write("# edited\n")


def _object(*args: str, code: int = 0) -> dict:
    result = runner.invoke(cli.app, ["ingest", *args, "--json"])
    assert result.exit_code == code, result.output
    return json.loads(result.stdout)


def _by_slug(payload: dict) -> dict[str, dict]:
    return {entry["slug"]: entry for entry in payload["sources"]}


# ---- the acceptance run -----------------------------------------------------


def test_one_run_says_what_happened_to_every_source(project: Path) -> None:
    """Fresh, unchanged, changed, withdrawn and missing, in one list and one object."""
    _scenario(project)
    (project / "fresh.md").write_text(NOTES.replace("eleven", "twelve"))

    result = runner.invoke(
        cli.app,
        ["ingest", "fresh.md", "notes.md", "deck.md", "gone.md", "missing.md", "--json"],
    )

    assert result.exit_code == cli.EXIT_USAGE
    assert result.stderr == ""
    payload = json.loads(result.stdout)
    assert payload["format"] == "backdraft/ingest-v1"
    assert payload["dry_run"] is False

    no_images = {"status": "not_applicable", "reason": None}
    assert payload["sources"] == [
        {
            "source": "fresh.md",
            "slug": "fresh",
            "name": "fresh.md",
            "media_type": "text",
            "pages": 1,
            "chars": 484,
            "outcome": "created",
            "restored": False,
            "slug_applied": None,
            "thin": False,
            "snapshots": no_images,
        },
        {
            "source": "notes.md",
            "slug": "notes",
            "name": "notes.md",
            "media_type": "text",
            "pages": 1,
            "chars": 484,
            "outcome": "unchanged",
            "restored": False,
            "slug_applied": None,
            "thin": False,
            "snapshots": no_images,
        },
        {
            "source": "deck.md",
            "slug": "deck",
            "name": "deck.md",
            "media_type": "text",
            "pages": 1,
            "chars": 453,
            "outcome": "generation",
            "restored": False,
            "slug_applied": None,
            "thin": False,
            "snapshots": no_images,
        },
        {
            "source": "gone.md",
            "slug": "gone",
            "name": "gone.md",
            "media_type": "text",
            "pages": 1,
            "chars": 424,
            "outcome": "unchanged",
            "restored": True,
            "slug_applied": None,
            "thin": False,
            "snapshots": no_images,
        },
    ]
    assert payload["failures"] == [{"source": "missing.md", "reason": MISSING_REASON}]
    assert payload["notes"] == [RESTORED_NOTE, GENERATION_NOTE]


def test_a_clean_run_exits_zero_with_nothing_failed(project: Path) -> None:
    (project / "notes.md").write_text(NOTES)
    payload = _object("notes.md")
    assert payload["failures"] == []
    assert payload["notes"] == []
    assert [entry["outcome"] for entry in payload["sources"]] == ["created"]


def test_every_source_failing_still_prints_the_object(project: Path) -> None:
    payload = _object("missing.md", code=cli.EXIT_USAGE)
    assert payload["sources"] == []
    assert payload["failures"] == [{"source": "missing.md", "reason": MISSING_REASON}]


# ---- a run that cannot start ------------------------------------------------


@pytest.mark.parametrize(
    "args",
    [
        ["a.md", "b.md", "--slug", "one"],
        ["a.md", "--config", "not-a-pair"],
    ],
)
def test_a_run_that_cannot_start_prints_no_object(project: Path, args: list[str]) -> None:
    """Nothing happened, so there is nothing to report: the error, on stderr, at exit 1."""
    result = runner.invoke(cli.app, ["ingest", *args, "--json"])
    assert result.exit_code == cli.EXIT_USAGE
    assert result.stdout == ""
    assert result.stderr.startswith("backdraft: ")


def test_no_registry_prints_no_object(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "notes.md").write_text(NOTES)
    for args in (["notes.md"], ["notes.md", "--dry-run"]):
        result = runner.invoke(cli.app, ["ingest", *args, "--json"])
        assert result.exit_code == cli.EXIT_USAGE
        assert result.stdout == ""


# ---- the fields -------------------------------------------------------------


def test_slug_applied_tells_three_things_apart(project: Path) -> None:
    (project / "notes.md").write_text(NOTES)
    named = _object("notes.md", "--slug", "chosen")["sources"][0]
    assert (named["slug"], named["slug_applied"]) == ("chosen", True)

    refused = _object("notes.md", "--slug", "other")
    assert refused["sources"][0]["slug"] == "chosen"
    assert refused["sources"][0]["slug_applied"] is False
    assert refused["notes"][0].startswith("note: --slug other not applied")

    assert _object("notes.md")["sources"][0]["slug_applied"] is None


def test_thin_is_the_mark_every_other_surface_shows(project: Path) -> None:
    """A short prose source is thin, and a small table is complete, by one rule."""
    (project / "stub.md").write_text("short\n")
    (project / "rates.csv").write_text("unit,rent\n4B,2400\n")
    payload = _object("stub.md", "rates.csv")
    entries = _by_slug(payload)
    assert entries["stub"]["thin"] is True
    assert entries["rates"]["thin"] is False
    assert any(note.startswith("note: little text extracted") for note in payload["notes"])


def test_a_pdf_whose_images_landed_says_captured(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _set_renderer(monkeypatch, _Renderer())
    _make_pdf(project / "t12.pdf", [["Occupancy closed at 91.4%"]])
    entry = _object("t12.pdf", "--extractor", "pdf-text")["sources"][0]
    assert entry["snapshots"] == {"status": "captured", "reason": None}
    # Re-ingesting renders nothing, and the images are still there.
    _set_renderer(monkeypatch, _uninstalled())
    again = _object("t12.pdf", "--extractor", "pdf-text")["sources"][0]
    assert again["outcome"] == "unchanged"
    assert again["snapshots"] == {"status": "captured", "reason": None}


def test_a_pdf_without_poppler_says_why_and_stays_a_success(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _set_renderer(monkeypatch, _uninstalled())
    _make_pdf(project / "t12.pdf", [["Occupancy closed at 91.4%"]])
    payload = _object("t12.pdf", "--extractor", "pdf-text")
    snapshots = payload["sources"][0]["snapshots"]
    assert snapshots["status"] == "not_captured"
    assert "poppler" in snapshots["reason"]
    assert payload["failures"] == []
    note = next(n for n in payload["notes"] if n.startswith("note: page images not captured"))
    assert snapshots["reason"] in note


def test_a_url_keeps_the_source_as_typed_and_names_itself_by_the_url(
    project: Path, serve
) -> None:
    page = b"<html><head><title>Q4</title></head><body><p>%s</p></body></html>" % (
        b"Bridgeview rose. " * 30
    )
    base = serve({"/q4": (200, "text/html; charset=utf-8", page)})
    entry = _object(f"{base}/q4", "--slug", "bridgeview")["sources"][0]
    assert entry["source"] == f"{base}/q4"
    assert entry["name"] == f"{base}/q4"
    assert (entry["slug"], entry["media_type"]) == ("bridgeview", "html")
    assert entry["snapshots"]["status"] == "not_applicable"


# ---- one owner for the wording ----------------------------------------------


def test_the_notes_are_the_reports_own_strings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The same run in two projects, one each way: the wording has one owner."""
    results = {}
    for flags in ([], ["--json"]):
        root = tmp_path / ("json" if flags else "report")
        root.mkdir()
        monkeypatch.chdir(root)
        runner.invoke(cli.app, ["init"])
        _scenario(root)
        (root / "stub.md").write_text("short\n")
        results[bool(flags)] = runner.invoke(
            cli.app, ["ingest", "gone.md", "deck.md", "stub.md", *flags]
        ).stdout
    report = [line for line in results[False].splitlines() if line.startswith("note: ")]
    assert len(report) == 3
    assert json.loads(results[True])["notes"] == report


# ---- the report did not move ------------------------------------------------


def test_the_report_without_json_is_byte_identical(project: Path) -> None:
    """Pinned from the command as it stood before `--json` existed."""
    (project / "notes.md").write_text(NOTES)
    (project / "thin.md").write_text("short\n")
    (project / "gone.md").write_text(GONE)
    (project / "deck.md").write_text(DECK)

    first = runner.invoke(cli.app, ["ingest", "notes.md", "thin.md", "gone.md", "deck.md"])
    assert first.exit_code == 0
    assert first.stderr == ""
    assert first.stdout == (
        "notes  notes.md  text  1 page  484 chars\n"
        "thin  thin.md  text  1 page  6 chars\n"
        "gone  gone.md  text  1 page  424 chars\n"
        "deck  deck.md  text  1 page  444 chars\n"
        "note: little text extracted — the source may simply be short, or may keep "
        "its content somewhere this extractor does not read. Read it with `backdraft "
        "read <slug>` before citing it, and tell the user the source came back thin "
        "rather than citing the shell of it: thin.\n"
    )

    assert runner.invoke(cli.app, ["forget", "gone", "--yes"]).exit_code == 0
    with (project / "deck.md").open("a") as handle:
        handle.write("# edited\n")

    second = runner.invoke(cli.app, ["ingest", "notes.md", "gone.md", "deck.md", "missing.md"])
    assert second.exit_code == cli.EXIT_USAGE
    assert second.stdout == (
        "notes  notes.md  text  1 page  484 chars  unchanged\n"
        "gone  gone.md  text  1 page  424 chars  unchanged  restored\n"
        "deck  deck.md  text  1 page  453 chars  new generation\n"
        f"{RESTORED_NOTE}\n"
        f"{GENERATION_NOTE}\n"
    )
    assert second.stderr == (
        "backdraft: 3 of 4 sources ingested; 1 failed:\n"
        f"  ! missing.md — {MISSING_REASON}\n"
        "fix these and re-run the same command: a source already in the registry "
        "re-ingests as a no-op when its bytes, extractor and config are unchanged.\n"
    )

    third = runner.invoke(cli.app, ["ingest", "notes.md", "--slug", "other"])
    assert third.exit_code == 0
    assert third.stdout == (
        "notes  notes.md  text  1 page  484 chars  unchanged  --slug not applied\n"
        "note: --slug other not applied — notes.md is already in the registry as "
        "notes, and a slug is fixed once assigned. Every token written against the "
        "source carries notes, so a rename would strand each one, and nothing renames "
        "a document: not `--slug`, and not `backdraft forget` then a re-ingest, which "
        "brings the same document back under the same slug. Cite it as notes.\n"
    )


# ---- --dry-run --------------------------------------------------------------


def test_a_dry_run_is_the_same_object_with_nulls_for_what_extraction_decides(
    project: Path,
) -> None:
    (project / "fresh.md").write_text(NOTES)
    payload = _object("fresh.md", "--dry-run")
    assert payload["format"] == "backdraft/ingest-v1"
    assert payload["dry_run"] is True
    assert payload["failures"] == []
    assert payload["sources"] == [
        {
            "source": "fresh.md",
            "slug": "fresh",
            "name": None,
            "media_type": "text",
            "pages": None,
            "chars": None,
            "outcome": "would-ingest",
            "restored": False,
            "slug_applied": None,
            "thin": None,
            "snapshots": None,
            "extractor": "text",
            "extracted_with": None,
        }
    ]
    assert payload["notes"][0].startswith("note: nothing is ingested yet")
    # The same keys as the run itself, and the slug it predicted.
    keys = set(payload["sources"][0]) - {"extractor", "extracted_with"}
    landed = _object("fresh.md")["sources"][0]
    assert set(landed) == keys
    assert landed["slug"] == payload["sources"][0]["slug"]


def test_a_dry_run_writes_nothing(project: Path) -> None:
    (project / "fresh.md").write_text(NOTES)
    _object("fresh.md", "--dry-run")
    registry = Registry.open(project)
    try:
        assert registry.documents() == []
    finally:
        registry.close()


def test_a_dry_run_says_what_the_registry_already_knows(project: Path) -> None:
    _scenario(project)
    payload = _object("notes.md", "gone.md", "--dry-run", "--extractor", "text")
    entries = _by_slug(payload)
    assert entries["notes"]["outcome"] == "already-ingested"
    assert entries["notes"]["extracted_with"] == "text"
    assert entries["notes"]["restored"] is False
    assert entries["gone"]["outcome"] == "already-ingested"
    assert entries["gone"]["restored"] is True

    refused = _object("notes.md", "--dry-run", "--slug", "other")["sources"][0]
    assert (refused["slug"], refused["slug_applied"]) == ("notes", False)


def test_a_dry_run_failure_is_a_failure_entry_at_exit_one(project: Path) -> None:
    (project / "fresh.md").write_text(NOTES)
    result = runner.invoke(cli.app, ["ingest", "fresh.md", "missing.md", "--dry-run", "--json"])
    assert result.exit_code == cli.EXIT_USAGE
    assert result.stderr == ""
    payload = json.loads(result.stdout)
    assert [entry["source"] for entry in payload["sources"]] == ["fresh.md"]
    assert payload["failures"] == [{"source": "missing.md", "reason": MISSING_REASON}]


def test_a_dry_run_names_a_spending_extractor_without_spending(project: Path) -> None:
    (project / "scan.pdf").write_bytes(b"%PDF-1.4\n")
    payload = _object("scan.pdf", "--dry-run", "--extractor", "vlm")
    assert payload["sources"][0]["extractor"] == "vlm"
    assert any("vision model" in note for note in payload["notes"])
