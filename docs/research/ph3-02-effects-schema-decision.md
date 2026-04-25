# PH3-02 effects metadata: schema-level vs annotation-level

**Round:** R43-D (2026-04-25)
**Status:** Decided — **Option B (annotation-level via `node.metadata['effects']`)**
**Depends on:** ADR-019 (no sandbox), R42-A feasibility note
**Informs:** PH3-02 adapter-effects tagging + Web UI ForkPlan warning badge

---

## Question

Phase 3 PH3-02 wants to surface *"this fork will re-execute N
network-effectful nodes"* in the Web UI before the user clicks Run.
For that we need each recorded `Node` to carry an **effects tag list**
(e.g. `["network"]`, `["fs", "db"]`).

Two ways to add the column:

- **Option A — schema-level.** Add `effects: list[str]` as a top-level
  field on `core.models.Node` and a new column to `nodes` table. Write
  a migration (`002_effects.sql`).
- **Option B — annotation-level.** Use the existing
  `node.metadata: dict[str, Any]` field (already round-tripped through
  the `metadata_json TEXT` column in the DB). Adapter writes
  `metadata["effects"] = [...]` during extract; readers access
  `node.metadata.get("effects", [])`.

## Spike

`tests/spikes/spike9_effects_metadata.py` — a 3-node LangGraph
(`plan → call_api → judge`) where `call_api` does one `httpx.post`
through a `MockTransport`. We:

1. Record the run via `LangGraphRecorder`.
2. Retrofit each node's `metadata_json` with
   `effects = EFFECT_HEURISTIC[node_name]` via a raw SQL `UPDATE` —
   this simulates what a PH3-02 adapter upgrade would do **inline**
   during `extract_run`, but keeps the spike independent of any
   adapter code change.
3. Reopen the store and verify three findings:

| Finding | Assertion | Result |
|---------|-----------|--------|
| **F1. Round-trip** | `metadata["effects"]` reads back identical | `{plan: [], call_api: ['network'], judge: []}` ✅ |
| **F2. No regression** | `list_runs`, `get_nodes_for_run` return 3 nodes with same shape | ✅ |
| **F3. Query ergonomics** | Filter "network-effectful nodes" in ≤2 lines of Python | `[n for n in nodes if "network" in n.metadata.get("effects", [])]` ✅ |

All three pass. Full spike output:

```
[F1] effects round-trip: {'plan': [], 'call_api': ['network'], 'judge': []}
[F2] list_runs + get_nodes_for_run still work: 3 nodes
[F3] network-effectful nodes: ['call_api']

SPIKE 9 RESULT: Option B (metadata['effects']) VIABLE ✅
```

## Decision: Option B

Use `node.metadata["effects"]`. No schema migration, no core-model change.

### Why

1. **Zero migration risk.** The `metadata_json` column is already a JSON
   TEXT blob, already persisted, already returned on read. PH3-02 can
   ship as a pure adapter-heuristic change + a UI read — no DB upgrade
   for existing users.
2. **Adapter-local scope.** The heuristic ("this LangGraph node did a
   network call") lives where framework knowledge belongs — inside
   `adapters/langgraph.py`. It can be refined per-adapter (AutoGen tools
   are tagged differently than LangGraph's `ToolNode`) without touching
   the core model.
3. **Forward-compatible promotion path.** If effects become a
   performance-sensitive query (e.g. *"give me all runs that touched
   the DB in the last week"* → wants an SQL index), we can promote to
   Option A later with a cheap migration: read `metadata_json ->>
   'effects'`, write to new column, drop key from metadata. Cost
   deferred until we have a proof the index matters.
4. **Web UI already works.** The `/runs/{id}/nodes` response serializes
   the full `metadata` dict. Web UI can read `node.metadata.effects`
   with zero backend endpoint change.
5. **Spike-level experimentation.** Different adapters or future
   heuristics (LLM-as-tagger, user-annotation override) can populate
   the key without ever needing a core-model ADR.

### When Option A would have won

- If we wanted to enforce `effects` as a **required** typed field
  (Pydantic validation, mypy narrowing). `metadata: dict[str, Any]` has
  no type safety — readers must `.get("effects", [])` defensively.
- If we wanted to push filtering into SQL for perf. The current Python
  filter is O(nodes-in-run); fine at 10²–10³ nodes, not fine at 10⁶.
- If effects needed to participate in alignment/diff (ADR-006 FROZEN —
  so this doesn't apply).

**None of these apply at PH3-02 scope.** When and if any of them do,
Option A migration is documented above.

## PH3-02 work breakdown (unlocked by this decision)

1. **`effect_kind` heuristic in `adapters/langgraph.py`** — recognise
   common tool shapes (`ToolNode` with known httpx/requests invocations,
   SQLAlchemy session ops, `Path.write_text`, `openai.*.create`).
   Fallback to `[]`. Round estimate: 0.5 round.
2. **Web UI ForkPlan warning badge** — the fork detail drawer already
   renders a ForkPlan preview. Add a conditional callout that counts
   downstream nodes whose `metadata.effects` intersects with a
   user-configurable "dangerous" set (default: `{network, fs, db}`).
   Round estimate: 0.5 round.
3. **(Optional) Adapter test fixture** — synthetic LangGraph with all
   four effect classes to pin the heuristic's output. Round estimate:
   0.5 round.

Total PH3-02: **~1.5 rounds** after this decision. Combined with
PH3-01 docs (1 round, already shipped in R43-A as
`docs/guides/side-effects.md`) and R43-B ADR-019 (already shipped),
Phase 3 v0.3.0 on-ramp is **on track for the revised 3.5–4.5 round
total estimate** from R42-A.

## Related files

- `docs/decisions/ADR-019-chronos-does-not-sandbox.md` — the ADR that
  asked this question.
- `tests/spikes/spike9_effects_metadata.py` — the spike.
- `src/chronos/core/models.py:114` — `Node.metadata` field.
- `src/chronos/store/migrations/001_init.sql` — `nodes.metadata_json` column.
- `src/chronos/adapters/langgraph.py:445` — where adapter writes node metadata today.
