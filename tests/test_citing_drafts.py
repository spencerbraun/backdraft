"""Which drafts cite a source, read back from the project's records.

`ingest`'s new-generation note and `show`'s drift hint both said drift may have
happened and named `locate` with a placeholder. The records every rooted bind
writes under `.backdraft/records/` say which drafts cite which source, as last
bound, so both now name the drafts. Everything here runs through the CLI against
a registry on disk, because the record's location is the whole mapping.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from backdraft import cli
from backdraft.gate.reader import HANDFUL, drift_commands
from backdraft.registry import DIRECTORY, CitingDraft, Registry, scan_records

runner = CliRunner()

NOTES = (
    "Revenue grew twelve percent in the third quarter of the year, led by the "
    "renewal of the two largest tenants at rents above the prior lease, and the "
    "sponsor expects the same pace to hold through the winter months ahead."
)
OTHER = (
    "Headcount rose to two hundred people across the firm by the end of the year, "
    "most of them hired into the leasing and property management teams that the "
    "sponsor built out after the acquisition closed in the spring."
)
INSERTED = (
    "An inserted paragraph long enough to stand as its own chunk, well past the two "
    "hundred characters the chunker merges below, so every ordinal under it on the "
    "page moves down by one while the words beneath it stay exactly as written."
)


@pytest.fixture(autouse=True)
def no_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(cli.HOME_ENV, raising=False)
    monkeypatch.delenv(cli.SESSION_ENV, raising=False)


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    assert invoke("init").exit_code == 0
    return tmp_path


def invoke(*args: str):
    return runner.invoke(cli.app, list(args))


def write(path: Path, *paragraphs: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n\n".join(paragraphs) + "\n", encoding="utf-8")
    return path


def token(project: Path, slug: str) -> str:
    with Registry.open(project) as registry:
        return next(
            a.token for a in registry.anchors_for_page(slug, 1) if a.kind == "chunk"
        )


def two_memos(project: Path) -> str:
    """`memos/q3.md` cites `notes`; `staff.md` cites only `other`. Returns the notes token."""
    write(project / "notes.md", NOTES)
    write(project / "other.md", OTHER)
    assert invoke("ingest", "notes.md", "other.md").exit_code == 0
    assert invoke("read", "notes", "p1", "--session", "s1").exit_code == 0
    assert invoke("read", "other", "p1", "--session", "s1").exit_code == 0
    cited = token(project, "notes")
    write(project / "memos" / "q3.md", f"[Revenue grew twelve percent]({cited}).")
    write(project / "staff.md", f"[Headcount reached two hundred]({token(project, 'other')}).")
    for memo in ("memos/q3.md", "staff.md"):
        bound = invoke("bind", memo, "--session", "s1")
        assert bound.exit_code == 0, bound.output
    return cited


def citing_lines(output: str) -> list[str]:
    return [line for line in output.splitlines() if line.startswith("note: as last bound")]


# ---- ingest -----------------------------------------------------------------


def test_a_new_generation_names_the_draft_citing_it_and_not_the_other(project: Path) -> None:
    two_memos(project)
    write(project / "notes.md", INSERTED, NOTES)

    result = invoke("ingest", "notes.md")

    assert result.exit_code == 0, result.output
    assert citing_lines(result.output) == [
        "note: as last bound, 1 draft cites notes — run `backdraft locate memos/q3.md` "
        "to see which of its citations drifted and where their words stand now."
    ]
    assert "staff.md" not in result.output


def test_an_unchanged_reingest_says_nothing_about_drafts(project: Path) -> None:
    two_memos(project)
    result = invoke("ingest", "notes.md")
    assert result.exit_code == 0
    assert result.output.splitlines()[0].endswith("unchanged")
    assert "as last bound" not in result.output
    assert "new generation" not in result.output


def test_a_new_generation_no_record_cites_prints_todays_note_alone(project: Path) -> None:
    """No records at all: the output is exactly what it was before drafts were named."""
    write(project / "notes.md", NOTES)
    assert invoke("ingest", "notes.md").exit_code == 0
    write(project / "notes.md", INSERTED, NOTES)

    result = invoke("ingest", "notes.md")

    notes = [line for line in result.output.splitlines() if line.startswith("note:")]
    assert len(notes) == 1 and notes[0].startswith("note: new generation of notes")
    assert notes[0].endswith("names the new token wherever the text only moved.")


def test_a_record_holding_invalid_json_is_skipped_and_counted(project: Path) -> None:
    two_memos(project)
    (project / DIRECTORY / "records" / "broken.backdraft.json").write_text("{bad")
    write(project / "notes.md", INSERTED, NOTES)

    result = invoke("ingest", "notes.md")

    assert result.exit_code == 0, result.output
    [line] = citing_lines(result.output)
    assert "`backdraft locate memos/q3.md`" in line
    assert "1 record under `.backdraft/records/` could not be read" in line


def test_several_regenerated_sources_say_which_each_draft_cites(project: Path) -> None:
    two_memos(project)
    write(project / "notes.md", INSERTED, NOTES)
    write(project / "other.md", INSERTED, OTHER)

    [line] = citing_lines(invoke("ingest", "notes.md", "other.md").output)

    assert line.startswith("note: as last bound, 2 drafts cite notes, other — run ")
    assert "`backdraft locate memos/q3.md` (notes) and `backdraft locate staff.md` (other)" in line


def test_only_unreadable_records_still_say_the_list_may_be_short(project: Path) -> None:
    """No draft named, but a skipped record means "none" is not known to be true."""
    write(project / "notes.md", NOTES)
    assert invoke("ingest", "notes.md").exit_code == 0
    records = project / DIRECTORY / "records"
    records.mkdir(parents=True, exist_ok=True)
    for name in ("a", "b"):
        (records / f"{name}.backdraft.json").write_text("{bad")
    write(project / "notes.md", INSERTED, NOTES)

    [line] = citing_lines(invoke("ingest", "notes.md").output)

    assert line == (
        "note: as last bound, no draft in this project cites notes (2 records under "
        "`.backdraft/records/` could not be read and were skipped, so this may be short)."
    )


def test_the_ingest_note_counts_drafts_past_a_handful(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    drafts = tuple(
        CitingDraft(path=project / f"d{n}.md", citations={"notes": 1})
        for n in range(HANDFUL + 2)
    )
    monkeypatch.setattr(cli, "citing_drafts", lambda registry, slugs: (drafts, 0))
    write(project / "notes.md", NOTES)
    assert invoke("ingest", "notes.md").exit_code == 0
    write(project / "notes.md", INSERTED, NOTES)

    [line] = citing_lines(invoke("ingest", "notes.md").output)

    assert line.startswith("note: as last bound, 7 drafts cite notes — run ")
    assert line.count("backdraft locate") == HANDFUL
    assert "`backdraft locate d4.md` and 2 more to see which of their citations" in line


def test_a_deleted_draft_is_not_named(project: Path) -> None:
    two_memos(project)
    (project / "memos" / "q3.md").unlink()
    write(project / "notes.md", INSERTED, NOTES)
    assert "as last bound" not in invoke("ingest", "notes.md").output


# ---- show -------------------------------------------------------------------


def test_show_on_a_drifted_token_names_the_citing_memos_locate(project: Path) -> None:
    cited = two_memos(project)
    write(project / "notes.md", INSERTED, NOTES)
    assert invoke("ingest", "notes.md").exit_code == 0

    result = invoke("show", cited, "--session", "s1")

    assert result.output.rstrip().endswith(
        "To find where the cited text itself went: backdraft locate memos/q3.md "
        "--session s1 (the draft citing it, as last bound)]"
    )


def test_drift_commands_count_past_a_handful() -> None:
    drafts = [f"d{n}.md" for n in range(HANDFUL + 2)]
    line = drift_commands(drafts)
    assert line.count("backdraft locate") == HANDFUL
    assert line.endswith("; and 2 more (the 7 drafts citing it, as last bound)")
    assert drift_commands([]) == "backdraft locate <doc.md>"


# ---- the reader -------------------------------------------------------------


def test_scan_maps_records_back_by_location_and_suffix(project: Path) -> None:
    two_memos(project)
    scan = scan_records(project.resolve())
    assert [d.path.relative_to(project.resolve()).as_posix() for d in scan.drafts] == [
        "memos/q3.md",
        "staff.md",
    ]
    assert scan.drafts[0].citations == {"notes": 1}
    assert scan.skipped == 0
    assert scan.citing("other")[0].path.name == "staff.md"


def test_scan_of_a_rootless_or_unbound_project_is_empty(tmp_path: Path) -> None:
    assert scan_records(None).drafts == ()
    assert scan_records(tmp_path).drafts == ()


def test_a_malformed_token_counts_nothing_and_does_not_spoil_the_record(
    project: Path,
) -> None:
    write(project / "notes.md", NOTES)
    assert invoke("ingest", "notes.md").exit_code == 0
    assert invoke("read", "notes", "p1", "--session", "s1").exit_code == 0
    write(
        project / "memo.md",
        f"[Revenue grew]({token(project, 'notes')}). [Bad](bd:NOPE).",
    )
    invoke("bind", "memo.md", "--session", "s1")

    scan = scan_records(project.resolve())

    assert scan.skipped == 0
    assert [d.citations for d in scan.drafts] == [{"notes": 1}]
