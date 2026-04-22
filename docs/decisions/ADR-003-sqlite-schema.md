# ADR-003: SQLite schema design, versioning strategy, and Chronos↔LangGraph mapping

**Status**: Accepted
**Date**: 2026-04-22
**Deciders**: Hermes Agent (autonomous)

## Context

M1.3 needs persistent storage. We need to answer three questions before writing any code:

1. **Schema shape** — what tables, what columns, what invariants
2. **Versioning** — how do we evolve schema without breaking existing `chronos.db` files
3. **LangGraph coupling** — do we store LangGraph's native `CheckpointTuple` verbatim, or re-shape into our own canonical model?

ADR-002 already picked LangGraph as the first adapter and surfaced 5 empirical findings. This ADR operationalizes those findings into a concrete schema.

## Decision

### 3.1 Schema: four tables

```
runs         — one row per agent execution (top-level unit of work)
nodes        — one row per executed node in a run (leaf/transition)
forks        — one row per fork event (linking child_run → parent_run at a node)
schema_info  — single-row table holding schema_version
```

Plus indices on `runs.started_at`, `nodes.run_id`, `nodes.parent_node_id`, `forks.child_run_id`.

See `migrations/001_init.sql` for DDL.

### 3.2 Versioning: numbered forward-only SQL migrations

- Migrations live in `src/chronos/store/migrations/NNN_name.sql`
- Each migration is idempotent (`CREATE TABLE IF NOT EXISTS` etc.) where safe, and records itself into `schema_info`
- A `chronos.db` file has a single `schema_version` row; on open we run all migrations where `migration.number > db.schema_version`
- **No downgrade path in v0.1**. If we ship v0.2 with a breaking change, we provide a one-time export-import tool, not an automatic downgrade.
- **Python-side validator** (pydantic `SCHEMA_VERSION = "0.1.0"` in `core/models.py`) kept in sync — if DB schema version string mismatches library version's expected range, we refuse to open (fail-fast over silent corruption).

### 3.3 LangGraph mapping: canonical reshape, not verbatim storage

We do **NOT** store LangGraph `CheckpointTuple` objects verbatim. We re-shape into our canonical model. Rationale:

- **Cross-framework future.** When we add AutoGen/CrewAI adapters (Phase 2), users want `chronos diff` to work across frameworks. That requires a canonical, framework-agnostic model.
- **LangGraph API stability.** Its internal checkpoint format has changed between 0.x and 1.x; we don't want our schema to track upstream churn.
- **Our own semantics.** We care about `parent_node_id` (semantic alignment — from ADR-002 finding #3), LLM call metadata, cost/latency overlays. LangGraph's native format doesn't capture these cleanly.

Mapping (LangGraph 1.1.9 terms on left, Chronos on right):

| LangGraph concept | Chronos table | Notes |
|---|---|---|
| A `graph.invoke(initial, {thread_id: X})` call | one `runs` row | `thread_id` stored as `runs.adapter_thread_id` |
| Each `StateSnapshot` with `step >= 0` | one `nodes` row | step=K snapshot captures the TRANSITION into node named by `snapshot.next[0]` |
| `snapshot.values` dict | `nodes.state_after_json` | Full state stored as JSON (CBOR later if size becomes an issue) |
| `snapshot.metadata.step` | `nodes.step_index` | Integer, kept for debugging/traceability but NOT for cross-run alignment |
| `snapshot.next[0]` | `nodes.node_name` | The semantic key used for alignment (per ADR-002) |
| `update_state(cfg_new, values, as_node=X)` | inserts one `forks` row | `child_run_id` + `parent_run_id` + `parent_node_id` + `edited_fields_json` |
| LLM-specific metadata (usage, model, cost) | `nodes.usage_json`, `nodes.model_name`, `nodes.cost_usd_cents` | Nullable — populated by adapter if available |

### 3.4 JSON columns, not normalized tables (for now)

`state_after_json`, `usage_json`, `edited_fields_json`, `tags_json` are all stored as TEXT with JSON content. Not normalized.

Rationale: state shape is user-defined (any pydantic model, any TypedDict), so normalizing would require schema-per-user which SQLite can't do sanely. SQLite 3.38+ has JSON1 built in; we can `SELECT` into JSON fields when needed for queries. Performance is a non-concern at v0.1 scale (< 10k nodes per DB).

Future escape hatch: if someone hits perf issues on a huge DB, we add a `nodes_indexed` table with commonly-queried extracted columns. Out of scope for v0.1.

## Invariants (encoded in CHECK constraints where possible)

1. `runs.ended_at IS NULL OR runs.ended_at >= runs.started_at`
2. `nodes.step_index >= 0`
3. `nodes.kind IN ('llm', 'tool', 'fn', 'router', 'fork', 'end')`
4. `runs.status IN ('pending', 'running', 'completed', 'failed', 'forked')`
5. `forks.child_run_id != forks.parent_run_id` (can't fork from self)
6. Each `nodes.parent_node_id` that is not NULL references an existing `nodes.id` within the SAME `run_id` (unless the node is the "first node after fork", in which case parent_node_id points to a node in a different run — see §3.5)

### 3.5 Fork boundary special case

When run B is forked from run A at node `A.nodes[k]`:
- `forks` row records the cross-run link
- The first node in B (`B.nodes[0]`) has `parent_node_id = A.nodes[k].id` (cross-run reference, allowed)
- Subsequent nodes in B have `parent_node_id` pointing within B
- This preserves the causal chain for `chronos diff` semantic alignment.

## Alternatives considered

**Alt 1: Store LangGraph CheckpointTuple verbatim (BLOB)**
Rejected: locks us into LangGraph's format; breaks ADR-002's multi-adapter future; makes cross-run diff impossible.

**Alt 2: Use LangGraph's own `SqliteSaver` and just read from its tables**
Rejected: `SqliteSaver.cursor` returns rows in a shape we don't control; can't add `runs` / `forks` metadata; locked to LangGraph.
But: we DO plan to *compose* with `SqliteSaver` — let it handle the raw checkpoint column, while our adapter writes to `runs/nodes/forks` alongside. This is the "tee" pattern.

**Alt 3: Alembic for migrations**
Rejected: overkill for v0.1. Raw numbered SQL files + `PRAGMA user_version` is simpler and has zero runtime dependency. Revisit at v0.3 if migration logic gets complex.

**Alt 4: DuckDB instead of SQLite**
Rejected for v0.1: SQLite has wider deployment, stdlib support, better tooling. DuckDB wins on analytical queries (cost overlays over 1M+ nodes) — revisit if Chronos Cloud happens in v0.4+.

## Consequences

**Positive**
- Schema is adapter-agnostic → unblocks AutoGen/CrewAI in Phase 2
- Forward-migrating SQL files are the simplest thing that works
- `parent_node_id` naturally captures the semantic alignment that ADR-002 flagged as mandatory for `chronos diff`

**Negative**
- Reshape logic in LangGraph adapter is non-trivial (test coverage critical)
- JSON columns mean we can't `INDEX` on arbitrary state fields — but this is fine for v0.1
- No downgrade path. Users who install v0.3 and try to open a v0.2 DB get a clear error, not a rollback.

**Neutral**
- We're storing redundant data (LangGraph's own saver also writes to its tables). Disk cost negligible at v0.1 scale.

## Revisit triggers

- Second adapter (AutoGen/CrewAI) reveals the canonical model is LangGraph-biased
- Single DB file exceeds 100 MB in dogfood → revisit storage efficiency (CBOR, compression)
- Users request real-time query over historical runs → maybe DuckDB
- Schema changes more than once per 3 months → maybe Alembic

## References

- ADR-001: Python 3.11+
- ADR-002: LangGraph first adapter + 5 spike findings
- `docs/design/architecture.md` — 5-layer architecture; `store` is layer 3
- `docs/research/feasibility.md` §Persistence — initial thinking that led here
- `tests/spikes/test_spike1_capture.py` — empirical proof of LangGraph snapshot shape
