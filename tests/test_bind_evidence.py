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


def test_sheet_meta_travels_into_sheets_and_windows() -> None:
    registry = _registry()
    styled = Page(
        number=1, kind="sheet", text="| ... |", name="model",
        cells=registry.page_rows["uw"][0].cells,
        meta={
            "palette": [{"b": 1, "fmt": "0.00%"}],
            "cells": {"D24": 0},
            "widths": {"C": 30.0, "D": 14.0, "Z": 9.0},
            "frozen": "A2",
        },
    )
    registry.page_rows["uw"] = [styled]
    evidence = assemble(registry, [_claim("bd:uw:model!D24:0000", "uw", "model!D24")])
    sheet = evidence["sheets"]["uw:model"]
    assert sheet["meta"]["palette"] == [{"b": 1, "fmt": "0.00%"}]
    window = evidence["windows"]["uw:model!D24"]
    assert window["styles"]["cells"]["D24"] == {"b": 1, "fmt": "0.00%"}
    # only the window's columns carry widths
    assert window["styles"]["widths"] == {"C": 30.0, "D": 14.0}


def test_unstyled_sheets_carry_no_meta_keys() -> None:
    evidence = assemble(_registry(), [_claim("bd:uw:model!D24:0000", "uw", "model!D24")])
    assert "meta" not in evidence["sheets"]["uw:model"]
    assert "styles" not in evidence["windows"]["uw:model!D24"]


def test_csv_documents_get_the_sheet_treatment() -> None:
    registry = _registry()
    registry.docs["uw"] = _doc("uw", "csv")
    evidence = assemble(registry, [_claim("bd:uw:p1:0000", "uw", "p1")])
    assert "uw:model" in evidence["sheets"]


def test_xls_documents_get_the_sheet_treatment() -> None:
    registry = _registry()
    registry.docs["uw"] = _doc("uw", "xls")
    evidence = assemble(registry, [_claim("bd:uw:p1:0000", "uw", "p1")])
    assert "uw:model" in evidence["sheets"]


# ---- provenance for a source that came from the web -------------------------


def _fetched(slug: str = "memo") -> Document:
    """The same document, but ingested from a URL rather than opened."""
    doc = _doc(slug, "html")
    return Document(
        slug=doc.slug, sha256=doc.sha256, path="https://example.com/reports/q4",
        filename=f"{slug}.html", media_type="html", created_at=doc.created_at,
        meta={"url": "https://example.com/reports/q4", "fetched_at": "2026-08-05T09:14:00Z"},
    )


def test_a_fetched_source_carries_its_origin_and_fetch_time() -> None:
    registry = _registry()
    registry.docs["memo"] = _fetched()
    evidence = assemble(registry, [_claim("bd:memo:p6.c1:0000", "memo", "p6.c1")])
    entry = evidence["documents"]["memo"]
    assert entry["url"] == "https://example.com/reports/q4"
    assert entry["fetched_at"] == "2026-08-05T09:14:00Z"
    assert entry["filename"] == "memo.html"


def test_a_file_source_carries_neither_key() -> None:
    """The whole point of making the keys conditional: an artifact built from
    files is byte-identical to one built before URL sources existed."""
    evidence = assemble(_registry(), [_claim("bd:memo:p6.c1:0000", "memo", "p6.c1")])
    assert set(evidence["documents"]["memo"]) == {"filename", "media_type"}


def test_a_fetch_time_without_a_url_is_not_provenance() -> None:
    """`fetched_at` alone says when nothing was taken from nowhere."""
    registry = _registry()
    registry.docs["memo"] = Document(
        slug="memo", sha256="0" * 64, path="/x/memo", filename="memo.pdf",
        media_type="pdf", created_at="2026-07-28T00:00:00Z",
        meta={"fetched_at": "2026-08-05T09:14:00Z"},
    )
    evidence = assemble(registry, [_claim("bd:memo:p6.c1:0000", "memo", "p6.c1")])
    assert set(evidence["documents"]["memo"]) == {"filename", "media_type"}


def test_meta_that_is_not_provenance_adds_nothing() -> None:
    registry = _registry()
    registry.docs["memo"] = Document(
        slug="memo", sha256="0" * 64, path="/x/memo", filename="memo.pdf",
        media_type="pdf", created_at="2026-07-28T00:00:00Z", meta={"pages": 3},
    )
    evidence = assemble(registry, [_claim("bd:memo:p6.c1:0000", "memo", "p6.c1")])
    assert set(evidence["documents"]["memo"]) == {"filename", "media_type"}
