"""`backdraft verify` — the recipient's check, in two tiers.

The point of the artifact is that someone who has only the file can check it.
That check used to be a prose procedure in `skills/backdraft-artifact/SKILL.md`
for an agent to re-implement each time, which is how a recipient's audit ends up
weaker than the producer's. So the tier that needs nothing but the file is
tested here without a registry anywhere above the fixture, exactly as a reader
who was emailed the artifact would run it.

The second tier is a different question — not "is this record intact" but "do
the sources still say this" — and its tests hold a real registry, edit a source
between ingests, and check that a status printed here is the status `bind`
would print. The one thing it must never do is mint: an audit that made its
subject citable would manufacture the evidence it was sent to inspect, and
`test_verifying_mints_nothing` is that pin.
"""

from __future__ import annotations

import json
import pathlib

import pytest
import typer
from typer.testing import CliRunner

from conftest_registry import PAGE_BREAK

from backdraft.kernel.artifact import ISLAND_ID, sidecar as artifact_payload
from backdraft.kernel.model import BindReport
from backdraft.registry import Registry
from backdraft.render import sidecar
from backdraft.render.cli import app as render_app

runner = CliRunner()

EXIT_USAGE = 1
EXIT_UNVERIFIED = 2


def _mounted() -> typer.Typer:
    """The top level, as SPEC Addendum B assembles it."""
    root = typer.Typer()

    @root.command()
    def init() -> None:
        """Stand-in for W1's own commands."""

    root.registered_commands.extend(render_app.registered_commands)
    root.registered_groups.extend(render_app.registered_groups)
    return root


app = _mounted()


@pytest.fixture(autouse=True)
def _no_ambient_registry(monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path) -> None:
    """No `.backdraft/` anywhere the tests do not put one.

    Discovery walks up from cwd, and the repo a developer runs this in is under
    a home directory that may hold one. Without this the tier-one tests would
    quietly run tier two.
    """
    monkeypatch.delenv("BACKDRAFT_HOME", raising=False)
    monkeypatch.chdir(tmp_path)


@pytest.fixture
def record(tmp_path: pathlib.Path, demo: BindReport) -> pathlib.Path:
    """A sidecar alone in a directory — the file a reader is handed."""
    return sidecar.write(demo, tmp_path / "memo.backdraft.json")


def _payload(path: pathlib.Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _rewrite(path: pathlib.Path, payload: dict) -> pathlib.Path:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def _first_anchored(payload: dict) -> dict:
    """The first citation in the record that carries a receipt."""
    return next(
        citation
        for claim in payload["claims"]
        for citation in claim["citations"]
        if "anchor" in citation
    )


# ---- tier one: the record against itself ------------------------------------


def test_a_clean_record_passes_with_no_registry_in_sight(record: pathlib.Path) -> None:
    result = runner.invoke(app, ["verify", str(record)])
    assert result.exit_code == 0, result.output
    assert "backdraft/artifact-v1" in result.output
    assert "no .backdraft/ found from here — not re-checked" in result.output


def test_the_report_says_how_many_receipts_held(record: pathlib.Path) -> None:
    result = runner.invoke(app, ["verify", str(record)])
    held = _payload(record)["summary"]["citations"]
    anchored = sum(
        1
        for claim in _payload(record)["claims"]
        for citation in claim["citations"]
        if "anchor" in citation
    )
    assert f"receipts: {anchored} of {anchored} hold" in result.output
    assert f"{held} citation(s)" in result.output


def test_a_recorded_unresolved_citation_is_not_a_failed_check(record: pathlib.Path) -> None:
    """A kept failure is the record working, not the record broken.

    The demo report carries every status there is. Tier one still exits 0: what
    the producer found is data the record faithfully carries, and gating on it
    would mean an honest artifact could never pass its own audit.
    """
    result = runner.invoke(app, ["verify", str(record)])
    assert "unresolved" in result.output
    assert result.exit_code == 0, result.output


def test_a_changed_snippet_names_the_claim_and_both_hashes(record: pathlib.Path) -> None:
    payload = _payload(record)
    citation = _first_anchored(payload)
    recorded = citation["anchor"]["snippet_sha256"]
    citation["anchor"]["snippet"] += " and one sentence nobody wrote."
    _rewrite(record, payload)

    result = runner.invoke(app, ["verify", str(record)])

    assert result.exit_code == EXIT_UNVERIFIED, result.output
    assert f"! receipt: {citation['token']}" in result.output
    assert f"the record says {recorded[:16]}" in result.output
    claim = next(c for c in payload["claims"] if citation in c["citations"])
    assert f"@{claim['start']}" in result.output
    assert " ".join(claim["text"].split())[:40] in result.output


def test_a_token_hash_that_does_not_match_its_own_snippet_fails(record: pathlib.Path) -> None:
    """The second half of step 2: a token pointing at somebody else's snippet.

    The snippet and its sha256 agree here — only the token's hash segment is
    wrong, which is the tamper that survives a hash-only check.
    """
    payload = _payload(record)
    citation = _first_anchored(payload)
    slug, locator = citation["anchor"]["slug"], citation["anchor"]["locator"]
    citation["token"] = f"bd:{slug}:{locator}:dead"
    _rewrite(record, payload)

    result = runner.invoke(app, ["verify", str(record)])

    assert result.exit_code == EXIT_UNVERIFIED, result.output
    assert "the token's hash dead is not a prefix of" in result.output


def test_a_token_naming_a_different_source_than_its_anchor_fails(record: pathlib.Path) -> None:
    payload = _payload(record)
    citation = _first_anchored(payload)
    anchor = citation["anchor"]
    digest = anchor["snippet_sha256"]
    citation["token"] = f"bd:elsewhere:{anchor['locator']}:{digest[:4]}"
    _rewrite(record, payload)

    result = runner.invoke(app, ["verify", str(record)])

    assert result.exit_code == EXIT_UNVERIFIED, result.output
    assert f"the token names elsewhere, the anchor is in {anchor['slug']}" in result.output


def test_a_token_pointing_at_a_different_place_than_its_anchor_fails(
    record: pathlib.Path,
) -> None:
    payload = _payload(record)
    citation = next(
        c
        for claim in payload["claims"]
        for c in claim["citations"]
        if "anchor" in c and c["anchor"]["locator"].startswith("p")
    )
    anchor = citation["anchor"]
    citation["token"] = f"bd:{anchor['slug']}:p99:{anchor['snippet_sha256'][:4]}"
    _rewrite(record, payload)

    result = runner.invoke(app, ["verify", str(record)])

    assert result.exit_code == EXIT_UNVERIFIED, result.output
    assert f"the token points at p99, the anchor at {anchor['locator']}" in result.output


def test_an_unparseable_token_on_an_anchored_citation_is_reported(
    record: pathlib.Path,
) -> None:
    payload = _payload(record)
    citation = _first_anchored(payload)
    citation["token"] = "bd:not a token"
    _rewrite(record, payload)

    result = runner.invoke(app, ["verify", str(record)])

    assert result.exit_code == EXIT_UNVERIFIED, result.output
    assert "the token does not parse" in result.output


def test_a_drifted_citation_is_checked_against_what_its_author_cited(
    record: pathlib.Path,
) -> None:
    """The trap in step 3, and the reason the spec used to state it wrongly.

    A `drifted` citation's token was minted from `drifted_from` — the snippet
    the author saw — while `anchor` carries what stands at that locator now, so
    the token's hash is deliberately *not* a prefix of the anchor's. A check
    that compared them would call every drifted artifact forged, which is the
    one status the format exists to carry honestly. The demo record holds one;
    it passes.
    """
    payload = _payload(record)
    drifted = next(
        citation
        for claim in payload["claims"]
        for citation in claim["citations"]
        if citation.get("drifted_from")
    )
    assert not drifted["anchor"]["snippet_sha256"].startswith(
        drifted["token"].rsplit(":", 1)[1]
    ), "fixture drift: this citation no longer exercises the two-snippet case"

    assert runner.invoke(app, ["verify", str(record)]).exit_code == 0


def test_a_changed_drifted_from_is_still_caught(record: pathlib.Path) -> None:
    """Lenient about which snippet, not about whether it matches."""
    payload = _payload(record)
    drifted = next(
        citation
        for claim in payload["claims"]
        for citation in claim["citations"]
        if citation.get("drifted_from")
    )
    drifted["drifted_from"] += " and a sentence the author never saw."
    _rewrite(record, payload)

    result = runner.invoke(app, ["verify", str(record)])

    assert result.exit_code == EXIT_UNVERIFIED, result.output
    assert "is not a prefix of drifted_from's" in result.output


def test_a_summary_that_disagrees_with_the_claims_fails(record: pathlib.Path) -> None:
    """`summary` is derived and never authoritative; the legend says so."""
    payload = _payload(record)
    payload["summary"]["citations"] += 4
    _rewrite(record, payload)

    result = runner.invoke(app, ["verify", str(record)])

    assert result.exit_code == EXIT_UNVERIFIED, result.output
    assert "does NOT agree with a recount" in result.output
    assert "trust claims" in result.output


def test_unmatched_claims_are_counted_not_flagged(
    tmp_path: pathlib.Path, backfill: BindReport
) -> None:
    """A claim nobody could anchor is a fact the record carries, not a defect."""
    path = sidecar.write(backfill, tmp_path / "notes.backdraft.json")
    result = runner.invoke(app, ["verify", str(path)])
    assert "unmatched claim(s)" in result.output
    assert "! unmatched" not in result.output


# ---- tier one: the HTML half ------------------------------------------------


def test_the_rendered_artifact_verifies_through_its_island(
    tmp_path: pathlib.Path, demo: BindReport
) -> None:
    """The half people forward is the half that has to be checkable."""
    doc = tmp_path / "memo.md"
    doc.write_text("# Memo\n", encoding="utf-8")
    sidecar.write(demo, sidecar.sidecar_path(doc))
    assert runner.invoke(app, ["render", str(doc)]).exit_code == 0

    result = runner.invoke(app, ["verify", str(doc.with_name("memo.backdraft.html"))])

    assert result.exit_code == 0, result.output
    assert "backdraft/artifact-v1" in result.output


def test_a_page_with_no_record_island_is_a_usage_error(tmp_path: pathlib.Path) -> None:
    page = tmp_path / "elsewhere.html"
    page.write_text("<!doctype html><html><body>not ours</body></html>", encoding="utf-8")
    result = runner.invoke(app, ["verify", str(page)])
    assert result.exit_code == EXIT_USAGE
    assert ISLAND_ID in result.output


# ---- tier one: what is not an artifact --------------------------------------


def test_a_missing_file_is_a_usage_error(tmp_path: pathlib.Path) -> None:
    result = runner.invoke(app, ["verify", str(tmp_path / "nope.backdraft.json")])
    assert result.exit_code == EXIT_USAGE
    assert "no such file" in result.output


def test_pointing_at_the_document_names_the_record_beside_it(
    tmp_path: pathlib.Path, demo: BindReport
) -> None:
    """The common miss, turned into the next command."""
    doc = tmp_path / "memo.md"
    doc.write_text("# Memo\n", encoding="utf-8")
    beside = sidecar.write(demo, sidecar.sidecar_path(doc))

    result = runner.invoke(app, ["verify", str(doc)])

    assert result.exit_code == EXIT_USAGE
    assert "is not a backdraft artifact" in result.output
    assert str(beside) in result.output


def test_a_structurally_broken_payload_is_a_usage_error(record: pathlib.Path) -> None:
    """Right format string, wrong shape: read it and refuse, do not guess at it.

    Exit 1 rather than 2, and the line matters: 1 is "I cannot read this", 2 is
    "I read it and it does not check out". A file this broken never reached a
    check.
    """
    payload = _payload(record)
    del payload["claims"][0]["start"]
    _rewrite(record, payload)

    result = runner.invoke(app, ["verify", str(record)])

    assert result.exit_code == EXIT_USAGE
    assert "is not a backdraft artifact" in result.output


def test_a_payload_whose_claims_are_not_claims_is_a_usage_error(
    record: pathlib.Path,
) -> None:
    payload = _payload(record)
    payload["claims"] = "not a list of claims"
    _rewrite(record, payload)

    result = runner.invoke(app, ["verify", str(record)])

    assert result.exit_code == EXIT_USAGE


def test_an_unknown_format_string_is_refused_rather_than_interpreted(
    record: pathlib.Path,
) -> None:
    payload = _payload(record)
    payload["$format"] = "backdraft/artifact-v9"
    _rewrite(record, payload)

    result = runner.invoke(app, ["verify", str(record)])

    assert result.exit_code == EXIT_USAGE
    assert "backdraft/artifact-v9" in result.output


# ---- tier two: against the sources ------------------------------------------


PAGE_ONE = "Page one holds the covenant language and nothing else worth quoting."
PAGE_TWO = "Page two carries the debt service coverage ratio of 1.42x this quarter."
PAGE_TWO_EDITED = "Page two now carries a debt service coverage ratio of 1.19x instead."


@pytest.fixture
def project(tmp_path: pathlib.Path, paged: object, monkeypatch: pytest.MonkeyPatch):
    """A real registry with one two-page source in it, and cwd inside it."""
    root = tmp_path / "project"
    root.mkdir()
    source = root / "quarterly-notes.md"
    source.write_text(PAGE_BREAK.join([PAGE_ONE, PAGE_TWO]), encoding="utf-8")
    with Registry.open(root) as registry:
        registry.ingest(source, extractor="paged")
        monkeypatch.chdir(root)
        yield registry, root, source


def _token(registry: Registry, page: int) -> str:
    return registry.anchors_for_page("quarterly-notes", page)[0].token


def _bound(root: pathlib.Path, registry: Registry, body: str) -> pathlib.Path:
    """A bound document's record, written where a reader would find it."""
    from backdraft.bind.binder import bind

    doc = root / "memo.md"
    doc.write_text(body, encoding="utf-8")
    report = bind(doc, registry, write=False)
    return sidecar.write(report, sidecar.sidecar_path(doc))


def test_a_registry_found_from_cwd_re_resolves_every_citation(project) -> None:
    registry, root, _ = project
    path = _bound(root, registry, f"The file says [1.42x]({_token(registry, 2)}).\n")

    result = runner.invoke(app, ["verify", str(path)])

    assert result.exit_code == 0, result.output
    assert f"sources: re-resolved against {root}" in result.output
    assert "resolved 1" in result.output


def test_the_registry_is_found_from_cwd_not_from_the_artifact(
    project, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An artifact is a file people forward; where it landed proves nothing.

    Same file, same registry, checked from a directory the registry is not
    under: tier two must not run, and the report must say it did not.
    """
    registry, root, _ = project
    path = _bound(root, registry, f"The file says [1.42x]({_token(registry, 2)}).\n")
    outside = tmp_path / "inbox"
    outside.mkdir()
    monkeypatch.chdir(outside)

    result = runner.invoke(app, ["verify", str(path)])

    assert result.exit_code == 0, result.output
    assert "no .backdraft/ found from here" in result.output


def test_a_token_naming_nothing_in_the_registry_exits_two(project) -> None:
    registry, root, _ = project
    path = _bound(root, registry, "The file says [1.42x](bd:ghost:p1.c1:0000).\n")

    result = runner.invoke(app, ["verify", str(path)])

    assert result.exit_code == EXIT_UNVERIFIED, result.output
    assert "! unresolved: bd:ghost:p1.c1:0000 — 1.42x @14" in result.output


def test_a_source_edited_since_binding_reports_drift_against_the_record(project) -> None:
    """The check the receipt exists to make rare, and the reason tier two exists.

    The record was clean when it was written; the source moved afterwards. The
    line item has to say both — what stands now, and that the record disagrees —
    or a reader cannot tell a stale artifact from a broken one.
    """
    registry, root, source = project
    token = _token(registry, 2)
    path = _bound(root, registry, f"The file says [1.42x]({token}).\n")
    assert runner.invoke(app, ["verify", str(path)]).exit_code == 0

    source.write_text(PAGE_BREAK.join([PAGE_ONE, PAGE_TWO_EDITED]), encoding="utf-8")
    registry.ingest(source, extractor="paged")

    result = runner.invoke(app, ["verify", str(path)])

    assert result.exit_code == EXIT_UNVERIFIED, result.output
    assert f"! drifted: {token} — the record says resolved" in result.output


def test_a_status_that_still_agrees_carries_no_disagreement_note(project) -> None:
    """`unresolved` then and `unresolved` now is one fact, said once."""
    registry, root, _ = project
    path = _bound(root, registry, "The file says [1.42x](bd:ghost:p1.c1:0000).\n")
    result = runner.invoke(app, ["verify", str(path)])
    assert "the record says" not in result.output


def test_verifying_mints_nothing(project) -> None:
    """Read-only, and the reason it is: showing is minting, auditing is not.

    `backdraft show` records every anchor it prints into the session ledger, so
    a token it printed becomes citable. An audit that did that would let a
    reader cite an artifact's evidence without ever opening the source.
    """
    registry, root, _ = project
    token = _token(registry, 2)
    path = _bound(root, registry, f"The file says [1.42x]({token}).\n")
    registry.ensure_session("default")

    assert runner.invoke(app, ["verify", str(path)]).exit_code == 0

    assert registry.was_shown("default", token) is False


def test_the_html_artifact_verifies_against_the_registry_too(project) -> None:
    registry, root, _ = project
    _bound(root, registry, f"The file says [1.42x]({_token(registry, 2)}).\n")
    doc = root / "memo.md"
    assert runner.invoke(app, ["render", str(doc)]).exit_code == 0

    result = runner.invoke(app, ["verify", str(root / "memo.backdraft.html")])

    assert result.exit_code == 0, result.output
    assert f"sources: re-resolved against {root}" in result.output


# ---- the island reader ------------------------------------------------------


def test_the_payload_reader_takes_either_half(tmp_path: pathlib.Path, demo: BindReport) -> None:
    """`render --to json` and the island of `--to html` are the same bytes."""
    doc = tmp_path / "memo.md"
    doc.write_text("# Memo\n", encoding="utf-8")
    path = sidecar.write(demo, sidecar.sidecar_path(doc))
    assert runner.invoke(app, ["render", str(doc)]).exit_code == 0

    from_json = sidecar.read_payload(path)
    from_html = sidecar.read_payload(doc.with_name("memo.backdraft.html"))

    assert from_json["$format"] == from_html["$format"]
    assert from_json["claims"] == from_html["claims"]
    assert from_json == artifact_payload(demo)


def test_a_renamed_sidecar_still_reads(tmp_path: pathlib.Path, demo: BindReport) -> None:
    """Decided by content, not by extension."""
    path = tmp_path / "somebody-renamed-this.txt"
    path.write_text(sidecar.dumps(demo), encoding="utf-8")
    assert sidecar.read_payload(path)["$format"] == "backdraft/artifact-v1"


def test_a_bare_json_value_is_not_a_payload(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "list.backdraft.json"
    path.write_text("[1, 2, 3]", encoding="utf-8")
    with pytest.raises(ValueError, match="bare list"):
        sidecar.read_payload(path)
