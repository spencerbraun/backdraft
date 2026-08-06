"""Evidence assembly: the context a citation's receipt sits in.

Bind is the one step that holds both the resolved claims and the registry, so
it is where the artifact's evidence is gathered: the cited pages as images (when
the registry has snapshots), each cited page's extracted text, a small cell
window around every cited cell, and the full values of every cited sheet for
the artifact's sheet view. Bounded by what is cited — never the corpus.

The result is a plain JSON-shaped dict, carried on `BindReport.evidence` and
described by `LEGEND["evidence"]`. Everything here is optional context: a
sidecar without evidence is still a complete record, so assembly degrades
rather than fails — a registry that cannot answer (a test fake, a missing
snapshot) simply contributes nothing.
"""

from __future__ import annotations

import base64
import re
from typing import Any, Iterable

from ..kernel.model import SHEET_MEDIA_TYPES, Claim

__all__ = ["assemble", "document_entry", "window_styles", "WINDOW_ROWS", "WINDOW_COLS"]

WINDOW_ROWS = 6
"""Rows kept above and below a cited cell in its window."""

WINDOW_COLS = 4
"""Columns kept left and right of a cited cell in its window."""

_CELL_RE = re.compile(r"^(?P<sheet>[^!]+)!(?P<col>[A-Z]{1,3})(?P<row>\d+)$")
_PAGE_RE = re.compile(r"^p(?P<page>\d+)(?:\.c\d+)?$")


def col_num(letters: str) -> int:
    """A1 column letters -> 1-based number."""
    n = 0
    for ch in letters:
        n = n * 26 + (ord(ch) - 64)
    return n


def col_letters(n: int) -> str:
    """1-based column number -> A1 letters."""
    out = ""
    while n:
        n, r = divmod(n - 1, 26)
        out = chr(65 + r) + out
    return out


def window_styles(
    meta: dict[str, Any] | None, cols: list[str], rows_out: list[dict[str, Any]]
) -> dict[str, Any]:
    """The window's slice of a sheet's styling: resolved styles per cell ref
    plus the window columns' widths. Palette indirection is unpacked here —
    a window is small, so it carries plain styles."""
    if not meta:
        return {}
    out: dict[str, Any] = {}
    palette = meta.get("palette") or []
    cell_refs = meta.get("cells") or {}
    resolved: dict[str, dict] = {}
    for row in rows_out:
        n = row["n"]
        for letter in row["cells"]:
            ref = f"{letter}{n}"
            idx = cell_refs.get(ref)
            if idx is not None and 0 <= idx < len(palette):
                resolved[ref] = palette[idx]
    if resolved:
        out["cells"] = resolved
    widths = meta.get("widths") or {}
    kept = {letter: widths[letter] for letter in cols if letter in widths}
    if kept:
        out["widths"] = kept
    return out


def document_entry(document) -> dict[str, Any]:  # noqa: ANN001
    """One source's entry in the evidence `documents` map.

    `filename` and `media_type` are always there. A source fetched from the web
    also carries `url` and `fetched_at` out of its document meta, so a reader
    holding only the artifact can go back to the live page and ask whether it
    still says this — the half of citing a web page that a frozen receipt
    cannot answer on its own.

    The two keys appear only where there is a URL, which is what keeps an
    artifact built from files byte-identical to one built before URL sources
    existed. Provenance, never identity: the sha256 is what the bytes were.
    """
    entry: dict[str, Any] = {
        "filename": document.filename,
        "media_type": document.media_type,
    }
    meta = getattr(document, "meta", None) or {}
    if url := meta.get("url"):
        entry["url"] = url
        if fetched_at := meta.get("fetched_at"):
            entry["fetched_at"] = fetched_at
    return entry


def assemble(registry, claims: Iterable[Claim], *, lean: bool = False) -> dict[str, Any] | None:  # noqa: ANN001
    """Evidence for every cited anchor, or None when there is nothing to give.

    `lean` skips page images (the only heavy part); text windows and sheet
    values are always cheap enough to include.
    """
    if not callable(getattr(registry, "document", None)) or not callable(
        getattr(registry, "page", None)
    ):
        return None

    cited_pages: dict[str, set[int]] = {}
    cited_cells: list[tuple[str, str, str, int]] = []  # slug, sheet, col, row
    sheet_pages: list[tuple[str, int]] = []
    slugs: list[str] = []

    documents: dict[str, Any] = {}

    def doc_for(slug: str):  # noqa: ANN202
        if slug not in documents:
            documents[slug] = registry.document(slug)
        return documents[slug]

    for claim in claims:
        for citation in claim.citations:
            anchor = citation.anchor
            if anchor is None:
                continue
            document = doc_for(anchor.slug)
            if document is None:
                continue
            if anchor.slug not in slugs:
                slugs.append(anchor.slug)
            locator = str(anchor.locator)
            if m := _CELL_RE.match(locator):
                cited_cells.append((anchor.slug, m["sheet"], m["col"], int(m["row"])))
            elif m := _PAGE_RE.match(locator):
                number = int(m["page"])
                if document.media_type in SHEET_MEDIA_TYPES:
                    sheet_pages.append((anchor.slug, number))
                else:
                    cited_pages.setdefault(anchor.slug, set()).add(number)

    if not slugs:
        return None

    evidence: dict[str, Any] = {
        "documents": {slug: document_entry(documents[slug]) for slug in slugs},
        "pages": {},
        "pagetexts": {},
        "windows": {},
        "sheets": {},
    }

    # ---- cited PDF pages: text always, image when stored and not lean ------
    can_image = callable(getattr(registry, "page_image", None))
    for slug, numbers in cited_pages.items():
        for number in sorted(numbers):
            page = registry.page(slug, number)
            if page is not None:
                evidence["pagetexts"][f"{slug}:p{number}"] = page.text
            if lean or not can_image:
                continue
            image = registry.page_image(slug, number)
            if image is not None:
                evidence["pages"][f"{slug}:p{number}"] = {
                    "format": image.format,
                    "width": image.width,
                    "height": image.height,
                    "data": base64.b64encode(image.data).decode("ascii"),
                }

    # ---- sheets: windows around cited cells, full values per cited sheet ---
    def sheet_page(slug: str, sheet: str):  # noqa: ANN202
        for page in registry.pages(slug):
            if page.kind == "sheet" and page.name == sheet:
                return page
        return None

    def cells_map(page) -> dict[tuple[int, int], str]:  # noqa: ANN001
        cells: dict[tuple[int, int], str] = {}
        for cell in page.cells:
            if m := re.match(r"^([A-Z]{1,3})(\d+)$", cell.ref):
                cells[(int(m.group(2)), col_num(m.group(1)))] = cell.value
        return cells

    def window(cells: dict[tuple[int, int], str], sheet: str,
               col: str | None, row: int | None,
               meta: dict[str, Any] | None = None) -> dict[str, Any]:
        if not cells:
            return {}
        if col is None:  # whole-sheet citation: top-left populated block
            r0 = min(r for r, _ in cells)
            c0 = min(c for _, c in cells)
            rows_range = range(r0, r0 + 2 * WINDOW_ROWS + 1)
            cols_range = range(c0, c0 + 2 * WINDOW_COLS + 1)
            cited = None
        else:
            r, c = row, col_num(col)
            rows_range = range(max(1, r - WINDOW_ROWS), r + WINDOW_ROWS + 1)
            cols_range = range(max(1, c - WINDOW_COLS), c + WINDOW_COLS + 1)
            cited = f"{col}{row}"
        live_rows = [r for r in rows_range if any((r, c) in cells for c in cols_range)]
        live_cols = [c for c in cols_range if any((r, c) in cells for r in rows_range)]
        if not live_rows or not live_cols:
            return {}
        rows_out = [
            {
                "n": r,
                "cells": {
                    col_letters(c): cells.get((r, c), "")
                    for c in range(min(live_cols), max(live_cols) + 1)
                },
            }
            for r in range(min(live_rows), max(live_rows) + 1)
        ]
        made: dict[str, Any] = {
            "sheet": sheet,
            "cited": cited,
            "cols": [col_letters(c) for c in range(min(live_cols), max(live_cols) + 1)],
            "rows": rows_out,
        }
        styles = window_styles(meta, made["cols"], rows_out)
        if styles:
            made["styles"] = styles
        return made

    cited_sheets: dict[tuple[str, str], Any] = {}

    def note_sheet(slug: str, sheet: str):  # noqa: ANN202
        key = (slug, sheet)
        if key not in cited_sheets:
            cited_sheets[key] = sheet_page(slug, sheet)
        return cited_sheets[key]

    for slug, sheet, col, row in cited_cells:
        key = f"{slug}:{sheet}!{col}{row}"
        if key in evidence["windows"]:
            continue
        page = note_sheet(slug, sheet)
        if page is None:
            continue
        made = window(cells_map(page), sheet, col, row, getattr(page, "meta", None))
        if made:
            evidence["windows"][key] = made

    for slug, number in sheet_pages:
        page = registry.page(slug, number)
        if page is None or page.kind != "sheet" or not page.name:
            continue
        note_sheet(slug, page.name)
        key = f"{slug}:p{number}"
        if key not in evidence["windows"]:
            made = window(cells_map(page), page.name, None, None, getattr(page, "meta", None))
            if made:
                evidence["windows"][key] = made

    for (slug, sheet), page in cited_sheets.items():
        if page is None:
            continue
        cells = cells_map(page)
        if not cells:
            continue
        maxr = max(r for r, _ in cells)
        maxc = max(c for _, c in cells)
        payload: dict[str, Any] = {
            "name": sheet,
            "nrows": maxr,
            "ncols": maxc,
            "rows": [
                [cells.get((r, c), "") for c in range(1, maxc + 1)]
                for r in range(1, maxr + 1)
            ],
        }
        meta = getattr(page, "meta", None)
        if meta:
            payload["meta"] = meta
        evidence["sheets"][f"{slug}:{sheet}"] = payload

    if not any((evidence["pages"], evidence["pagetexts"],
                evidence["windows"], evidence["sheets"])):
        return None
    return evidence
