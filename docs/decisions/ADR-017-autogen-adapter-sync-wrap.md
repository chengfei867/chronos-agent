# ADR-017: AutoGen Adapter — Sync-Wrap Strategy for Async-First Frameworks

**Status**: Accepted
**Date**: 2026-04-24 (Round 33)
**Deciders**: chengfei867, Hermes Agent
**Depends on**: ADR-016 (adapter interface), ADR-015 (extractor contract v2)
**Related**: `docs/research/multi-framework-risks.md` R-4 (async-execution mismatch)

---

## Context

### The forcing function

R33 opens Phase 2's headline work: shipping a **second real** framework adapter — AutoGen — to prove `AdapterProtocol` (ADR-016) isn't a LangGraph look-alike. `autogen-agentchat==0.7.5` is the target SDK.

### The structural mismatch

AutoGen 0.7 is **async-first by API contract**. The top-level execution surfaces — `Team.run()`, `Team.run_stream()`, `AssistantAgent.on_messages()` — are all coroutines/async generators with no sync equivalents:

```python
# from autogen_agentchat/teams/_group_chat/_base_group_chat.py
async def run(self, *, task, ...) -> TaskResult: ...
async def run_stream(self, *, task, ...) -> AsyncGenerator[...]: ...
```

`RecorderProtocol` (ADR-016 P1) defines `record()` as a **sync** `AbstractContextManager[RunRef]`:

```python
def record(self, runtime: Any, *, thread_id: str, ...) -> AbstractContextManager[RunRef]: ...
```

A user block written naively cannot span both worlds — you can't `await team.run(...)` inside a `with recorder.record(...) as ref:` block.

### The R33 spike result

Before writing this ADR we ran a 3-minute spike (`/tmp/spike_autogen.py`) to answer one question: *"Can we call `await team.run(...)` from inside a sync context manager via `asyncio.run()`?"*

Result: **yes**, with caveats. `asyncio.run(team.run(task=...))` returns a full `TaskResult` object containing `messages: list[BaseChatMessage]` covering the entire multi-agent exchange. Every participant utterance, every tool call, every termination decision is observable *after the fact* from this single return value — no async streaming required to see the nodes.

This is the first evidence that the mismatch is **API-surface-deep**, not architecturally deep.

### The two paths

**Path A — Sync wrap** (this ADR's choice)

Keep `RecorderProtocol` as-is. The AutoGen adapter's `record()` is a sync CM. Users do:

```python
with autogen_adapter.build_recorder(store).record(team, thread_id="t1") as ref:
    result = asyncio.run(team.run(task="say hi"))
# on CM exit: AutoGenRecorder walks result.messages, persists Nodes, populates ref
```

Node derivation happens in `__exit__` by inspecting the user-returned `TaskResult` (or by the user optionally calling `ref.submit_result(result)` — bikeshed below).

**Path B — Parallel `AsyncRecorderProtocol` family**

Introduce a second Protocol family. Users do:

```python
async with autogen_adapter.build_async_recorder(store).record(team, thread_id="t1") as ref:
    result = await team.run(task="say hi")
```

Two parallel Protocols (sync + async); adapters pick which one they implement; cross-adapter code fans out through a union type.

---

## Decision

**We take Path A for Phase 2.** The AutoGen adapter ships as a sync `RecorderProtocol` implementation; users wrap their async AutoGen calls with `asyncio.run()` inside the `with` block.

### Why sync wrap wins *for our goals*

1. **DX is the north star.** Chronos is an OSS tool competing for GitHub stars, not a framework ceremony. "Install. Write 3 lines. See your agents." is the pitch. `asyncio.run()` is one line users already know; `async with` flips every call site in their codebase.

2. **Single Protocol family = single audit surface.** Two parallel Protocols double the ADR-015/016 invariants (fork semantics, atomicity, extractor contract). Each future adapter would have to decide sync-or-async; each bug hunt would have to repro on both. For a 2-framework Phase 2 this is overkill.

3. **The spike proved `TaskResult` is enough.** For the Phase 2 scope (record multi-agent runs, map messages to Nodes, extract usage per message), post-hoc inspection of `TaskResult.messages` gives us the same data as async streaming. Async streaming only buys **progressive** observation — a UI concern we've explicitly deferred to Phase 3+ (ADR-014 non-goal).

4. **We can always add Path B later without breaking users.** `AsyncRecorderProtocol` can land as a strict superset in a future minor version if/when streaming or cancellation becomes necessary. Taking Path B now would be premature — we'd be paying interface-expansion costs before knowing what async users actually need.

### What the AutoGen adapter provides

- `autogen_adapter: AdapterProtocol` (module-level, per ADR-016 / R32 convention for langgraph + linear).
- `AutoGenRecorder(store, kind_map=None, usage_extractor=None)` conforming to `RecorderProtocol`.
- `record(runtime: Team, *, thread_id, task_description=None, tags=None)` — sync CM.
  - On enter: yields a `RunRef` with `run_id=None`, `node_ids=[]`, plus an **optional `submit_result(task_result)` method** as a convenience hook — if the user calls it, the recorder persists immediately on exit; if not, the recorder falls back to reading from `runtime.message_history` (AutoGen's internal buffer) as a best-effort.
  - On exit (no exception): persist `Run` with `status=COMPLETED`, one `Node` per `BaseChatMessage` in `TaskResult.messages`, each node's `state_after` = the cumulative message list at that point.
  - On exit (exception): persist with `status=FAILED`, still best-effort-populate nodes, re-raise.
- Usage extraction: AutoGen messages carry `models_usage: RequestUsage | None` fields (`prompt_tokens`, `completion_tokens`). The adapter's default `UsageExtractor` sums these per-node directly, bypassing LangGraph's callback-based `ADR-015 Layer 4`.
- Fork: **v0.2.0 scope does not ship fork for AutoGen.** Emitting a fork plan for a message-based execution model is a separate research ticket (candidate ADR-018). `AutoGenRecorder.fork()` exists as a `NotImplementedError` stub so the `RecorderProtocol` is structurally satisfied; calling it raises `AdapterError("fork not yet supported for AutoGen — tracked in roadmap Phase 3")`. The dual-adapter dogfood test (ADR-014 R3 artefact) stays gated on LangGraph + Linear; we do not extend it to AutoGen until fork lands.

### The `submit_result` hook rationale

AutoGen doesn't emit a Python-accessible event stream *unless* the user calls `team.run_stream()`. Because we chose `team.run()` (sync-wrap-friendly), the only way the recorder sees messages is by observing what the user got back. Options:

1. **User calls `ref.submit_result(result)` explicitly** — opt-in, zero ambiguity.
2. **Recorder reaches into `runtime.message_history`** — implicit, couples us to AutoGen internals.
3. **Recorder intercepts `team.run` via monkey-patching** — magic, rejected.

We ship both (1) and (2): (1) is the documented primary path (guaranteed correctness); (2) is the fallback for "I forgot to call submit_result" so the recorder is never silently empty. If both diverge, `submit_result` wins.

---

## Consequences

### Positive

- AutoGen adapter ships in 1–2 rounds instead of 3–5 (no new Protocol family, no migration plan for existing adapters).
- Users only learn one Chronos API shape across all adapters.
- ADR-015 extractor contract is unmodified; the AutoGen extractor is pure "read `models_usage` off each message" — simpler than LangGraph's callback bridge.
- Path B remains available if we ever need streaming; taking Path A now doesn't burn that bridge.

### Negative

- Users write `asyncio.run(team.run(...))` inside a sync `with` block. This is a minor idiom tax and must be documented prominently in `README` + `examples/autogen_quickstart.py`.
- Users already running inside an event loop (e.g. Jupyter, FastAPI) have to use `asyncio.get_event_loop().run_until_complete(...)` or `nest_asyncio` — a known Python foot-gun we inherit but don't cause.
- We defer AutoGen fork to Phase 3+ (ADR-018 candidate). A minor feature gap that's acceptable because the R33 goal is "second framework record + usage", not feature parity.

### Neutral

- `AutoGenRecorder.fork()` raising `NotImplementedError`-as-`AdapterError` is a deliberate design: it keeps structural `RecorderProtocol` conformance (so `isinstance(recorder, RecorderProtocol)` passes) while making the missing capability loud at call time rather than silent.

### Rollback plan

If Phase 2 dogfood reveals `asyncio.run()` is too painful in practice (e.g. all our users turn out to be FastAPI users hitting loop-already-running errors), we add an `AsyncRecorderProtocol` family in v0.3 as a strict superset. The sync adapter keeps working; async adopters migrate; no forced migration.

---

## Alternatives Considered

1. **Path B (parallel async Protocol family)** — rejected above. Primary cost is doubling every cross-adapter invariant.
2. **Force AutoGen users to write a custom sync wrapper** — rejected: shifts Chronos's core mission (nice DX) onto every user. Not a real alternative, included for completeness.
3. **Adopt `asgiref.sync.async_to_sync`** — considered, rejected: adds a transitive dependency for a one-liner we could do with stdlib `asyncio.run()`. Not worth it.
4. **Monkey-patch `team.run` to auto-intercept** — rejected: magic, breaks the "Chronos is transparent to your framework" property.

---

## References

- ADR-016 §P1 `RecorderProtocol` (sync CM contract)
- `docs/research/multi-framework-risks.md` R-4 (async execution)
- `/tmp/spike_autogen.py` — R33 spike confirming `asyncio.run()` round-trip works
- AutoGen source: `autogen_agentchat/teams/_group_chat/_base_group_chat.py::run`

*Last edited: 2026-04-24 (R33)*
