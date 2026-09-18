"""`backdraft locate`: where a re-ingest moved the text a document's citations quote.

Everything here is real — a registry on disk, sources ingested through the CLI, a
memo bound against them — because the question is what happens to real tokens
when a real source re-chunks. The paragraphs are each over the chunker's 200
characters, so every one is its own chunk and inserting one above the others
shifts their ordinals without changing their text: the case the command exists
for.
"""

from __future__ import annotations

import shlex
import sqlite3
from pathlib import Path

import pytest
from typer.testing import CliRunner

from backdraft import cli
from backdraft.kernel.claims import parse_claims
from backdraft.registry import DIRECTORY, Registry

runner = CliRunner()

OCCUPANCY = (
    "Occupancy at the property closed the third quarter at 92.0 percent, up from 88.5 "
    "percent a year earlier, as the lease-up of the renovated units on the east side of "
    "the complex finished ahead of the schedule the sponsor had set."
)
COVERAGE = (
    "Net operating income for the trailing twelve months came to 4,120,000 dollars, "
    "which the lender underwrote against annual debt service of 2,900,000 dollars for "
    "a coverage ratio of 1.42x on the in-place loan balance."
)
TAXES = (
    "Real estate taxes of 412,300 dollars were the largest single expense line, and a "
    "reassessment appeal filed with the county board of revision in the spring remains "
    "pending with no hearing date scheduled yet."
)
LOBBY = (
    "The sponsor has also committed to a lobby refresh and a new leasing office, "
    "neither of which is reflected in the operating statement, and both of which the "
    "lender asked to see priced before the loan closes this winter."
)
CLAIMS = ("Occupancy closed at 92.0%", "NOI covered debt service 1.42x", "Taxes were $412,300")


@pytest.fixture(autouse=True)
def no_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Neither discovery nor the session leaks in from the developer's shell."""
    monkeypatch.delenv(cli.HOME_ENV, raising=False)
    monkeypatch.delenv(cli.SESSION_ENV, raising=False)


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    assert invoke("init").exit_code == 0
    return tmp_path


def invoke(*args: str):
    return runner.invoke(cli.app, list(args))


def write_source(project: Path, *paragraphs: str) -> Path:
    source = project / "notes.md"
    source.write_text("\n\n".join(paragraphs) + "\n", encoding="utf-8")
    return source


def ingest(source: Path) -> None:
    result = invoke("ingest", str(source))
    assert result.exit_code == 0, result.output


def chunk_tokens(project: Path, slug: str = "notes") -> list[str]:
    """Every chunk token on page 1 of the current generation, in order."""
    with Registry.open(project) as registry:
        return [
            anchor.token
            for anchor in registry.anchors_for_page(slug, 1)
            if anchor.kind == "chunk"
        ]


def write_memo(project: Path, tokens: list[str], claims=CLAIMS) -> Path:
    memo = project / "memo.md"
    sentences = " ".join(f"[{claim}]({token})." for claim, token in zip(claims, tokens))
    memo.write_text(f"# Memo\n\n{sentences}\n", encoding="utf-8")
    return memo


def offsets(memo: Path) -> list[int]:
    return [claim.start for claim in parse_claims(memo.read_text(encoding="utf-8"))]


def bound_under_s1(project: Path, *paragraphs: str) -> tuple[Path, list[str]]:
    """Ingest the paragraphs, read them under `s1`, and bind a memo citing each chunk clean."""
    ingest(write_source(project, *paragraphs))
    assert invoke("read", "notes", "p1", "--session", "s1").exit_code == 0
    tokens = chunk_tokens(project)
    memo = write_memo(project, tokens)
    bound = invoke("bind", "memo.md", "--session", "s1")
    assert bound.exit_code == 0, bound.output
    return memo, tokens


def closing_command(line: str) -> list[str]:
    """The runnable command a bracketed closing line names, as argv for the runner."""
    assert line.startswith("[") and line.endswith("]"), line
    return shlex.split(line[:-1].split(": backdraft ", 1)[1])


# ---- the acceptance ---------------------------------------------------------


def test_three_citations_pushed_down_by_a_new_paragraph_are_moved_with_their_new_tokens(
    project: Path,
) -> None:
    memo, cited = bound_under_s1(project, OCCUPANCY, COVERAGE, TAXES)
    ingest(write_source(project, LOBBY, OCCUPANCY, COVERAGE, TAXES))
    now = chunk_tokens(project)[1:]
    assert [token.split(":")[3] for token in now] == [token.split(":")[3] for token in cited]

    result = invoke("locate", "memo.md", "--session", "s1")

    assert result.exit_code == 0, result.output
    lines = result.stdout.splitlines()
    assert lines[:2] == ["3 citation(s) in memo.md, 3 drifted", "  moved: 3"]
    assert lines[2:5] == [
        f"  ! moved: {old} — now at {new} — {claim} @{start}"
        for old, new, claim, start in zip(cited, now, CLAIMS, offsets(memo))
    ]
    assert lines[5] == (
        "[Nothing was rewritten. Put each moved token in place of the old one in memo.md, "
        "then show the new ones, which this session has not seen, and re-bind: "
        f"backdraft show {' '.join(now)} --session s1]"
    )
    assert len(lines) == 6


def test_applying_the_moved_tokens_and_following_the_closing_line_binds_clean(
    project: Path,
) -> None:
    memo, cited = bound_under_s1(project, OCCUPANCY, COVERAGE, TAXES)
    ingest(write_source(project, LOBBY, OCCUPANCY, COVERAGE, TAXES))
    located = invoke("locate", "memo.md", "--session", "s1")
    now = chunk_tokens(project)[1:]

    text = memo.read_text(encoding="utf-8")
    for old, new in zip(cited, now):
        text = text.replace(old, new)
    memo.write_text(text, encoding="utf-8")

    # Printing a token is not showing it: the session has seen the old tokens'
    # text and never these names, so a re-bind before the closing line is run
    # says exactly that, and nothing else.
    early = invoke("bind", "memo.md", "--session", "s1")
    assert early.exit_code == 2
    assert "  not_shown: 3" in early.stdout.splitlines()

    shown = invoke(*closing_command(located.stdout.splitlines()[-1]))
    assert shown.exit_code == 0, shown.output

    rebound = invoke("bind", "memo.md", "--session", "s1")
    assert rebound.exit_code == 0, rebound.output
    assert "  resolved: 3" in rebound.stdout.splitlines()
    assert invoke("locate", "memo.md", "--session", "s1").stdout == (
        "3 citation(s) in memo.md, 0 drifted\n"
    )


def test_a_citation_whose_text_was_deleted_is_gone_and_proposes_no_token(
    project: Path,
) -> None:
    memo, cited = bound_under_s1(project, OCCUPANCY, COVERAGE, TAXES)
    ingest(write_source(project, OCCUPANCY, TAXES))
    starts = offsets(memo)

    result = invoke("locate", "memo.md", "--session", "s1")

    assert result.exit_code == 0
    lines = result.stdout.splitlines()
    # The first paragraph never moved, so its citation is not drifted at all.
    assert lines[:3] == ["3 citation(s) in memo.md, 2 drifted", "  gone: 1", "  moved: 1"]
    assert lines[3] == f"  ! gone: {cited[1]} — {CLAIMS[1]} @{starts[1]}"
    assert lines[4] == (
        f"  ! moved: {cited[2]} — now at {chunk_tokens(project)[1]} — {CLAIMS[2]} @{starts[2]}"
    )
    assert lines[-1] == (
        "[A gone citation's text was edited or removed, so nothing is proposed. Read what "
        f"it cited, then search for the new wording: backdraft show {cited[1]} --session s1]"
    )


def test_a_sentence_edited_by_one_figure_is_gone_not_moved(project: Path) -> None:
    """Exact text only. A near match proposed as a move would rewrite provenance."""
    _, cited = bound_under_s1(project, OCCUPANCY, COVERAGE, TAXES)
    ingest(write_source(project, LOBBY, OCCUPANCY, COVERAGE.replace("1.42x", "1.43x"), TAXES))

    lines = invoke("locate", "memo.md").stdout.splitlines()

    assert lines[:3] == ["3 citation(s) in memo.md, 3 drifted", "  gone: 1", "  moved: 2"]
    gone = [line for line in lines if line.startswith("  ! gone:")]
    assert gone == [f"  ! gone: {cited[1]} — {CLAIMS[1]} @{offsets(Path('memo.md'))[1]}"]
    assert "now at" not in gone[0]


def test_a_document_whose_sources_have_no_new_generation_reports_nothing(
    project: Path,
) -> None:
    bound_under_s1(project, OCCUPANCY, COVERAGE, TAXES)

    result = invoke("locate", "memo.md", "--session", "s1")

    assert result.exit_code == 0
    assert result.stdout == "3 citation(s) in memo.md, 0 drifted\n"


def test_nothing_is_written_to_the_registry_the_ledger_or_the_record(
    project: Path,
) -> None:
    bound_under_s1(project, OCCUPANCY, COVERAGE, TAXES)
    ingest(write_source(project, LOBBY, OCCUPANCY, COVERAGE, TAXES))
    tables = ("documents", "extractions", "anchors", "ledger", "sessions", "bindings")
    files = {
        path: path.read_bytes()
        for path in project.rglob("*")
        if path.is_file() and path.name != "registry.db"
    }

    def counts() -> dict[str, int]:
        with sqlite3.connect(project / DIRECTORY / "registry.db") as connection:
            return {
                table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in tables
            }

    before = counts()
    # A session nothing has started is read as empty, never created.
    for args in (("--session", "s1"), ("--session", "never-started"), ()):
        assert invoke("locate", "memo.md", *args).exit_code == 0

    assert counts() == before
    assert {path: path.read_bytes() for path in files} == files


# ---- what is not proposed ---------------------------------------------------


def test_text_standing_in_several_places_is_ambiguous_and_names_them(
    project: Path,
) -> None:
    memo, cited = bound_under_s1(project, OCCUPANCY, COVERAGE, TAXES)
    ingest(write_source(project, COVERAGE, OCCUPANCY, TAXES, COVERAGE))
    now = chunk_tokens(project)

    lines = invoke("locate", "memo.md", "--session", "s1").stdout.splitlines()

    # Taxes stayed third, so its token carried over and only two citations drifted.
    assert lines[:3] == ["3 citation(s) in memo.md, 2 drifted", "  ambiguous: 1", "  moved: 1"]
    ambiguous = [line for line in lines if line.startswith("  ! ambiguous:")]
    assert ambiguous == [
        f"  ! ambiguous: {cited[1]} — the cited text stands at 2 places: {now[0]}, {now[3]}"
        f" — {CLAIMS[1]} @{offsets(memo)[1]}"
    ]
    assert lines[-1] == (
        "[Nothing is proposed for an ambiguous citation: show the places its line names "
        "and cite the one the claim is about, or re-read the source.]"
    )


def test_a_chunk_is_looked_for_among_chunks_and_never_the_page_around_it(
    project: Path,
) -> None:
    """A page whose one chunk is its whole text carries one hash on two anchors,
    and a citation of a chunk has moved to a chunk: the same-kind rule is what
    keeps that a `moved` rather than an `ambiguous` naming the page too."""
    memo, cited = bound_under_s1(project, OCCUPANCY, COVERAGE)
    ingest(write_source(project, COVERAGE))
    with Registry.open(project) as registry:
        hashes = {
            anchor.kind: anchor.receipt.snippet_sha256
            for anchor in registry.anchors_for_page("notes", 1)
        }
    assert hashes["page"] == hashes["chunk"], "the case this test exists for"

    lines = invoke("locate", "memo.md").stdout.splitlines()

    assert lines[:2] == ["2 citation(s) in memo.md, 2 drifted", "  gone: 1"]
    assert (
        f"  ! moved: {cited[1]} — now at {chunk_tokens(project)[0]} — {CLAIMS[1]} "
        f"@{offsets(memo)[1]}"
    ) in lines


def test_an_ambiguous_line_names_three_places_and_counts_the_rest(project: Path) -> None:
    _, cited = bound_under_s1(project, OCCUPANCY, COVERAGE)
    ingest(write_source(project, COVERAGE, OCCUPANCY, COVERAGE, COVERAGE, COVERAGE))
    now = chunk_tokens(project)

    lines = invoke("locate", "memo.md").stdout.splitlines()

    ambiguous = next(line for line in lines if line.startswith("  ! ambiguous:"))
    named = ", ".join([now[0], now[2], now[3]])
    assert f"— the cited text stands at 4 places, among them {named} —" in ambiguous
    assert now[4] not in ambiguous


@pytest.fixture
def rates(project: Path):
    """A rate sheet, rewritable between ingests, and the tokens of its cells."""
    from openpyxl import Workbook

    path = project / "rates.xlsx"

    def write(*rows: tuple[str, float]) -> Path:
        book = Workbook()
        sheet = book.active
        sheet.title = "Rates"
        sheet.append(["Rate", "Value"])
        for row in rows:
            sheet.append(list(row))
        book.save(path)
        return path

    return write


def cell_token(project: Path, ref: str) -> str:
    with Registry.open(project) as registry:
        return next(
            anchor.token
            for anchor in registry.anchors_for_page("rates", 1)
            if anchor.locator.format() == f"rates!{ref}"
        )


def test_a_cell_whose_value_stands_at_one_other_address_is_ambiguous_not_moved(
    project: Path, rates
) -> None:
    """Two rates of 6.25% are two facts; a value alone does not say a cell moved."""
    ingest(rates(("Going-in cap", 0.0625), ("Exit cap", 0.0675)))
    cited = cell_token(project, "B2")
    memo = write_memo(project, [cited], claims=["a going-in cap rate of 6.25%"])
    ingest(rates(("Vacancy", 0.05), ("Going-in cap", 0.0625), ("Exit cap", 0.0675)))
    standing = cell_token(project, "B3")

    lines = invoke("locate", "memo.md").stdout.splitlines()

    assert lines == [
        "1 citation(s) in memo.md, 1 drifted",
        "  ambiguous: 1",
        f"  ! ambiguous: {cited} — the cited value stands at {standing}, and a value alone "
        f"does not say the cell moved — a going-in cap rate of 6.25% @{offsets(memo)[0]}",
        "[Nothing is proposed for an ambiguous citation: show the places its line names "
        "and cite the one the claim is about, or re-read the source.]",
    ]


def test_a_cell_whose_value_is_nowhere_is_gone(project: Path, rates) -> None:
    ingest(rates(("Going-in cap", 0.0625), ("Exit cap", 0.0675)))
    cited = cell_token(project, "B2")
    write_memo(project, [cited], claims=["a going-in cap rate of 6.25%"])
    ingest(rates(("Going-in cap", 0.06), ("Exit cap", 0.0675)))

    lines = invoke("locate", "memo.md").stdout.splitlines()

    assert lines[1] == "  gone: 1"
    assert lines[2].startswith(f"  ! gone: {cited} — ")


def test_a_withdrawn_sources_citations_are_binds_to_report_not_this(
    project: Path,
) -> None:
    """Withdrawn outranks drifted in `citation_for`, and a withdrawal has no new place."""
    bound_under_s1(project, OCCUPANCY, COVERAGE, TAXES)
    ingest(write_source(project, LOBBY, OCCUPANCY, COVERAGE, TAXES))
    assert invoke("forget", "notes", "--yes").exit_code == 0

    result = invoke("locate", "memo.md")

    assert result.exit_code == 0
    assert result.stdout == "3 citation(s) in memo.md, 0 drifted\n"


# ---- the closing line -------------------------------------------------------


def test_moved_tokens_the_session_has_seen_close_on_the_bind_itself(project: Path) -> None:
    bound_under_s1(project, OCCUPANCY, COVERAGE, TAXES)
    ingest(write_source(project, LOBBY, OCCUPANCY, COVERAGE, TAXES))
    assert invoke("read", "notes", "p1", "--session", "s1").exit_code == 0

    lines = invoke("locate", "memo.md", "--session", "s1").stdout.splitlines()

    assert lines[-1] == (
        "[Nothing was rewritten. Put each moved token in place of the old one in memo.md, "
        "then re-bind: backdraft bind memo.md --session s1]"
    )


def test_an_exported_session_is_read_and_not_repeated_in_the_closing_line(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The gate's hint rule: only a typed `--session` has to be carried forward."""
    bound_under_s1(project, OCCUPANCY, COVERAGE, TAXES)
    ingest(write_source(project, LOBBY, OCCUPANCY, COVERAGE, TAXES))
    now = chunk_tokens(project)[1:]
    monkeypatch.setenv(cli.SESSION_ENV, "s1")

    unseen = invoke("locate", "memo.md").stdout.splitlines()[-1]
    assert unseen.endswith(f": backdraft show {' '.join(now)}]")

    assert invoke("show", *now).exit_code == 0
    seen = invoke("locate", "memo.md").stdout.splitlines()[-1]
    assert seen.endswith(": backdraft bind memo.md]")


def test_a_token_cited_twice_on_one_claim_is_one_line_item(project: Path) -> None:
    _, cited = bound_under_s1(project, OCCUPANCY, COVERAGE)
    (project / "memo.md").write_text(
        f"[Occupancy closed at 92.0%]({cited[1]};{cited[1]}).\n", encoding="utf-8"
    )
    ingest(write_source(project, LOBBY, OCCUPANCY, COVERAGE))

    lines = invoke("locate", "memo.md").stdout.splitlines()

    assert lines[0] == "2 citation(s) in memo.md, 1 drifted"
    assert len([line for line in lines if line.startswith("  ! ")]) == 1


def test_a_malformed_or_unknown_token_is_not_looked_for(project: Path) -> None:
    ingest(write_source(project, OCCUPANCY))
    (project / "memo.md").write_text(
        "[One](bd:nope). [Two](bd:notes:p9.c9:abcd).\n", encoding="utf-8"
    )

    result = invoke("locate", "memo.md")

    assert result.exit_code == 0
    assert result.stdout == "2 citation(s) in memo.md, 0 drifted\n"


# ---- usage ------------------------------------------------------------------


def test_a_missing_document_is_a_usage_error(project: Path) -> None:
    result = invoke("locate", "absent.md")
    assert result.exit_code == 1
    assert "no such document: absent.md" in result.stderr


def test_a_document_that_is_not_utf8_is_a_usage_error_not_a_traceback(
    project: Path,
) -> None:
    (project / "memo.md").write_bytes(b"caf\xe9 [x](bd:notes:p1.c1:abcd)\n")
    result = invoke("locate", "memo.md")
    assert result.exit_code == 1
    assert isinstance(result.exception, SystemExit)
    assert "memo.md is not UTF-8 text" in result.stderr


def test_no_registry_is_a_usage_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "memo.md").write_text("[x](bd:notes:p1.c1:abcd)\n", encoding="utf-8")
    result = invoke("locate", "memo.md")
    assert result.exit_code == 1
    assert "run `backdraft init`" in result.stderr


def test_the_registry_is_found_from_the_documents_directory(
    project: Path, monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory
) -> None:
    """`bind`'s discovery rule, so the two commands on one document agree on the registry."""
    _, cited = bound_under_s1(project, OCCUPANCY, COVERAGE, TAXES)
    ingest(write_source(project, LOBBY, OCCUPANCY, COVERAGE, TAXES))
    elsewhere = tmp_path_factory.mktemp("elsewhere")
    monkeypatch.chdir(elsewhere)

    result = invoke("locate", str(project / "memo.md"))

    assert result.exit_code == 0, result.output
    assert f"  ! moved: {cited[0]} — now at " in result.stdout


def test_the_top_level_help_lists_locate() -> None:
    assert "locate" in invoke("--help").stdout
