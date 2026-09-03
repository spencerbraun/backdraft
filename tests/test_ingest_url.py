"""URL sources, end to end: fetch, snapshot, cite, re-fetch, drift.

Everything here runs against `tests/test_fetch.py`'s loopback server, so the
suite stays network-free while the transport stays real. The invariant under
test is the one the decision row states: a source's identity is the sha256 of
the bytes fetched at ingest time, and the URL is provenance riding alongside —
so a page that changed comes back as a new generation of the same document, and
the citations written against the old one report `drifted` rather than
vanishing.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from backdraft import cli, fetch
from backdraft.registry import Registry, slug_for

runner = CliRunner()

pytest_plugins = ["test_fetch"]  # the `serve` fixture and its handler

PAGE = b"""<!doctype html>
<html><head><title>Bridgeview Q4</title></head><body>
<h1>Bridgeview Holdings</h1>
<p>Net operating income for the trailing twelve months was $4.1 million, up
eleven percent year over year. The increase is concentrated in the two suburban
assets; the urban core properties were flat, and one of them lost an anchor
tenant in February whose space has not yet been backfilled.</p>
</body></html>
"""

REVISED = PAGE.replace(b"$4.1 million", b"$4.4 million")

CSV = b"Unit,Tenant,Rent\n101,Acme Corp,2400\n102,Beta LLC,1875.5\n"


@pytest.fixture(autouse=True)
def no_home_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(cli.HOME_ENV, raising=False)
    monkeypatch.delenv(cli.SESSION_ENV, raising=False)


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    runner.invoke(cli.app, ["init"])
    return tmp_path


def _page_routes(body: bytes = PAGE) -> dict:
    return {"/q4": (200, "text/html; charset=utf-8", body)}


def _export(root: Path) -> dict:
    with Registry.open(root) as registry:
        return registry.export_json()


def _document(root: Path, slug: str) -> dict:
    return next(d for d in _export(root)["documents"] if d["slug"] == slug)


def _first_token(read_output: str) -> str:
    """The first chunk token the gate printed. It comes bracketed, on its own line."""
    return next(
        line.strip("[]") for line in read_output.splitlines() if line.startswith("[bd:")
    )


# ---- capture ----------------------------------------------------------------


def test_a_url_ingests_as_a_document_named_by_its_path(project: Path, serve) -> None:
    base = serve(_page_routes())
    result = runner.invoke(cli.app, ["ingest", f"{base}/q4"])
    assert result.exit_code == 0, result.output
    assert f"q4  {base}/q4  html  1 page" in result.output


def test_ingest_names_a_fetched_page_by_its_url_not_its_staging_file(
    project: Path, serve
) -> None:
    """`q4.html` is a name `fetch.filename_for` invented for a temporary file.

    It is the first thing an agent sees about a fetched source, so it is the
    first place the fictional name must not appear.
    """
    base = serve(_page_routes())
    output = runner.invoke(cli.app, ["ingest", f"{base}/q4"]).output
    assert "q4.html" not in output


def test_the_origin_and_the_fetch_time_are_stored_as_document_meta(
    project: Path, serve
) -> None:
    base = serve(_page_routes())
    runner.invoke(cli.app, ["ingest", f"{base}/q4"])
    meta = _document(project, "q4")["meta"]
    assert meta["url"] == f"{base}/q4"
    assert meta["fetched_at"].endswith("Z")


def test_the_document_records_the_url_as_its_path_not_the_staging_file(
    project: Path, serve
) -> None:
    """The staged file is a temporary directory that is gone by now."""
    base = serve(_page_routes())
    runner.invoke(cli.app, ["ingest", f"{base}/q4"])
    assert _document(project, "q4")["path"] == f"{base}/q4"


def test_ls_shows_where_a_fetched_source_came_from(project: Path, serve) -> None:
    base = serve(_page_routes())
    runner.invoke(cli.app, ["ingest", f"{base}/q4"])
    listed = runner.invoke(cli.app, ["ls"]).output
    assert f"q4\t{base}/q4\thtml\t1 page" in listed
    assert "q4.html" not in listed


def test_ls_and_read_name_a_fetched_source_the_same_way(project: Path, serve) -> None:
    """One registry, one name. `ls` and the gate's list both go through
    `kernel.model.source_name`; this pins them together rather than pinning
    either."""
    base = serve(_page_routes())
    runner.invoke(cli.app, ["ingest", f"{base}/q4"])
    listed = runner.invoke(cli.app, ["ls"]).output
    read = runner.invoke(cli.app, ["read"]).output
    assert f"{base}/q4" in listed and f"{base}/q4" in read
    assert "q4.html" not in listed and "q4.html" not in read


def test_a_file_ingest_prints_the_ls_line_it_always_did(project: Path, note: Path) -> None:
    """A registry of files prints what it always did: four fields, filename
    second. The origin replaces that field where there is one; it never joins
    it as a fifth."""
    runner.invoke(cli.app, ["ingest", str(note)])
    line = runner.invoke(cli.app, ["ls"]).output.strip()
    assert line == "quarterly-notes\tquarterly-notes.md\ttext\t1 page"


def test_an_exported_file_document_carries_no_meta_key(project: Path, note: Path) -> None:
    runner.invoke(cli.app, ["ingest", str(note)])
    assert "meta" not in _document(project, "quarterly-notes")


# ---- the slug a URL is given ------------------------------------------------


def _slugs(root: Path) -> list[str]:
    return [document["slug"] for document in _export(root)["documents"]]


def test_two_sites_index_pages_get_two_slugs_that_name_their_sites() -> None:
    """The failure this rule exists for, decided where it is decided.

    Both pages stage as `index.html` under the old stem rule, so the second
    became `index-2` — a handle every token in the draft then carries, naming
    nothing a reader can act on. No server here on purpose: the slug is settled
    by the address, before any bytes exist, and the loopback fixture cannot
    offer two hostnames to show it with.
    """
    slugs = [
        slug_for(fetch.filename_for(url, "text/html"))
        for url in (
            "https://a.example/reports/2025/index.html",
            "https://b.example/docs/index.html",
        )
    ]
    assert slugs == ["a-example-index", "b-example-index"]


def test_a_path_that_names_its_page_keeps_naming_it(project: Path, serve) -> None:
    """The common case does not get uglier to fix the collision case."""
    base = serve({"/reports/q4-2025": (200, "text/html", PAGE)})
    runner.invoke(cli.app, ["ingest", f"{base}/reports/q4-2025"])
    assert _slugs(project) == ["q4-2025"]


def test_a_bare_numeric_id_is_named_by_its_host(project: Path, serve) -> None:
    """`12345` is a slug that says nothing; the site it came from says something."""
    base = serve({"/articles/12345": (200, "text/html", PAGE)})
    runner.invoke(cli.app, ["ingest", f"{base}/articles/12345"])
    assert _slugs(project) == ["127-0-0-1-12345"]


def test_a_url_with_an_empty_path_falls_back_to_the_host(project: Path, serve) -> None:
    base = serve({"/": (200, "text/html", PAGE)})
    runner.invoke(cli.app, ["ingest", base])
    assert _slugs(project) == ["127-0-0-1"]


def test_two_pages_colliding_after_the_new_rule_still_dedupe(project: Path, serve) -> None:
    """The host is a better stem, not a unique one — `-2` stays the backstop."""
    base = serve(
        {
            "/a/index.html": (200, "text/html", PAGE),
            "/b/index.html": (200, "text/html", PAGE.replace(b"$4.1", b"$4.7")),
        }
    )
    result = runner.invoke(cli.app, ["ingest", f"{base}/a/index.html", f"{base}/b/index.html"])
    assert result.exit_code == 0, result.output
    assert _slugs(project) == ["127-0-0-1-index", "127-0-0-1-index-2"]


# ---- the gate behaves as it does for any other text source ------------------


def test_a_fetched_page_is_readable_and_its_tokens_bind(project: Path, serve) -> None:
    base = serve(_page_routes())
    runner.invoke(cli.app, ["ingest", f"{base}/q4"])
    read = runner.invoke(cli.app, ["read", "q4", "p1", "--session", "s-web"])
    assert read.exit_code == 0, read.output
    assert "bd:q4:p1.c1:" in read.output

    token = _first_token(read.output)
    doc = project / "memo.md"
    doc.write_text(f"[NOI rose eleven percent]({token}).\n", encoding="utf-8")
    bound = runner.invoke(cli.app, ["bind", str(doc), "--session", "s-web"])
    assert bound.exit_code == 0, bound.output


def test_the_bound_markdown_names_a_fetched_source_the_way_ls_does(
    project: Path, serve
) -> None:
    """Every surface that names a source gives one answer, and the bound
    markdown is the surface where it matters most: it is what travels into a
    pull request or an email, where the HTML artifact cannot follow. It went
    through `Document.filename` until 2026-09-03 and so called a fetched page
    by the staging file `fetch.filename_for` invented for it."""
    base = serve(_page_routes())
    runner.invoke(cli.app, ["ingest", f"{base}/q4"])
    read = runner.invoke(cli.app, ["read", "q4", "p1", "--session", "s-web"])
    token = _first_token(read.output)
    doc = project / "memo.md"
    doc.write_text(f"[NOI rose eleven percent]({token}).\n", encoding="utf-8")
    runner.invoke(cli.app, ["bind", str(doc), "--session", "s-web", "--bound"])

    bound = (project / "memo.bound.md").read_text(encoding="utf-8")
    listed = runner.invoke(cli.app, ["ls"]).output
    assert f"{base}/q4" in bound and f"{base}/q4" in listed
    assert "q4.html" not in bound


def test_a_backfill_proposal_names_a_fetched_source_the_same_way(
    project: Path, serve
) -> None:
    """Backfill's open list is the second place the markdown names a document,
    and it reads the same owner — so the fix is one, not two."""
    base = serve(_page_routes())
    runner.invoke(cli.app, ["ingest", f"{base}/q4"])
    doc = project / "memo.md"
    doc.write_text("NOI for the trailing twelve months was $4.1 million.\n", encoding="utf-8")
    runner.invoke(cli.app, ["bind", str(doc), "--mode", "backfill", "--bound"])

    bound = (project / "memo.bound.md").read_text(encoding="utf-8")
    assert "proposed: `bd:q4:" in bound
    assert f"{base}/q4" in bound
    assert "q4.html" not in bound


def test_search_finds_a_fetched_page(project: Path, serve) -> None:
    base = serve(_page_routes())
    runner.invoke(cli.app, ["ingest", f"{base}/q4"])
    found = runner.invoke(cli.app, ["search", "suburban"])
    assert found.exit_code == 0
    assert "bd:q4:" in found.output


# ---- re-fetch and drift -----------------------------------------------------


def test_re_fetching_an_unchanged_page_makes_no_new_generation(
    project: Path, serve
) -> None:
    base = serve(_page_routes())
    runner.invoke(cli.app, ["ingest", f"{base}/q4"])
    first = _document(project, "q4")
    runner.invoke(cli.app, ["ingest", f"{base}/q4"])
    second = _document(project, "q4")

    assert len(second["extractions"]) == 1
    assert second["extractions"][0]["id"] == first["extractions"][0]["id"]


def test_re_fetching_an_unchanged_page_still_moves_the_fetch_time(
    project: Path, serve
) -> None:
    """`fetched_at` is when the page was last confirmed to say this."""
    routes = _page_routes()
    base = serve(routes)
    runner.invoke(cli.app, ["ingest", f"{base}/q4"])
    first = _document(project, "q4")["meta"]["fetched_at"]
    runner.invoke(cli.app, ["ingest", f"{base}/q4"])
    assert _document(project, "q4")["meta"]["fetched_at"] >= first


def test_a_changed_page_is_a_new_generation_of_the_same_document(
    project: Path, serve
) -> None:
    routes = _page_routes()
    base = serve(routes)
    runner.invoke(cli.app, ["ingest", f"{base}/q4"])
    routes["/q4"] = (200, "text/html; charset=utf-8", REVISED)
    runner.invoke(cli.app, ["ingest", f"{base}/q4"])

    assert len(_export(project)["documents"]) == 1
    generations = _document(project, "q4")["extractions"]
    assert len(generations) == 2
    assert [g["is_current"] for g in generations] == [False, True]


def test_a_citation_into_the_page_as_it_was_reports_drifted(
    project: Path, serve
) -> None:
    routes = _page_routes()
    base = serve(routes)
    runner.invoke(cli.app, ["ingest", f"{base}/q4"])
    read = runner.invoke(cli.app, ["read", "q4", "p1", "--session", "s-web"])
    token = _first_token(read.output)

    routes["/q4"] = (200, "text/html; charset=utf-8", REVISED)
    runner.invoke(cli.app, ["ingest", f"{base}/q4"])

    doc = project / "memo.md"
    doc.write_text(f"[NOI was $4.1 million]({token}).\n", encoding="utf-8")
    bound = runner.invoke(cli.app, ["bind", str(doc), "--session", "s-web"])
    assert bound.exit_code == cli.EXIT_UNRESOLVED
    assert "drifted" in bound.output


# ---- content type picks the extractor ---------------------------------------


def test_the_served_content_type_selects_the_extractor(project: Path, serve) -> None:
    """A URL with no file extension serving CSV still lands on the csv path."""
    base = serve({"/rent-roll": (200, "text/csv", CSV)})
    result = runner.invoke(cli.app, ["ingest", f"{base}/rent-roll"])
    assert f"rent-roll  {base}/rent-roll  csv" in result.output
    assert _document(project, "rent-roll")["extractions"][0]["extractor"] == "csv"


def test_a_pdf_served_from_a_url_takes_the_pdf_path(project: Path, tmp_path: Path, serve) -> None:
    """A binary type routes through the staged file's suffix like any other."""
    from test_snapshots import _make_pdf

    pdf = _make_pdf(tmp_path / "t12.pdf", [["Debt service coverage ratio: 1.42x"]])
    base = serve({"/download": (200, "application/pdf", pdf.read_bytes())})
    result = runner.invoke(cli.app, ["ingest", f"{base}/download"])
    assert result.exit_code == 0, result.output
    assert f"download  {base}/download  pdf  1 page" in result.output
    assert _document(project, "download")["extractions"][0]["extractor"] == "pdf-text"


def test_an_unlabelled_body_is_read_as_a_page(project: Path, serve) -> None:
    """The thing at the end of an http URL with no type and no suffix is a page."""
    base = serve({"/thing": (200, "", b"<p>Just a paragraph.</p>")})
    runner.invoke(cli.app, ["ingest", f"{base}/thing"])
    assert _document(project, "thing")["media_type"] == "html"


# ---- failure ----------------------------------------------------------------


def test_a_failed_fetch_exits_1_with_the_status(project: Path, serve) -> None:
    base = serve({})
    result = runner.invoke(cli.app, ["ingest", f"{base}/gone"])
    assert result.exit_code == cli.EXIT_USAGE
    assert "HTTP 404" in result.output


def test_a_fetch_failure_names_the_url_once_and_says_what_to_do(
    project: Path, serve, ingest_failure_reason
) -> None:
    """The URL half of the same rule the file half follows: the `!` line leads
    with the source, so the reason says what happened and what to do instead of
    saying the URL again."""
    base = serve({})
    url = f"{base}/gone"
    result = runner.invoke(cli.app, ["ingest", url])
    reason = ingest_failure_reason(result, url)
    assert reason.startswith("the server returned HTTP 404")
    assert "save the page from a browser" in reason
    assert url not in reason


def test_an_empty_body_is_a_failure_rather_than_an_empty_document(
    project: Path, serve, ingest_failure_reason
) -> None:
    """A 200 with nothing in it is the shape a JavaScript-rendered page takes
    here, and it used to land as a document with no text to cite."""
    base = serve({"/spa": (200, "text/html", b"")})
    url = f"{base}/spa"
    result = runner.invoke(cli.app, ["ingest", url])
    assert result.exit_code == cli.EXIT_USAGE
    reason = ingest_failure_reason(result, url)
    assert "empty body" in reason and "JavaScript" in reason
    with Registry.open(project) as registry:
        assert registry.documents() == []


def test_a_file_url_is_refused_by_name(project: Path) -> None:
    result = runner.invoke(cli.app, ["ingest", "file:///etc/hosts"])
    assert result.exit_code == cli.EXIT_USAGE
    assert "ingest reads http and https" in result.output


def test_slug_still_names_exactly_one_source(project: Path, serve) -> None:
    base = serve(_page_routes())
    result = runner.invoke(
        cli.app, ["ingest", f"{base}/q4", f"{base}/q4", "--slug", "only-one"]
    )
    assert result.exit_code == cli.EXIT_USAGE
    assert "pass one source" in result.output


def test_a_slug_can_be_given_to_a_fetched_page(project: Path, serve) -> None:
    base = serve(_page_routes())
    runner.invoke(cli.app, ["ingest", f"{base}/q4", "--slug", "bridgeview-web"])
    assert _document(project, "bridgeview-web")["meta"]["url"] == f"{base}/q4"


# ---- files and URLs in one run ----------------------------------------------


def test_a_run_can_mix_files_and_urls(project: Path, serve, note: Path) -> None:
    base = serve(_page_routes())
    result = runner.invoke(cli.app, ["ingest", str(note), f"{base}/q4"])
    assert result.exit_code == 0, result.output
    slugs = {d["slug"] for d in _export(project)["documents"]}
    assert slugs == {"quarterly-notes", "q4"}


def test_the_same_page_under_two_urls_stays_one_document(project: Path, serve) -> None:
    """`documents.sha256` is UNIQUE: identical bytes are one document, whatever
    they were called on the way in."""
    base = serve({"/a": (200, "text/html", PAGE), "/b": (200, "text/html", PAGE)})
    runner.invoke(cli.app, ["ingest", f"{base}/a"])
    runner.invoke(cli.app, ["ingest", f"{base}/b"])
    assert len(_export(project)["documents"]) == 1


def test_a_saved_html_file_ingests_without_any_url(project: Path, tmp_path: Path) -> None:
    """The same extractor, reached the ordinary way."""
    path = tmp_path / "saved.html"
    path.write_bytes(PAGE)
    result = runner.invoke(cli.app, ["ingest", str(path)])
    assert "saved  saved.html  html" in result.output
    assert "meta" not in _document(project, "saved")


# ---- the artifact links back ------------------------------------------------


def _cite_the_page(project: Path, base: str) -> Path:
    """Ingest the page, read it, and write a memo citing its first chunk."""
    runner.invoke(cli.app, ["ingest", f"{base}/q4"])
    read = runner.invoke(cli.app, ["read", "q4", "p1", "--session", "s-web"])
    doc = project / "memo.md"
    doc.write_text(
        f"# Bridgeview\n\n[NOI rose eleven percent]({_first_token(read.output)}).\n",
        encoding="utf-8",
    )
    result = runner.invoke(cli.app, ["bind", str(doc), "--session", "s-web"])
    assert result.exit_code == 0, result.output
    return doc


def test_the_artifact_links_back_to_the_page_it_quoted(project: Path, serve) -> None:
    """The receipt is frozen; the link is how a reader asks whether it still
    says this. Both the source list and the cited claim's card carry it."""
    base = serve(_page_routes())
    doc = _cite_the_page(project, base)
    result = runner.invoke(cli.app, ["render", str(doc), "--to", "html"])
    assert result.exit_code == 0, result.output
    page = (project / "memo.backdraft.html").read_text(encoding="utf-8")

    url = f"{base}/q4"
    assert f'<a class="origin" href="{url}">{url}</a>' in page
    listing = page.split('<ul class="srclist">', 1)[1].split("</ul>", 1)[0]
    assert f'href="{url}"' in listing
    card = page.split('<article class="card"', 1)[1]
    assert f'href="{url}"' in card.split("</article>", 1)[0]
    assert '<span class="asof">fetched 2' in page
    # the staged filename is not what the reader is shown
    assert "q4.html" not in listing


def test_the_markdown_projection_names_the_url_too(project: Path, serve) -> None:
    base = serve(_page_routes())
    doc = _cite_the_page(project, base)
    result = runner.invoke(cli.app, ["render", str(doc), "--to", "footnotes"])
    assert result.exit_code == 0, result.output
    text = (project / "memo.footnotes.md").read_text(encoding="utf-8")
    assert f"<{base}/q4> as of 2" in text


def test_a_file_source_renders_with_no_origin_at_all(project: Path, note: Path) -> None:
    """The addition is conditional: nothing about a file ingest changed."""
    runner.invoke(cli.app, ["ingest", str(note)])
    read = runner.invoke(cli.app, ["read", "quarterly-notes", "p1", "--session", "s-file"])
    doc = project / "memo.md"
    doc.write_text(f"# Memo\n\n[A claim]({_first_token(read.output)}).\n", encoding="utf-8")
    assert runner.invoke(cli.app, ["bind", str(doc), "--session", "s-file"]).exit_code == 0
    runner.invoke(cli.app, ["render", str(doc), "--to", "html"])
    page = (project / "memo.backdraft.html").read_text(encoding="utf-8")
    assert 'class="origin"' not in page
    assert 'class="asof"' not in page
