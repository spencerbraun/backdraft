"""The search side of the gate: FTS results that are themselves citable.

A searched snippet is minted exactly like a read one. This is the whole point of
routing search through the gate: search that returns text with nothing citable
attached forces a page read purely to obtain an anchor, a tax on every lookup.
Here the result *is* the anchor, and the
read hint below the results is an affordance, not a prerequisite.

Consumes the pinned registry surface (SPEC Addendum A) and nothing else.
"""

from __future__ import annotations

import shlex
from typing import TYPE_CHECKING

from ..kernel.hashing import normalize

from .reader import LIST_HINT, GateError

if TYPE_CHECKING:
    from collections.abc import Iterable

    from ..registry.store import Registry, SearchHit

__all__ = ["EXCERPT_CHARS", "PHRASE_FALLBACK_NOTE", "search", "render_search"]

EXCERPT_CHARS = 160
"""How much of a snippet a result line shows before deferring to a page read."""

PHRASE_FALLBACK_NOTE = "(query retried as a phrase)"
"""Shown when the registry could not parse the query as FTS5 syntax.

The retry changes the question: `NOI 1.42x` as a boolean query asks for both
terms anywhere, as a phrase it asks for those tokens adjacent and in order. A
reader who is not told cannot distinguish "no such fact" from "not asked that
way", so the gate says it — once, on its own line, rather than as an error.
"""

_ELLIPSIS = "..."
_DEFAULT_LIMIT = 20
"""Mirrors `Registry.search`'s own default, so the CLI and the store agree."""


def search(
    registry: Registry,
    query: str,
    *,
    slug: str | None = None,
    limit: int = _DEFAULT_LIMIT,
    session: str | None = None,
) -> str:
    """Run `query` through the registry's FTS index and render the results.

    Each hit is one line carrying its token, its document and page, and an
    excerpt of its snippet; a read hint follows for every distinct page matched.
    Every hit's anchor is recorded in `session` before the text is returned — a
    result the writer saw is a result the writer may cite.

    Raises `GateError` if `slug` names no document.
    """
    if slug is not None and registry.document(slug) is None:
        raise GateError(f"no such document: {slug!r}; {LIST_HINT}")
    hits = registry.search(query, slug=slug, limit=limit)
    _mint(registry, session, hits)
    return render_search(query, hits, slug=slug)


def render_search(query: str, hits: Iterable[SearchHit], *, slug: str | None = None) -> str:
    """Render search results. Pure: minting happens in `search`.

    NOTE: `phrase_fallback` and `total` are read *before* `hits` is copied into
    a plain list — they ride on the result object the registry returned.
    """
    retried = bool(getattr(hits, "phrase_fallback", False))
    total = getattr(hits, "total", None)
    hits = list(hits)
    if total is None:
        total = len(hits)
    scope = f" in {slug}" if slug else ""
    note = [PHRASE_FALLBACK_NOTE] if retried else []
    if not hits and not total:
        return "\n".join(
            [
                f'No results for "{query}"{scope}.',
                *note,
                "",
                "[List documents: backdraft read]",
            ]
        )

    if total > len(hits):
        count = f"{len(hits)} of {total} results"
    else:
        count = f"{len(hits)} result" if len(hits) == 1 else f"{len(hits)} results"
    lines = [f'{count} for "{query}"{scope}', *note, ""]
    for hit in hits:
        lines.append(f"[{hit.anchor.token}]  {hit.slug} p{hit.page_number}")
        lines.append(f"  {_excerpt(hit.anchor.receipt.snippet)}")
        lines.append("")

    seen: list[tuple[str, int]] = []
    for hit in hits:
        if (hit.slug, hit.page_number) not in seen:
            seen.append((hit.slug, hit.page_number))
    lines += [f"[Read the page: backdraft read {s} p{n}]" for s, n in seen]
    if total > len(hits):
        lines.append(_widen_hint(query, slug, total))
    return "\n".join(line.rstrip() for line in lines).rstrip("\n")


def _widen_hint(query: str, slug: str | None, total: int) -> str:
    """The line that names the command showing the results `--limit` cut.

    `read`'s continuation hint is the model: say what was withheld and give the
    exact command that produces it, rather than leaving the caller to work out
    which flag to move. The query is shell-quoted because a real one carries `$`
    and commas, and a hint that has to be repaired before it runs is not a hint.
    """
    scope = f" --in {slug}" if slug else ""
    return (
        f"[See all {total}: backdraft search {shlex.quote(query)}{scope} --limit {total}]"
    )


def _excerpt(snippet: str) -> str:
    """A snippet collapsed onto one line and cut to `EXCERPT_CHARS`.

    NOTE: the cut is from the start rather than centred on the match. FTS5
    decides what matched (stemming, phrase queries), and the gate does not
    re-derive anything the registry owns; the token on the line above is the
    thing to cite, and the read hint is the way to see the rest.
    """
    text = normalize(snippet)
    return text if len(text) <= EXCERPT_CHARS else text[:EXCERPT_CHARS] + _ELLIPSIS


def _mint(registry: Registry, session: str | None, hits: Iterable[SearchHit]) -> None:
    """Record every result's anchor under the session."""
    if session is None:
        return
    anchor_ids = sorted({hit.anchor.id for hit in hits if hit.anchor.id is not None})
    if not anchor_ids:
        return
    session_id = registry.ensure_session(session)
    registry.record_shown(session_id, anchor_ids)
