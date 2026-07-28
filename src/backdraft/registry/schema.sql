-- The DDL. Single source of truth for registry shape (SPEC.md § Registry).
--
-- Applied by `Registry.open` against a fresh `.backdraft/registry.db`; every
-- statement is idempotent so opening an existing registry is a no-op.

CREATE TABLE IF NOT EXISTS documents (
  id INTEGER PRIMARY KEY,
  slug TEXT NOT NULL UNIQUE,
  sha256 TEXT NOT NULL UNIQUE,
  path TEXT NOT NULL,            -- as given at ingest; informational
  filename TEXT NOT NULL,
  media_type TEXT NOT NULL,      -- 'pdf' | 'xlsx' | 'text'
  created_at TEXT NOT NULL       -- ISO-8601 UTC, everywhere
);

CREATE TABLE IF NOT EXISTS extractions (
  id INTEGER PRIMARY KEY,
  document_id INTEGER NOT NULL REFERENCES documents(id),
  extractor TEXT NOT NULL,       -- 'pdf-text' | 'xlsx' | 'text' | 'vlm' | ...
  extractor_version TEXT NOT NULL,
  config_hash TEXT NOT NULL,
  deterministic INTEGER NOT NULL,
  is_current INTEGER NOT NULL DEFAULT 1,   -- one current per document (partial unique index)
  created_at TEXT NOT NULL
);

-- The "one current generation per document" rule, enforced by the database
-- rather than by the code that flips the flag.
CREATE UNIQUE INDEX IF NOT EXISTS idx_extractions_current
  ON extractions(document_id) WHERE is_current = 1;

CREATE TABLE IF NOT EXISTS pages (
  id INTEGER PRIMARY KEY,
  extraction_id INTEGER NOT NULL REFERENCES extractions(id),
  number INTEGER NOT NULL,       -- 1-based
  kind TEXT NOT NULL,            -- 'page' | 'sheet'
  name TEXT,                     -- sheet name for kind='sheet'
  text TEXT NOT NULL,            -- the snapshot; receipts quote THIS
  summary TEXT,                  -- optional, for TOC
  UNIQUE (extraction_id, number)
);

CREATE TABLE IF NOT EXISTS page_images (
  extraction_id INTEGER NOT NULL REFERENCES extractions(id),
  number INTEGER NOT NULL,       -- matches pages.number
  format TEXT NOT NULL,          -- 'webp' | 'png' | 'jpeg'
  width INTEGER NOT NULL,
  height INTEGER NOT NULL,
  data BLOB NOT NULL,            -- the page as the extractor saw it
  PRIMARY KEY (extraction_id, number)
);

CREATE TABLE IF NOT EXISTS anchors (
  id INTEGER PRIMARY KEY,
  extraction_id INTEGER NOT NULL REFERENCES extractions(id),
  page_number INTEGER NOT NULL,
  kind TEXT NOT NULL,            -- 'chunk' | 'cell' | 'range' | 'page'
  locator TEXT NOT NULL,         -- exactly the token's locator segment
  snippet TEXT NOT NULL,         -- verbatim from the snapshot (the receipt)
  snippet_sha256 TEXT NOT NULL,
  token TEXT NOT NULL,           -- full bd:... string
  start_off INTEGER, end_off INTEGER,
  created_at TEXT NOT NULL,
  UNIQUE (extraction_id, locator)
);
CREATE INDEX IF NOT EXISTS idx_anchors_token ON anchors(token);   -- token repeats across generations when content unchanged

CREATE TABLE IF NOT EXISTS sessions (
  id TEXT PRIMARY KEY,           -- caller-supplied or generated
  label TEXT,
  started_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ledger (
  session_id TEXT NOT NULL REFERENCES sessions(id),
  anchor_id INTEGER NOT NULL REFERENCES anchors(id),
  shown_at TEXT NOT NULL,
  PRIMARY KEY (session_id, anchor_id)
);

CREATE TABLE IF NOT EXISTS bindings (
  id INTEGER PRIMARY KEY,
  doc_path TEXT NOT NULL,
  session_id TEXT,
  mode TEXT NOT NULL,            -- 'frontwalk' | 'backfill'
  report_json TEXT NOT NULL,     -- full BindReport
  bound_at TEXT NOT NULL
);

CREATE VIRTUAL TABLE IF NOT EXISTS search USING fts5(snippet, token UNINDEXED, slug UNINDEXED, page UNINDEXED);
