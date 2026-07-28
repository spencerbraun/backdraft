"""Evidence assembly: cited-only, windowed, degradable."""

from __future__ import annotations

from dataclasses import dataclass

from backdraft.bind.evidence import assemble, col_letters, col_num
from backdraft.extract.base import PageImage
from backdraft.kernel.model import (
    Anchor,
    CellValue,
    Citation,
    CitationStatus,
    Claim,
    Document,
    Page,
    Receipt,
)
from backdraft.kernel.tokens import parse_locator


@dataclass
class FakeEvidenceRegistry:
    """Just enough registry for `assemble`: documents, pages, page images."""

    docs: dict
    page_rows: dict  # slug -> list[Page]
    images: dict  # (slug, number) -> PageImage

    def document(self, slug):
        return self.docs.get(slug)

    def pages(self, slug):
        return self.page_rows.get(slug, [])

    def page(self, slug, number):
        for page in self.page_rows.get(slug, []):
            if page.number == number:
                return page
        return None

    def page_image(self, slug, number):
        return self.images.get((slug, number))


def _doc(slug: str, media: str) -> Document:
    return Document(
        slug=slug, sha256="0" * 64, path=f"/x/{slug}", filename=f"{slug}.{media}",
        media_type=media, created_at="2026-07-28T00:00:00Z",
    )


def _claim(token: str, slug: str, locator: str, snippet: str = "s") -> Claim:
    parsed = parse_locator(locator)
    return Claim(
        text="claim", start=0, end=5,
        citations=(
            Citation(
                token=token, status=CitationStatus.RESOLVED,
                anchor=Anchor(
                    slug=slug, locator=parsed,
                    receipt=Receipt(snippet=snippet, snippet_sha256="0" * 64),
                    token=token,
                ),
            ),
        ),
    )


def _registry() -> FakeEvidenceRegistry:
    sheet = Page(
        number=1, kind="sheet", text="| ... |", name="model",
        cells=(
            CellValue(ref="C23", value="NOI"),
            CellValue(ref="D23", value="3105877"),
            CellValue(ref="C24", value="Debt Yield"),
            CellValue(ref="D24", value="0.0765"),
        ),
    )
    pdf_page = Page(number=6, kind="page", text="# LOAN REQUEST\n\nProceeds.")
    return FakeEvidenceRegistry(
        docs={"uw": _doc("uw", "xlsx"), "memo": _doc("memo", "pdf")},
        page_rows={"uw": [sheet], "memo": [pdf_page]},
        images={("memo", 6): PageImage(data=b"ABCD", format="webp", width=4, height=4)},
    )


def test_cell_citation_yields_window_and_full_sheet() -> None:
    evidence = assemble(_registry(), [_claim("bd:uw:model!D24:0000", "uw", "model!D24")])
    window = evidence["windows"]["uw:model!D24"]
    assert window["cited"] == "D24"
    assert window["cols"] == ["C", "D"]
    assert [row["n"] for row in window["rows"]] == [23, 24]
    sheet = evidence["sheets"]["uw:model"]
    assert sheet["nrows"] == 24 and sheet["ncols"] == 4
    assert sheet["rows"][23][3] == "0.0765"


def test_page_citation_yields_text_and_image() -> None:
    evidence = assemble(_registry(), [_claim("bd:memo:p6.c1:0000", "memo", "p6.c1")])
    assert evidence["pagetexts"]["memo:p6"].startswith("# LOAN REQUEST")
    page = evidence["pages"]["memo:p6"]
    assert page["format"] == "webp" and page["data"] == "QUJDRA=="
    assert evidence["documents"]["memo"]["media_type"] == "pdf"


def test_lean_skips_images_but_keeps_text() -> None:
    evidence = assemble(
        _registry(), [_claim("bd:memo:p6.c1:0000", "memo", "p6.c1")], lean=True
    )
    assert evidence["pages"] == {}
    assert "memo:p6" in evidence["pagetexts"]


def test_uncited_sources_contribute_nothing() -> None:
    evidence = assemble(_registry(), [_claim("bd:memo:p6.c1:0000", "memo", "p6.c1")])
    assert "uw" not in evidence["documents"]
    assert evidence["windows"] == {} and evidence["sheets"] == {}


def test_whole_sheet_citation_yields_a_topleft_window() -> None:
    evidence = assemble(_registry(), [_claim("bd:uw:p1:0000", "uw", "p1")])
    window = evidence["windows"]["uw:p1"]
    assert window["cited"] is None
    assert "uw:model" in evidence["sheets"]


def test_an_incapable_registry_degrades_to_none() -> None:
    class Bare:
        pass

    assert assemble(Bare(), [_claim("bd:uw:model!D24:0000", "uw", "model!D24")]) is None


def test_no_citations_means_no_evidence() -> None:
    assert assemble(_registry(), [Claim(text="t", start=0, end=1)]) is None


def test_column_math_round_trips() -> None:
    for n in (1, 26, 27, 52, 703):
        assert col_num(col_letters(n)) == n
