# ADR-005: Fork Semantics and Re-Recording Algorithm

- **Status**: Accepted
- **Date**: 2026-04-23
- **Supersedes / Related**: ADR-003 (forks table), ADR-004 (snapshot→node mapping)

---

## Context

Round 4 (M1.4) shipped `LangGraphRecorder` that takes a completed LangGraph
run on a thread and produces a canonical `Run` + `Node[]` record.

Round 5 (M1.5) needs the **fork primitive**: given a previously-recorded
`Run`, let the user choose a step `k`, edit some state fields, and
re-execute downstream on a new thread. The result must be persisted as a
second `Run` linked to the parent via the `forks` table (schema from
ADR-003).

Two non-trivial questions this ADR answers:

1. **What does `get_state_history()` look like on a forked thread?**
   (It's NOT the same as an originally-invoked thread.)
2. **What is the public API surface for fork?**

---

## Spike 5 — Empirical Evidence

`tests/spikes/spike5_probe_fork_history.py` compared the original thread
A (invoked normally) against a forked thread B (seeded via
`update_state(cfg_b, values, as_node="research")` then `invoke(None, cfg_b)`).

Key observations (`build_graph()` from spike 1: plan→research→draft→review→finalize):

| Property | Thread A | Thread B |
|---|---|---|
| Snapshot count | 7 (= N+2 for 5 nodes) | 4 (= **N+1** for 3 downstream nodes) |
| `metadata.source` sequence | `[input, loop, loop, loop, loop, loop, loop]` | `[update, loop, loop, loop]` |
| `metadata.step` sequence | `[-1, 0, 1, 2, 3, 4, 5]` | `[0, 1, 2, 3]` (restarts!) |
| First snapshot `tasks` | `[]` (placeholder) | `['draft']` (next to run) |
| First snapshot `next` | `('plan',)` | `('draft',)` |
| Last snapshot `tasks / next` | `[] / ()` (terminal) | `[] / ()` (terminal) |
| Values on first snap | Initial input only | **Full seeded state** (all fields the fork carried over) |

### Structural consequences

1. The Round 4 adapter **rejects** thread B: it asserts
   `snapshots[0].metadata["source"] == "input"`. Forked threads produce
   `"update"` instead.

2. Thread B has **no input placeholder**. The seed snapshot
   (`source='update'`) plays a **dual role**: seed state AND pre-execution
   marker for the first downstream node (`tasks[0].name == 'draft'`,
   `next == ('draft',)`).

3. Step numbering is **thread-local** and restarts at 0 on the forked
   thread. We cannot use `step` as a stable global index for nodes across
   a fork family — we must compute step_index ourselves for the child Run.

4. Forked threads only record re-executed downstream nodes. Nodes
   *before* the fork point are NOT duplicated in thread B (they live in
   thread A's Run).

---

## Decision

### A. Fork API

Add a second context manager on `LangGraphRecorder`:

```python
recorder = LangGraphRecorder(store, kind_map=...)

with recorder.fork(
    parent_run_id="...",
    at_node_id="...",            # the Node in the parent Run to fork from
    overrides={"research": "..."},  # state-value overrides applied at the fork point
    child_thread_id="t-fork-1",
    reason="test alternative research",
    tags=["exploration"],
) as fork_ref:
    graph.invoke(None, {"configurable": {"thread_id": "t-fork-1"}})
# on exit:
#   fork_ref.child_run_id   → UUID of new Run
#   fork_ref.fork_id        → UUID of Fork record linking parent → child
```

Top-level convenience will come later (`chronos.fork(...)`); this ADR
only commits to the recorder-level contract.

### B. What the adapter does inside `fork(...)`

**Before yielding** (setup):

1. Load the parent `Run` from the store.
2. Load the parent `Node` identified by `at_node_id`; capture its
   `state_after` — this is the state as it existed at the fork point.
3. Apply `overrides` on top of `state_after` → `seeded_state`.
4. Look up `as_node` — set to the parent node's `node_name` so LangGraph
   treats the seeded state as if `<node_name>` just produced it, and the
   graph's edge from `<node_name>` determines the next executed node.
5. Resolve the parent Run's `adapter_thread_id` *must* differ from the
   `child_thread_id` (else we'd overwrite the parent's checkpoints).
6. Call `graph.update_state(cfg_child, seeded_state, as_node=<node_name>)`.
   This writes the seed checkpoint on the child thread.

**User code runs** `graph.invoke(None, cfg_child)` to let the graph
continue from the seeded state.

**On context exit** (teardown):

1. Walk `graph.get_state_history(cfg_child)`, reverse to oldest-first.
2. Validate `snapshots[0].metadata["source"] == "update"` — if not, raise
   `AdapterError` (LangGraph API drift).
3. Build the child `Run`:
   - `adapter = "langgraph"`, `adapter_thread_id = child_thread_id`
   - `initial_state = snapshots[0].values` (the seeded values)
   - `final_state = snapshots[-1].values`
   - `metadata = {"forked_from_run": parent_run_id, "forked_at_node": at_node_id, ...}`
   - `tags = [..., "fork"]` (auto-tag + user tags)
4. Build the child `Node[]`:
   - **Iterate `i in range(0, len-1)`** (NOT `range(1, len-1)` like Round 4):
     `pre = snapshots[i]`, `post = snapshots[i+1]`, same as before.
   - `step_index` for the child Run starts from
     `parent_node.step_index + 1` so the absolute position in the fork
     family stays monotonic. Local step number from `metadata['step']` is
     preserved in `node.metadata['langgraph_step']` for debuggability.
   - `parent_node_id`:
     - First re-executed node (i=0) → set to `at_node_id`
       (cross-Run parent pointer — the fork point's node in the PARENT
       Run; this encodes causality in the node tree).
     - Subsequent nodes → previous child node in the same child Run
       (same as Round 4).
5. Build the `Fork` record (ADR-003 `forks` table):
   - `parent_run_id`, `parent_node_id=at_node_id`, `child_run_id=<new>`
   - `edited_fields = overrides` (raw dict — schema already stores JSON)
   - `reason`
6. Persist in one transaction: `put_run(child)`,
   `put_node(...)`-each, `put_fork(fork_record)`.

### C. Failure semantics

- If the user's `graph.invoke(None, ...)` raises inside the block, the
  adapter still persists the partial child Run + whatever nodes exist
  + the Fork link, marking child `status = FAILED`. Then re-raises.
  (Mirrors Round 4 policy; maintains "forks are never silently lost".)
- If `parent_run_id` doesn't exist, raise `AdapterError` **before** yielding.
- If `at_node_id` doesn't belong to `parent_run_id`, raise `AdapterError`.
- If `child_thread_id == parent.adapter_thread_id`, raise `AdapterError`
  to protect the parent's checkpoints.

### D. Edge cases considered & handled

- **Fork from the terminal node**: meaningless — no downstream. We raise
  `AdapterError("cannot fork from terminal node: no downstream to re-execute")`
  if the referenced node's `node_name` has no outgoing edges *or*
  `update_state` produces a thread with `next=()` immediately. (We do the
  cheaper structural test first; the `next=()` test is a backstop.)
- **No override (pure replay)**: allowed. `overrides` can be empty — the
  user just wants to re-run the downstream deterministically. Still
  writes a Fork row with `edited_fields={}`.
- **Override introduces a new key**: permitted (LangGraph's state is a
  dict-like; extra keys flow through). The fork record's `edited_fields`
  captures it verbatim.
- **Forking an already-forked run**: fine, the Fork row just points to
  the chosen parent Run. Fork chains are a linked list / DAG via
  `forks.parent_run_id → forks.child_run_id`.
- **Refork same parent+node with different overrides**: allowed. Each
  produces a separate child Run with its own Fork row. No uniqueness
  constraint on `(parent_run_id, parent_node_id)`.

---

## Alternatives Considered

### Alt 1 — Seed by deep-copying the checkpointer's state file

Instead of `update_state`, directly copy the LangGraph checkpointer's
sqlite/memory rows from thread A to thread B, preserving the native
"input + loop" shape.

**Rejected** because:
- It tightly couples us to each checkpointer implementation
  (`InMemorySaver`, `SqliteSaver`, Postgres, ...). We'd need N adapters.
- LangGraph's public contract is `update_state`. Going under it is
  version-fragile.
- The "update" source in the forked thread's history is actually
  useful signal — it lets us tell forked threads apart from originals
  at inspection time.

### Alt 2 — Re-invoke the whole graph from scratch, with the edited state

Set `cfg_b`, call `graph.invoke(modified_initial_state, cfg_b)` — but
that also re-executes every pre-fork node.

**Rejected** because:
- Wastes work (the whole point of fork is to reuse pre-fork results).
- Non-deterministic pre-fork nodes (LLM calls!) would produce *different*
  pre-fork state, so the "fork" wouldn't actually preserve the context
  the user wanted to fork from.

### Alt 3 — Put the fork primitive outside the adapter

Separate module `chronos.ops.fork(store, run_id, ...)` that does not know
about LangGraph. Call into `graph.update_state` via user-supplied callback.

**Rejected for v0.1** because the current `LangGraphRecorder` already
owns the LangGraph ↔ canonical-model translation; splitting the fork
logic across two modules means duplicating the snapshot-walk code. We
can refactor to a framework-agnostic `chronos.ops` layer in Phase 2 when
AutoGen adapter arrives — that's the natural boundary.

---

## Consequences

### Positive

- Users get one-liner fork: `recorder.fork(parent, at=..., overrides=...)`.
- Fork lineage is queryable from the store (ADR-003 `forks` table).
- Child Run is a first-class Run — all existing read APIs (list, get,
  get_nodes) work unchanged.
- The code path is a small delta on the already-tested Round 4 pipeline:
  same `_persist_from_history` logic with a different loop bound
  (`range(0, len-1)` vs `range(1, len-1)`) and a different `source` check.

### Negative / accepted cost

- Small code duplication in the persistence loop (different bounds,
  different source check). We'll factor it into a private
  `_persist_history(snapshots, *, loop_start, expected_first_source, ...)`
  helper shared between `record()` and `fork()`.
- `step_index` on a child run's first node is `parent.step_index + 1`,
  which means step numbers within a single child Run are not zero-based.
  Mitigated: child Run's `Node` rows still use monotonically increasing
  step_index; we also stash `langgraph_step` in node metadata.

### Open questions (deferred)

- **Determinism**: fork only makes sense if re-executing downstream is
  deterministic enough to be comparable to the parent. For spike fixtures
  (FakeLLM) it's fully deterministic. For real LLMs, Phase 3 introduces
  `determinism modes` (roadmap). v0.1 leaves this to the user.
- **Side effects**: if a downstream node calls an external API (email,
  DB write), fork re-executes it. ADR-006 (Phase 3) will address
  sandboxing; v0.1 documents the caveat.

---

## Test Plan

- **Unit** (`tests/unit/test_adapter_fork.py`, duck-typed fakes):
  - `fork()` builds correct child Run from synthesized forked history
  - `source='input'` on child thread → `AdapterError`
  - `source='update'` on child thread → OK
  - `parent_run_id` not found → `AdapterError`
  - `at_node_id` not in parent run → `AdapterError`
  - `child_thread_id == parent.adapter_thread_id` → `AdapterError`
  - Child node `parent_node_id` of first child node is `at_node_id`
    (cross-run pointer)
  - Child `step_index` starts at `parent.step_index + 1`
  - Fork record written with correct `edited_fields`
  - Failed child invoke → child Run persisted with `status=FAILED` +
    Fork still written
  - Empty overrides allowed (replay mode)

- **Integration** (`tests/integration/test_fork_e2e.py`, real LangGraph):
  - Record parent run on thread A
  - Fork at research node with `overrides={"research": "..."}`
  - Assert child Run's final_state differs from parent's
  - Assert cross-process: close store, reopen subprocess, verify parent
    + child + fork row all present
  - Assert `forks` linkage: `get_fork_for_child(child_run_id)` returns
    the correct Fork record

---

*Author: Hermes Agent (Round 5). Spike 5 raw evidence lives in
`tests/spikes/spike5_probe_fork_history.py`.*
