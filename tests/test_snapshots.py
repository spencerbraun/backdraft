"""Page snapshots: the local renderer, the capture at ingest, and the backfill.

Ingest captures page images for every PDF, not just the VLM path's, so the
keyless text-layer route produces the same artifact evidence. The properties
worth pinning are that it is *best-effort* (a machine without poppler ingests
exactly as before, and says so), that it never touches citation identity, and
that it leaves the VLM path's own stored pixels alone.

Rendering is faked here rather than shelled out to poppler, so the suite runs
the same everywhere; `test_real_poppler_renders_a_page` is the one test that
exercises the actual binary, and skips where it is absent.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from backdraft import cli
from backdraft.extract import snapshots
from backdraft.extract.base import ExtractedPage, PageImage, register
from backdraft.registry import Registry

runner = CliRunner()

HAS_POPPLER = shutil.which("pdftoppm") is not None and shutil.which("pdfinfo") is not None


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (cli.HOME_ENV, cli.SESSION_ENV, "BACKDRAFT_SNAPSHOT_QUALITY",
                 "BACKDRAFT_SNAPSHOT_MAX_HEIGHT"):
        monkeypatch.delenv(name, raising=False)


def _make_pdf(path: Path, pages: list[list[str]]) -> Path:
    """A tiny PDF with a text layer, so `pdf-text` has something to extract."""
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas

    sheet = canvas.Canvas(str(path), pagesize=letter)
    for lines in pages:
        text = sheet.beginText(72, 720)
        for line in lines:
            text.textLine(line)
        sheet.drawText(text)
        sheet.showPage()
    sheet.save()
    return path


@pytest.fixture
def report(tmp_path: Path) -> Path:
    return _make_pdf(
        tmp_path / "t12-audit.pdf",
        [["Debt service coverage ratio: 1.42x"], ["Net operating income: $4.1 million"]],
    )


class _Renderer:
    """Stands in for poppler: one blank page image per request, and a call log."""

    def __init__(self, *, height: int = 2112, width: int = 1632) -> None:
        self.height = height
        self.width = width
        self.calls: list[int] = []
        self.dpis: list[int] = []

    def __call__(self, path: str, *, dpi: int, fmt: str, first_page: int, last_page: int):
        from PIL import Image

        self.calls.append(first_page)
        self.dpis.append(dpi)
        return [Image.new("RGB", (self.width, self.height), "white")]


@pytest.fixture
def renderer(monkeypatch: pytest.MonkeyPatch) -> _Renderer:
    """Every `convert_from_path` in this module goes through the fake."""
    fake = _Renderer()
    _set_renderer(monkeypatch, fake)
    return fake


def _breaking(error: Exception):
    """A renderer that raises instead of rendering."""

    def convert_from_path(path: str, **kwargs):
        raise error

    return convert_from_path


def _uninstalled():
    """What pdf2image raises when poppler is not on the machine."""
    from pdf2image.exceptions import PDFInfoNotInstalledError

    return _breaking(
        PDFInfoNotInstalledError("Unable to get page count. Is poppler installed?")
    )


def _set_renderer(monkeypatch: pytest.MonkeyPatch, renderer) -> None:
    """Point `pdf2image.convert_from_path` at `renderer` for the rest of the test."""
    import pdf2image

    monkeypatch.setattr(pdf2image, "convert_from_path", renderer)


@pytest.fixture
def no_poppler(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_renderer(monkeypatch, _uninstalled())


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """An initialized project, with cwd inside it."""
    monkeypatch.chdir(tmp_path)
    runner.invoke(cli.app, ["init"])
    return tmp_path


# ---- the renderer -----------------------------------------------------------


def test_render_yields_one_webp_per_page(report: Path, renderer: _Renderer) -> None:
    rendered = list(snapshots.render(report, [1, 2]))
    assert [number for number, _ in rendered] == [1, 2]
    assert renderer.calls == [1, 2]  # one poppler call per page, bounded memory
    assert all(image.format == "webp" and image.data for _, image in rendered)


def test_render_downscales_to_the_height_budget(report: Path, renderer: _Renderer) -> None:
    (_, image), = snapshots.render(report, [1])
    assert image.height == 1056  # the 2112px render, halved
    assert image.width == 816  # aspect preserved


def test_render_honors_the_budget_config(report: Path, renderer: _Renderer) -> None:
    (_, image), = snapshots.render(report, [1], config={"snapshot_max_height": "400"})
    assert image.height == 400


def test_a_render_under_the_budget_is_left_alone(
    report: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _set_renderer(monkeypatch, _Renderer(height=500, width=400))
    (_, image), = snapshots.render(report, [1])
    assert (image.width, image.height) == (400, 500)


def test_missing_poppler_names_the_install(report: Path, no_poppler: None) -> None:
    with pytest.raises(snapshots.SnapshotError, match="brew install poppler"):
        list(snapshots.render(report, [1]))


def test_missing_render_deps_name_the_reinstall(
    report: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A broken install is a different gap from a missing poppler, and says so:
    installing poppler would not fix a pdf2image that will not import."""
    import builtins

    real_import = builtins.__import__

    def blocked(name: str, *args, **kwargs):
        if name.split(".")[0] in ("PIL", "pdf2image"):
            raise ImportError(f"No module named {name!r}")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", blocked)
    with pytest.raises(snapshots.SnapshotError, match="reinstall backdraft"):
        list(snapshots.render(report, [1]))


def test_a_render_failure_names_the_page(report: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _set_renderer(monkeypatch, _breaking(ValueError("bad xref")))
    with pytest.raises(snapshots.SnapshotError, match=r"could not render page 2"):
        list(snapshots.render(report, [2]))


def test_a_page_poppler_will_not_return_is_an_error(
    report: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _set_renderer(monkeypatch, lambda path, **kwargs: [])
    with pytest.raises(snapshots.SnapshotError, match="no page 9"):
        list(snapshots.render(report, [9]))


@pytest.mark.parametrize(
    "config, expected",
    [
        ({}, 200),
        ({"dpi": "300"}, 300),
        ({"dpi": 300}, 300),
        ({"dpi": ""}, 200),  # an unset --config value is not a request for 0 dpi
        ({"dpi": "0"}, 1),  # floored, so poppler is never handed a nonsense dpi
        ({"dpi": "glossy"}, 200),  # a typo degrades to the default, never crashes
    ],
)
def test_dpi_resolves_from_the_config(config: dict, expected: int) -> None:
    assert snapshots.dpi_for(config) == expected


def test_the_dpi_config_reaches_poppler(report: Path, renderer: _Renderer) -> None:
    list(snapshots.render(report, [1], config={"dpi": "144"}))
    assert renderer.dpis == [144]


def test_an_explicit_dpi_beats_the_config(report: Path, renderer: _Renderer) -> None:
    """`--dpi` is the flag on `snapshot-pages`; config is what `ingest` carries."""
    list(snapshots.render(report, [1], dpi=90, config={"dpi": "144"}))
    assert renderer.dpis == [90]


def test_both_pdf_paths_share_one_encoder() -> None:
    """The vlm extractor and this module must store identical pixels for the
    same page, so the encoding lives in one place and vlm imports it. A second
    copy growing back in vlm.py is the regression this catches."""
    from backdraft.extract import vlm

    assert (vlm.fit, vlm.encode, vlm.dpi_for) == (
        snapshots.fit, snapshots.encode, snapshots.dpi_for
    )
    assert vlm.DEFAULT_DPI == snapshots.DEFAULT_DPI


def test_fit_and_encode_are_the_budget(report: Path) -> None:
    from PIL import Image

    page = Image.new("RGB", (1632, 2112), "white")
    fitted = snapshots.fit(page, 1056)
    assert (fitted.width, fitted.height) == (816, 1056)
    assert snapshots.fit(fitted, 1056) is fitted  # already under budget, untouched
    snapshot = snapshots.encode(fitted, 85)
    assert (snapshot.format, snapshot.width, snapshot.height) == ("webp", 816, 1056)
    assert snapshot.data[:4] == b"RIFF"


@pytest.mark.skipif(not HAS_POPPLER, reason="poppler is not installed on this machine")
def test_real_poppler_renders_a_page(report: Path) -> None:
    (number, image), = snapshots.render(report, [1])
    assert number == 1
    assert image.format == "webp"
    assert image.height == 1056  # US Letter at 200dpi, downscaled to the budget
    assert image.data[:4] == b"RIFF"  # a real WebP, not a placeholder


# ---- capture into the registry ----------------------------------------------


def test_capture_stores_every_page(root: Path, report: Path, renderer: _Renderer) -> None:
    registry = Registry.open(root)
    try:
        document = registry.ingest(report, extractor="pdf-text")
        stored = list(snapshots.capture(registry, document.slug, report))
        assert [number for number, _ in stored] == [1, 2]
        assert registry.page_image(document.slug, 1).format == "webp"
        assert registry.page_image(document.slug, 2).width == 816
    finally:
        registry.close()


def test_capture_without_an_extraction_is_an_error(root: Path, report: Path) -> None:
    registry = Registry.open(root)
    try:
        with pytest.raises(snapshots.SnapshotError, match="no current extraction"):
            list(snapshots.capture(registry, "nothing-here", report))
    finally:
        registry.close()


# ---- capture at ingest ------------------------------------------------------


def test_ingest_captures_page_snapshots(project: Path, renderer: _Renderer) -> None:
    _make_pdf(project / "t12.pdf", [["Occupancy closed at 91.4%"], ["Cap rate 5.75%"]])
    result = runner.invoke(cli.app, ["ingest", "t12.pdf"])
    assert result.exit_code == 0, result.output
    registry = Registry.open(project)
    try:
        assert registry.page_image("t12", 1) is not None
        assert registry.page_image("t12", 2) is not None
    finally:
        registry.close()


def test_ingest_without_poppler_succeeds_and_names_the_backfill(
    project: Path, no_poppler: None
) -> None:
    _make_pdf(project / "t12.pdf", [["Occupancy closed at 91.4%"]])
    result = runner.invoke(cli.app, ["ingest", "t12.pdf"])
    assert result.exit_code == 0, result.output
    assert "t12  t12.pdf  pdf  1 page" in result.output
    assert "snapshot-pages" in result.output
    assert "brew install poppler" in result.output
    assert "t12" in result.output.split("Backfill later")[1]
    registry = Registry.open(project)
    try:
        assert registry.page_image("t12", 1) is None
    finally:
        registry.close()


def test_the_note_names_every_document_that_missed(project: Path, no_poppler: None) -> None:
    _make_pdf(project / "t12.pdf", [["Occupancy closed at 91.4%"]])
    _make_pdf(project / "rent-roll.pdf", [["Unit 4B leases at $2,400"]])
    result = runner.invoke(cli.app, ["ingest", "t12.pdf", "rent-roll.pdf"])
    assert result.exit_code == 0, result.output
    tail = result.output.split("Backfill later")[1]
    assert "t12" in tail and "rent-roll" in tail
    assert result.output.count("note: page images not captured") == 1  # one line, once


def test_distinct_failures_are_reported_separately(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Slugs are grouped under the reason they actually failed for, not the first one."""
    _make_pdf(project / "t12.pdf", [["Occupancy closed at 91.4%"]])
    _make_pdf(project / "rent-roll.pdf", [["Unit 4B leases at $2,400"]])
    uninstalled = _uninstalled()

    def convert_from_path(path: str, **kwargs):
        if "rent-roll" in path:
            raise ValueError("bad xref")
        return uninstalled(path, **kwargs)

    _set_renderer(monkeypatch, convert_from_path)
    result = runner.invoke(cli.app, ["ingest", "t12.pdf", "rent-roll.pdf"])
    assert result.exit_code == 0, result.output
    notes = [line for line in result.output.splitlines() if "page images not captured" in line]
    assert len(notes) == 2
    poppler, = [line for line in notes if "brew install poppler" in line]
    xref, = [line for line in notes if "bad xref" in line]
    assert poppler.endswith("for: t12.")
    assert xref.endswith("for: rent-roll.")


def test_ingest_carries_the_render_budget_into_the_capture(
    project: Path, renderer: _Renderer
) -> None:
    """`--config` reaches the capture, so one flag means the same thing on both
    PDF paths rather than only on the one that calls a model."""
    _make_pdf(project / "t12.pdf", [["Occupancy closed at 91.4%"]])
    result = runner.invoke(
        cli.app,
        ["ingest", "t12.pdf", "--config", "dpi=144",
         "--config", "snapshot_max_height=400"],
    )
    assert result.exit_code == 0, result.output
    assert renderer.dpis == [144]
    registry = Registry.open(project)
    try:
        assert registry.page_image("t12", 1).height == 400
    finally:
        registry.close()


def test_a_non_pdf_ingest_never_renders(project: Path, renderer: _Renderer) -> None:
    (project / "memo.md").write_text("Occupancy closed at 91.4%.\n", encoding="utf-8")
    result = runner.invoke(cli.app, ["ingest", "memo.md"])
    assert result.exit_code == 0, result.output
    assert renderer.calls == []


class _Snapshotting:
    """A PDF extractor that supplies its own page images, as the VLM path does."""

    name = "snapshot-test-vlm"
    version = "1"
    deterministic = True

    def can_handle(self, path: Path, media_type: str) -> bool:
        return False  # explicit `--extractor` only, never `auto`

    def extract(self, path: Path, config: dict):
        yield ExtractedPage(
            number=1, kind="page", text="Occupancy closed at 91.4%.",
            image=PageImage(data=b"MODEL-SAW-THIS", format="webp", width=816, height=1056),
        )


register(_Snapshotting())


def test_ingest_leaves_extractor_supplied_images_alone(
    project: Path, renderer: _Renderer
) -> None:
    _make_pdf(project / "t12.pdf", [["Occupancy closed at 91.4%"]])
    result = runner.invoke(
        cli.app, ["ingest", "t12.pdf", "--extractor", "snapshot-test-vlm"]
    )
    assert result.exit_code == 0, result.output
    assert renderer.calls == []  # the pixels the model was shown are the receipt
    registry = Registry.open(project)
    try:
        assert registry.page_image("t12", 1).data == b"MODEL-SAW-THIS"
    finally:
        registry.close()


def _tokens(registry: Registry, slug: str) -> list[str]:
    return [
        anchor.token
        for page in registry.pages(slug)
        for anchor in registry.anchors_for_page(slug, page.number)
    ]


def test_capturing_snapshots_never_moves_a_token(
    tmp_path: Path, report: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The whole point of hooking after extraction: identity cannot notice."""
    minted = []
    for name, render, snapshotted in (
        ("with", _Renderer(), True),
        ("without", _uninstalled(), False),
    ):
        root = tmp_path / name
        root.mkdir()
        shutil.copy(report, root / report.name)
        monkeypatch.chdir(root)
        runner.invoke(cli.app, ["init"])
        _set_renderer(monkeypatch, render)
        assert runner.invoke(cli.app, ["ingest", report.name]).exit_code == 0
        registry = Registry.open(root)
        try:
            assert (registry.page_image("t12-audit", 1) is not None) is snapshotted
            minted.append(_tokens(registry, "t12-audit"))
        finally:
            registry.close()
    assert minted[0] == minted[1]


# ---- the backfill command ---------------------------------------------------


def test_snapshot_pages_backfills(project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Ingested on a machine without poppler, snapshotted later on one with it.

    The order is the whole test, so the renderer is swapped between the two
    commands rather than left to fixture ordering.
    """
    _make_pdf(project / "t12.pdf", [["Occupancy closed at 91.4%"], ["Cap rate 5.75%"]])
    _set_renderer(monkeypatch, _uninstalled())
    runner.invoke(cli.app, ["ingest", "t12.pdf"])
    registry = Registry.open(project)
    try:
        assert registry.page_image("t12", 1) is None  # the gap the backfill closes
    finally:
        registry.close()

    _set_renderer(monkeypatch, _Renderer())
    result = runner.invoke(cli.app, ["snapshot-pages", "t12"])
    assert result.exit_code == 0, result.output
    assert "t12  p1  816x1056" in result.output
    assert "stored 2 page snapshot(s)" in result.output
    registry = Registry.open(project)
    try:
        assert registry.page_image("t12", 1) is not None
        assert registry.page_image("t12", 2) is not None
    finally:
        registry.close()


def test_snapshot_pages_finds_a_moved_source(project: Path, renderer: _Renderer) -> None:
    _make_pdf(project / "t12.pdf", [["Occupancy closed at 91.4%"]])
    runner.invoke(cli.app, ["ingest", "t12.pdf"])
    (project / "t12.pdf").rename(project / "archive.pdf")
    missing = runner.invoke(cli.app, ["snapshot-pages", "t12"])
    assert missing.exit_code == 1
    assert "pass --file" in missing.output
    found = runner.invoke(cli.app, ["snapshot-pages", "t12", "--file", "archive.pdf"])
    assert found.exit_code == 0, found.output


def test_snapshot_pages_honors_the_dpi_flag(project: Path, renderer: _Renderer) -> None:
    _make_pdf(project / "t12.pdf", [["Occupancy closed at 91.4%"]])
    runner.invoke(cli.app, ["ingest", "t12.pdf"])
    result = runner.invoke(cli.app, ["snapshot-pages", "t12", "--dpi", "120"])
    assert result.exit_code == 0, result.output
    assert renderer.dpis == [snapshots.DEFAULT_DPI, 120]  # ingest's, then the flag's


def test_snapshot_pages_rejects_an_unknown_slug(project: Path) -> None:
    result = runner.invoke(cli.app, ["snapshot-pages", "nope"])
    assert result.exit_code == 1
    assert "no document with slug 'nope'" in result.output


def test_snapshot_pages_rejects_a_non_pdf(project: Path) -> None:
    (project / "memo.md").write_text("Occupancy closed at 91.4%.\n", encoding="utf-8")
    runner.invoke(cli.app, ["ingest", "memo.md"])
    result = runner.invoke(cli.app, ["snapshot-pages", "memo"])
    assert result.exit_code == 1
    assert "not a PDF" in result.output


def test_snapshot_pages_without_poppler_exits_clean(project: Path, no_poppler: None) -> None:
    """Exit 1 with the install line — never a traceback out of pdf2image."""
    _make_pdf(project / "t12.pdf", [["Occupancy closed at 91.4%"]])
    runner.invoke(cli.app, ["ingest", "t12.pdf"])
    result = runner.invoke(cli.app, ["snapshot-pages", "t12"])
    assert result.exit_code == 1
    assert result.exception is None or isinstance(result.exception, SystemExit)
    assert "apt install poppler-utils" in result.output
