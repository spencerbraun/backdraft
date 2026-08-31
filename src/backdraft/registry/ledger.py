"""The ledger: every token minted into a writer's context, per session.

This is what lets bind distinguish "cited what you were shown" from "cited a
valid token you were never shown" — a hallucination class most systems cannot
express. The gate writes here on every emitted token; bind reads.

Plain functions over a connection rather than a second stateful object: the
Registry is the only stateful thing in the system, and it delegates here.
"""

from __future__ import annotations

import sqlite3
import uuid
from typing import Sequence

__all__ = [
    "ensure_session",
    "record_shown",
    "sessions",
    "shown_by_document",
    "was_shown",
]


def ensure_session(
    connection: sqlite3.Connection, session_id: str | None, label: str | None, now: str
) -> str:
    """Return an existing or freshly created session id.

    A `None` id mints one. NOTE: the spec says "caller-supplied or generated"
    without fixing the generated form; a uuid4 hex is opaque, collision-free and
    short enough to paste into `--session`.
    """
    resolved = session_id or uuid.uuid4().hex
    connection.execute(
        "INSERT INTO sessions (id, label, started_at) VALUES (?, ?, ?) "
        "ON CONFLICT(id) DO NOTHING",
        (resolved, label, now),
    )
    return resolved


def record_shown(
    connection: sqlite3.Connection,
    session_id: str,
    anchor_ids: Sequence[int],
    now: str,
) -> None:
    """Record that these anchors were shown in this session.

    Idempotent: showing the same anchor twice keeps the first `shown_at`, because
    what bind asks is whether the writer ever saw it.
    """
    connection.executemany(
        "INSERT INTO ledger (session_id, anchor_id, shown_at) VALUES (?, ?, ?) "
        "ON CONFLICT(session_id, anchor_id) DO NOTHING",
        [(session_id, int(anchor_id), now) for anchor_id in anchor_ids],
    )


def was_shown(connection: sqlite3.Connection, session_id: str, token: str) -> bool:
    """True if any anchor named by `token` was shown in this session.

    Matched by token, not by anchor id: a token that survived a re-ingest names a
    new anchor row with the same name, and the writer did see it.
    """
    row = connection.execute(
        "SELECT 1 FROM ledger JOIN anchors ON anchors.id = ledger.anchor_id "
        "WHERE ledger.session_id = ? AND anchors.token = ? LIMIT 1",
        (session_id, token),
    ).fetchone()
    return row is not None


def shown_by_document(connection: sqlite3.Connection, session_id: str) -> list[tuple[str, int]]:
    """`(slug, count)` per document this session was shown anything from.

    Counted by *distinct token* rather than by ledger row, for the reason
    `was_shown` matches by token: a span that survived a re-ingest is a second
    anchor row with the same name, and the writer saw one thing, not two. A
    document nothing was shown from is absent rather than zero — the caller is
    asking what the session holds, and `documents()` already answers what exists.

    Ordered like `Registry.documents()`, oldest ingest first, so the coverage
    list and the gate's document list read down in the same order.
    """
    return [
        (row["slug"], int(row["shown"]))
        for row in connection.execute(
            "SELECT documents.slug AS slug, COUNT(DISTINCT anchors.token) AS shown "
            "FROM ledger "
            "JOIN anchors ON anchors.id = ledger.anchor_id "
            "JOIN extractions ON extractions.id = anchors.extraction_id "
            "JOIN documents ON documents.id = extractions.document_id "
            "WHERE ledger.session_id = ? "
            "GROUP BY documents.id "
            "ORDER BY documents.created_at, documents.id",
            (session_id,),
        )
    ]


def sessions(connection: sqlite3.Connection) -> list[dict]:
    """Every session, oldest first."""
    return [
        {"id": row["id"], "label": row["label"], "started_at": row["started_at"]}
        for row in connection.execute(
            "SELECT id, label, started_at FROM sessions ORDER BY started_at, id"
        )
    ]
