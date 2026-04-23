# Multi-Framework Portability Risks

**Status**: Research note — not an ADR, not a promise of resolution.
**Round**: R27 (2026-04-23)
**Owner**: Hermes Agent
**Satisfies**: ADR-014 criterion R4 (Phase 2 entry checklist, 3/4 green after this doc)
**Preconditions**: ADR-016 (R26) ✅ adapter interface contract; ADR-015 (R25) ✅ extractor contract v2

---

## Why this doc exists

ADR-014 R4 requires a **written risks doc with mitigations** before Phase 2 (multi-framework adapters, AutoGen, Web UI) opens. ADR-016 defined the *shape* of a Chronos adapter as three Protocols; this doc asks the adversarial question the contract itself cannot answer:

> When we finally implement a non-LangGraph adapter, what will break that we did not predict?

Six risks are tracked below. Each has a stable identifier (R-1 … R-6), a three-paragraph structure (description / empirical evidence / mitigation), and an explicit **owner** (which ADR or Phase is responsible for resolving it). Risks flagged for **Phase 3** are not resolved in Phase 2 — we merely commit to not letting them silently leak through the adapter interface.

This is a living document. When R28-R29 ships the reference non-LangGraph adapter, each risk gets a pass/fail verdict appended.

---

## R-1: Event-model drift

**Description.** Chronos's canonical model assumes discrete "nodes" each with a `state_before` / `state_after` snapshot pair. LangGraph fits naturally — `graph.get_state_history()` emits exactly this. AutoGen's `GroupChat` emits a linear message stream with turn-level granularity; what we'd call a "node" maps to a single agent's reply, but there is no state snapshot at turn boundaries. CrewAI's task DAG emits task-start / task-complete events with `inputs` / `output` but no intermediate state dict. The same canonical `Node` row thus represents three semantically different things across frameworks, and downstream diff / replay code might assume LangGraph semantics.

**Empirical evidence.** R20 swarm dogfood (`docs/case-studies/langgraph-swarm.md` Finding #3) already surfaced this within LangGraph: `Node` has `state_after` only, no `state_before`, because LangGraph snapshots live between nodes not at their boundaries. Users building mental models of "diff per node" had to be told this. Extending to a second framework with a fundamentally different event model will 10× the cognitive friction.

**Mitigation.**
- **ADR-016 `NodeIdentityResolver` Protocol** is the only injection point an adapter has for declaring what constitutes a node in its runtime. Adapters must document this mapping in their module docstring.
- **No cross-framework diff invariant is promised.** Diff is defined on `Node.state_after` dicts and adapters fill `state_after` with whatever shape they have; it is the user's job to diff comparable runs, not Chronos's to normalize across frameworks.
- **Reference adapter choice matters**: R28-R29 should pick a second adapter whose event model *differs* from LangGraph (the leading candidate — minimal linear-pipeline adapter — has the same snapshot-per-step shape, which would give false confidence). Proposal: linear-pipeline first for contract shake-out, then AutoGen second for real event-model divergence.
- **Owner**: ADR-016 (interface) + future ADR-018 (cross-framework diff semantics, if diff proves insufficient).

---

## R-2: Fork primitive is fundamentally not portable

**Description.** LangGraph `fork()` works because `graph.update_state(as_node=…)` + `graph.invoke(None, {…})` resumes from a checkpointer. This entire mechanism is LangGraph-specific. AutoGen has no checkpointer concept — a GroupChat's state is the message list, and "continuing from step N with overrides" means reconstructing the message list up to step N, patching it, and handing it to a new GroupChatManager. CrewAI's tasks are fire-and-forget; "forking from a task" likely means re-running the task with different inputs, which is closer to re-submit than to resume.

**Empirical evidence.** R23-A (`progress/2026-04-23-round-23a.md`) discovered the checkpointer-persistence trap: using `InMemorySaver` rebuilt per factory call registered the fork in Chronos but produced `node_ids=[]` because the child run never saw the parent's state. This is already a LangGraph-specific footgun; AutoGen will have its own equally sharp equivalent, and the current ADR-016 `fork()` Protocol is silent on how adapters are allowed to seed state.

**Mitigation.**
- **ADR-016 `fork()` Protocol only requires the *postcondition***: "a child run exists that starts from `parent state_after` (at `at_node_id`) + `overrides`, and records through to completion or failure." The *mechanism* is deliberately not specified — LangGraph uses `update_state`; AutoGen adapters will pre-build the message history and hand it to a new GroupChatManager.
- **Adapters MUST document their fork mechanism** in the module docstring and MUST have a dogfood test exercising the fork path. If an adapter cannot support fork, it raises `AdapterError("fork not supported by this adapter")` at call time — not at import time, and not silently.
- **Phase 2 red line** (R30 task): no Chronos core code may call LangGraph checkpointer methods. Any `ctx.checkpointer` leak into `chronos.core.*` is a fail-the-PR condition.
- **Owner**: ADR-016 (contract); R28-R29 (proof-of-portability via reference adapter fork test).

---

## R-3: Usage metering has irregular gaps across providers, and the gaps differ per framework

**Description.** ADR-015 Layer 5 already handles multi-provider usage field mapping. But the question of *whether usage is available at all* at a given Chronos node boundary varies. LangGraph attaches usage to each LLM callback, so every LLM call inside a node accumulates cleanly (Layer 4 delta policy). AutoGen's `ChatResult.usage` is occasionally `None` when the underlying model client doesn't emit it, and GroupChat can include "silent" agents whose usage is routed to the group not the turn. CrewAI computes usage per-task at `Crew.kickoff()` end, not per-agent-call, which means intra-task tool calls vanish.

**Empirical evidence.** R18 swarm dogfood (`docs/case-studies/langgraph-swarm.md` Finding #1) caught a multi-LLM-per-node undercount: the extractor correctly returned per-call deltas but the recorder summed only the *last* call's usage, not the full per-node total. The fix (ADR-012 → consolidated in ADR-015 Layer 4) added explicit per-node delta accumulation — but the bug existed in production for two rounds. A second adapter with different accumulation semantics (e.g., AutoGen's per-turn vs. per-message model) will very plausibly reintroduce the same class of bug.

**Mitigation.**
- **ADR-015 Layer 1 permits `UsageResult = None`.** Adapters MUST NOT fabricate zeros when the underlying runtime returns no usage — `None` propagates to `Node.prompt_tokens=None, Node.completion_tokens=None`, and downstream cost calculations handle `None` correctly (checked in tests).
- **ADR-015 Layer 4 accumulation policy is invariant.** Adapters that add their own accumulation MUST write regression tests mirroring `test_multi_llm_per_node_sums_correctly` before their first CI run.
- **CI adapter double-dogfood** (R28-R29 deliverable): run the same `record → fork plan → fork exec` suite against LangGraph and the reference adapter; assert non-zero usage on both for runs that use real LLM calls. Usage gaps are acceptable **only** if the adapter's module docstring explicitly documents the gap.
- **Owner**: ADR-015 (contract); R28-R29 (CI evidence).

---

## R-4: Async vs sync execution model

**Description.** LangGraph is sync-first with a parallel async surface (`.ainvoke` / `.astream_events`). AutoGen is async-first — `GroupChatManager.run()` returns a coroutine, and most modern AutoGen code uses `asyncio.run()`. CrewAI supports both but its documentation leans sync. The current `RecorderProtocol.record()` and `.fork()` return synchronous context managers (`ContextManager[...]`). An adapter author working in async-first framework would either (a) block the event loop inside `__enter__` / `__exit__` , or (b) write `AsyncRecorderProtocol` parallel hierarchy.

**Empirical evidence.** R17 supervisor case study (`docs/case-studies/langgraph-supervisor.md:140`) explicitly flagged `.astream_events` as "not tested" — streaming support was known fragile. ADR-016 itself is silent on async. The Web UI planned for Phase 2 will almost certainly be async (FastAPI / asyncio); if the Recorder blocks, the UI deadlocks.

**Mitigation.**
- **R27 decision** (captured here, not in an ADR yet): defer `AsyncRecorderProtocol` to the first adapter that actually needs it. LangGraph sync works today; a minimal linear-pipeline adapter (R28 candidate) is sync. **AutoGen is where the async question becomes concrete** — when/if AutoGen adapter work starts, the first commit writes ADR-017 (`AsyncRecorderProtocol`) as a parallel Protocol, not a mutation of `RecorderProtocol`.
- **No `await recorder.record(...)` is allowed** through the current contract. Adapters that need async MUST wait for ADR-017.
- **Sync recorder in async host is tractable** via `asyncio.to_thread` + recorder-internal locking, but this is adapter-author responsibility, not Chronos core's.
- **Owner**: Deferred ADR-017 (triggered by AutoGen adapter PR in Phase 2); R27 flags the gap.

---

## R-5: Deterministic replay is not a cross-framework concept

**Description.** Chronos promises "replay" via ADR-006 (replay semantics) using LangGraph checkpointers — the child run re-enters from a known state and, given the same inputs, produces the same outputs because the LLM calls were cached or mocked. This relies on LangGraph's checkpointer model. AutoGen's "determinism" is a function of agent seed + model seed + tool mock, none of which Chronos controls. CrewAI has no determinism story — task scheduling can interleave differently across runs.

**Empirical evidence.** The `chronos replay` TUI ships today against LangGraph-recorded runs and "just works" because the LangGraph checkpointer encodes everything needed to rebuild state. Porting it to AutoGen runs would require Chronos to either (a) record every tool call's output (blow up DB), or (b) declare that AutoGen replay is "best-effort reconstruction" not "exact re-execution."

**Mitigation.**
- **Phase 3 problem, flagged here.** R27 does not resolve; Phase 2 explicitly does not promise cross-framework replay.
- **ADR-016 contract does not require `replay()`.** Replay lives in the CLI (`chronos replay`), which today assumes LangGraph semantics. When the second adapter lands (R28-R29), the replay CLI either stays LangGraph-only (explicit check: raise on non-LangGraph runs) or degrades to a state-viewer (no re-execution). Lean toward the former: `chronos replay --adapter langgraph` becomes required, default errors with a helpful message.
- **If a user wants cross-framework replay**, they implement it on top of `state_after` dumps themselves. Chronos's contribution is durable recording, not deterministic re-execution.
- **Owner**: Phase 3 (if ever); R27 flags; R28-R29 must add the adapter-type guard to `replay` CLI.

---

## R-6: Side-effect strategy (tool calls, outbound HTTP, DB writes) is framework-specific

**Description.** Forking a recorded run means re-executing node code. If nodes have side effects — sending an email, charging a credit card, writing to a production DB — naive fork execution re-triggers those side effects. LangGraph nodes are arbitrary Python functions with no metadata distinguishing "pure" from "side-effecting." AutoGen tools are declared via `@tool` with loose conventions. CrewAI tools are `BaseTool` subclasses, also without a side-effect taxonomy.

**Empirical evidence.** ADR-006 (fork semantics, R5) explicitly deferred side-effect strategy to Phase 3 with a "caveat emptor" note. R22's `fork plan --emit python` artifact-first approach (ADR-008) was *partially motivated* by this: the user fills in two TODO blocks with the graph factory and input state, which forces them to think about whether they're willing to re-run the graph. This is a social mitigation, not a technical one.

**Mitigation.**
- **Phase 3 problem.** No change in Phase 2.
- **Status quo**: `fork plan --emit python` stub output, with its explicit TODO blocks, is the correct UX for the current era. Chronos does not call user code in the execute path — the user does.
- **Future ADR (tentatively ADR-019)** could introduce a `@chronos.pure` / `@chronos.idempotent` decorator convention and a `Node.side_effects` column; both are speculative and not warranted without user demand.
- **Owner**: Phase 3 (ADR-006 lineage); R27 flags.

---

## Summary table

| ID | Risk | Severity | Owner | Phase 2 action |
|----|------|----------|-------|-----------------|
| R-1 | Event-model drift | Medium | ADR-016 | R28-R29: pick adapter with divergent event model |
| R-2 | Fork primitive not portable | **High** | ADR-016 | R28-R29: adapter must pass fork dogfood; red line on core |
| R-3 | Usage metering gaps | Medium | ADR-015 | R28-R29: CI double-dogfood asserts non-zero usage |
| R-4 | Async vs sync | Medium | Deferred ADR-017 | None until AutoGen adapter PR opens |
| R-5 | Replay not cross-framework | Low | Phase 3 | R28-R29: `chronos replay` gains adapter-type guard |
| R-6 | Side-effect strategy | Low | Phase 3 | None; current UX (stub with TODOs) is correct |

**Two of six risks require concrete Phase 2 action (R-2 red line + R-3 CI evidence)**. One (R-4) is flagged for when it becomes concrete. Three are either already in the contract (R-1) or legitimately deferred (R-5, R-6).

---

## Phase 2 entry checklist delta

With this document written, ADR-014 criteria status becomes:

- **R1** — adapter interface + ≥1 reference impl: Contract ✅ (R26 ADR-016) / Impl ❌ (R28-R29)
- **R2** — extractor contract consolidated: ✅ (R25 ADR-015)
- **R3** — dogfood in CI against two adapters: ❌ (R28-R29)
- **R4** — multi-framework risks doc: **✅ (R27 this doc)**

**3/4 contract/doc criteria green. R1-impl + R3 remain as R28-R29.** Phase 2 opens at R30.

---

## Review cadence

This doc is not frozen. When R28-R29 lands, each risk gets a **verdict paragraph** appended: did the reference adapter confirm the risk, refute it, or surface a new one? R-4 specifically will get its ADR-017 link inserted the first time an async adapter is attempted.

If any Phase 2 PR triggers a risk not on this list, add R-7 / R-8 / … with the same three-paragraph structure rather than editing existing entries.
