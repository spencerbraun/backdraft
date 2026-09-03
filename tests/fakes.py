"""An in-memory Registry for bind's tests.

W1 owns `registry/store.py`; W3 only consumes the surface Addendum A pins. This
fake implements exactly the names bind touches — `resolve`, `was_shown`,
`search`, `document`, `ensure_session`, `save_binding`, `close` — with the same
return shapes, so a test can put a registry into any state bind must handle
(drifted generation, missing anchor, empty ledger) without a database.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from backdraft.kernel.hashing import snippet_hash, token_hash
from backdraft.kernel.model import Anchor, Document, Receipt
from backdraft.kernel.tokens import format_token, parse_locator


@dataclass(frozen=True)
class FakeResolution:
    """`Resolution(anchor, current)` — the shape Addendum A pins."""

    anchor: Anchor
    current: bool


@dataclass(frozen=True)
class FakeSearchHit:
    """`SearchHit(anchor, slug, page_number)`."""

    anchor: Anchor
    slug: str
    page_number: int


@dataclass
class FakeAnchorRegistry:
    """Anchors, documents, a ledger and a bindings table, all in memory."""

    _anchors: dict[str, FakeResolution] = field(default_factory=dict)
    _documents: dict[str, Document] = field(default_factory=dict)
    _shown: set[tuple[str, str]] = field(default_factory=set)
    bindings: list[dict[str, object]] = field(default_factory=list)
    sessions: list[str] = field(default_factory=list)
    closed: bool = False

    # --- test setup -------------------------------------------------------

    def add_anchor(
        self,
        slug: str,
        locator: str,
        snippet: str,
        *,
        current: bool = True,
        page_number: int = 1,
        anchor_id: int | None = None,
    ) -> Anchor:
        """Mint an anchor exactly as ingest would: token hash over the snippet."""
        parsed = parse_locator(locator)
        digest = token_hash(snippet)
        anchor = Anchor(
            slug=slug,
            locator=parsed,
            receipt=Receipt(snippet=snippet, snippet_sha256=snippet_hash(snippet)),
            token=format_token(slug, parsed, digest),
            page_number=page_number,
            id=anchor_id if anchor_id is not None else len(self._anchors) + 1,
        )
        self._anchors[anchor.token] = FakeResolution(anchor=anchor, current=current)
        self._documents.setdefault(
            slug,
            Document(
                slug=slug,
                sha256="0" * 64,
                path=f"/corpus/{slug}.pdf",
                filename=f"{slug}.pdf",
                media_type="pdf",
                created_at="2026-07-27T00:00:00Z",
            ),
        )
        return anchor

    def add_document(self, slug: str, filename: str, *, url: str | None = None) -> Document:
        """`url` makes it a fetched source, shaped as the registry shapes one:
        `path` is the address, `filename` names the staging file, and `meta`
        carries the origin — the case where the two disagree about the name."""
        document = Document(
            slug=slug,
            sha256="0" * 64,
            path=url or f"/corpus/{filename}",
            filename=filename,
            media_type="html" if url else "pdf",
            created_at="2026-07-27T00:00:00Z",
            meta=None if url is None else {"url": url, "fetched_at": "2026-07-27T00:00:00Z"},
        )
        self._documents[slug] = document
        return document

    def show(self, session_id: str, token: str) -> None:
        """Record a token as minted into `session_id`'s context."""
        self._shown.add((session_id, token))

    # --- Addendum A -------------------------------------------------------

    def resolve(self, token: str) -> FakeResolution | None:
        return self._anchors.get(token)

    def anchors_for_page(self, slug: str, number: int) -> list[Anchor]:
        """Current-generation anchors on one page, as Addendum A pins."""
        return [
            resolution.anchor
            for resolution in self._anchors.values()
            if resolution.current
            and resolution.anchor.slug == slug
            and resolution.anchor.page_number == number
        ]

    def document(self, slug: str) -> Document | None:
        return self._documents.get(slug)

    def search(
        self, query: str, *, slug: str | None = None, limit: int = 20
    ) -> list[FakeSearchHit]:
        """Naive token-overlap ranking — enough to exercise proposals.

        Understands the slice of FTS5 syntax bind actually emits: quoted terms
        joined by `OR`. Anything cleverer would be testing a reimplementation of
        FTS5 rather than bind.
        """
        terms = {
            word.lower().strip('"')
            for word in query.split()
            if word and word.upper() not in {"OR", "AND", "NOT"}
        }
        terms.discard("")
        scored: list[tuple[int, Anchor]] = []
        for resolution in self._anchors.values():
            anchor = resolution.anchor
            if slug is not None and anchor.slug != slug:
                continue
            words = {word.lower().strip(".,") for word in anchor.receipt.snippet.split()}
            score = len(terms & words)
            if score:
                scored.append((score, anchor))
        scored.sort(key=lambda item: (-item[0], item[1].token))
        return [
            FakeSearchHit(anchor=anchor, slug=anchor.slug, page_number=anchor.page_number or 1)
            for _score, anchor in scored[:limit]
        ]

    def ensure_session(self, session_id: str | None, label: str | None = None) -> str:
        resolved = session_id or "default"
        self.sessions.append(resolved)
        return resolved

    def record_shown(self, session_id: str, anchor_ids) -> None:
        for resolution in self._anchors.values():
            if resolution.anchor.id in set(anchor_ids):
                self._shown.add((session_id, resolution.anchor.token))

    def was_shown(self, session_id: str, token: str) -> bool:
        return (session_id, token) in self._shown

    def save_binding(
        self, *, doc_path: str, session_id: str | None, mode: str, report_json: str
    ) -> int:
        self.bindings.append(
            {
                "doc_path": doc_path,
                "session_id": session_id,
                "mode": mode,
                "report_json": report_json,
            }
        )
        return len(self.bindings)

    def close(self) -> None:
        self.closed = True
