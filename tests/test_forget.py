"""`backdraft forget` — withdrawal, and everything that must survive it.

One file across every layer, the way `test_reingest.py` covers drift, because
the whole of this feature is a single claim that spans all of them: *a withdrawn
source leaves every surface that offers something to read, and nothing else about
it moves.* Splitting the store half from the gate half would leave the claim
untested in the middle, which is exactly where it can fail — a delete would pass
every "it is gone from `ls`" test ever written.

So the two halves are always asserted together: what disappeared, and what did
not. The second half is the one that matters, since a token already written into
somebody's draft or artifact must never quietly become an unexplained
`unresolved`.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from backdraft import cli
from backdraft.registry import GENERATION, Registry, RegistryError, UNCHANGED

runner = CliRunner()

SCRATCH = """\
A scratch copy of the quarterly notes, kept around by accident and never meant
to be a source. It puts the replacement reserve at $400 per unit per year, which
is the number nobody should ever cite.
"""


@pytest.fixture(autouse=True)
def no_home_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(cli.HOME_ENV, raising=False)
    monkeypatch.delenv(cli.SESSION_ENV, raising=False)


@pytest.fixture
def scratch(tmp_path: Path) -> Path:
    """The duplicate an unattended folder ingest picks up and should not have."""
    path = tmp_path / "scratch.md"
    path.write_text(SCRATCH, encoding="utf-8")
    return path


@pytest.fixture
def two(tmp_path: Path, note: Path, scratch: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """An initialized project holding a real source and a scratch copy, cwd inside."""
    monkeypatch.chdir(tmp_path)
    runner.invoke(cli.app, ["init"])
    result = runner.invoke(cli.app, ["ingest", str(note), str(scratch)])
    assert result.exit_code == 0, result.output
    return tmp_path


def _run(*args: str):
    return runner.invoke(cli.app, list(args))


def _forget(slug: str = "scratch"):
    result = _run("forget", slug, "--yes")
    assert result.exit_code == 0, result.output
    return result


def _token(root: Path, slug: str) -> str:
    """The first chunk token of a document's first page, straight off the store."""
    with Registry.open(root) as registry:
        page = registry.pages(slug)[0]
        anchors = registry.anchors_for_page(slug, page.number)
        return next(anchor.token for anchor in anchors if anchor.locator.kind == "chunk")


def _counts(root: Path) -> tuple[int, int, int]:
    """(documents, extractions, anchors) straight out of the export.

    The check that withdrawal removed nothing. Read from the export rather than
    from SQL so it is the portable form under test — the one a migration or a
    second implementation would rebuild a registry from.
    """
    with Registry.open(root) as registry:
        payload = registry.export_json()
    extractions = [e for d in payload["documents"] for e in d["extractions"]]
    anchors = [a for e in extractions for a in e["anchors"]]
    return len(payload["documents"]), len(extractions), len(anchors)


# ---- what disappears --------------------------------------------------------


def test_forget_takes_a_source_out_of_ls_read_and_search(two: Path) -> None:
    """The acceptance case: two documents in, one forgotten, one left on offer."""
    before = _run("search", "replacement reserve")
    assert "scratch" in before.stdout

    _forget()

    listed = _run("ls")
    assert "quarterly-notes" in listed.stdout and "scratch" not in listed.stdout
    gate_list = _run("read")
    assert "quarterly-notes" in gate_list.stdout and "scratch" not in gate_list.stdout
    assert "1 document" in gate_list.stdout
    found = _run("search", "replacement reserve")
    assert "scratch" not in found.stdout


def test_a_withdrawn_documents_anchors_leave_the_search_total_too(two: Path) -> None:
    """Not just the page of hits: the count a `--limit` run offers to widen to.

    The filter lives in the shared `_match_sql`, so a total that still counted a
    withdrawn document would send a caller widening `--limit` to reach results
    that can never appear.
    """
    wide = _run("search", "the OR a OR of", "--limit", "1")
    assert "scratch" in _run("search", "the OR a OR of").stdout
    before = wide.stdout.splitlines()[0]

    _forget()

    after = _run("search", "the OR a OR of", "--limit", "1").stdout.splitlines()[0]
    assert before != after, "the pre-limit total ignored the withdrawal"


def test_the_gate_refuses_a_withdrawn_documents_contents(two: Path) -> None:
    """And says which of the two "nothing to serve" cases this is, plus the way back."""
    _forget()
    for args in (("read", "scratch"), ("read", "scratch", "p1")):
        result = _run(*args)
        assert result.exit_code == 1, result.output
        assert "withdrawn from the registry on" in result.stderr
        assert "backdraft ingest" in result.stderr
        assert "no such document" not in result.stderr


def test_search_scoped_to_a_withdrawn_slug_is_refused_in_the_same_words(
    two: Path,
) -> None:
    """`--in` used to carry its own copy of the missing-slug wording."""
    _forget()
    scoped = _run("search", "reserve", "--in", "scratch")
    toc = _run("read", "scratch")
    assert scoped.exit_code == 1
    assert scoped.stderr == toc.stderr


def test_an_unknown_slug_still_reads_as_a_typo_rather_than_a_withdrawal(
    two: Path,
) -> None:
    """The negative branch of the message above: two mistakes, two next steps."""
    result = _run("read", "nope")
    assert result.exit_code == 1
    assert "no such document" in result.stderr
    assert "withdrawn" not in result.stderr


# ---- what does not disappear ------------------------------------------------


def test_forget_removes_no_row(two: Path) -> None:
    """Withdrawal, not deletion — the storage decision, asserted as one."""
    before = _counts(two)
    _forget()
    assert _counts(two) == before


def test_a_withdrawn_documents_token_still_shows_its_receipt(two: Path) -> None:
    """The failure this whole design exists to prevent, checked from the outside.

    The receipt prints, so somebody holding an artifact that cites a withdrawn
    source can still read what it said; the status says `unresolved` and the
    reason says why, so nobody mistakes it for a source still on offer.
    """
    token = _token(two, "scratch")
    _forget()

    result = _run("show", token)
    assert result.exit_code == 1, result.output
    assert "unresolved" in result.stdout
    assert "withdrawn from the registry on" in result.stdout
    assert "$400 per unit per year" in result.stdout
    assert "backdraft ingest" in result.stdout


def test_show_offers_the_way_back_instead_of_a_read_it_would_refuse(two: Path) -> None:
    """A read hint pointing at a withdrawn page is a hint that fails when used."""
    token = _token(two, "scratch")
    assert "[Read the page: backdraft read scratch p1]" in _run("show", token).stdout

    _forget()

    shown = _run("show", token).stdout
    assert "[Read the page: backdraft read scratch" not in shown
    assert "backdraft ingest" in shown


def test_the_store_still_resolves_a_withdrawn_documents_anchor(
    root: Path, note: Path
) -> None:
    """`resolve` is untouched: the status decision is `citation_for`'s alone."""
    with Registry.open(root) as registry:
        registry.ingest(note)
        token = registry.anchors_for_page("quarterly-notes", 1)[1].token
        registry.forget("quarterly-notes")
        resolution = registry.resolve(token)
        assert resolution is not None
        assert resolution.current is True
        assert resolution.anchor.token == token


def test_session_show_keeps_a_withdrawn_source_and_marks_it(two: Path) -> None:
    """The one place a withdrawn document is still listed, because the ledger is
    a record: dropping the row would rewrite what the writer was shown, and the
    total would stop agreeing with the ledger the export carries."""
    _run("read", "scratch", "p1")
    _run("read", "quarterly-notes", "p1")
    before = _run("session", "show").stdout
    assert "withdrawn" not in before, before

    _forget()

    after = _run("session", "show").stdout
    assert "scratch" in after
    assert "withdrawn" in after
    assert "no longer counts as coverage" in after


def test_a_session_with_nothing_withdrawn_prints_what_it_always_did(two: Path) -> None:
    """The byte-identity half of the rule above."""
    _run("read", "quarterly-notes", "p1")
    shown = _run("session", "show").stdout
    assert "withdrawn" not in shown


# ---- what bind and verify say -----------------------------------------------


def _memo(root: Path, token: str) -> Path:
    path = root / "memo.md"
    path.write_text(
        "# Bridgeview\n\n"
        f"The [replacement reserve is $400 per unit per year]({token}), per the notes.\n",
        encoding="utf-8",
    )
    return path


def test_bind_reports_a_withdrawn_source_rather_than_passing_it(two: Path) -> None:
    """Exit 2 and a line item, because the alternative is a document that keeps
    citing a source the registry no longer offers with nothing looking wrong."""
    token = _token(two, "scratch")
    _memo(two, token)
    # Through the gate first: front-walk judges `not_shown` against the ledger,
    # and a token lifted straight off the store was never shown to anyone.
    _run("read", "scratch", "p1")
    assert _run("bind", "memo.md").exit_code == 0

    _forget()

    result = _run("bind", "memo.md")
    assert result.exit_code == 2, result.output
    assert "unresolved: 1" in result.stdout
    assert f"! unresolved: {token} — withdrawn from the registry on" in result.stdout


def test_the_reason_travels_into_the_record_and_out_of_verify(two: Path) -> None:
    """`verify`'s line names it too: `unresolved` alone cannot tell a withdrawn
    source from one that was never there, and they need opposite responses."""
    token = _token(two, "scratch")
    _memo(two, token)
    _run("read", "scratch", "p1")
    _forget()
    _run("bind", "memo.md")
    assert _run("render", "memo.md", "--to", "html").exit_code == 0

    result = _run("verify", "memo.backdraft.html")
    assert result.exit_code == 2, result.output
    assert f"! unresolved: {token} — withdrawn from the registry on" in result.stdout

    from backdraft.kernel.artifact import record_path

    record = json.loads(
        record_path(two, two / "memo.md").read_text(encoding="utf-8")
    )
    citation = record["claims"][0]["citations"][0]
    assert citation["status"] == "unresolved"
    assert citation["error"].startswith("withdrawn from the registry on")


# ---- the way back -----------------------------------------------------------


def test_re_ingesting_a_forgotten_file_brings_the_same_document_back(
    two: Path, scratch: Path
) -> None:
    """The case that decides the storage: one slug, not a second one beside it."""
    token = _token(two, "scratch")
    before = _counts(two)
    _forget()

    result = _run("ingest", str(scratch))
    assert result.exit_code == 0, result.output
    assert "unchanged" in result.stdout and "restored" in result.stdout
    assert "came back" in result.stdout

    assert _counts(two) == before, "a second document was created"
    assert "scratch" in _run("ls").stdout
    assert _token(two, "scratch") == token
    assert "resolved" in _run("show", token).stdout


def test_re_ingesting_an_edited_forgotten_file_says_both_things(
    two: Path, scratch: Path
) -> None:
    """`restored` is a fact beside the outcome, not a fourth value of it."""
    _forget()
    scratch.write_text(SCRATCH.replace("$400", "$410"), encoding="utf-8")

    result = _run("ingest", str(scratch))
    assert "new generation" in result.stdout and "restored" in result.stdout

    with Registry.open(two) as registry:
        document = registry.document("scratch")
        assert document is not None and document.withdrawn_at is None
        generations = [
            entry
            for doc in registry.export_json()["documents"]
            if doc["slug"] == "scratch"
            for entry in doc["extractions"]
        ]
    assert len(generations) == 2


def test_an_untouched_ingest_says_nothing_about_withdrawal(two: Path, note: Path) -> None:
    """The negative branch: a registry nobody forgot anything in reads as before."""
    result = _run("ingest", str(note))
    assert "restored" not in result.stdout and "came back" not in result.stdout


# ---- the command itself -----------------------------------------------------


def test_forget_names_what_it_withdrew_and_what_survived(two: Path) -> None:
    result = _forget()
    assert result.stdout.startswith("forgot scratch (scratch.md, text, 1 page)")
    assert "backdraft show" in result.stdout
    # The path ingest was given, so the way back is literally re-runnable.
    assert f"backdraft ingest {two / 'scratch.md'}" in result.stdout


def test_forget_on_an_unknown_slug_exits_1_naming_the_known_ones(two: Path) -> None:
    result = _run("forget", "nope", "--yes")
    assert result.exit_code == 1
    assert "no document with slug 'nope'" in result.stderr
    assert "quarterly-notes" in result.stderr and "scratch" in result.stderr


def test_forget_in_an_empty_registry_says_so_rather_than_listing_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    runner.invoke(cli.app, ["init"])
    result = _run("forget", "nope", "--yes")
    assert result.exit_code == 1
    assert "nothing is ingested here" in result.stderr


def test_forgetting_twice_keeps_the_first_date_and_is_not_a_failure(two: Path) -> None:
    """The end state the caller asked for, so not an error — but not a claim to
    have withdrawn it now either, since the first date is the useful answer."""
    _forget()
    with Registry.open(two) as registry:
        first = registry.document("scratch")
    assert first is not None

    again = _run("forget", "scratch", "--yes")
    assert again.exit_code == 0
    assert "was already withdrawn from the registry on" in again.stdout
    assert not again.stdout.startswith("forgot")

    with Registry.open(two) as registry:
        second = registry.document("scratch")
    assert second is not None and second.withdrawn_at == first.withdrawn_at


def test_forget_without_yes_withdraws_nothing_and_names_the_flag(two: Path) -> None:
    """A prompt is unreachable from a script or an agent, so it is told the flag."""
    result = _run("forget", "scratch")
    assert result.exit_code == 1
    assert "--yes" in result.stderr
    assert "scratch" in _run("ls").stdout


def test_forget_asks_where_something_can_answer(
    two: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """And a no at the prompt withdraws nothing, which is the point of asking."""
    monkeypatch.setattr(cli, "_interactive", lambda: True)

    declined = runner.invoke(cli.app, ["forget", "scratch"], input="n\n")
    assert declined.exit_code == 1
    assert "scratch" in _run("ls").stdout

    accepted = runner.invoke(cli.app, ["forget", "scratch"], input="y\n")
    assert accepted.exit_code == 0, accepted.output
    assert "scratch" not in _run("ls").stdout


def test_the_registry_guards_a_slug_the_cli_would_have_caught(
    root: Path, note: Path
) -> None:
    """`forget`'s message belongs to the CLI, which knows the slugs to list; this
    is the invariant a library caller that skipped that check meets."""
    with Registry.open(root) as registry:
        registry.ingest(note)
        with pytest.raises(RegistryError, match="no document with slug 'nope'"):
            registry.forget("nope")


# ---- the export -------------------------------------------------------------


def test_the_export_carries_a_withdrawn_document_whole(two: Path) -> None:
    """Anchors included, or every token minted from it would strand on reload."""
    _forget()
    payload = json.loads(_run("export").stdout)
    entry = next(doc for doc in payload["documents"] if doc["slug"] == "scratch")
    assert entry["withdrawn_at"].endswith("Z")
    assert entry["extractions"][0]["anchors"], "a withdrawn document exported no anchors"


def test_an_export_with_no_withdrawal_carries_no_such_key(two: Path) -> None:
    """The conditional-key rule `meta` set: a registry of ordinary sources
    exports exactly what it exported before withdrawal existed."""
    payload = json.loads(_run("export").stdout)
    assert all("withdrawn_at" not in doc for doc in payload["documents"])


def test_ingest_outcomes_are_unchanged_by_the_restore_field(
    registry: Registry, note: Path
) -> None:
    """`restored` defaults false, so nothing that never withdrew anything moved."""
    first = registry.ingest(note)
    assert first.restored is False
    second = registry.ingest(note)
    assert (second.outcome, second.restored) == (UNCHANGED, False)
    registry.forget(note.stem)
    third = registry.ingest(note)
    assert (third.outcome, third.restored) == (UNCHANGED, True)
    note.write_text("Entirely different prose, long enough to chunk. " * 8, "utf-8")
    registry.forget(note.stem)
    fourth = registry.ingest(note)
    assert (fourth.outcome, fourth.restored) == (GENERATION, True)
