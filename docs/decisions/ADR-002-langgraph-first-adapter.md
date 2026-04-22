# ADR-002: LangGraph `checkpointer` as first adapter; `update_state(as_node=…)` as fork primitive

**Status**: Accepted
**Date**: 2026-04-22
**Deciders**: Hermes Agent (autonomous)
**Supersedes**: none

## Context

Phase 1 of chronos-agent needs a concrete framework to prove the record / replay / fork / diff cycle. ADR-001 picked Python 3.11+ for core + adapters. The remaining question: **which agent framework do we integrate first?**

Candidates (per `docs/research/competitors.md`):
- **LangGraph** — explicit state graph, built-in `checkpointer` abstraction (MemorySaver, SQLite, Postgres), `get_state_history` and `update_state` APIs, **closest competitor** to chronos but also the strongest foundation to build on.
- AutoGen (Microsoft) — agent conversations, less explicit state snapshotting.
- CrewAI — role-based, opinionated, weak state introspection.
- Raw LangChain AgentExecutor — no native checkpointing.

## Decision

**LangGraph is the first adapter**. We reuse its `checkpointer` infrastructure as the storage primitive and treat `StateGraph.update_state(config, values, as_node=...)` as the fork primitive.

Rationale:
1. **Prior art is a feature, not a threat.** LangGraph already solved "persist arbitrary state between node executions"; we don't reinvent it. Chronos' value-add (cross-run diff, fork UX, cost overlay, cross-framework trees) sits *above* the checkpoint primitive.
2. **Proof:** Spikes 1-3 (M1.1) validated the full cycle on LangGraph 1.1.9 with zero framework patches — pure external integration via the public `CompiledStateGraph` API.
3. **Marginal cost low:** no C/Rust extension; no custom serialization; no monkey-patching of user agents.
4. **Forking is possible.** `update_state(config_new_thread, modified_values, as_node="research")` creates a new thread whose continuation skips already-done nodes — this is exactly "fork here with modified prompt".

## Alternatives considered

- **Build our own framework first, adapters later.** Rejected: 10× the work to prove the same point. We want chronos to work with the ecosystem, not replace it.
- **AutoGen first.** Rejected: state is implicit in message history; snapshotting requires framework-internal hooks.
- **Generic OpenTelemetry adapter first.** Rejected for Phase 1 — OTel captures traces but not *state*, which is what fork needs.

## Spike findings (empirical)

These facts were measured in `tests/spikes/` and WILL inform every downstream design:

1. **LangGraph produces N+1 post-input snapshots for an N-node linear graph.**
   - Each node has a "pre-execution" snapshot (step=K, next=(node_name,), values=pre-node)
   - Plus one final snapshot (step=N, next=(), values=post-final).
   - Implication: Chronos' `Node` record cannot be 1:1 with LangGraph step. We'll materialize one `Node` per *executed* transition (N total for an N-node graph) and stash the step=N "completion marker" as `Run.completed_state`.

2. **Forked threads have different step counts than their parent.**
   - When we seed thread-B via `update_state(cfg, values, as_node="research")`, thread-B's history starts at whatever step `update_state` assigns — not continuous with thread-A's numbering.
   - **Design consequence**: `chronos diff` MUST align runs by **semantic key** (node name or user-provided alignment), NOT by step index. Spike 3's simple index-based alignment is incorrect for fork-style diffs and we noted this in the spike output.
   - This is now a **must-have design constraint** for M1.5 (`chronos fork`) and M1.7 (`chronos diff`).

3. **`StateGraph.get_state_history(config)` returns NEWEST-first.**
   - Trap for future implementers. Always re-reverse if you want chronological order.

4. **`InMemorySaver` works cross-thread within one process, not across processes.**
   - For Chronos' persistence layer (M1.3) we need `SqliteSaver` or a Chronos-native saver wrapping it. InMemorySaver is dev-only.

5. **Deterministic fakes are essential for CI.**
   - All spikes use `tests/spikes/fake_llm.py` (sha256-based) → tests are reproducible, no API keys, no flaky network. Every spike & integration test in Chronos should default to the fake adapter.

## Consequences

**Positive**
- M1.3 (storage schema) is informed by real `CheckpointTuple` shape, not guessed.
- M1.5 (`chronos fork`) has a known-working recipe: `update_state(new_cfg, state, as_node=X)` then `invoke(None, new_cfg)`.
- M1.7 (`chronos diff`) already has a working algorithm prototype (Spike 3) — needs only the semantic-alignment fix.

**Negative**
- Chronos v0.1 will only support LangGraph. AutoGen / CrewAI adapters are Phase 2 (M2.x).
- If LangGraph redesigns its checkpointer API (unlikely in 1.x), our adapter breaks. Pinning to 1.x in `pyproject.toml` mitigates.
- Users with raw-Python agents get nothing in Phase 1. We document this clearly in the README.

**Neutral**
- Tight dependency on `langgraph-checkpoint` as a transitive. Acceptable.

## References

- Spike 1: `tests/spikes/test_spike1_capture.py` — 5-node pipeline, 6-snapshot history
- Spike 2: `tests/spikes/test_spike2_fork.py` — fork with `update_state(as_node=...)`
- Spike 3: `tests/spikes/test_spike3_diff.py` — diff prototype (reveals alignment issue)
- `docs/research/competitors.md` §LangGraph — 300-line competitive analysis
- `docs/research/feasibility.md` §State capture — feasibility assessment

## Revisit triggers

Reopen this ADR if:
- LangGraph 2.x deprecates `update_state(as_node=...)`
- A second adapter (AutoGen / CrewAI) reveals the snapshot API is too LangGraph-specific and we need a neutral abstraction
- Users demand non-LangGraph support before M2.x
