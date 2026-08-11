"""Fixtures shared by the store and extract tests.

Everything is real: a real SQLite file, a real workbook, a real PDF. The registry
is the one stateful object in the system and a fake of it would only test the
fake.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from backdraft.extract.base import ExtractedPage, register
from backdraft.kernel.model import CellValue
from backdraft.registry import Registry


@pytest.fixture
def root(tmp_path: Path) -> Path:
    """A project root; `Registry.open` creates `.backdraft/` inside it."""
    return tmp_path


@pytest.fixture
def registry(root: Path) -> Registry:
    with Registry.open(root) as opened:
        yield opened


@pytest.fixture
def note(tmp_path: Path) -> Path:
    """A markdown file whose text chunks into three chunks."""
    path = tmp_path / "quarterly-notes.md"
    path.write_text(_PROSE, encoding="utf-8")
    return path


@pytest.fixture
def workbook(tmp_path: Path) -> Path:
    """A small two-sheet workbook, generated so the fixture is readable here."""
    from openpyxl import Workbook

    book = Workbook()
    sheet = book.active
    sheet.title = "Rent Roll (2025)"
    sheet.append(["Unit", "Tenant", "Rent"])
    sheet.append(["101", "Acme Corp", 2400])
    sheet.append(["102", "Beta LLC", 1875.5])
    other = book.create_sheet("Summary")
    other.append(["NOI", 4100000])
    book.save(tmp_path / "model.xlsx")
    return tmp_path / "model.xlsx"


PAGE_BREAK = "\n---\n"
"""What the `paged` test extractor splits a file on."""


class PagedExtractor:
    """A deterministic multi-page extractor over a real file.

    Splits the file's text on `---` lines. Tests that exercise drift need pages
    that change *because the bytes changed*, which is the only way a deterministic
    extractor's output ever moves.
    """

    name = "paged"
    version = "1"
    deterministic = True

    def can_handle(self, path: Path, media_type: str) -> bool:
        return True

    def extract(self, path: Path, config: dict):
        text = path.read_text(encoding="utf-8")
        for number, page in enumerate(text.split(PAGE_BREAK), start=1):
            yield ExtractedPage(number=number, kind="page", text=page.strip())


@pytest.fixture
def paged() -> PagedExtractor:
    """Register the `paged` extractor for the duration of a test."""
    register(PagedExtractor())
    return PagedExtractor()


@pytest.fixture
def scripted() -> type:
    """A test extractor factory: hand it pages, register it under a name."""

    class Scripted:
        def __init__(
            self,
            name: str,
            pages: list[ExtractedPage],
            *,
            deterministic: bool = True,
            config_keys: dict[str, str] | None = None,
        ):
            self.name = name
            self.version = "1"
            self.deterministic = deterministic
            # Declared like a real extractor's, so a test that passes `--config`
            # to this one is testing config, not the validator that guards it.
            self.config_keys = dict(config_keys or {})
            self.pages = pages
            register(self)

        def can_handle(self, path: Path, media_type: str) -> bool:
            return True

        def extract(self, path: Path, config: dict):
            yield from self.pages

    return Scripted


def sheet_page(number: int, name: str, text: str, cells: list[tuple[str, str]]) -> ExtractedPage:
    """A sheet page for tests that do not need a real workbook."""
    return ExtractedPage(
        number=number,
        kind="sheet",
        name=name,
        text=text,
        cells=[CellValue(ref=ref, value=value) for ref, value in cells],
    )


_PROSE = """\
The portfolio's debt service coverage ratio finished the quarter at 1.42x, which
clears the 1.25x covenant with room to spare. Management attributes the margin to
the lease-up at the Riverside asset and to the refinancing completed in March,
which lowered the blended coupon by roughly seventy basis points.

Net operating income for the trailing twelve months was $4.1 million, up eleven
percent year over year. The increase is concentrated in the two suburban assets;
the urban core properties were flat, and one of them lost an anchor tenant in
February whose space has not yet been backfilled.

Looking forward, the sponsor projects stabilized net operating income of $4.6
million by the end of next year. That projection assumes the vacant anchor space
leases at market and that expense growth stays under three percent, neither of
which is contractually committed at this time.
"""
