"""`backdraft doctor`: every optional capability, asked before a verb needs it.

The rule under test is that the report and the verb cannot disagree, so each
gap is asserted against the constant the verb itself prints — and that the
report is never a failure surface: exit 0 in every state, keys named and never
printed.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from backdraft import cli
from backdraft.bind.verify import entail as _entail_instance  # noqa: F401 - loads the module
from backdraft.extract import base, snapshots
from backdraft.registry import DIRECTORY, SCHEMA_VERSION
from backdraft.render import math as render_math

entail_module = sys.modules["backdraft.bind.verify.entail"]

runner = CliRunner()

HAS_POPPLER = shutil.which("pdftoppm") is not None and shutil.which("pdfinfo") is not None

FAKE_KEY = "sk-doctor-FAKE-0123456789abcdef"


@pytest.fixture(autouse=True)
def isolated(monkeypatch: pytest.MonkeyPatch) -> None:
    """No home override, session or real key leaks in from the developer's shell."""
    for name in (cli.HOME_ENV, cli.SESSION_ENV, "BACKDRAFT_VLM_API_KEY", "BACKDRAFT_ENTAIL_API_KEY"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    runner.invoke(cli.app, ["init"])
    return tmp_path


@pytest.fixture
def no_poppler(monkeypatch: pytest.MonkeyPatch) -> None:
    """What pdf2image raises, at the call the real render path makes first."""
    import pdf2image
    from pdf2image.exceptions import PDFInfoNotInstalledError

    def pdfinfo_from_path(*args, **kwargs):
        raise PDFInfoNotInstalledError("Unable to get page count. Is poppler installed?")

    def convert_from_path(*args, **kwargs):
        raise PDFInfoNotInstalledError("Unable to get page count. Is poppler installed?")

    monkeypatch.setattr(pdf2image, "pdfinfo_from_path", pdfinfo_from_path)
    monkeypatch.setattr(pdf2image, "convert_from_path", convert_from_path)


@pytest.fixture
def no_math(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(render_math, "_LOOKED", True)
    monkeypatch.setattr(render_math, "_CONVERTER", None)


@pytest.fixture
def with_math(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(render_math, "_LOOKED", True)
    monkeypatch.setattr(render_math, "_CONVERTER", lambda tex, **kwargs: "<math/>")


@pytest.fixture
def no_xls(monkeypatch: pytest.MonkeyPatch) -> None:
    """The extra uninstalled, through the real import failure rather than a stub."""
    monkeypatch.delitem(base.EXTRACTORS, "xls", raising=False)
    monkeypatch.delitem(sys.modules, "backdraft.extract.xls", raising=False)
    monkeypatch.setitem(sys.modules, "python_calamine", None)


@pytest.fixture
def everything_else_ready(monkeypatch: pytest.MonkeyPatch, with_math: None) -> None:
    """Every capability but the registry present, so a test can isolate that one."""
    monkeypatch.setattr(snapshots, "unavailable", lambda: None)
    monkeypatch.setattr(cli, "vlm_gap", lambda config=None: None)
    monkeypatch.setattr(entail_module, "unavailable", lambda: None)

    import backdraft.extract

    monkeypatch.setattr(backdraft.extract, "get", lambda name: object())


@pytest.fixture
def everything_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    no_poppler: None,
    no_math: None,
    no_xls: None,
) -> None:
    """Every capability gone, from a directory with no registry above it."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(entail_module, "anthropic", None)


def _line(output: str, name: str) -> str:
    """The status line a capability opens with."""
    lines = [line for line in output.splitlines() if line.startswith(name)]
    assert len(lines) == 1, output
    return lines[0]


def _block(output: str, name: str) -> str:
    """A capability's status line plus its indented continuation lines."""
    lines = output.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith(name))
    block = [lines[start]]
    for line in lines[start + 1 :]:
        if not line.startswith(" "):
            break
        block.append(line)
    return "\n".join(block)


# ---- poppler -----------------------------------------------------------------


def test_without_poppler_it_names_the_install_ingest_would_print(
    project: Path, no_poppler: None
) -> None:
    result = runner.invoke(cli.app, ["doctor"])
    assert result.exit_code == 0, result.output
    block = _block(result.output, "page images")
    assert "missing" in _line(result.output, "page images")
    assert snapshots.POPPLER_HINT in block
    assert snapshots.MISSING_EFFECT in block  # images missing, citations unaffected


def test_the_poppler_line_matches_ingests_note_word_for_word(
    project: Path, no_poppler: None
) -> None:
    """The acceptance check: what the report says is what ingest says when it happens."""
    from reportlab.pdfgen import canvas

    pdf = project / "t12.pdf"
    page = canvas.Canvas(str(pdf))
    page.drawString(72, 720, "Occupancy closed at 91.4%")
    page.save()
    ingested = runner.invoke(cli.app, ["ingest", "t12.pdf"])
    assert ingested.exit_code == 0, ingested.output
    reported = runner.invoke(cli.app, ["doctor"])
    for said in (snapshots.POPPLER_HINT, snapshots.MISSING_EFFECT):
        assert said in ingested.output
        assert said in reported.output


@pytest.mark.skipif(not HAS_POPPLER, reason="poppler is not installed on this machine")
def test_real_poppler_is_reported_ready() -> None:
    assert snapshots.unavailable() is None


def test_a_broken_pdf2image_is_named_as_such(monkeypatch: pytest.MonkeyPatch) -> None:
    """A missing poppler and a missing pdf2image have different fixes."""
    monkeypatch.setitem(sys.modules, "pdf2image", None)
    gap = snapshots.unavailable()
    assert gap is not None and "reinstall backdraft" in gap and "poppler" not in gap.split("(")[0]


# ---- math ---------------------------------------------------------------------


def test_without_math_it_says_formulas_render_verbatim(project: Path, no_math: None) -> None:
    result = runner.invoke(cli.app, ["doctor"])
    assert result.exit_code == 0, result.output
    block = _block(result.output, "math")
    assert "missing" in _line(result.output, "math")
    assert "verbatim" in block
    assert render_math.INSTALL in block


def test_with_math_nothing_is_missing_for_it(project: Path, with_math: None) -> None:
    result = runner.invoke(cli.app, ["doctor"])
    assert result.exit_code == 0, result.output
    assert "ready" in _line(result.output, "math")
    assert "verbatim" not in _block(result.output, "math")


def test_render_and_doctor_name_the_same_math_install() -> None:
    from backdraft.render.cli import VERBATIM_MATH_NOTE

    assert render_math.INSTALL in VERBATIM_MATH_NOTE


# ---- the registry -------------------------------------------------------------


def test_without_a_registry_it_runs_and_names_only_that(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, everything_else_ready: None
) -> None:
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(cli.app, ["doctor"])
    assert result.exit_code == 0, result.output
    assert "missing" in _line(result.output, "registry")
    assert "backdraft init" in _line(result.output, "registry")
    assert "[1 of 6 missing: registry." in result.output
    assert not (tmp_path / DIRECTORY).exists()  # read-only: nothing was created


def test_a_home_override_naming_an_empty_directory_is_reported_not_created(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(cli.HOME_ENV, str(tmp_path))
    result = runner.invoke(cli.app, ["doctor"])
    assert result.exit_code == 0, result.output
    assert cli.HOME_ENV in _line(result.output, "registry")
    assert not (tmp_path / DIRECTORY).exists()


def test_a_damaged_registry_is_a_gap_in_the_registrys_own_words(
    project: Path, everything_else_ready: None
) -> None:
    database = project / DIRECTORY / "registry.db"
    database.write_bytes(b"not a database, " * 64)
    result = runner.invoke(cli.app, ["doctor"])
    assert result.exit_code == 0, result.output
    line = _line(result.output, "registry")
    assert "missing" in line and "is not a registry backdraft can read" in line
    assert line.count(str(database)) == 1, line
    assert database.read_bytes() == b"not a database, " * 64  # nothing repaired


def test_a_registry_counts_its_documents(project: Path, note: Path) -> None:
    runner.invoke(cli.app, ["ingest", str(note)])
    result = runner.invoke(cli.app, ["doctor"])
    assert result.exit_code == 0, result.output
    line = _line(result.output, "registry")
    assert "ready" in line and "1 document(s)" in line


def test_all_ready_says_so(project: Path, everything_else_ready: None) -> None:
    result = runner.invoke(cli.app, ["doctor"])
    assert result.exit_code == 0, result.output
    assert "missing" not in result.output
    assert result.output.rstrip().endswith("[All 6 ready.]")


# ---- the other extras ---------------------------------------------------------


def test_without_xls_it_names_the_extra_ingest_would(project: Path, no_xls: None) -> None:
    with pytest.raises(base.ExtractionError) as raised:
        base.get("xls")
    result = runner.invoke(cli.app, ["doctor"])
    assert result.exit_code == 0, result.output
    assert str(raised.value) in _line(result.output, "legacy .xls")
    assert "backdraft[xls]" in result.output


def test_without_the_entail_extra_it_names_the_skip_bind_would_record(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(entail_module, "anthropic", None)
    result = runner.invoke(cli.app, ["doctor"])
    assert result.exit_code == 0, result.output
    assert entail_module.EXTRA_MISSING in _line(result.output, "entail check")
    assert "backdraft[entail]" in result.output


def test_without_an_entail_key_it_says_the_key_is_absent(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(entail_module, "anthropic", object())
    result = runner.invoke(cli.app, ["doctor"])
    block = _block(result.output, "entail check")
    assert entail_module.KEY_MISSING in block
    assert "BACKDRAFT_ENTAIL_API_KEY absent" in block


def test_the_vision_line_is_ingests_note(project: Path) -> None:
    from backdraft.extract import vlm_gap

    gap = vlm_gap()
    result = runner.invoke(cli.app, ["doctor"])
    assert gap is not None  # no key in this isolated environment
    assert gap in _line(result.output, "vision model")
    assert "BACKDRAFT_VLM_API_KEY absent" in _block(result.output, "vision model")


# ---- credentials ----------------------------------------------------------------


@pytest.mark.parametrize("where", ["env", "file"])
def test_a_key_is_named_set_and_its_value_never_appears(
    project: Path, monkeypatch: pytest.MonkeyPatch, where: str
) -> None:
    if where == "env":
        monkeypatch.setenv("BACKDRAFT_VLM_API_KEY", FAKE_KEY)
        monkeypatch.setenv("BACKDRAFT_ENTAIL_API_KEY", FAKE_KEY)
    else:
        (project / DIRECTORY / "env").write_text(
            f"BACKDRAFT_VLM_API_KEY={FAKE_KEY}\nBACKDRAFT_ENTAIL_API_KEY={FAKE_KEY}\n",
            encoding="utf-8",
        )
    result = runner.invoke(cli.app, ["doctor"])
    assert result.exit_code == 0, result.output
    assert FAKE_KEY not in result.output
    assert FAKE_KEY[-8:] not in result.output  # not even a masked tail
    assert "BACKDRAFT_VLM_API_KEY set" in result.output
    assert "BACKDRAFT_ENTAIL_API_KEY set" in result.output
    assert "ready" in _line(result.output, "vision model")


def test_ambient_keys_are_not_read(project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", FAKE_KEY)
    monkeypatch.setenv("ANTHROPIC_API_KEY", FAKE_KEY)
    result = runner.invoke(cli.app, ["doctor"])
    assert FAKE_KEY not in result.output
    assert "BACKDRAFT_VLM_API_KEY absent" in result.output


def test_it_exits_zero_with_everything_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    no_poppler: None,
    no_math: None,
    no_xls: None,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(entail_module, "anthropic", None)
    result = runner.invoke(cli.app, ["doctor"])
    assert result.exit_code == 0, result.output
    assert "[6 of 6 missing:" in result.output


# ---- the report, pinned -----------------------------------------------------------


ALL_MISSING_REPORT = """\
registry      missing  no .backdraft/ in {cwd} or any directory above it — `backdraft init` makes one
              costs    every verb but `init`, `skill` and `doctor` needs one: ingest, read, search, bind and render all stop here with exit 1.
page images   missing  poppler is not installed, so PDF pages cannot be rendered here (macOS: `brew install poppler`; Debian/Ubuntu: `apt install poppler-utils`)
              costs    ingest: PDFs land without page images. Citations and quotes are unaffected; artifacts just carry no cited-page image.
vision model  missing  Glossy or scanned PDFs extract better through a vision model: set BACKDRAFT_VLM_API_KEY in .backdraft/env.
              costs    ingest: `auto` reads a PDF's text layer, so a scan comes back thin, and an image cannot be ingested at all. A PDF with a text layer, and every other format, is unaffected.
              key      BACKDRAFT_VLM_API_KEY absent
legacy .xls   missing  extractor 'xls' is unavailable: legacy .xls needs: install 'backdraft[xls]'
              costs    ingest: an .xls workbook is refused; .xlsx and .csv are unaffected.
entail check  missing  the [entail] extra is not installed — `pip install 'backdraft[entail]'` (or `uv tool install 'backdraft[entail]'`)
              costs    bind: `--check entail` records every pair as `skip` with this reason; the bind still completes and its exit code is unaffected.
              key      BACKDRAFT_ENTAIL_API_KEY absent
math          missing  the `[math]` extra is not installed — `pip install 'backdraft[math]'` (or `uv tool install 'backdraft[math]'`)
              costs    render: LaTeX in a draft renders verbatim, as written, rather than as math. No citation is affected.
[6 of 6 missing: registry, page images, vision model, legacy .xls, entail check, math. Each `costs` line is what the verbs do without it; each verb still says so itself at the moment it matters.]
"""

ALL_READY_REPORT = """\
registry      ready    {cwd}/.backdraft, schema {schema}, 0 document(s)
page images   ready    poppler renders PDF pages for the artifact's cited-page view
vision model  ready    `auto` reads PDFs and images through the vision model, off this machine
              key      BACKDRAFT_VLM_API_KEY absent
legacy .xls   ready    ingest reads .xls workbooks, values only
entail check  ready    `bind --check entail` asks a model judge whether each snippet supports its claim
              key      BACKDRAFT_ENTAIL_API_KEY absent
math          ready    render turns LaTeX in a draft into MathML
[All 6 ready.]
"""


def test_the_report_with_everything_missing_is_pinned(everything_missing: None) -> None:
    result = runner.invoke(cli.app, ["doctor"])
    assert result.output == ALL_MISSING_REPORT.replace("{cwd}", str(Path.cwd()))


def test_the_report_with_everything_ready_is_pinned(
    project: Path, everything_else_ready: None
) -> None:
    result = runner.invoke(cli.app, ["doctor"])
    assert result.output == ALL_READY_REPORT.replace("{cwd}", str(project)).replace(
        "{schema}", str(SCHEMA_VERSION)
    )


# ---- --json -----------------------------------------------------------------------


def _doctor_json() -> dict[str, dict]:
    """The object at exit 0, parsed whole, its capabilities keyed by name."""
    result = runner.invoke(cli.app, ["doctor", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert set(payload) == {"format", "capabilities"}
    assert payload["format"] == "backdraft/doctor-v1"
    return {capability["name"]: capability for capability in payload["capabilities"]}


def test_json_with_everything_missing_asserts_every_field(everything_missing: None) -> None:
    from backdraft.extract import vlm_gap

    def gap(name: str, gap: str, costs: str, key: dict | None = None) -> dict:
        return {
            "name": name,
            "ready": False,
            "gap": gap,
            "costs": costs,
            "ready_detail": None,
            "key": key,
        }

    # The registry's three fields are null: there is no registry to describe.
    assert _doctor_json() == {
        "registry": {
            **gap(
                "registry",
                f"no {DIRECTORY}/ in {Path.cwd()} or any directory above it — "
                "`backdraft init` makes one",
                "every verb but `init`, `skill` and `doctor` needs one: ingest, read, "
                "search, bind and render all stop here with exit 1.",
            ),
            "root": None,
            "schema_version": None,
            "documents": None,
        },
        "page images": gap(
            "page images",
            snapshots.POPPLER_HINT,
            f"ingest: PDFs land without page images. {snapshots.MISSING_EFFECT}",
        ),
        "vision model": gap(
            "vision model",
            vlm_gap(),
            "ingest: `auto` reads a PDF's text layer, so a scan comes back thin, and an "
            "image cannot be ingested at all. A PDF with a text layer, and every other "
            "format, is unaffected.",
            {"name": "BACKDRAFT_VLM_API_KEY", "set": False},
        ),
        "legacy .xls": gap(
            "legacy .xls",
            "extractor 'xls' is unavailable: legacy .xls needs: install 'backdraft[xls]'",
            "ingest: an .xls workbook is refused; .xlsx and .csv are unaffected.",
        ),
        "entail check": gap(
            "entail check",
            entail_module.EXTRA_MISSING,
            "bind: `--check entail` records every pair as `skip` with this reason; the "
            "bind still completes and its exit code is unaffected.",
            {"name": "BACKDRAFT_ENTAIL_API_KEY", "set": False},
        ),
        "math": gap(
            "math",
            f"the `[math]` extra is not installed — {render_math.INSTALL}",
            "render: LaTeX in a draft renders verbatim, as written, rather than as math. "
            "No citation is affected.",
        ),
    }


def test_json_with_everything_ready_asserts_every_field(
    project: Path, everything_else_ready: None
) -> None:
    def ready(name: str, detail: str, key: dict | None = None) -> dict:
        return {
            "name": name,
            "ready": True,
            "gap": None,
            "costs": None,
            "ready_detail": detail,
            "key": key,
        }

    assert _doctor_json() == {
        "registry": {
            **ready("registry", f"{project / DIRECTORY}, schema {SCHEMA_VERSION}, 0 document(s)"),
            "root": str(project),
            "schema_version": SCHEMA_VERSION,
            "documents": 0,
        },
        "page images": ready(
            "page images", "poppler renders PDF pages for the artifact's cited-page view"
        ),
        "vision model": ready(
            "vision model",
            "`auto` reads PDFs and images through the vision model, off this machine",
            {"name": "BACKDRAFT_VLM_API_KEY", "set": False},
        ),
        "legacy .xls": ready("legacy .xls", "ingest reads .xls workbooks, values only"),
        "entail check": ready(
            "entail check",
            "`bind --check entail` asks a model judge whether each snippet supports its claim",
            {"name": "BACKDRAFT_ENTAIL_API_KEY", "set": False},
        ),
        "math": ready("math", "render turns LaTeX in a draft into MathML"),
    }


def test_json_keeps_the_reports_order(project: Path) -> None:
    assert list(_doctor_json()) == [
        "registry",
        "page images",
        "vision model",
        "legacy .xls",
        "entail check",
        "math",
    ]


def test_json_counts_the_documents_as_a_number(project: Path) -> None:
    source = project / "note.md"
    source.write_text("Occupancy closed at 91.4%.\n", encoding="utf-8")
    assert runner.invoke(cli.app, ["ingest", str(source)]).exit_code == 0
    registry = _doctor_json()["registry"]
    assert registry["ready"] is True
    assert registry["documents"] == 1


@pytest.mark.parametrize("where", ["env", "file"])
def test_json_says_a_key_is_set_and_its_value_appears_nowhere(
    project: Path, monkeypatch: pytest.MonkeyPatch, where: str
) -> None:
    if where == "env":
        monkeypatch.setenv("BACKDRAFT_VLM_API_KEY", FAKE_KEY)
        monkeypatch.setenv("BACKDRAFT_ENTAIL_API_KEY", FAKE_KEY)
    else:
        (project / DIRECTORY / "env").write_text(
            f"BACKDRAFT_VLM_API_KEY={FAKE_KEY}\nBACKDRAFT_ENTAIL_API_KEY={FAKE_KEY}\n",
            encoding="utf-8",
        )
    result = runner.invoke(cli.app, ["doctor", "--json"])
    assert result.exit_code == 0, result.output
    assert FAKE_KEY not in result.output
    assert FAKE_KEY[-8:] not in result.output
    capabilities = {c["name"]: c for c in json.loads(result.stdout)["capabilities"]}
    assert capabilities["vision model"]["key"] == {"name": "BACKDRAFT_VLM_API_KEY", "set": True}
    assert capabilities["entail check"]["key"] == {
        "name": "BACKDRAFT_ENTAIL_API_KEY",
        "set": True,
    }


def test_json_on_a_damaged_registry_names_the_root_and_counts_nothing(project: Path) -> None:
    database = project / DIRECTORY / "registry.db"
    database.write_bytes(b"not a database, " * 64)
    registry = _doctor_json()["registry"]
    assert registry["ready"] is False
    assert "is not a registry backdraft can read" in registry["gap"]
    assert registry["root"] == str(project)
    assert registry["schema_version"] is None and registry["documents"] is None
    assert database.read_bytes() == b"not a database, " * 64


def test_json_on_a_home_override_naming_an_empty_directory_creates_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(cli.HOME_ENV, str(tmp_path))
    registry = _doctor_json()["registry"]
    assert registry["ready"] is False
    assert cli.HOME_ENV in registry["gap"]
    assert registry["root"] is None  # the override names a directory, not a registry
    assert not (tmp_path / DIRECTORY).exists()
