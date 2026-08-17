"""Text helpers: escaping, naming, verdict prose, and the drift diff.

Everything here turns record data into reader-facing words — humanized source
names, plain-language locations, verdict sentences instead of debug strings,
and the word-level diff a drifted citation shows. No HTML structure lives
here beyond the inline fragments those words need.
"""

from __future__ import annotations

import difflib
import html as html_module
import re
from typing import Any

from .. import markdown
from .._text import fetched_on
from ...kernel.model import SHEET_MEDIA_TYPES, Citation, CitationStatus, Claim, Verdict

CELL_RE = re.compile(r"^(?P<sheet>[^!]+)!(?P<ref>[A-Z]{1,3}\d+)$")
PAGE_RE = re.compile(r"^p(?P<page>\d+)(?:\.c\d+)?$")
IMAGE_TAG_RE = re.compile(r"\[(?:IMAGE|CHART|MAP):[^\]]*\]\s*")
SUBTITLE_RE = re.compile(r"^\*([^*].*?)\*\s*$")

_STATUS_RANK = {
    CitationStatus.RESOLVED: 0,
    CitationStatus.NOT_SHOWN: 1,
    CitationStatus.DRIFTED: 2,
    CitationStatus.UNRESOLVED: 3,
    CitationStatus.MALFORMED: 4,
}

_STATUS_SENTENCE = {
    CitationStatus.UNRESOLVED: (
        "This citation names nothing in the sources; the claim is untraced."
    ),
    CitationStatus.NOT_SHOWN: "The source exists, but the writer was never shown it.",
    CitationStatus.DRIFTED: "The source has changed since this was written.",
    CitationStatus.MALFORMED: "The citation is malformed and could not be checked.",
}


def _esc(value: Any) -> str:
    return html_module.escape(str(value), quote=True)


# ---- small text helpers -----------------------------------------------------


def split_subtitle(source: str) -> tuple[str, str | None]:
    """An italic line directly under the `# title` is the document's subtitle.

    Returns (source without that line, subtitle text or None). The subtitle is
    a fill-in slot the author owns; the masthead shows it under the title.
    """
    lines = source.splitlines(keepends=True)
    seen_title = False
    for index, line in enumerate(lines):
        if not line.strip():
            continue
        if line.startswith("# ") and not seen_title:
            seen_title = True
            continue
        if seen_title and (match := SUBTITLE_RE.match(line.strip())):
            return "".join(lines[:index] + lines[index + 1:]), match.group(1)
        break
    return source, None


def humanize_sheet(slug: str) -> str:
    fixed = {"dy": "DY", "t12": "T12", "ttm": "TTM", "noi": "NOI"}
    return " ".join(
        fixed.get(word, word.capitalize()) for word in slug.replace("-", " ").split()
    )


def source_title(slug: str, docs: dict) -> str:
    """A human name for a source: its filename's stem, humanized.

    A slug-shaped stem (`t12-summary`, `underwriting-model`) reads as a
    machine identifier where a reader expects a name, so it is title-cased
    through the same fixed-caps table sheet names use. A stem with its own
    casing is somebody's chosen name and passes through untouched.

    A fetched page has no filename anybody chose — `fetch.filename_for` names
    the staging file, so a Wikipedia article arrives as `index.html` and would
    title itself "Index". The slug is the chosen handle there, so where a
    document carries a URL the slug is the name, for the same reason the source
    list shows the URL in the filename's place: the invented name must not be
    the one a reader trusts.
    """
    entry = docs.get(slug)
    base = (
        str(entry.get("filename", slug)).rsplit(".", 1)[0].replace("_", " ")
        if entry and not entry.get("url")
        else slug
    )
    if re.fullmatch(r"[a-z0-9][a-z0-9 \-]*", base):
        return humanize_sheet(base.replace(" ", "-"))
    return base


ORIGIN_SCHEMES = ("http://", "https://")
"""The only schemes an origin URL may be linked under. Artifact rule 3 forbids
`javascript:` URLs, so this is an allowlist rather than a guard against one
known-bad scheme: whatever the registry stored, only these become live."""


def origin(slug: str, docs: dict) -> tuple[str, str]:
    """A fetched source's origin as `(url html, fetch date)`; `("", "")` for a file.

    The URL is a live link — the artifact's CSP forbids fetching, not linking,
    and pointing back at the page is half of what citing one is for: the receipt
    says what it said, the link is how a reader asks whether it still does. A
    URL under an unrecognized scheme is shown as plain text rather than dropped;
    provenance the reader must paste by hand still beats provenance withheld.
    """
    entry = docs.get(slug) or {}
    url = str(entry.get("url") or "")
    if not url:
        return "", ""
    if url.lower().startswith(ORIGIN_SCHEMES):
        html = f'<a class="origin" href="{_esc(url)}">{_esc(url)}</a>'
    else:
        html = f'<span class="origin">{_esc(url)}</span>'
    return html, fetched_on(entry.get("fetched_at"))


def md_html(text: str) -> str:
    """Snippet or page text rendered as markdown for human display."""
    return markdown.to_html(IMAGE_TAG_RE.sub("", text), [])


def table_heavy(text: str) -> bool:
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        return False
    return sum(1 for line in lines if line.lstrip().startswith("|")) > len(lines) * 0.4


def worst_status(claim: Claim) -> CitationStatus:
    statuses = [citation.status for citation in claim.citations]
    if not statuses:
        return CitationStatus.UNRESOLVED
    return max(statuses, key=_STATUS_RANK.__getitem__)


def _page_word(media: str | None) -> str:
    """What a `pN` locator names for this media type: slides for decks,
    heading sections for Word documents, pages for everything else."""
    if media == "pptx":
        return "Slide"
    if media == "docx":
        return "Sec."
    return "Page"


def location(anchor, docs: dict) -> str:
    locator = str(anchor.locator)
    if match := CELL_RE.match(locator):
        return f"{_esc(humanize_sheet(match['sheet']))} &middot; {match['ref']}"
    if match := PAGE_RE.match(locator):
        media = docs.get(anchor.slug, {}).get("media_type")
        if media in SHEET_MEDIA_TYPES:
            return "sheet"
        return f"{_page_word(media)} {match['page']}"
    return _esc(locator)


def short_loc(anchor, docs: dict) -> str:
    """Compact label for the source selector: `Page 6`, `Slide 3`, `D24`, `Sheet`."""
    if anchor is None:
        return "untraced"
    locator = str(anchor.locator)
    if match := CELL_RE.match(locator):
        return match["ref"]
    if match := PAGE_RE.match(locator):
        media = docs.get(anchor.slug, {}).get("media_type")
        if media in SHEET_MEDIA_TYPES:
            return "Sheet"
        return f"{_page_word(media)} {match['page']}"
    return locator


# ---- verdict language -------------------------------------------------------

_VALUES_FOUND_RE = re.compile(r"^(\d+) value\(s\) found in snippet$")
_NOT_FOUND_RE = re.compile(r"^not found in snippet: (.+)$")
_ROUNDED_RE = re.compile(r"^rounded match: (.+)$")
_TOKENS_RE = re.compile(r"^(\d+)/(\d+) claim tokens in snippet")
_QUOTED_MISSING_RE = re.compile(r"^quoted span not in snippet: (.+)$")
_QUOTED_CASE_RE = re.compile(r"^quoted span differs in case: (.+)$")
_QUOTED_OK_RE = re.compile(r"^(\d+) quoted span\(s\) verbatim in snippet$")

_METHOD_LABEL = {
    "value-trace": "Figures",
    "overlap": "Wording",
    "entail": "Reading",
    "recompute": "Math",
}


def humanize_verdict(verdict: Verdict) -> tuple[str, str]:
    """(label, sentence) for the record layer. Debug strings become prose."""
    label = _METHOD_LABEL.get(verdict.method, verdict.method)
    detail = verdict.detail or ""
    if verdict.method == "value-trace":
        if match := _VALUES_FOUND_RE.match(detail):
            count = int(match.group(1))
            sentence = (
                "The figure in this claim appears in this source."
                if count == 1
                else f"All {count} figures in this claim appear in this source."
            )
        elif match := _NOT_FOUND_RE.match(detail):
            sentence = f"Not found in this source: {match.group(1)}."
        elif match := _ROUNDED_RE.match(detail):
            sentence = f"Matched only after rounding: {match.group(1)}."
        else:
            sentence = detail
        return label, sentence
    if verdict.method == "overlap":
        if match := _TOKENS_RE.match(detail):
            found, total = int(match.group(1)), int(match.group(2))
            sentence = (
                "None of the claim's wording appears in this source."
                if found == 0
                else f"{found} of the claim's {total} words appear in this source."
            )
        elif match := _QUOTED_MISSING_RE.match(detail):
            sentence = f"Quoted phrase not found verbatim in this source: {match.group(1)}."
        elif match := _QUOTED_CASE_RE.match(detail):
            sentence = f"Quoted phrase differs from this source in casing: {match.group(1)}."
        elif match := _QUOTED_OK_RE.match(detail):
            sentence = "Every quoted phrase appears verbatim in this source."
        else:
            sentence = detail
        return label, sentence
    return label, detail or str(verdict.status)


# ---- drift ------------------------------------------------------------------

_WORD_RE = re.compile(r"\s+|\S+")


def _word_diff(before: str, after: str) -> tuple[str, str]:
    """Escaped HTML for both snippets, with `<del>`/`<ins>` on what moved."""
    old_words = _WORD_RE.findall(before)
    new_words = _WORD_RE.findall(after)
    matcher = difflib.SequenceMatcher(a=old_words, b=new_words, autojunk=False)
    old: list[str] = []
    new: list[str] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        old_text = html_module.escape("".join(old_words[i1:i2]))
        new_text = html_module.escape("".join(new_words[j1:j2]))
        if tag == "equal":
            old.append(old_text)
            new.append(new_text)
            continue
        if old_text:
            old.append(f"<del>{old_text}</del>")
        if new_text:
            new.append(f"<ins>{new_text}</ins>")
    return "".join(old), "".join(new)


def _drift_block(citation: Citation) -> str:
    if citation.drifted_from is None:
        return ""
    now = citation.anchor.receipt.snippet if citation.anchor else ""
    old_html, new_html = _word_diff(citation.drifted_from, now)
    return (
        '<div class="drift">'
        f'<div class="drift-row"><span>as cited</span><p>{old_html}</p></div>'
        f'<div class="drift-row"><span>now</span><p>{new_html}</p></div>'
        "</div>"
    )
