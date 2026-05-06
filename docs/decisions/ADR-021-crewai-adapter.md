# ADR-021: CrewAI adapter — event-bus recorder, sync-first, three-segment node_name

**Status**: Accepted
**Date**: 2026-04-27 (Round 51)
**Deciders**: Hermes Agent (autonomous)
**Depends on**: ADR-016 (adapter interface), ADR-020 (three-segment `node_name`),
 ADR-017 (async strategy — explicitly **not** inherited here)
**Related**: `tests/spikes/spike12_crewai_events.py` (empirical trigger),
 `src/chronos/adapters/autogen/` (shape reference),
 `src/chronos/adapters/effects.py` (R44-A classifier,
 consumer of `node_name`)

---

## Context

CrewAI is the third framework on the chronos-agent adapter roadmap, after
LangGraph (ADR-014) and AutoGen (ADR-017). Each previous adapter taught us
one architectural constraint:

- **LangGraph** — state-dict-based execution, graph-defined node names.
  Native fit for `node_name`; no `Team.run()` async burden.
- **AutoGen** — message-based, async-first `Team.run()` coroutine, tool
  function name buried one level below the event class name. Forced both
  ADR-017 (sync-wrap at call site) and ADR-020 (three-segment
  `node_name = "{source}:{ClassName}:{tool_name}"`).

CrewAI sits in a third spot in that design space: **event-bus-based,
sync-first `Crew.kickoff()`, tool metadata carried at the top level of
the event payload**. Spike 12 (`tests/spikes/spike12_crewai_events.py`)
characterized it empirically over 8 synthetic events on
`crewai_event_bus`. This ADR codifies the resulting adapter interface
before we scaffold the package.

### What Spike 12 established

Six findings gate the adapter design; all are asserted by
`spike12_crewai_events.py`:

- **F1 — Tool-event payload is already three-segment-ready.**
  `ToolUsageStartedEvent` and `ToolUsageFinishedEvent` carry `tool_name`
  and `agent_role` as top-level pydantic fields. The ADR-020
  `node_name = f"{agent_role}:{EventClassName}:{tool_name}"` construction
  is a pure string join — no reflection, no message-content scraping
  (contrast AutoGen, which had to teach the classifier a surgery rule).
- **F2 — Task events carry `task_name`.** `TaskStartedEvent` and
  `TaskCompletedEvent` expose `task_name` via `getattr` (attribute was
  added in mid-2024 versions and is safe to treat as stable on
  `>=0.80`).
- **F3 — LLM events thread `call_id` across started/completed pairs**
  and carry `model`, `usage`, and `response`. That gives the recorder
  enough to emit one `LLM`-kind `Node` per call without needing to hold
  state across events.
- **F4 — ⚠️ Sync handlers dispatch on a `ThreadPoolExecutor`, not
  inline.** `crewai_event_bus.emit()` returns a
  `concurrent.futures.Future`; without `future.result()` *and*
  `crewai_event_bus.flush(timeout=…)` before reading the buffer, a
  second same-class emit within the same synchronous caller can be
  lost. Reproducer in commit `f3ae302` (spike12 docstring). This is
  the single biggest departure from AutoGen/LangGraph and dictates the
  recorder's threading model.
- **F5 — `scoped_handlers()` context manager cleanly detaches
  handlers on `__exit__`.** Maps 1:1 to our `Recorder.record()` CM
  lifecycle; no handler leakage across runs, no manual
  `unregister()` bookkeeping.
- **F6 — `Crew.kickoff()` is sync.** `kickoff_async` exists as an opt-in
  path. **ADR-017's `asyncio.run()` sync-wrap is NOT needed** for the
  CrewAI adapter — users call `crew.kickoff()` inline inside the
  recorder CM.

### Why this matters for the classifier (ADR-020 fit)

The R44-A effect classifier only reads `node_name`. With F1 above, the
CrewAI recorder can build a function-shaped third segment natively,
which means:

- `researcher:ToolUsageStartedEvent:fetch_weather_api` → `network` tag
  (existing `\bfetch_\w+\b` regex).
- `researcher:ToolUsageStartedEvent:read_file` → `fs` tag
  (existing `\bread_file\b` regex).
- `researcher:ToolUsageFinishedEvent:query_database` → `db` tag.

No classifier patch required. No per-adapter effect table. The R48-A
"use real adapter output in classifier tests" lesson carries over —
but the shape itself is a drop-in.

## Decision

### D1 — Recorder uses CrewAI's event bus via `scoped_handlers()`

```python
from crewai.events import crewai_event_bus

@contextmanager
def record(self, target, *, thread_id):
    run = self._start_run(...)
    ref = RunRef(run_id=run.id, ...)
    self._buffer = []  # thread-safe via self._lock
    with crewai_event_bus.scoped_handlers():
        crewai_event_bus.on(ToolUsageStartedEvent)(self._on_tool_started)
        # ... register all F1/F2/F3 event kinds ...
        try:
            yield ref
        finally:
            crewai_event_bus.flush(timeout=self.flush_timeout_s)
            self._drain_buffer_to_store(run)
```

- No manual `unregister()` path; `scoped_handlers()` guarantees detach
  on both normal exit and exceptions (F5).
- `flush(timeout=…)` before `_drain_buffer_to_store` is **required**,
  not optional — without it, ThreadPoolExecutor-queued handlers can
  race past the CM exit (F4). Default `flush_timeout_s = 5.0`.

### D2 — Buffer is thread-safe (`threading.Lock` + list)

F4's async dispatch means handler callbacks run on CrewAI's executor
threads. The recorder MUST protect its staging buffer:

```python
self._lock = threading.Lock()
self._buffer: list[_PendingNode] = []

def _on_tool_started(self, source, event):
    pending = self._build_tool_node(event, "started")
    with self._lock:
        self._buffer.append(pending)
```

Store writes happen after `flush()` on the main thread, so SqliteStore
itself does not need to be thread-safe from the recorder's side — the
lock scope is strictly the staging list.

### D3 — `node_name` is three-segment per ADR-020

Format is fixed by ADR-020 and confirmed viable by F1. For tool events:

```python
node_name = f"{event.agent_role}:{type(event).__name__}:{event.tool_name}"
```

For LLM and task events (where there's no `tool_name`), the third
segment is a best-effort identity token so the shape stays uniform for
CLI/UI column alignment:

```python
# LLM:   "{agent_role}:LLMCallStartedEvent:{call_id}"
# Task:  "{agent_role or '*'}:TaskStartedEvent:{task_name}"
```

The classifier only fires on tool events (regex library is tool-name
shaped), so the identity-token third segment for LLM/Task is
classifier-inert — safe by construction.

### D4 — Kind map covers {TOOL, LLM, FN, END}

Defaults, overridable via `kind_map: dict[str, NodeKind]`:

| CrewAI event class          | Default `NodeKind` |
|-----------------------------|--------------------|
| `TaskStartedEvent`          | `FN`               |
| `TaskCompletedEvent`        | `FN`               |
| `ToolUsageStartedEvent`     | `TOOL`             |
| `ToolUsageFinishedEvent`    | `TOOL`             |
| `LLMCallStartedEvent`       | `LLM`              |
| `LLMCallCompletedEvent`     | `LLM`              |
| `CrewKickoffCompletedEvent` | `END`              |

Agent-level events (`AgentExecutionStartedEvent` /
`AgentExecutionCompletedEvent`) are deliberately **not recorded** in
the MVP — they're a superset of task+tool+llm spans, would double-count
in the timeline, and can be added behind a flag later if a user needs
them.

### D5 — `Crew.kickoff` is called by the user, inline, sync

No `asyncio.run` wrapper. The documented usage pattern is:

```python
with crewai_adapter.build_recorder(store).record(crew, thread_id="t1") as ref:
    result = crew.kickoff(inputs={"topic": "weather"})
    ref.submit_result(result)
```

`kickoff_async` callers are supported as a follow-up only if a user
asks; no anticipatory code.

### D6 — Telemetry is disabled at import time in tests

CrewAI's default telemetry phones home on `import crewai` (OpenTelemetry
traces + PostHog). The adapter itself does **not** touch telemetry at
runtime (users may want their own tracing), but our test harness and
spike sets `CREWAI_DISABLE_TELEMETRY=1` and `OTEL_SDK_DISABLED=true`
before any crewai import. The recorder module's `__init__` will include
a docstring note recommending the same for production use in sandboxed
CI.

### D7 — Usage extraction from `LLMCallCompletedEvent.usage`

`usage` is a dict with `prompt_tokens` / `completion_tokens` /
`total_tokens` (verified F3). Copy verbatim into
`chronos.core.models.Usage`. Like AutoGen, `reasoning_tokens` stays 0
— CrewAI doesn't surface it.

The ADR-015 `UsageExtractor` callback is **not** wired in (same rule
as AutoGen): passing a non-`None` `usage_extractor` raises
`AdapterError`.

### D8 — Version constraint `crewai >= 0.80, < 1.0`

- `0.80+` is where `scoped_handlers()`, `Future`-returning `emit()`,
  and the `tool_name` / `agent_role` top-level fields on
  `ToolUsage*Event` are all stable.
- Pin upper bound at `< 1.0` pre-emptively — CrewAI hasn't cut a 1.0
  yet and the event schema is explicitly marked unstable in their
  docs.

## Consequences

### Positive

- **Effect classifier works out of the box.** No per-adapter shim, no
  classifier patch, no new regex rules. ADR-020's three-segment
  shape earns a second framework "for free."
- **Sync-first kickoff removes the biggest AutoGen ergonomics pain
  point.** Users don't wrap calls in `asyncio.run(...)`. Existing
  chronos code samples, CLI `chronos run`, and the Web UI
  "run/fork" flow all apply unmodified.
- **Event-bus model is the cleanest framework-to-chronos mapping
  we've seen.** LangGraph's `StateSnapshot` needed a history-walk;
  AutoGen's `TaskResult.messages` needed an on-exit drain. CrewAI
  emits individual events pre-shaped for Node creation — the
  recorder is mostly glue.
- **`scoped_handlers()` eliminates a whole failure mode.**
  AutoGen/LangGraph recorders could in principle leak subscribers
  across runs if an exception bypassed cleanup. CrewAI's CM
  guarantees detach, so this can't happen.

### Negative

- **Threading model is new.** F4's ThreadPoolExecutor dispatch is a
  footgun for anyone contributing to the CrewAI recorder without
  reading this ADR. The module docstring must call out the
  `flush()+lock` requirement prominently, and the recorder tests must
  include a concurrency smoke (rapid-fire same-class emits) to keep
  the regression fence up.
- **We now carry three distinct adapter paradigms.** LangGraph
  (state-dict, graph), AutoGen (message list, async), CrewAI (event
  stream, sync). Any cross-cutting refactor in the adapter layer will
  need to thread three needles. The `protocols.RecorderProtocol` CM
  interface continues to be the shield against this leaking upward.
- **`kickoff_async` is unsupported in v0.1 of the adapter.** If a
  heavy user wants the async path we'll need a small ADR delta, but
  F6 says the sync path is the idiomatic one and we're not preempting.
- **No agent-level events in MVP (D4).** A user wanting an "agent"
  row in the timeline will have to wait. Low priority — nobody has
  asked yet and the tool/llm/task slice already captures the signal.

## Alternatives considered

### Alternative 1 — Listener-class subclassing (`BaseEventListener`)

CrewAI's docs push `class MyListener(BaseEventListener): setup_listeners(self, event_bus): ...`
as the recommended extension pattern. Pros: more idiomatic-CrewAI,
self-documenting. Cons: listener registration is *global*, no
per-run scope, conflicts with our CM lifecycle. `scoped_handlers()`
is CrewAI's own solution for the exact problem we have — it exists
because the listener class is too coarse-grained for run-scoped
recording. **Rejected**.

### Alternative 2 — Monkey-patch `Crew.kickoff` like the LangGraph compile-hook

LangGraph's recorder hooks `graph.compile()`. Pros: zero user code
changes. Cons: CrewAI has no equivalent compile step, and the bus
already offers a clean inversion point. Monkey-patching `kickoff`
would add brittleness (version-dependent signatures, multi-crew
runs, reentrancy) for no gain over the CM pattern. **Rejected**.

### Alternative 3 — Synchronous inline handlers (force-synchronous dispatch)

In theory the adapter could patch `crewai_event_bus` to replace the
`ThreadPoolExecutor` with an inline dispatch. Pros: no threading
model in the recorder. Cons: mutates global CrewAI state, would
break concurrent users, and the F4 reproducer shows CrewAI's
executor is load-bearing in their own fan-out logic.
**Rejected — not our executor to touch.**

### Alternative 4 — Inherit ADR-017 sync-wrap even though `kickoff` is sync

Strictly additive. Pros: uniform with AutoGen. Cons: `asyncio.run()`
around a sync function is a no-op at best and an event-loop misuse
at worst. F6 makes this pointless. **Rejected**.

## Follow-ups

- **R51 implementation.** Scaffold `src/chronos/adapters/crewai/`
  (`__init__.py`, `recorder.py`), mirror the AutoGen shape. Duck-only
  unit tests + module-level `crewai_adapter` singleton.
- **Concurrency regression test.** `test_adapter_crewai.py` must
  include a test that fires three `ToolUsageStartedEvent`s of the same
  class back-to-back and verifies all three land in the buffer (F4
  regression fence).
- **End-to-end live spike (Round 52 candidate).** Point a real
  OneAPI GLM/Claude at a 2-agent crew with 3 tools, mirror
  spike10's AutoGen test plan, confirm effect tags light up on real
  events. Deferred — offline spike12 + unit tests are the R51 gate.
- **`effects_map` keyword coverage audit.** Check whether CrewAI's
  conventional tool names (e.g. `SerperDevTool`, `WebsiteSearchTool`)
  trip the existing regex library or need new rules. Low risk; most
  CrewAI example code uses `snake_case_tool_names` already.
- **Agent-level events** — defer until user demand. Design sketch:
  add `"AgentExecutionStartedEvent": NodeKind.FN` to `kind_map`,
  opt-in via `adapter_specific={"record_agent_events": True}`.

## References

- `tests/spikes/spike12_crewai_events.py` — empirical trigger,
  F1–F6 asserted on `crewai_event_bus`.
- `src/chronos/adapters/autogen/__init__.py` /
  `src/chronos/adapters/autogen/recorder.py` — shape reference for
  the CrewAI scaffold.
- `src/chronos/adapters/effects.py` — R44-A classifier, consumes the
  three-segment `node_name`.
- ADR-016 — adapter interface (Recorder/Adapter protocols).
- ADR-017 — AutoGen sync-wrap strategy (NOT inherited).
- ADR-020 — three-segment `node_name` shape (inherited).
- CrewAI source: `crewai/events/event_bus.py:485–590`
  (`emit` / dispatch / flush),
  `crewai/events/types/{tool_usage,task,llm}_events.py`
  (event schemas).

## Three-trigger re-open rule (mirrors ADR-013 / ADR-019 / ADR-020)

This ADR may be revisited only if **at least three** of the following fire:

1. CrewAI's event schema changes such that `tool_name` or `agent_role`
   stops being top-level (would force a parse rule like AutoGen's).
2. `crewai_event_bus.emit()` changes from Future-returning to inline
   (would let us drop the flush+lock machinery).
3. `Crew.kickoff` becomes async-only (would force ADR-017
   inheritance after all).
4. A real-user bug report shows the three-segment `node_name` colliding
   with CrewAI's own logging/tracing in a way that damages UX.
5. A CrewAI 1.0 release materially reworks the adapter surface (e.g.
   introduces a first-class "tracer" interface that obsoletes the
   event-bus path).

Until then, the event-bus recorder + sync-first `kickoff` + ADR-020
three-segment `node_name` is the convention.
