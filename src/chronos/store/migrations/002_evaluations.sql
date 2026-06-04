-- Migration 002 — ADR-030 Evaluation & Scoring (R115, Phase 6 RC)
--
-- Purely additive. Adds one new table (`evaluations`) plus a unique index.
-- Bumps schema_info.schema_version from 0.1.0 to 0.2.0 (minor — additive
-- only, forward-compatible: a 0.1.0 library opening a 0.2.0 DB just sees an
-- extra table it doesn't query).
--
-- Idempotent: re-applying on a DB that already has the table is a no-op
-- (CREATE TABLE IF NOT EXISTS, CREATE UNIQUE INDEX IF NOT EXISTS, UPDATE on
-- a single-row schema_info table). Safe to run on every open.
--
-- See ``docs/decisions/ADR-030-evaluation-scoring.md`` §Schema for rationale.

-- -----------------------------------------------------------------------------
-- evaluations — one row per (run, evaluator) result
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS evaluations (
    id              TEXT PRIMARY KEY,                                   -- UUID4
    run_id          TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    evaluator_name  TEXT NOT NULL,
    score           REAL,                                               -- nullable; convention: higher = better
    passed          INTEGER,                                            -- 0/1, nullable, for boolean evaluators
    rationale       TEXT,                                               -- nullable, free-form
    metadata_json   TEXT NOT NULL DEFAULT '{}',                         -- JSON-encoded dict
    created_at      TEXT NOT NULL,                                      -- ISO-8601 UTC

    -- Re-running an evaluator overwrites the prior result via
    -- INSERT … ON CONFLICT(run_id, evaluator_name) DO UPDATE in the
    -- store layer (see SqliteStore.put_evaluation).
    CHECK (passed IS NULL OR passed IN (0, 1))
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_evaluations_run_evaluator
    ON evaluations (run_id, evaluator_name);

CREATE INDEX IF NOT EXISTS idx_evaluations_run_id
    ON evaluations (run_id);

-- -----------------------------------------------------------------------------
-- Bump schema_version. UPDATE (not INSERT OR IGNORE) — the row already exists
-- from migration 001. Idempotent: re-applying on a 0.2.0 DB is a no-op
-- (WHERE matches nothing). CRITICAL: the WHERE clause filters on the EXACT
-- prior version ('0.1.0') and NOT on `schema_version != '0.2.0'`, so a DB
-- carrying a future major (e.g. tampered '99.0.0' or a real 0.3.0) is left
-- alone and the library-side major-mismatch guard in
-- ``SqliteStore._verify_schema_version`` can reject it.
-- -----------------------------------------------------------------------------
UPDATE schema_info
   SET schema_version = '0.2.0',
       applied_at     = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
 WHERE id = 1
   AND schema_version = '0.1.0';
