"""`ingest --dry-run`: what a source would be called, while that is still cheap.

A slug is written into every token of every document cited against a source and
is stable once assigned, so choosing one wrong costs a re-ingest and a rewritten
draft. The docs' advice — pass `--slug` for a fetched page — asks for a
permanent choice; this is the way to see what the default would be first.

The invariant the whole file circles is one sentence: the prediction equals the
outcome. Two tests pin it directly, one for a file and one over the loopback
server; the rest pin what the prediction has to say about a registry that
already holds the source, or a name another document already took.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from backdraft import cli, fetch
from backdraft.registry import Registry

runner = CliRunner()

pytest_plugins = ["test_fetch"]  # the `serve` fixture and its handler

WIKI = "https://en.wikipedia.org/w/index.php?title=Franklin_County,_Ohio&oldid=1367935775"

PAGE = b"""<!doctype html>
<html><head><title>Bridgeview Q4</title></head><body>
<h1>Bridgeview Holdings</h1>
<p>Net operating income for the trailing twelve months was $4.1 million, up
eleven percent year over year across the suburban assets.</p>
</body></html>
"""


@pytest.fixture(autouse=True)
def no_home_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(cli.HOME_ENV, raising=False)
    monkeypatch.delenv(cli.SESSION_ENV, raising=False)


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    runner.invoke(cli.app, ["init"])
    return tmp_path


def _refuse(*_: object, **__: object):
    raise AssertionError("--dry-run fetched something")


class _Network:
    """The network, blocked, with a way to let one ingest through.

    The one promise `--dry-run` makes that cannot be read off its output is the
    thing it does not do, so it is asserted structurally rather than by eye —
    blocked for every test here, and the three that need a real ingest to
    compare against open it for exactly that call. Its own `MonkeyPatch` rather
    than the fixture's, because `undo()` on the shared one would also undo the
    chdir that put the test inside its project.
    """

    def __init__(self) -> None:
        self._patch = pytest.MonkeyPatch()
        self.block()

    def block(self) -> None:
        self._patch.setattr(fetch, "fetch", _refuse)

    def open(self) -> None:
        self._patch.undo()

    def close(self) -> None:
        self._patch.undo()


@pytest.fixture(autouse=True)
def network():
    net = _Network()
    yield net
    net.close()


def _state(root: Path) -> dict:
    """What a dry run must leave exactly as it found it: the whole registry."""
    with Registry.open(root) as registry:
        return registry.export_json()


# ---- the prediction is the outcome ------------------------------------------


def test_the_slug_a_file_is_told_it_would_take_is_the_one_it_takes(
    project: Path, note: Path
) -> None:
    predicted = runner.invoke(cli.app, ["ingest", str(note), "--dry-run"])
    assert predicted.exit_code == 0
    slug = predicted.stdout.split()[0]

    ingested = runner.invoke(cli.app, ["ingest", str(note)])
    assert ingested.exit_code == 0
    assert ingested.stdout.split()[0] == slug


def test_the_slug_a_url_is_told_it_would_take_is_the_one_it_takes(
    project: Path, serve, network
) -> None:
    """The half of the answer a dry run can settle without bytes, checked against bytes."""
    base = serve({"/q4": (200, "text/html; charset=utf-8", PAGE)})
    url = f"{base}/q4"
    predicted = runner.invoke(cli.app, ["ingest", url, "--dry-run"])
    assert predicted.exit_code == 0
    slug, media_type = predicted.stdout.split()[0], predicted.stdout.split()[2]

    network.open()  # this one wants the real transport
    ingested = runner.invoke(cli.app, ["ingest", url])
    assert ingested.exit_code == 0
    assert ingested.stdout.split()[0] == slug
    assert ingested.stdout.split()[2] == media_type


def test_a_generic_url_segment_earns_the_host_in_front_of_it(project: Path) -> None:
    """The 2026-08-19 rule, asked about rather than discovered after the fact."""
    result = runner.invoke(cli.app, ["ingest", WIKI, "--dry-run"])
    assert result.exit_code == 0
    assert result.stdout.startswith("en-wikipedia-org-index  ")
    assert " html" in result.stdout.splitlines()[0]


def test_a_file_is_named_by_its_stem_and_typed_by_its_suffix(
    project: Path, note: Path
) -> None:
    line = runner.invoke(cli.app, ["ingest", str(note), "--dry-run"]).stdout.splitlines()[0]
    assert line.split() == ["quarterly-notes", str(note), "text"]


# ---- nothing happens --------------------------------------------------------


def test_a_dry_run_creates_nothing_and_mints_nothing(
    project: Path, note: Path
) -> None:
    runner.invoke(cli.app, ["ingest", str(note)])
    before = _state(project)
    result = runner.invoke(cli.app, ["ingest", WIKI, str(note), "--dry-run"])
    assert result.exit_code == 0
    assert _state(project) == before


def test_a_dry_run_of_an_unknown_url_leaves_an_empty_registry_empty(
    project: Path,
) -> None:
    before = _state(project)
    assert runner.invoke(cli.app, ["ingest", WIKI, "--dry-run"]).exit_code == 0
    assert _state(project) == before
    assert before["documents"] == []


def test_a_dry_run_says_the_media_type_is_the_one_thing_the_fetch_settles(
    project: Path,
) -> None:
    result = runner.invoke(cli.app, ["ingest", WIKI, "--dry-run"])
    assert "nothing was fetched" in result.stdout
    assert "the content type the server sends" in result.stdout


def test_a_file_only_dry_run_says_nothing_about_fetching(
    project: Path, note: Path
) -> None:
    """The note is about web sources; a folder of files should not read it."""
    assert "fetched" not in runner.invoke(
        cli.app, ["ingest", str(note), "--dry-run"]
    ).stdout


def test_a_dry_run_of_an_ingested_source_offers_no_advice_it_cannot_take(
    project: Path, note: Path
) -> None:
    """`--slug` names a *new* document, so suggesting it for one already here is
    advice that cannot be followed."""
    runner.invoke(cli.app, ["ingest", str(note)])
    assert "--slug" not in runner.invoke(
        cli.app, ["ingest", str(note), "--dry-run"]
    ).stdout


def test_a_fresh_source_is_told_the_slug_is_still_choosable(
    project: Path, note: Path
) -> None:
    result = runner.invoke(cli.app, ["ingest", str(note), "--dry-run"])
    assert "`--slug <name>` still names quarterly-notes" in result.stdout
    assert "every token written against the source carries the slug" in result.stdout


# ---- what the registry already has ------------------------------------------


def test_a_source_already_ingested_says_so_and_names_the_slug_it_has(
    project: Path, note: Path
) -> None:
    runner.invoke(cli.app, ["ingest", str(note), "--slug", "t12-audit"])
    line = runner.invoke(cli.app, ["ingest", str(note), "--dry-run"]).stdout.splitlines()[0]
    assert line.startswith("t12-audit  ")
    assert line.endswith("already ingested")


def test_a_url_already_ingested_is_matched_on_the_url(
    project: Path, serve, network
) -> None:
    """A re-fetch keeps the slug it has, so the dry run must not predict a new one."""
    base = serve({"/q4": (200, "text/html; charset=utf-8", PAGE)})
    url = f"{base}/q4"
    network.open()
    runner.invoke(cli.app, ["ingest", url, "--slug", "bridgeview"])
    network.block()
    line = runner.invoke(cli.app, ["ingest", url, "--dry-run"]).stdout.splitlines()[0]
    assert line.startswith("bridgeview  ")
    assert "already ingested" in line


def test_an_ingested_urls_media_type_is_the_recorded_one_not_a_guess(
    project: Path, serve, network
) -> None:
    """`/data` carries no suffix, so the address alone would guess `html`; the
    registry knows the server called it CSV."""
    base = serve({"/data": (200, "text/csv", b"Unit,Rent\n101,2400\n")})
    url = f"{base}/data"
    network.open()
    runner.invoke(cli.app, ["ingest", url])
    network.block()
    result = runner.invoke(cli.app, ["ingest", url, "--dry-run"])
    assert result.stdout.splitlines()[0].split()[2] == "csv"
    assert "nothing was fetched" not in result.stdout


def test_a_name_another_document_took_is_reported_as_taken(
    project: Path, note: Path, tmp_path: Path
) -> None:
    runner.invoke(cli.app, ["ingest", str(note)])
    twin = tmp_path / "elsewhere" / "quarterly-notes.md"
    twin.parent.mkdir()
    twin.write_text("Different words entirely, on the same filename.", encoding="utf-8")
    line = runner.invoke(cli.app, ["ingest", str(twin), "--dry-run"]).stdout.splitlines()[0]
    assert line.startswith("quarterly-notes-2  ")
    assert line.endswith("quarterly-notes is taken")


def test_a_copy_of_an_ingested_file_is_that_document_not_a_new_one(
    project: Path, note: Path, tmp_path: Path
) -> None:
    """Identity is the bytes, so a copy under another name keeps the first slug —
    the dry run reads the bytes rather than guessing from the name."""
    runner.invoke(cli.app, ["ingest", str(note)])
    copy = tmp_path / "a-copy.md"
    copy.write_bytes(note.read_bytes())
    line = runner.invoke(cli.app, ["ingest", str(copy), "--dry-run"]).stdout.splitlines()[0]
    assert line.startswith("quarterly-notes  ")
    assert "already ingested" in line


def test_a_withdrawn_source_says_it_is_withdrawn(project: Path, note: Path) -> None:
    """`ls` denies it exists, so `already ingested` on its own would read as a lie."""
    runner.invoke(cli.app, ["ingest", str(note)])
    runner.invoke(cli.app, ["forget", "quarterly-notes", "--yes"])
    line = runner.invoke(cli.app, ["ingest", str(note), "--dry-run"]).stdout.splitlines()[0]
    assert line.endswith("already ingested, withdrawn")


def test_slug_on_an_ingested_source_says_it_would_not_rename_it(
    project: Path, note: Path
) -> None:
    """A slug is stable once assigned and `ingest` silently ignores `--slug`
    here; saying nothing would let the caller believe the rename was coming."""
    runner.invoke(cli.app, ["ingest", str(note)])
    line = runner.invoke(
        cli.app, ["ingest", str(note), "--dry-run", "--slug", "something-else"]
    ).stdout.splitlines()[0]
    assert line.startswith("quarterly-notes  ")
    assert line.endswith("--slug would not rename it")


def test_a_free_requested_slug_is_reported_plainly(project: Path, note: Path) -> None:
    line = runner.invoke(
        cli.app, ["ingest", str(note), "--dry-run", "--slug", "t12-audit"]
    ).stdout.splitlines()[0]
    assert line.split() == ["t12-audit", str(note), "text"]


def test_a_requested_slug_already_taken_fails_and_says_how_to_check(
    project: Path, note: Path, tmp_path: Path
) -> None:
    runner.invoke(cli.app, ["ingest", str(note), "--slug", "t12-audit"])
    other = tmp_path / "other.md"
    other.write_text("Other words.", encoding="utf-8")
    result = runner.invoke(
        cli.app, ["ingest", str(other), "--dry-run", "--slug", "t12-audit"]
    )
    assert result.exit_code == cli.EXIT_USAGE
    assert "already taken" in result.stderr
    assert "--dry-run" in result.stderr


# ---- what it cannot answer --------------------------------------------------


def test_a_missing_path_is_a_failure_rather_than_a_confident_slug(
    project: Path, tmp_path: Path
) -> None:
    """The commonest reason to ask is uncertainty about the source itself."""
    result = runner.invoke(cli.app, ["ingest", str(tmp_path / "nope.pdf"), "--dry-run"])
    assert result.exit_code == cli.EXIT_USAGE
    assert "0 of 1 source named; 1 failed" in result.stderr
    assert "Check the spelling" in result.stderr
    assert "nope" not in result.stdout


def test_the_dry_runs_failure_report_does_not_claim_an_ingest(
    project: Path, tmp_path: Path
) -> None:
    """`_unread_report` is shared with `ingest`, whose closing line is about
    re-running a half-landed list. Nothing landed here."""
    result = runner.invoke(cli.app, ["ingest", str(tmp_path / "nope.pdf"), "--dry-run"])
    assert "Nothing was ingested either way" in result.stderr
    assert "re-run the same command" not in result.stderr
    assert "sources ingested" not in result.stderr


def test_a_failed_source_does_not_stop_the_ones_behind_it(
    project: Path, note: Path, tmp_path: Path
) -> None:
    result = runner.invoke(
        cli.app, ["ingest", str(tmp_path / "nope.pdf"), str(note), "--dry-run"]
    )
    assert result.exit_code == cli.EXIT_USAGE
    assert "quarterly-notes" in result.stdout
    assert "1 of 2 sources named; 1 failed" in result.stderr


def test_a_scheme_that_cannot_be_fetched_is_refused_in_fetchs_own_words(
    project: Path,
) -> None:
    """One owner for the wording: the dry run and the fetch refuse it alike."""
    result = runner.invoke(cli.app, ["ingest", "ftp://x.example/a.pdf", "--dry-run"])
    assert result.exit_code == cli.EXIT_USAGE
    assert "cannot fetch 'ftp' URLs" in result.stderr


def test_a_slug_with_several_sources_is_a_usage_error_here_too(
    project: Path, note: Path
) -> None:
    result = runner.invoke(
        cli.app, ["ingest", str(note), WIKI, "--dry-run", "--slug", "x"]
    )
    assert result.exit_code == cli.EXIT_USAGE


def test_a_dry_run_without_a_registry_says_to_init(tmp_path: Path, monkeypatch) -> None:
    """The answer depends on what is already ingested, so there is no answering
    without a registry to ask."""
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(cli.app, ["ingest", "x.pdf", "--dry-run"])
    assert result.exit_code == cli.EXIT_USAGE
    assert "backdraft init" in result.stderr
