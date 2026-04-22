# ADR-004: LangGraph StateSnapshot → Chronos Node Mapping

**Status**: Accepted
**Date**: 2026-04-22 (Round 4)
**Context**: `Phase 1 / M1.4` — LangGraph recorder adapter
**Supersedes**: None. Extends ADR-002 (LangGraph first adapter).
**See also**: `tests/spikes/spike4_probe_snapshot.py` (empirical evidence)

---

## Context

M1.4 requires a **recorder adapter** that converts a completed LangGraph run
into Chronos's canonical `Run` + `Node[]` + `Fork` records, with no manual
reshape required from the user.

Round 3 CONTEXT.md speculated that per-step data would live in
`StateSnapshot.metadata["writes"]`. **This turned out to be wrong.** Spike 4
probed a real run and discovered the actual shape. This ADR records those
findings and commits to the resulting mapping algorithm.

## Empirical Findings (Spike 4 output)

Running a 4-node pipeline (`plan → research → draft → polish`) produced
**6 snapshots**, structured as follows (newest-first from `get_state_history`):

| idx | step | source | next        | values keys                          | tasks[0].name   |
|-----|------|--------|-------------|--------------------------------------|-----------------|
| 0   | 4    | loop   | `()`        | all fields incl. `final`             | —               |
| 1   | 3    | loop   | `('polish',)`  | task, plan, research, draft, log   | `polish`        |
| 2   | 2    | loop   | `('draft',)`   | task, plan, research, log          | `draft`         |
| 3   | 1    | loop   | `('research',)`| task, plan, log                    | `research`      |
| 4   | 0    | loop   | `('plan',)`    | task, log (= initial)              | `plan`          |
| 5   | -1   | input  | `('__start__',)` | _empty_                          | `__start__`     |

### Finding 1 — `metadata["writes"]` is always `null` on stored checkpoints

The `writes` field shows up in *in-flight* metadata but is cleared once the
checkpoint is persisted. **Do not read it.** It was in our notes from
ADR-002 speculation — that note was wrong.

### Finding 2 — `snapshot.tasks[i].result` holds the per-node output

When a snapshot has `next=('plan',)`, its `tasks[0]` = the Plan task,
and `tasks[0].result` = the dict Plan *will write* into state on its next
tick. Critically, this means the snapshot **before** a node ran contains
both the name of that node AND (at replay time) what it produced.

However: `tasks[0].result` is only populated on snapshots that were captured
mid-execution; on a fully-completed run some snapshots have `tasks=[]`. We
can't rely on `result` alone.

### Finding 3 — The "step" mapping for executed nodes

For a run with nodes `[N1, N2, ..., Nk]`:
- `history[reversed]` yields snapshots at steps `-1, 0, 1, ..., k-1, k`.
- Step `-1` is the `__start__` input placeholder — **skip**.
- Step `i` (for `0 ≤ i < k`) represents state **before** node `Ni+1` runs,
  but its `tasks[0].name` tells us which node is *about* to run = `Ni+1`.
- Step `k` is the **terminal** state after the last node wrote. `next=()`
  and `tasks=[]`. This is the final state, not a separate node.

### Finding 4 — State delta is `values[step=i+1] − values[step=i]`

The delta is recoverable by set-diffing the dict keys/values between
adjacent snapshots. For Chronos purposes we **store the full `state_after`**
per node (i.e. `values` at step `i+1`) rather than a delta, because diff
is v0.1's value-add and we want full state available for any-point-fork.

### Finding 5 — `parent_config.checkpoint_id` chains snapshots

Each snapshot's `config.configurable.checkpoint_id` points to a unique id;
`parent_config.configurable.checkpoint_id` is the previous snapshot's id.
This gives us a clean causal chain **within** a single thread. We will map
it to Chronos's `Node.parent_node_id`.

### Finding 6 — `snapshot.created_at` is an ISO-8601 UTC string

Usable directly as our `Node.started_at` (approximation; LangGraph doesn't
give us a separate `ended_at`, so we set `ended_at = next_snapshot.created_at`
as a proxy for "node completed when the next snapshot was taken").

## Decision — The Mapping Algorithm

Given a completed LangGraph run with thread_id `T`:

```
history_reversed = list(reversed(graph.get_state_history(cfg)))
# Yields: [snap[-1], snap[0], snap[1], ..., snap[k]]   (oldest-first)
```

### Run record

```
Run(
  id                  = uuid4(),
  adapter             = "langgraph",
  adapter_thread_id   = T,
  status              = COMPLETED,                 # assuming no exception
  started_at          = history_reversed[0].created_at,
  ended_at            = history_reversed[-1].created_at,
  initial_state       = history_reversed[1].values  if len>=2 else {},
                         # snap[0] = state BEFORE node[0] ran (= initial user input)
  final_state         = history_reversed[-1].values,
  metadata            = {"checkpoint_ns": "", "langgraph_version": lg.__version__},
)
```

### Node records — iterate pairs

```
for i in range(1, len(history_reversed) - 1):
    pre  = history_reversed[i]      # snapshot BEFORE node ran
    post = history_reversed[i + 1]  # snapshot AFTER node ran

    node_name = pre.tasks[0].name   # the node that was about to run
    step_idx  = pre.metadata["step"]
    # ^ step_idx will be 0, 1, 2, ... k-1 (one per executed node)

    Node(
      id                = uuid4(),
      run_id            = run.id,
      step_index        = step_idx,
      node_name         = node_name,
      kind              = classify(node_name),    # see §Classification below
      parent_node_id    = prev_node.id if prev_node else None,
      started_at        = pre.created_at,
      ended_at          = post.created_at,
      state_after       = post.values,
      model_name        = None,                   # LangGraph doesn't expose this
      usage             = None,                   # ditto; adapter can't know
      cost_usd_cents    = None,
      metadata          = {
          "checkpoint_id"       : post.config["configurable"]["checkpoint_id"],
          "parent_checkpoint_id": pre.config["configurable"]["checkpoint_id"],
      },
    )
```

**Key insight**: `history_reversed[0]` is the `source=input` placeholder
(`step=-1`, empty values). We skip it. `history_reversed[-1]` is the terminal
snapshot — its values become `run.final_state`, but we do not emit a Node
for it (no task ran there; `next=()`).

### Classification (`kind`) — v0.1 heuristic

LangGraph doesn't carry a type tag on nodes. For v0.1 we default every
executed node to `NodeKind.FN` (generic function). Users who want richer
typing can pass `kind_map={"plan": NodeKind.LLM, ...}` to the recorder.
LLM / tool detection via wrapping chat models is **out of scope for M1.4**
and deferred to M2 (provider-specific spans).

### Token/cost fields

LangGraph's StateSnapshot has **no first-class token/usage fields**. These
remain `None` in v0.1. Users who care about cost must either:
1. Embed usage dicts in their state (we'll harvest from `values` if
   `kind_map` marks a node as LLM and we find a conventional `usage`
   sub-dict).
2. Wait for M2 provider spans.

We explicitly **do not** try to re-parse LLM outputs — that's unreliable
and couples the adapter to provider SDKs.

## Consequences

### Positive
- Post-run reconstruction is **pure**: given `graph` + `thread_id` + a
  completed run, the adapter is deterministic. No mid-run hooks needed.
- Works for **any** LangGraph graph without modification.
- The checkpoint_id chain gives us a natural fork anchor for M1.5.
- `kind_map` injection point keeps the adapter pluggable without
  hardcoding semantics.

### Negative
- No per-node token/cost capture in v0.1 (deferred to M2).
- `ended_at` is approximate (start of the *next* snapshot, not true node
  completion time). Adequate for UX, not for tight SLO monitoring.
- Assumes the checkpointer persisted every step. If the user configured
  selective checkpointing, we'd miss nodes. **Document this in the
  recorder docstring.**
- `source=input` step=-1 detection is an empirical convention — if a
  future LangGraph version changes it, our adapter breaks. Guarded by a
  dedicated unit test (`test_adapter_skips_start_placeholder`).

### Neutral
- We're harvesting from `get_state_history()` post-run, not subscribing to
  live events. For M1.4's scope (offline replay/fork) this is fine; if
  M2 needs real-time streaming capture, we'll add a checkpointer wrapper
  then.

## Alternatives Considered

### A. Wrap `CheckpointSaver.put()` to tee every write

**Rejected for M1.4**: more invasive, couples us to LangGraph's internal
protocol, and doesn't give us anything we can't recover post-run.
Reconsider if/when M1.6 needs streaming.

### B. Walk `metadata["writes"]`

**Rejected** — the spike proved `writes` is cleared on persistence. Would
work only for an in-flight snapshot subscription (which we decided against
per Alt A).

### C. Map each snapshot 1:1 to a Node

**Rejected** — would produce N+1 nodes for N executed steps (counting the
initial input placeholder) and wouldn't align with user mental model.
Users think in terms of "nodes that ran," not "checkpoints that persisted."

## Open Questions (deferred)

- **Fork recording**: how do we detect `update_state(as_node=...)` was
  called externally? For now Chronos's own fork API will emit the `Fork`
  record itself; we only record forks we authored. → M1.5.
- **Interrupts**: if the graph had `interrupt_before=...`, extra snapshots
  may appear with `next` populated but no task running. Needs a spike in M2.

## Test Plan

1. **Unit** — mock `graph.get_state_history()` to return a crafted list,
   assert 1:1 node mapping, skip of step=-1, correct parent_node_id chain.
2. **Integration** — rewrite `tests/integration/fixtures_writer.py` to use
   the adapter; spike1's 5-node pipeline should produce identical nodes
   via adapter as via hand-reshape. All 45 tests still pass.
3. **Unit — edge cases**: 1-node graph, 0-node graph (should still yield a
   Run with no Nodes), graph with cycle (same node_name at different step_idx).
