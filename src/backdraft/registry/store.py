"""The Registry: the only stateful object in the system.

It owns one SQLite file under `.backdraft/` and everything in it — documents,
extraction generations, pages, anchors, the FTS index, the ledger, bindings. The
kernel stays pure; the gate, bind and render layers read through this surface and
implement none of it (SPEC.md § Addendum A pins the surface).

Two behaviours carry the design and are worth stating plainly:

**Anchors are eager.** Ingest mints every chunk and every populated cell up
front. They are cheap rows, and it means `search`, `read` and `bind` all hit one
table — the contract is only that any token the gate ever emitted resolves, and
minting everything at ingest is the simplest way to guarantee it.

**Tokens survive re-ingest.** A new extraction is a new generation; the old one
keeps its anchors and loses `is_current`. Each new anchor whose locator *and*
snippet hash match the prior current generation keeps that generation's token
verbatim, so editing page 4 of a PDF leaves every citation on pages 1-3 exactly
where it was. `resolve` reports which generation answered, and bind turns
"answered by an old one" into `drifted`.
"""

from __future__ import annotations

import json
import re
import sqlite3
import unicodedata
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable, Sequence

from ..extract import ExtractedPage, base as extract_base
from ..kernel import chunking
from ..kernel.errors import BackdraftError, TokenError
from ..kernel.hashing import TOKEN_HASH_LENGTHS, config_hash, content_hash, snippet_hash
from ..kernel.claims import parse_citation
from ..kernel.model import (
    Anchor,
    CellValue,
    Citation,
    CitationStatus,
    Document,
    MediaType,
    Page,
    Receipt,
)
from ..kernel.tokens import ChunkLocator, PageLocator, format_token
from ..kernel.tokens import parse as parse_token
from ..kernel.tokens import parse_locator
from . import ledger as ledger_module

__all__ = [
    "CREATED",
    "DIRECTORY",
    "EXPORT_FORMAT",
    "GENERATION",
    "UNCHANGED",
    "Ingested",
    "Registry",
    "RegistryError",
    "Resolution",
    "SearchHit",
    "SearchResults",
    "citation_for",
    "current_at",
    "media_type_for",
    "sanitize_sheet_name",
    "slug_for",
]

DIRECTORY = ".backdraft"
"""The per-project registry directory, found by walking up from cwd."""

DATABASE = "registry.db"

EXPORT_FORMAT = "backdraft/registry-v1"
"""NOTE: the spec does not name the export; a format string makes the dump
self-describing, matching the artifact's `$format` habit."""

SLUG_MAX = 32
"""A slug is 2-32 characters (kernel/tokens.py enforces the grammar)."""

CREATED = "created"
"""`ingest` outcome: the registry had no such document."""

GENERATION = "generation"
"""`ingest` outcome: a new extraction generation of a document already here.

The one outcome with a consequence for existing work — citations into the
generation just superseded resolve to it still, and `bind` reports them
`drifted`.
"""

UNCHANGED = "unchanged"
"""`ingest` outcome: a no-op. Same bytes, same deterministic extractor, same
config, so the current generation is already the answer and nothing was
written — no second generation, and every token untouched."""

_SCHEMA = Path(__file__).with_name("schema.sql")
_NON_SLUG = re.compile(r"[^a-z0-9]+")
_MEDIA_SUFFIXES: dict[str, MediaType] = {
    ".pdf": "pdf",
    ".xlsx": "xlsx",
    ".xlsm": "xlsx",
    ".xltx": "xlsx",
    ".xltm": "xlsx",
    ".xls": "xls",
    ".csv": "csv",
    ".tsv": "csv",
    ".docx": "docx",
    ".pptx": "pptx",
    ".png": "image",
    ".jpg": "image",
    ".jpeg": "image",
    ".tif": "image",
    ".tiff": "image",
    ".webp": "image",
    ".html": "html",
    ".htm": "html",
    ".xhtml": "html",
}


class RegistryError(BackdraftError):
    """The registry could not do what was asked of it."""


@dataclass(frozen=True, slots=True)
class Ingested(Document):
    """The document, plus which of ingest's three outcomes produced it.

    `ingest` does one of three things and used to report all three identically:
    it creates a document, adds a *new generation* to one whose bytes or config
    moved, or does nothing at all because re-running would reproduce what is
    already there. The distinction is not cosmetic — a new generation is the
    moment citations into the previous one may start reporting `drifted`, which
    is the one thing a caller re-ingesting after an edit most needs to know.

    A `Document` subclass rather than a new return type, for the reason
    `SearchResults` is a `list` subclass: Addendum A pins `ingest` to
    `-> Document`, and this still is one — every caller that reads `.slug` is
    unaffected, the fakes keep working, and the one caller that cares reads
    `outcome`.

    One consequence of that, since a dataclass compares by class: an `Ingested`
    never equals the plain `Document` the read side returns for the same row.
    Compare what persists — `slug`, `sha256`, `id` — rather than the objects.
    """

    outcome: str = CREATED


@dataclass(frozen=True, slots=True)
class Resolution:
    """What `resolve` found: the anchor, and whether it is still current.

    `current=False` means the token names a superseded generation — the snippet
    is what the writer actually saw, and bind maps this to status `drifted`.
    """

    anchor: Anchor
    current: bool


@dataclass(frozen=True, slots=True)
class SearchHit:
    """One search result: a mintable anchor and where it lives."""

    anchor: Anchor
    slug: str
    page_number: int


class SearchResults(list[SearchHit]):
    """The hits, plus how the query had to be run to get them.

    `search` retries a query FTS5 cannot parse as a quoted phrase, which changes
    what "no results" means: `1.42x` as a phrase matches the two tokens `1.42`
    and `x` adjacent, not the boolean query the caller wrote. A silent retry
    makes an empty result look like an absent fact, so the fallback is reported.

    A `list` subclass rather than a new return type on purpose: Addendum A pins
    `search` to `list[SearchHit]`, and this still is one — every caller that
    iterates, indexes or measures it is unaffected, and the one caller that
    cares reads the flag.
    """

    __slots__ = ("phrase_fallback",)

    def __init__(self, hits: Iterable[SearchHit] = (), *, phrase_fallback: bool = False):
        super().__init__(hits)
        self.phrase_fallback = phrase_fallback


def media_type_for(path: Path) -> MediaType:
    """The media type of a file, by extension. Anything unknown is text."""
    return _MEDIA_SUFFIXES.get(path.suffix.lower(), "text")


def slug_for(filename: str) -> str:
    """The slug a filename suggests: kebab, lowercase, truncated to 32.

    NOTE: the grammar needs at least two characters starting with alnum-lower, so
    a degenerate stem (`a.pdf`, `_.txt`) is padded rather than rejected —
    refusing to ingest a file over its name would be absurd. Truncation cuts
    wherever 32 characters land, which is often mid-word and sometimes on a
    hyphen; the hyphen is trimmed afterwards, so a long name yields `q4-report`
    rather than `q4-report-`.
    """
    stem = unicodedata.normalize("NFKD", Path(filename).stem).encode("ascii", "ignore")
    base = _NON_SLUG.sub("-", stem.decode("ascii").lower()).strip("-")[:SLUG_MAX].rstrip("-")
    if len(base) < 2:
        base = f"{base}-doc".strip("-") if base else "doc"
    return base


def sanitize_sheet_name(name: str) -> str:
    """A sheet name reduced to the sheetref charset: lowercase kebab.

    The grammar forbids `:` `!` `;` `(` `)` and whitespace inside a sheetref;
    this goes further and kebabs the whole name, so `Rent Roll (2025)` becomes
    `rent-roll-2025` and a token stays readable and typeable.
    """
    reduced = _NON_SLUG.sub("-", unicodedata.normalize("NFC", name).lower()).strip("-")
    return reduced or "sheet"


def current_at(registry: "Registry", anchor: Anchor) -> Anchor | None:
    """The current generation's anchor at `anchor`'s locator, if it survived.

    The other half of drift. `Registry.resolve` finds the anchor a token names in
    whichever generation holds it and says whether that generation is current;
    when it is not, this is what stands at the same locator now. Two callers need
    exactly that — `bind` to fill a `drifted` citation's two sides, the gate to
    print them under `show` — and the dependency rule forbids either importing
    the other, so the answer lives with `anchors_for_page`, which is where it
    was always read from.

    A module function rather than a `Registry` method on purpose: it composes the
    pinned surface and adds nothing to it, so the fakes W2 and W3 test against
    (SPEC § Addendum A) keep working unchanged. Takes anything with
    `anchors_for_page` for the same reason.

    None when the locator is gone from the current extraction — a page that lost
    a chunk, or lost the page. Callers differ on what to do with that, which is
    why this answers the lookup and stops there.
    """
    if anchor.page_number is None:
        return None
    for candidate in registry.anchors_for_page(anchor.slug, anchor.page_number):
        if candidate.locator == anchor.locator:
            return candidate
    return None


def citation_for(registry: "Registry", token: str) -> Citation:
    """What one token says against this registry, with no session in the picture.

    The token-to-status walk, in one place. `bind` takes it to resolve a
    document's citations and `verify` takes it to re-check an artifact against
    the sources, and the dependency rule forbids either importing the other —
    which is how one six-line decision tree becomes two. So it lives beside
    `current_at`, for the same reason and by the same rule: a module function
    that composes the pinned surface without widening it.

    Four of the five statuses come back. `malformed` is decided by
    `kernel.claims.parse_citation`, the same call bind's kernel step makes, so
    the reserved `bd:calc(...)` form lands identically everywhere; `drifted`
    carries the superseded snippet in `drifted_from` and the anchor standing at
    that locator now (or, when the locator itself is gone, the cited one, so the
    two sides of the diff agree). `not_shown` is deliberately absent: it is a
    fact about a ledger session, and the caller that has one adds it — see
    `bind.binder._resolve_citation`.

    NOTE: the gate's `show` walks the same tree and keeps its own copy, on
    purpose. It mints what it prints, and a drift mints *both* anchors — the
    cited one and the one standing there now — which a `Citation` cannot carry:
    it holds one anchor and the other side's snippet. Folding `show` in here
    would mean widening the return value for the one caller that needs more.
    """
    citation = parse_citation(token)
    if citation.status is CitationStatus.MALFORMED:
        return citation
    resolution = registry.resolve(token)
    if resolution is None:
        return Citation(token=token, status=CitationStatus.UNRESOLVED)
    anchor = resolution.anchor
    if resolution.current:
        return Citation(token=token, status=CitationStatus.RESOLVED, anchor=anchor)
    return Citation(
        token=token,
        status=CitationStatus.DRIFTED,
        anchor=current_at(registry, anchor) or anchor,
        drifted_from=anchor.receipt.snippet,
    )


class Registry:
    """SQLite + FTS5 behind the surface in SPEC.md § Addendum A."""

    def __init__(self, root: Path, connection: sqlite3.Connection) -> None:
        self.root = root
        self._connection = connection

    # ---- lifecycle ----------------------------------------------------------

    @classmethod
    def open(cls, root: Path) -> "Registry":
        """Open (creating if needed) the registry under `root/.backdraft/`.

        Discovery — which `root` — lives in the CLI. Creating the schema here
        rather than in `init` keeps every entry point working against a fresh
        checkout, and the DDL is idempotent.
        """
        root = Path(root)
        directory = root / DIRECTORY
        directory.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(directory / DATABASE)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        with connection:
            connection.executescript(_SCHEMA.read_text(encoding="utf-8"))
        return cls(root, connection)

    def close(self) -> None:
        """Close the underlying connection. Idempotent."""
        self._connection.close()

    def __enter__(self) -> "Registry":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    # ---- write side ---------------------------------------------------------

    def ingest(
        self,
        path: Path,
        *,
        extractor: str | None = None,
        slug: str | None = None,
        config: dict | None = None,
        url: str | None = None,
        fetched_at: str | None = None,
    ) -> Document:
        """Snapshot a file into a new extraction generation.

        Runs the extractor, writes pages, mints every anchor and rebuilds the
        file's search rows. Tokens carry over from the prior current generation
        wherever locator and snippet hash both match.

        Re-ingesting identical bytes with the same deterministic extractor and
        config is a no-op: the existing generation is already the answer, so no
        second generation is created and every token is untouched.

        `extractor` names one (`None` or `"auto"` picks the first that can handle
        the file). `slug` is honoured only when the document is new — a slug is
        stable once assigned. `config` is hashed into the generation's identity,
        and is validated against the chosen extractor's declared keys first, so
        a key that extractor never reads raises rather than silently hashing
        into a generation nothing asked for.

        `url` says the file at `path` is a snapshot staged from the web: the
        document then records the URL as its path and carries `{url,
        fetched_at}` as meta, and continuity across re-fetches follows the URL
        rather than the temporary file the bytes were staged in. Identity is
        still the sha256 of those bytes — a page that changed since the last
        fetch is a new generation of the same document, exactly like an edited
        file. Fetching is the caller's job; the registry opens no sockets.

        Returns an `Ingested` — a `Document` carrying `outcome`, one of
        `CREATED`, `GENERATION` or `UNCHANGED`. The registry knows which of the
        three happened; deriving it again from outside would mean
        re-implementing `_is_noop`, so it is reported rather than re-derived.
        """
        path = Path(path)
        try:
            data = path.read_bytes()
        except OSError as error:
            raise RegistryError(f"cannot read {path}: {error}") from error

        sha256 = content_hash(data)
        media_type = media_type_for(path)
        chosen = (
            extract_base.select(path, media_type, config)
            if extractor in (None, "auto")
            else extract_base.get(extractor)
        )
        settings = dict(config or {})
        # After selection, never before: `auto` picks per file, so only the
        # chosen extractor can say whether `dpi` is a setting or a typo. Before
        # the no-op check, so a misspelled key fails on a re-ingest too.
        extract_base.check_config(chosen, settings)
        settings_hash = config_hash(settings)

        existing = self._find_document(sha256=sha256, path=path, url=url)
        if existing is not None and self._is_noop(existing, sha256, chosen, settings_hash):
            # A re-fetch that changed nothing still moves the clock: `fetched_at`
            # is when the page was last confirmed to say this, which is the
            # question a reader of a months-old citation actually has.
            return _ingested(self._touch_meta(existing, url, fetched_at), UNCHANGED)

        pages = list(chosen.extract(path, settings))

        now = _now()
        with self._connection:
            document = self._upsert_document(
                existing, sha256, path, media_type, slug, now, url, fetched_at
            )
            previous = self._current_extraction_id(document.id)
            self._connection.execute(
                "UPDATE extractions SET is_current = 0 WHERE document_id = ? AND is_current = 1",
                (document.id,),
            )
            extraction_id = self._insert_extraction(document.id, chosen, settings_hash, now)
            self._write_pages(document, extraction_id, previous, pages, now)
        return _ingested(document, CREATED if existing is None else GENERATION)

    # ---- read side ----------------------------------------------------------

    def documents(self) -> list[Document]:
        """Every ingested document, oldest first."""
        meta = self._meta_by_document()
        return [
            _document(row, meta.get(row["id"]))
            for row in self._connection.execute(
                "SELECT * FROM documents ORDER BY created_at, id"
            )
        ]

    def document(self, slug: str) -> Document | None:
        """One document by slug, or None."""
        row = self._connection.execute(
            "SELECT * FROM documents WHERE slug = ?", (slug,)
        ).fetchone()
        return _document(row, self._meta_for(row["id"])) if row else None

    def pages(self, slug: str) -> list[Page]:
        """The current extraction's pages, in order. Sheets carry their cells."""
        extraction_id = self._current_extraction_for_slug(slug)
        if extraction_id is None:
            return []
        cells = self._cells_by_page(extraction_id)
        meta = self._meta_by_page(extraction_id)
        return [
            _page(row, cells.get(row["number"], ()), meta.get(row["number"]))
            for row in self._connection.execute(
                "SELECT * FROM pages WHERE extraction_id = ? ORDER BY number",
                (extraction_id,),
            )
        ]

    def page(self, slug: str, number: int) -> Page | None:
        """One page of the current extraction, or None."""
        extraction_id = self._current_extraction_for_slug(slug)
        if extraction_id is None:
            return None
        row = self._connection.execute(
            "SELECT * FROM pages WHERE extraction_id = ? AND number = ?",
            (extraction_id, number),
        ).fetchone()
        if row is None:
            return None
        return _page(
            row,
            self._cells_by_page(extraction_id).get(number, ()),
            self._meta_by_page(extraction_id).get(number),
        )

    def page_image(self, slug: str, number: int) -> extract_base.PageImage | None:
        """The stored visual snapshot of one current-extraction page, or None.

        Present when the extractor supplied one at ingest (the VLM path) or when
        `snapshot-pages` backfilled it; absent for text-only extractions.
        """
        extraction_id = self._current_extraction_for_slug(slug)
        if extraction_id is None:
            return None
        row = self._connection.execute(
            "SELECT format, width, height, data FROM page_images "
            "WHERE extraction_id = ? AND number = ?",
            (extraction_id, number),
        ).fetchone()
        if row is None:
            return None
        return extract_base.PageImage(
            data=row["data"], format=row["format"],
            width=int(row["width"]), height=int(row["height"]),
        )

    def save_page_image(
        self,
        extraction_id: int,
        number: int,
        *,
        data: bytes,
        format: str,
        width: int,
        height: int,
    ) -> None:
        """Store (or replace) one page's visual snapshot. Commits."""
        with self._connection:
            self._connection.execute(
                "INSERT OR REPLACE INTO page_images "
                "(extraction_id, number, format, width, height, data) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (extraction_id, number, format, width, height, data),
            )

    def current_extraction_id(self, slug: str) -> int | None:
        """The current generation's id for `slug`, or None. For backfill tools."""
        return self._current_extraction_for_slug(slug)

    def anchors_for_page(self, slug: str, number: int) -> list[Anchor]:
        """Every anchor on one page of the current extraction, in mint order.

        The page anchor comes first, then its chunks or cells — the order the
        gate renders them in.
        """
        extraction_id = self._current_extraction_for_slug(slug)
        if extraction_id is None:
            return []
        return [
            _anchor(row, slug)
            for row in self._connection.execute(
                "SELECT * FROM anchors WHERE extraction_id = ? AND page_number = ? ORDER BY id",
                (extraction_id, number),
            )
        ]

    def resolve(self, token: str) -> Resolution | None:
        """Find the anchor a token names, in any generation.

        Current generation wins; otherwise the most recent generation that has
        it answers with `current=False`. A token that does not parse — including
        the reserved `bd:calc(...)` form — resolves to None, because a malformed
        citation is bind's to report, not the registry's to guess at.
        """
        try:
            parse_token(token)
        except TokenError:
            return None
        row = self._connection.execute(
            "SELECT anchors.*, documents.slug AS slug, extractions.is_current AS is_current "
            "FROM anchors "
            "JOIN extractions ON extractions.id = anchors.extraction_id "
            "JOIN documents ON documents.id = extractions.document_id "
            "WHERE anchors.token = ? "
            "ORDER BY extractions.is_current DESC, extractions.created_at DESC, extractions.id DESC "
            "LIMIT 1",
            (token,),
        ).fetchone()
        if row is None:
            return None
        return Resolution(anchor=_anchor(row, row["slug"]), current=bool(row["is_current"]))

    def search(
        self, query: str, *, slug: str | None = None, limit: int = 20
    ) -> SearchResults:
        """Full-text search over the current generation's anchors.

        Results are anchors, so a searched snippet is citable without a page read
        — otherwise every search is followed by a page read purely to obtain
        something quotable.

        The query is FTS5 syntax, so `covenant OR NOI` and `NEAR(rent roll)`
        work. NOTE: a query FTS5 cannot parse — `1.42x`, `Q4/2025`, anything with
        punctuation — is retried as a quoted phrase rather than rejected. Analysts
        search for numbers, and a number is not a syntax error. The retry is
        recorded on the result (`phrase_fallback`) rather than hidden: it changes
        what the query means, so the caller gets to say so.
        """
        try:
            return SearchResults(self._search(query, slug, limit))
        except sqlite3.OperationalError:
            phrase = '"' + query.replace('"', '""') + '"'
        try:
            return SearchResults(
                self._search(phrase, slug, limit), phrase_fallback=True
            )
        except sqlite3.OperationalError as error:  # pragma: no cover - phrases always parse
            raise RegistryError(f"invalid search query {query!r}: {error}") from error

    def _search(self, query: str, slug: str | None, limit: int) -> list[SearchHit]:
        sql = (
            "SELECT anchors.*, documents.slug AS slug "
            "FROM search "
            "JOIN anchors ON anchors.token = search.token "
            "JOIN extractions ON extractions.id = anchors.extraction_id AND extractions.is_current = 1 "
            "JOIN documents ON documents.id = extractions.document_id "
            "WHERE search MATCH ?"
        )
        parameters: list[Any] = [query]
        if slug is not None:
            sql += " AND documents.slug = ?"
            parameters.append(slug)
        sql += " ORDER BY rank LIMIT ?"
        parameters.append(limit)
        rows = self._connection.execute(sql, parameters).fetchall()
        return [
            SearchHit(
                anchor=_anchor(row, row["slug"]),
                slug=row["slug"],
                page_number=row["page_number"],
            )
            for row in rows
        ]

    # ---- ledger -------------------------------------------------------------

    def ensure_session(self, session_id: str | None, label: str | None = None) -> str:
        """Return an existing session id, or create one (generating an id if needed)."""
        with self._connection:
            return ledger_module.ensure_session(self._connection, session_id, label, _now())

    def record_shown(self, session_id: str, anchor_ids: Sequence[int]) -> None:
        """Record that these anchors were minted into the session's context."""
        with self._connection:
            ledger_module.record_shown(self._connection, session_id, anchor_ids, _now())

    def was_shown(self, session_id: str, token: str) -> bool:
        """True if this session was ever shown the anchor this token names."""
        return ledger_module.was_shown(self._connection, session_id, token)

    # ---- bind persistence ---------------------------------------------------

    def save_binding(
        self,
        *,
        doc_path: str,
        session_id: str | None,
        mode: str,
        report_json: str,
    ) -> int:
        """Store one bind run's report. Returns the binding's row id."""
        with self._connection:
            cursor = self._connection.execute(
                "INSERT INTO bindings (doc_path, session_id, mode, report_json, bound_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (doc_path, session_id, mode, report_json, _now()),
            )
        return int(cursor.lastrowid or 0)

    def export_json(self) -> dict:
        """The whole registry as plain JSON-able data, for portability and diffing.

        Every generation is included, not just the current one: the superseded
        anchors are what make a drifted citation explainable.
        """
        documents: list[dict] = []
        for document in self.documents():
            extractions = []
            for extraction in self._connection.execute(
                "SELECT * FROM extractions WHERE document_id = ? ORDER BY created_at, id",
                (document.id,),
            ):
                extractions.append(
                    {
                        "id": extraction["id"],
                        "extractor": extraction["extractor"],
                        "extractor_version": extraction["extractor_version"],
                        "config_hash": extraction["config_hash"],
                        "deterministic": bool(extraction["deterministic"]),
                        "is_current": bool(extraction["is_current"]),
                        "created_at": extraction["created_at"],
                        "pages": [
                            {
                                "number": page["number"],
                                "kind": page["kind"],
                                "name": page["name"],
                                "text": page["text"],
                                "summary": page["summary"],
                            }
                            for page in self._connection.execute(
                                "SELECT * FROM pages WHERE extraction_id = ? ORDER BY number",
                                (extraction["id"],),
                            )
                        ],
                        "anchors": [
                            {
                                "id": anchor["id"],
                                "page_number": anchor["page_number"],
                                "kind": anchor["kind"],
                                "locator": anchor["locator"],
                                "snippet": anchor["snippet"],
                                "snippet_sha256": anchor["snippet_sha256"],
                                "token": anchor["token"],
                                "start": anchor["start_off"],
                                "end": anchor["end_off"],
                                "created_at": anchor["created_at"],
                            }
                            for anchor in self._connection.execute(
                                "SELECT * FROM anchors WHERE extraction_id = ? ORDER BY id",
                                (extraction["id"],),
                            )
                        ],
                    }
                )
            entry: dict[str, Any] = {
                "slug": document.slug,
                "sha256": document.sha256,
                "path": document.path,
                "filename": document.filename,
                "media_type": document.media_type,
                "created_at": document.created_at,
            }
            if document.meta:
                # Only where there is provenance to carry, so an export of a
                # registry of files is unchanged from before URL sources.
                entry["meta"] = document.meta
            entry["extractions"] = extractions
            documents.append(entry)
        return {
            "$format": EXPORT_FORMAT,
            "documents": documents,
            "sessions": ledger_module.sessions(self._connection),
            "ledger": [
                {
                    "session_id": row["session_id"],
                    "token": row["token"],
                    "shown_at": row["shown_at"],
                }
                for row in self._connection.execute(
                    "SELECT ledger.session_id, anchors.token AS token, ledger.shown_at "
                    "FROM ledger JOIN anchors ON anchors.id = ledger.anchor_id "
                    "ORDER BY ledger.shown_at, ledger.anchor_id"
                )
            ],
            "bindings": [
                {
                    "id": row["id"],
                    "doc_path": row["doc_path"],
                    "session_id": row["session_id"],
                    "mode": row["mode"],
                    "report": json.loads(row["report_json"]),
                    "bound_at": row["bound_at"],
                }
                for row in self._connection.execute("SELECT * FROM bindings ORDER BY id")
            ],
        }

    # ---- ingest internals ---------------------------------------------------

    def _find_document(
        self, *, sha256: str, path: Path, url: str | None = None
    ) -> Document | None:
        """The document this ingest is about, if the registry already has it.

        Matched by bytes, then by origin — the URL for a fetched source, the
        path for a file. NOTE: the spec identifies a document by its bytes, but
        a re-ingest of an *edited* file has different bytes and must still be
        the same document — otherwise nothing ever drifts, it just becomes a
        second document. Origin continuity carries identity across an edit.
        `slug` deliberately does not participate: it names a *new* document, and
        a taken slug is an error rather than a silent retarget.

        Bytes are checked first because `documents.sha256` is UNIQUE: when the
        same content arrives twice under two origins it is one document, and
        deciding otherwise would be a constraint violation rather than a policy.
        """
        meta = self._meta_by_document()
        row = self._connection.execute(
            "SELECT * FROM documents WHERE sha256 = ?", (sha256,)
        ).fetchone()
        if row is not None:
            return _document(row, meta.get(row["id"]))
        target = None if url is not None else path.resolve()
        for row in self._connection.execute("SELECT * FROM documents ORDER BY id"):
            origin = (meta.get(row["id"]) or {}).get("url")
            if url is not None:
                if origin == url:
                    return _document(row, meta.get(row["id"]))
                continue
            # A fetched document's `path` is its URL, so it can never be the
            # file being ingested — and resolving it as one would be nonsense.
            if origin is None and Path(row["path"]).resolve() == target:
                return _document(row, meta.get(row["id"]))
        return None

    def _meta_by_document(self) -> dict[int, dict]:
        """Provenance metadata per document id, absent for documents with none."""
        return {
            row["document_id"]: json.loads(row["meta"])
            for row in self._connection.execute("SELECT * FROM document_meta")
        }

    def _meta_for(self, document_id: int) -> dict | None:
        row = self._connection.execute(
            "SELECT meta FROM document_meta WHERE document_id = ?", (document_id,)
        ).fetchone()
        return json.loads(row["meta"]) if row else None

    def _save_meta(self, document_id: int, meta: dict) -> None:
        self._connection.execute(
            "INSERT OR REPLACE INTO document_meta (document_id, meta) VALUES (?, ?)",
            (document_id, json.dumps(meta, separators=(",", ":"), sort_keys=True)),
        )

    def _touch_meta(
        self, document: Document, url: str | None, fetched_at: str | None
    ) -> Document:
        """Record a re-fetch that produced identical bytes. No new generation."""
        if url is None:
            return document
        meta = {**(document.meta or {}), "url": url}
        if fetched_at is not None:
            meta["fetched_at"] = fetched_at
        with self._connection:
            self._save_meta(document.id, meta)  # type: ignore[arg-type]
        return replace(document, meta=meta)

    def _is_noop(
        self, document: Document, sha256: str, extractor: Any, settings_hash: str
    ) -> bool:
        """True if re-running this extractor would reproduce the current generation."""
        if document.sha256 != sha256 or not extractor.deterministic:
            return False
        row = self._connection.execute(
            "SELECT 1 FROM extractions WHERE document_id = ? AND is_current = 1 "
            "AND extractor = ? AND extractor_version = ? AND config_hash = ? "
            "AND deterministic = 1",
            (document.id, extractor.name, extractor.version, settings_hash),
        ).fetchone()
        return row is not None

    def _upsert_document(
        self,
        existing: Document | None,
        sha256: str,
        path: Path,
        media_type: MediaType,
        slug: str | None,
        now: str,
        url: str | None = None,
        fetched_at: str | None = None,
    ) -> Document:
        """Insert a new document, or point an existing one at the new bytes."""
        # A fetched source records where it came from, not where it was staged:
        # the staging file is gone by the time anything reads this.
        stored_path = url if url is not None else str(path)
        meta = None if url is None else {"url": url, "fetched_at": fetched_at or now}
        if existing is not None:
            self._connection.execute(
                "UPDATE documents SET sha256 = ?, path = ?, filename = ?, media_type = ? "
                "WHERE id = ?",
                (sha256, stored_path, path.name, media_type, existing.id),
            )
            if meta is not None:
                self._save_meta(existing.id, meta)  # type: ignore[arg-type]
            # NOTE: `slug` is ignored here on purpose — a slug is stable once
            # assigned, because tokens already in an authored document use it.
            return Document(
                slug=existing.slug,
                sha256=sha256,
                path=stored_path,
                filename=path.name,
                media_type=media_type,
                created_at=existing.created_at,
                meta=meta if meta is not None else existing.meta,
                id=existing.id,
            )
        assigned = self._assign_slug(slug, path.name)
        cursor = self._connection.execute(
            "INSERT INTO documents (slug, sha256, path, filename, media_type, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (assigned, sha256, stored_path, path.name, media_type, now),
        )
        document_id = int(cursor.lastrowid or 0)
        if meta is not None:
            self._save_meta(document_id, meta)
        return Document(
            slug=assigned,
            sha256=sha256,
            path=stored_path,
            filename=path.name,
            media_type=media_type,
            created_at=now,
            meta=meta,
            id=document_id,
        )

    def _assign_slug(self, requested: str | None, filename: str) -> str:
        """A slug unique in this registry, deduped `-2`, `-3`, ....

        An explicitly requested slug is never silently renamed: if it is taken,
        that is an error the caller has to see.
        """
        taken = {row[0] for row in self._connection.execute("SELECT slug FROM documents")}
        if requested is not None:
            if requested in taken:
                raise RegistryError(f"slug {requested!r} is already taken")
            return requested
        return _dedupe(slug_for(filename), taken, SLUG_MAX)

    def _insert_extraction(
        self, document_id: int | None, extractor: Any, settings_hash: str, now: str
    ) -> int:
        cursor = self._connection.execute(
            "INSERT INTO extractions (document_id, extractor, extractor_version, "
            "config_hash, deterministic, is_current, created_at) VALUES (?, ?, ?, ?, ?, 1, ?)",
            (
                document_id,
                extractor.name,
                extractor.version,
                settings_hash,
                int(bool(extractor.deterministic)),
                now,
            ),
        )
        return int(cursor.lastrowid or 0)

    def _current_extraction_id(self, document_id: int | None) -> int | None:
        row = self._connection.execute(
            "SELECT id FROM extractions WHERE document_id = ? AND is_current = 1",
            (document_id,),
        ).fetchone()
        return int(row[0]) if row else None

    def _current_extraction_for_slug(self, slug: str) -> int | None:
        row = self._connection.execute(
            "SELECT extractions.id FROM extractions "
            "JOIN documents ON documents.id = extractions.document_id "
            "WHERE documents.slug = ? AND extractions.is_current = 1",
            (slug,),
        ).fetchone()
        return int(row[0]) if row else None

    def _write_pages(
        self,
        document: Document,
        extraction_id: int,
        previous: int | None,
        pages: Iterable[ExtractedPage],
        now: str,
    ) -> None:
        """Write pages, mint their anchors, and rebuild the document's search rows."""
        carried = self._prior_anchors(previous)
        minted: dict[str, str] = {}
        sheet_names: set[str] = set()
        self._connection.execute("DELETE FROM search WHERE slug = ?", (document.slug,))

        for page in pages:
            name = page.name
            if page.kind == "sheet":
                name = _dedupe(sanitize_sheet_name(page.name or ""), sheet_names, SLUG_MAX)
                sheet_names.add(name)
            self._connection.execute(
                "INSERT INTO pages (extraction_id, number, kind, name, text, summary) "
                "VALUES (?, ?, ?, ?, ?, NULL)",
                (extraction_id, page.number, page.kind, name, page.text),
            )
            if page.image is not None:
                # Inline rather than save_page_image: this runs inside ingest's
                # transaction, which must not be committed early.
                self._connection.execute(
                    "INSERT OR REPLACE INTO page_images "
                    "(extraction_id, number, format, width, height, data) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        extraction_id, page.number, page.image.format,
                        page.image.width, page.image.height, page.image.data,
                    ),
                )
            if page.meta:
                self._connection.execute(
                    "INSERT OR REPLACE INTO page_meta (extraction_id, number, meta) "
                    "VALUES (?, ?, ?)",
                    (extraction_id, page.number, json.dumps(page.meta, separators=(",", ":"))),
                )
            for locator, snippet, offsets in _locations(page, name):
                self._insert_anchor(
                    document=document,
                    extraction_id=extraction_id,
                    page_number=page.number,
                    locator=locator,
                    snippet=snippet,
                    offsets=offsets,
                    carried=carried,
                    minted=minted,
                    now=now,
                )

    def _prior_anchors(self, extraction_id: int | None) -> dict[str, tuple[str, str]]:
        """locator -> (token, snippet_sha256) for the generation being superseded."""
        if extraction_id is None:
            return {}
        return {
            row["locator"]: (row["token"], row["snippet_sha256"])
            for row in self._connection.execute(
                "SELECT locator, token, snippet_sha256 FROM anchors WHERE extraction_id = ?",
                (extraction_id,),
            )
        }

    def _insert_anchor(
        self,
        *,
        document: Document,
        extraction_id: int,
        page_number: int,
        locator: Any,
        snippet: str,
        offsets: tuple[int, int] | None,
        carried: dict[str, tuple[str, str]],
        minted: dict[str, str],
        now: str,
    ) -> None:
        text = locator.format()
        digest = snippet_hash(snippet)
        previous = carried.get(text)
        if previous is not None and previous[1] == digest:
            token = previous[0]
            # NOTE: an inherited hash length claims its prefix only if free; token
            # stability outranks tidiness in the (vanishing) contested case.
            minted.setdefault(parse_token(token).hash, digest)
        else:
            token = format_token(document.slug, locator, _mint(digest, minted))

        start, end = offsets if offsets is not None else (None, None)
        self._connection.execute(
            "INSERT INTO anchors (extraction_id, page_number, kind, locator, snippet, "
            "snippet_sha256, token, start_off, end_off, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                extraction_id,
                page_number,
                locator.kind,
                text,
                snippet,
                digest,
                token,
                start,
                end,
                now,
            ),
        )
        if locator.kind != "page":
            # NOTE: page anchors are deliberately not indexed — a page's text is
            # the concatenation of its chunks, so indexing both would return every
            # hit twice and let a whole page outrank the paragraph that matched.
            self._connection.execute(
                "INSERT INTO search (snippet, token, slug, page) VALUES (?, ?, ?, ?)",
                (snippet, token, document.slug, str(page_number)),
            )

    def _cells_by_page(self, extraction_id: int) -> dict[int, tuple[CellValue, ...]]:
        """Cell values per page, rebuilt from the cell anchors that already hold them."""
        cells: dict[int, list[CellValue]] = {}
        for row in self._connection.execute(
            "SELECT page_number, locator, snippet FROM anchors "
            "WHERE extraction_id = ? AND kind = 'cell' ORDER BY id",
            (extraction_id,),
        ):
            locator = parse_locator(row["locator"])
            cells.setdefault(row["page_number"], []).append(
                CellValue(ref=locator.cell.format(), value=row["snippet"])  # type: ignore[union-attr]
            )
        return {number: tuple(values) for number, values in cells.items()}

    def _meta_by_page(self, extraction_id: int) -> dict[int, dict]:
        """Presentation metadata per page, absent for pages that have none."""
        return {
            row["number"]: json.loads(row["meta"])
            for row in self._connection.execute(
                "SELECT number, meta FROM page_meta WHERE extraction_id = ?",
                (extraction_id,),
            )
        }


# ---- module helpers ---------------------------------------------------------


def _locations(
    page: ExtractedPage, name: str | None
) -> list[tuple[Any, str, tuple[int, int] | None]]:
    """Every anchor a page yields: the page itself, then its chunks or cells.

    One page-kind anchor always exists, even for a blank page, so `bd:doc:p4:...`
    names something for every page number the document has.
    """
    locations: list[tuple[Any, str, tuple[int, int] | None]] = [
        (PageLocator(page=page.number), page.text, None)
    ]
    if page.kind == "sheet":
        for cell in page.cells or ():
            locator = parse_locator(f"{name}!{cell.ref}")
            locations.append((locator, cell.value, None))
        return locations
    for piece in chunking.chunk(page.text):
        locations.append(
            (
                ChunkLocator(page=page.number, ordinal=piece.ordinal),
                piece.text,
                (piece.start, piece.end),
            )
        )
    return locations


def _mint(digest: str, minted: dict[str, str]) -> str:
    """The shortest hash prefix that is unambiguous within this generation.

    Steps 4 -> 6 -> 8. Two anchors with the *same* snippet share a prefix
    happily; only two different snippets colliding force an extension.
    """
    for length in TOKEN_HASH_LENGTHS:
        prefix = digest[:length]
        if minted.setdefault(prefix, digest) == digest:
            return prefix
    raise RegistryError(f"snippet hash {digest[:8]} collides at every minted length")


def _dedupe(base: str, taken: set[str] | frozenset[str], limit: int) -> str:
    """`base`, or `base-2`, `base-3`, ... — whichever is free, within `limit` chars."""
    if base not in taken:
        return base
    ordinal = 2
    while True:
        suffix = f"-{ordinal}"
        candidate = f"{base[: limit - len(suffix)].rstrip('-')}{suffix}"
        if candidate not in taken:
            return candidate
        ordinal += 1


def _now() -> str:
    """ISO-8601 UTC, the only timestamp format in the registry."""
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _document(row: sqlite3.Row, meta: dict | None = None) -> Document:
    return Document(
        slug=row["slug"],
        sha256=row["sha256"],
        path=row["path"],
        filename=row["filename"],
        media_type=row["media_type"],
        created_at=row["created_at"],
        meta=meta,
        id=row["id"],
    )


def _ingested(document: Document, outcome: str) -> Ingested:
    """The same document, saying which of ingest's three outcomes made it."""
    return Ingested(
        slug=document.slug,
        sha256=document.sha256,
        path=document.path,
        filename=document.filename,
        media_type=document.media_type,
        created_at=document.created_at,
        meta=document.meta,
        id=document.id,
        outcome=outcome,
    )


def _page(
    row: sqlite3.Row, cells: tuple[CellValue, ...], meta: dict | None = None
) -> Page:
    return Page(
        number=row["number"],
        kind=row["kind"],
        text=row["text"],
        name=row["name"],
        summary=row["summary"],
        cells=cells,
        meta=meta,
        extraction_id=row["extraction_id"],
        id=row["id"],
    )


def _anchor(row: sqlite3.Row, slug: str) -> Anchor:
    return Anchor(
        slug=slug,
        locator=parse_locator(row["locator"]),
        receipt=Receipt(snippet=row["snippet"], snippet_sha256=row["snippet_sha256"]),
        token=row["token"],
        extraction_id=row["extraction_id"],
        page_number=row["page_number"],
        start=row["start_off"],
        end=row["end_off"],
        id=row["id"],
    )
