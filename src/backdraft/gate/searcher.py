"""The search side of the gate: FTS results that are themselves citable.

A searched snippet is minted exactly like a read one. This is the whole point of
routing search through the gate: search that returns text with nothing citable
attached forces a page read purely to obtain an anchor, a tax on every lookup.
Here the result *is* the anchor, and the
read hint below the results is an affordance, not a prerequisite.

A hit whose text may run on past its own chunk — a paragraph the chunker split,
or a page break — carries the chunk on the other side too, minted with it, so a
claim that straddles the two is written with both tokens rather than the one the
query happened to land in (`reader.adjoining`).

Consumes the pinned registry surface (SPEC Addendum A) and nothing else.
"""

from __future__ import annotations

import shlex
from typing import TYPE_CHECKING

from .reader import (
    ADJOINING_NOTE,
    Adjoining,
    adjoining,
    adjoining_lines,
    excerpt,
    require_document,
    session_argument,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from ..registry.store import Registry, SearchHit

__all__ = ["PHRASE_FALLBACK_NOTE", "search", "render_search"]

PHRASE_FALLBACK_NOTE = "(query retried as a phrase)"
"""Shown when the registry could not parse the query as FTS5 syntax.

The retry changes the question: `NOI 1.42x` as a boolean query asks for both
terms anywhere, as a phrase it asks for those tokens adjacent and in order. A
reader who is not told cannot distinguish "no such fact" from "not asked that
way", so the gate says it — once, on its own line, rather than as an error.
"""

_DEFAULT_LIMIT = 20
"""Mirrors `Registry.search`'s own default, so the CLI and the store agree."""


def search(
    registry: Registry,
    query: str,
    *,
    slug: str | None = None,
    limit: int = _DEFAULT_LIMIT,
    session: str | None = None,
    session_flag: str | None = None,
) -> str:
    """Run `query` through the registry's FTS index and render the results.

    Each hit is one line carrying its token, its document and page, and an
    excerpt of its snippet; a read hint follows for every distinct page matched.
    Under a hit whose text may run on into the chunk beside it, that chunk is
    named too (`reader.adjoining`). Every hit's anchor, and every adjoining one,
    is recorded in `session` before the text is returned — a result the writer
    saw is a result the writer may cite. Every hint carries `session_flag`, the
    `--session` the caller typed (`reader.session_argument`).

    Raises a `GateError` if `slug` names no document the gate will serve — an
    unknown slug, or one `forget` withdrew. `require_document` owns both
    wordings, so a slug refused here is refused in the same words a read
    refuses it in.
    """
    if slug is not None:
        require_document(registry, slug)
    hits = registry.search(query, slug=slug, limit=limit)
    beside = adjoining(registry, (hit.anchor for hit in hits))
    _mint(registry, session, hits, beside)
    return render_search(query, hits, slug=slug, session_flag=session_flag, beside=beside)


def render_search(
    query: str,
    hits: Iterable[SearchHit],
    *,
    slug: str | None = None,
    session_flag: str | None = None,
    beside: Mapping[str, Adjoining] | None = None,
) -> str:
    """Render search results. Pure: minting happens in `search`.

    `beside` is `reader.adjoining`'s answer for these hits, keyed by token;
    a hit it names nothing for renders exactly as it did before there was one.

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
    carried = session_argument(session_flag)
    if not hits and not total:
        return "\n".join(
            [
                f'No results for "{query}"{scope}.',
                *note,
                "",
                f"[List documents: backdraft read{carried}]",
            ]
        )

    if total > len(hits):
        count = f"{len(hits)} of {total} results"
    else:
        count = f"{len(hits)} result" if len(hits) == 1 else f"{len(hits)} results"
    lines = [f'{count} for "{query}"{scope}', *note, ""]
    beside = beside or {}
    for hit in hits:
        lines.append(f"[{hit.anchor.token}]  {hit.slug} p{hit.page_number}")
        lines.append(f"  {excerpt(hit.anchor.receipt.snippet)}")
        if hit.anchor.token in beside:
            lines += adjoining_lines(hit.anchor, beside[hit.anchor.token], indent="  ")
        lines.append("")

    seen: list[tuple[str, int]] = []
    for hit in hits:
        if (hit.slug, hit.page_number) not in seen:
            seen.append((hit.slug, hit.page_number))
    lines += [f"[Read the page: backdraft read {s} p{n}{carried}]" for s, n in seen]
    if total > len(hits):
        lines.append(_widen_hint(query, slug, total, carried))
    if any(hit.anchor.token in beside for hit in hits):
        lines += ["", ADJOINING_NOTE]
    return "\n".join(line.rstrip() for line in lines).rstrip("\n")


def _widen_hint(query: str, slug: str | None, total: int, carried: str = "") -> str:
    """The line that names the command showing the results `--limit` cut.

    `read`'s continuation hint is the model: say what was withheld and give the
    exact command that produces it, rather than leaving the caller to work out
    which flag to move. The query is shell-quoted because a real one carries `$`
    and commas, and a hint that has to be repaired before it runs is not a hint.
    `carried` is the typed `--session`, since the wider search mints too.
    """
    scope = f" --in {slug}" if slug else ""
    return (
        f"[See all {total}: backdraft search {shlex.quote(query)}{scope} "
        f"--limit {total}{carried}]"
    )


def _mint(
    registry: Registry,
    session: str | None,
    hits: Iterable[SearchHit],
    beside: Mapping[str, Adjoining],
) -> None:
    """Record every result's anchor, and every chunk named beside one, under the session."""
    if session is None:
        return
    shown = [hit.anchor for hit in hits]
    shown += [a for pair in beside.values() for a in (pair.before, pair.after) if a is not None]
    anchor_ids = sorted({anchor.id for anchor in shown if anchor.id is not None})
    if not anchor_ids:
        return
    session_id = registry.ensure_session(session)
    registry.record_shown(session_id, anchor_ids)
