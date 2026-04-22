-- Chronos Agent — Schema 001: initial tables
-- See docs/decisions/ADR-003-sqlite-schema.md for rationale.
--
-- This file is run on a fresh DB (and idempotent re-runs are safe).
-- All timestamps are ISO-8601 UTC strings (TEXT). SQLite stores them as TEXT;
-- we parse in Python with datetime.fromisoformat.

PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

-- -----------------------------------------------------------------------------
-- schema_info — single-row table tracking applied migrations
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS schema_info (
    id              INTEGER PRIMARY KEY CHECK (id = 1),   -- enforce single row
    schema_version  TEXT NOT NULL,                        -- SemVer (e.g. "0.1.0")
    applied_at      TEXT NOT NULL
);

-- -----------------------------------------------------------------------------
-- runs — one row per agent execution
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS runs (
    id                   TEXT PRIMARY KEY,                      -- UUID4 string
    adapter              TEXT NOT NULL,                         -- 'langgraph', 'autogen', ...
    adapter_thread_id    TEXT NOT NULL,                         -- framework-specific thread id
    status               TEXT NOT NULL CHECK (status IN
                            ('pending','running','completed','failed','forked')),
    started_at           TEXT NOT NULL,                         -- ISO-8601 UTC
    ended_at             TEXT,                                  -- nullable until completion
    task_description     TEXT,                                  -- optional human label
    initial_state_json   TEXT NOT NULL,                         -- JSON: input state
    final_state_json     TEXT,                                  -- JSON: final state (if completed)
    tags_json            TEXT NOT NULL DEFAULT '[]',            -- JSON array of strings
    metadata_json        TEXT NOT NULL DEFAULT '{}',            -- JSON: adapter-specific extras

    CHECK (ended_at IS NULL OR ended_at >= started_at)
);

CREATE INDEX IF NOT EXISTS idx_runs_started_at ON runs (started_at DESC);
CREATE INDEX IF NOT EXISTS idx_runs_status     ON runs (status);
CREATE INDEX IF NOT EXISTS idx_runs_adapter    ON runs (adapter);

-- -----------------------------------------------------------------------------
-- nodes — one row per executed node (graph step) in a run
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS nodes (
    id                   TEXT PRIMARY KEY,                      -- UUID4 string
    run_id               TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    step_index           INTEGER NOT NULL CHECK (step_index >= 0),
    node_name            TEXT NOT NULL,                         -- semantic key (e.g. "research")
    kind                 TEXT NOT NULL CHECK (kind IN
                            ('llm','tool','fn','router','fork','end')),

    -- Causal chain. Within-run parent is a node in same run_id; for the
    -- FIRST node after a fork, parent_node_id points to a node in a different
    -- run (enforced at app level, not at SQL level, because REFERENCES can't
    -- express "same-run-OR-cross-run-via-forks-table").
    parent_node_id       TEXT REFERENCES nodes(id) ON DELETE SET NULL,

    started_at           TEXT NOT NULL,
    ended_at             TEXT,
    state_after_json     TEXT NOT NULL,                         -- JSON: state post-node

    -- LLM-specific fields (nullable; populated by LLM nodes only)
    model_name           TEXT,
    usage_json           TEXT,                                  -- {prompt_tokens, completion_tokens, ...}
    cost_usd_cents       INTEGER,                               -- integer cents to avoid floats

    -- Tool-specific fields (nullable)
    tool_name            TEXT,
    tool_input_json      TEXT,
    tool_output_json     TEXT,
    error_message        TEXT,

    metadata_json        TEXT NOT NULL DEFAULT '{}',

    CHECK (ended_at IS NULL OR ended_at >= started_at)
);

CREATE INDEX IF NOT EXISTS idx_nodes_run_id         ON nodes (run_id, step_index);
CREATE INDEX IF NOT EXISTS idx_nodes_parent         ON nodes (parent_node_id);
CREATE INDEX IF NOT EXISTS idx_nodes_name           ON nodes (node_name);
CREATE INDEX IF NOT EXISTS idx_nodes_kind           ON nodes (kind);

-- -----------------------------------------------------------------------------
-- forks — cross-run causal links
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS forks (
    id                   TEXT PRIMARY KEY,                      -- UUID4
    parent_run_id        TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    parent_node_id       TEXT NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
    child_run_id         TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    created_at           TEXT NOT NULL,
    edited_fields_json   TEXT NOT NULL DEFAULT '{}',            -- {field_name: new_value}
    reason               TEXT,                                  -- human-readable why

    CHECK (parent_run_id != child_run_id),
    UNIQUE (child_run_id)                                       -- one fork per child
);

CREATE INDEX IF NOT EXISTS idx_forks_parent_run  ON forks (parent_run_id);
CREATE INDEX IF NOT EXISTS idx_forks_parent_node ON forks (parent_node_id);
CREATE INDEX IF NOT EXISTS idx_forks_child_run   ON forks (child_run_id);

-- -----------------------------------------------------------------------------
-- Record this migration (idempotent: only inserts on fresh DB; does NOT
-- overwrite a tampered or future-version schema_info row, so the library's
-- version-compat check in _verify_schema_version() can correctly reject
-- incompatible DBs).
-- -----------------------------------------------------------------------------
INSERT OR IGNORE INTO schema_info (id, schema_version, applied_at)
VALUES (1, '0.1.0', strftime('%Y-%m-%dT%H:%M:%fZ', 'now'));
