# ADR-016: Adapter Interface — Protocol-Based Contract for Framework Recorders

**Status**: Accepted
**Date**: 2026-04-23 (Round 26)
**Deciders**: chengfei867, Hermes Agent
**Consolidates**: (none — first adapter-interface ADR)
**Depends on**: ADR-004 (snapshot→node mapping), ADR-005 (fork semantics), ADR-015 (extractor contract v2)
**Supersedes**: the roadmap's vague "ADR-005 on adapter interface" placeholder (roadmap reference was stale; ADR-005 became fork semantics in R5)

---

## Context

### Why we need this now

ADR-014 ("Phase 2 entry criteria", R24) froze the transition to multi-framework support behind four gates:

- **R1** — Adapter interface extracted as a typed `Protocol` with ≥1 non-LangGraph reference implementation landed *behind a feature flag*.
- **R2** — Extractor contract formalised (✅ delivered by ADR-015 in R25).
- **R3** — Dogfood triple (record → fork plan emit → fork plan exec) green on LangGraph **and** the Phase-2 reference adapter, in CI.
- **R4** — A written "what breaks at multi-framework boundary" risks doc with mitigations.

**This ADR addresses R1.** It does *not* ship the reference adapter; it defines the contract the reference adapter will implement. Writing the contract before the adapter is deliberate: we want the Protocol to be derivable from `LangGraphRecorder`'s *external* behaviour, not retrofitted after AutoGen/CrewAI wiring bends the shape.

### What actually varies across frameworks

Frameworks we care about (LangGraph today; AutoGen + CrewAI considered for Phase 2) differ along axes the current code conflates:

| Axis | LangGraph (today) | AutoGen (hypothetical) | CrewAI (hypothetical) |
|------|-------------------|------------------------|------------------------|
| Execution model | Checkpointed state machine | Message-passing conversation | Task DAG with role-based agents |
| Node identity source | `source='loop'` snapshots + `writes` dict | `ChatResult.message.source` field | Task object + agent role |
| State model | Mutable dict at every step | Immutable message history | Task inputs/outputs + shared context |
| Fork primitive | `graph.update_state(as_node=…)` + `graph.invoke(None)` | Re-seed agent history, re-invoke | Re-submit task with altered input |
| Usage origin | Callback-attached LLM runs (ADR-015 Layer 4) | `ChatCompletion.usage` per message | Per-task `llm.usage` attribute |
| Determinism | Checkpointer-driven (shared saver) | Agent-seed + tool-mock | Task-executor seed |

The current `LangGraphRecorder.record`/`.fork` API *happens* to be framework-agnostic at the **signature** level — the arguments are `graph`, `thread_id`, `overrides`, etc. — but the *semantics* bake in LangGraph assumptions (snapshot history shape, `update_state(as_node=...)`, `AdapterError` wording). We need to separate the contract from the LangGraph-specific implementation without breaking existing callers.

### Non-goals

- **No AutoGen/CrewAI adapter in this ADR.** R1 requires ≥1 reference non-LangGraph implementation, but that ships in a later round (targeted R29 per the roadmap refresh). ADR-016 is the *contract*; the implementation is a separate deliverable.
- **No changes to `Run`/`Node`/`Fork` schema.** ADR-003 owns the persistence model; the adapter interface consumes it.
- **No changes to the extractor contract.** ADR-015 is final; ADR-016 references it.
- **No changes to CLI.** ADR-016 is a library-internal contract. The CLI already operates on `Run`/`Node`/`Fork` rows, which are framework-agnostic.
- **No new Protocol for "adapter discovery" / plugin registry.** Phase 2 may need one; Phase 1 has exactly one adapter, so a registry is premature.

---

## Decision

**Three `typing.Protocol` classes** in `src/chronos/adapters/protocols.py`, plus **two dataclass aliases** that are already framework-agnostic. The `LangGraphRecorder` keeps its current public signature and becomes the first conformant implementation; no user-facing rename.

### P1. `RecorderProtocol` — the core record/fork contract

```python
class RecorderProtocol(Protocol):
    """Framework-agnostic recorder. All methods are context managers."""

    def record(
        self,
        runtime: Any,
        *,
        thread_id: str,
        task_description: str | None = None,
        tags: list[str] | None = None,
    ) -> ContextManager[RunRef]: ...

    def fork(
        self,
        runtime: Any,
        *,
        parent_run_id: str,
        at_node_id: str,
        overrides: dict[str, Any] | None = None,
        child_thread_id: str,
        reason: str | None = None,
        task_description: str | None = None,
        tags: list[str] | None = None,
    ) -> ContextManager[ForkRef]: ...
```

**Renames** (contract level only):
- Parameter `graph` → `runtime`. LangGraph calls it a graph; AutoGen calls it a `GroupChatManager`; CrewAI calls it a `Crew`. `runtime` is neutral.
- `LangGraphRecorder` keeps `graph=` as a **positional-compatible alias** — existing callers unaffected; new adapters use `runtime=`.

**Semantics required of every implementation**:

1. **`record()` ctx-manager contract**:
   - On enter: yield a mutable `RunRef(thread_id=…)` with `run_id=None`, `node_ids=[]`.
   - On normal exit: persist a `Run` + its `Node`s with `status=COMPLETED`; populate `ref.run_id` and `ref.node_ids` *before* returning to caller.
   - On exception from the user block: persist with `status=FAILED`, populate the ref, **re-raise**.
   - Empty runs (user never invoked the runtime) are a silent no-op — no Run row.

2. **`fork()` ctx-manager contract**:
   - On enter: validate `parent_run_id` and `at_node_id` exist in the store and that `at_node_id.run_id == parent_run_id`. Validate `child_thread_id != parent.adapter_thread_id`. Seed the child execution so the runtime continues from the parent node's `state_after` merged with `overrides`.
   - On normal exit: persist child `Run` + `Node`s + `Fork` row; populate `ref.child_run_id`, `ref.fork_id`, `ref.node_ids`.
   - On exception from the user block: persist with `status=FAILED` (child run still committed for inspection), **re-raise**.

3. **Atomicity**: persistence happens in a single `store.transaction()`. Partial runs are never committed.

4. **Idempotency**: re-entering `record()` with the same `thread_id` is legal and creates a *new* Run (thread_id is not a key; UUID is).

5. **Errors**: structural drift (runtime emitted an unexpected shape) raises `AdapterError`. Nothing else in the adapter layer should leak framework-specific exceptions to callers.

### P2. `AdapterProtocol` — the constructor contract

```python
class AdapterProtocol(Protocol):
    """What every adapter module must expose at import time."""

    def build_recorder(
        self,
        store: SqliteStore,
        *,
        kind_map: dict[str, NodeKind] | None = None,
        usage_extractor: UsageExtractor | None = None,
        **adapter_specific: Any,
    ) -> RecorderProtocol: ...

    name: str  # e.g. "langgraph", "autogen", "crewai"
    version_constraint: str  # e.g. ">=0.4,<0.6" — the runtime library version range
```

This is the **plugin shape** — the one thing a new-adapter package exposes. It is deliberately small: it hands you a `RecorderProtocol`. Everything else (callbacks, checkpointer bridges, message buses) is an internal concern of the adapter.

**`**adapter_specific`** is the pressure-release valve. LangGraph has zero extra kwargs today; AutoGen will probably need `group_chat_filter=` or similar. Keyword-only, adapter-owned — never leaks into cross-adapter code.

### P3. `NodeIdentityResolver` — the pluggable naming hook

```python
class NodeIdentityResolver(Protocol):
    """Maps a framework-native execution event → (node_name, node_kind).

    LangGraph uses `source='loop' + writes` to derive `node_name`; other
    frameworks will extract it differently. This is the ONE
    framework-specific piece of state-machine semantics we expose as a hook.
    """

    def resolve(self, event: Any) -> tuple[str, NodeKind] | None: ...
```

**Why expose this?** Because `kind_map` today is a static name→kind dict. For AutoGen, the node *name* itself is derived (it's the speaker name in a message). A resolver lets the adapter author plug in "how do I get the node_name from *your* event type" without us inventing an event taxonomy.

Phase 1 default resolver for LangGraph is trivial and lives inside `LangGraphRecorder` — no user exposure. We document this Protocol now so Phase 2 adapter authors have a known hook.

### Layering vs. ADR-015 (extractor contract)

ADR-015 defines a 5-layer stack for **usage extraction** (Layer 1 input → Layer 5 emission). ADR-016 is orthogonal:

- ADR-015 = "how do we pull `{prompt_tokens, completion_tokens, cost_usd, model_name}` out of whatever the framework produces"
- ADR-016 = "how do we drive recording/forking across any framework"

The two meet at **`UsageExtractor`** (ADR-015 Layer 1–3 protocol), which `AdapterProtocol.build_recorder` accepts as a parameter. Adapters are responsible for *finding* the raw LLM event objects in their framework and feeding them to the `UsageExtractor`; the extractor is responsible for producing canonical `CallUsage`. Same contract both directions — no framework code in extractors, no extractor logic in adapters.

### Dataclass aliases (no change)

`RunRef` and `ForkRef` stay as-is. They were already framework-neutral dataclasses. We move their definitions from `adapters/langgraph.py` to `adapters/protocols.py` and re-export from `adapters/langgraph.py` for backward compatibility. No import-path change for users.

---

## Consequences

### Positive

- **R1 (ADR-014) is structurally satisfied** as soon as we land one non-LangGraph adapter that conforms. The contract is ready; the adapter can be sketched as a thin `autogen_stub.py` for Phase 2 entry.
- **`LangGraphRecorder` becomes a reference implementation** rather than "the adapter". Testing can target the Protocol via duck typing; fakes in tests become trivial (already the case for unit tests — we never imported real LangGraph).
- **`AdapterError` is now the one supported failure mode**. Phase 2 adapter authors know: if your framework drifts, raise `AdapterError`. Any other leak is a bug.
- **No migration needed**. Existing `LangGraphRecorder(store, kind_map=…, usage_extractor=…)` call sites keep working. `graph=` positional/keyword still accepted.

### Negative / costs

- **One more Protocol file** to read before writing a new adapter. Mitigated by making `adapters/protocols.py` < 200 LOC and *only* containing the 3 Protocols + 2 dataclass re-exports.
- **`NodeIdentityResolver` is speculative**. We don't have a second adapter yet to prove it's shaped right. Acceptable: if Phase 2 discovers the resolver is wrong, we revisit in ADR-017. The cost of guessing the hook now < cost of retrofitting later (R5's adapter rush was painful).
- **`runtime=` rename** introduces a minor cognitive load: docstrings now say `runtime`, codebase internals still use `graph` for LangGraph-specific methods. Mitigated by the positional alias and by keeping `graph` everywhere it's *actually* a LangGraph graph.
- **No enforcement mechanism** — Python Protocols are structural, not nominal. Conformance is verified by tests, not by the runtime. This is by design (ADR-015 took the same stance); we rely on CI, not inheritance.

### Neutral / deferred

- **Plugin discovery / registry**: defer to Phase 2 when we have ≥2 adapters and need to dispatch by name. Candidate mechanism: entry points group `chronos.adapters`. Not in ADR-016.
- **Async variants**: `AsyncRecorderProtocol` may be needed for AutoGen (which is async-first). Not in ADR-016. We'll either add it in ADR-017 or absorb async under the sync Protocol if it turns out users always drive via `asyncio.run()`.
- **Partial conformance**: an adapter that supports `record()` but not `fork()` (e.g., a read-only OTel receiver in Phase 3) is legal today by returning `ContextManager[ForkRef]` that raises `NotImplementedError` on enter. A cleaner split (two separate Protocols) is deferred until we have that use case.

---

## Alternatives considered

### A1. Abstract base class (`abc.ABC`) instead of `Protocol`

Rejected. `Protocol` gives us structural typing — `LangGraphRecorder` is *already* a conformant recorder without inheriting from anything. ABCs would force every adapter to import from `chronos.adapters.base`, creating a runtime dependency that structural typing doesn't need. ADR-015 also chose Protocol for the extractor stack; consistency matters.

### A2. Single "Adapter" Protocol that includes both construction and record/fork

Rejected. Mixing the module-level plugin shape (`build_recorder`, `name`, `version_constraint`) with the instance-level recording shape (`record`, `fork`) forces the instance to know metadata that only matters at import time. Splitting into `AdapterProtocol` (module shape) + `RecorderProtocol` (instance shape) is cleaner and matches how `setuptools` / `entry_points` think about plugins.

### A3. Drop `NodeIdentityResolver` until we need it

Considered but rejected. The argument: YAGNI, we have one adapter, don't speculate. The counter-argument: ADR-014 gate R3 requires dogfooding a second adapter in CI, and R23 taught us that `node_name` derivation is the *first* thing that breaks at a framework boundary (LangGraph `writes` dict vs. anything else). Documenting the hook now (even as a 3-line Protocol) is cheap insurance. If Phase 2 reshapes it, we revisit.

### A4. Make `UsageExtractor` part of `RecorderProtocol` directly

Rejected. ADR-015 already defines `UsageExtractor` as a standalone Protocol passed to the recorder. Re-declaring it inside `RecorderProtocol` would duplicate the layer boundary. Composition over aggregation: `RecorderProtocol` *accepts* a `UsageExtractor`; it doesn't *extend* it.

### A5. `runtime: Any` → `runtime: Runtime` (another Protocol)

Rejected. We would have to define what "a runtime" is (has `get_state_history`? has `update_state`?), which *is* framework-specific. The whole point of the adapter layer is to wall off that knowledge. `Any` is honest here; the recorder internally knows how to talk to its own framework's runtime.

---

## Rollout

1. **This ADR.** Define the contract (R26).
2. **Refactor LangGraphRecorder** to import `RunRef`/`ForkRef` from `adapters/protocols.py`; verify conformance via a `cast(RecorderProtocol, LangGraphRecorder(...))` smoke test (R26 or R27).
3. **Add `langgraph_adapter: AdapterProtocol`** module-level instance exposing `build_recorder`, `name="langgraph"`, `version_constraint` (R27).
4. **Sketch a minimal second adapter** (AutoGen stub or a toy in-memory "linear pipeline" adapter) that conforms, *behind a feature flag* — satisfies ADR-014 R1 (R28–R29).
5. **Gate-check ADR-014**: R1 ✅, R2 ✅ (ADR-015), R3 pending (needs dogfood on adapter #2), R4 pending (risks doc).

---

## References

- ADR-004: LangGraph snapshot→node mapping — the first framework-specific algorithm this interface abstracts over.
- ADR-005: Fork semantics — the fork contract this Protocol inherits.
- ADR-014: Phase 2 entry criteria — R1 is what this ADR satisfies.
- ADR-015: Extractor contract v2 — the sister contract for usage extraction; cited by `RecorderProtocol` constructor kwargs.
- Roadmap Phase 2 "AutoGen adapter" bullet — updated in R26 to reference this ADR instead of the stale "ADR-005 on adapter interface" placeholder.
