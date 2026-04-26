# ADR-020: Adapter tool-event `node_name` shape — embed tool name

**Status**: Accepted
**Date**: 2026-04-27 (Round 48-A)
**Deciders**: Hermes Agent (autonomous)
**Depends on**: ADR-016 (adapter interface), ADR-019 (no sandbox — Phase 3 "warn, don't sandbox" charter)
**Related**: `docs/research/r48a-autogen-tool-effects.md` (R48-A research note, empirical trigger),
`tests/spikes/spike10_autogen_tool_effects.py` (R48-A real-LLM spike),
`src/chronos/adapters/effects.py` (R44-A effect classifier, PH3-02)

---

## Context

Phase 3's effect-awareness pipeline (R44-A → R47) ships in three layers:

1. **Adapter layer** — each recorder computes `Node.metadata["effects"]` by
   running a keyword-regex classifier over `Node.node_name`.
2. **CLI layer** — `chronos fork plan` reads those tags to show a
   "downstream side-effects" preview (R45-A, PH3-03).
3. **Web UI layer** — `ForkPlanModal` surfaces a warning Alert when
   `effects_summary.dangerous_count > 0` (R46-A, PH3-04).

The classifier (`src/chronos/adapters/effects.py::classify_effects`) works
purely by substring / word-boundary regex: `\bfetch_\w+\b` → `network`,
`\bread_file\b` → `fs`, etc. The input string is `node_name`.

### The bug R48-A caught

R44-A unit tests for the classifier used synthetic `node_name` strings
that already looked function-shaped (`"fetch_weather"`, `"read_file"`).
But the AutoGen recorder synthesizes `node_name` from message shape, not
from any function name, because AutoGen is message-based not
graph-based.

Before R48-A, AutoGen tool events emitted:

    node_name = "{source}:{ClassName}"   # e.g. "coder:ToolCallExecutionEvent"

The actual tool function name (`fetch_weather_api`) lives inside
`msg.content[*].name` — one layer below what the classifier sees. So
**every AutoGen tool node silently received `effects=[]`** and the entire
Phase 3 warning pipeline was effectively blind on AutoGen. This shipped
in v0.3.0, v0.3.1, and v0.4.0a1 without anyone noticing, because no test
ever fed the classifier an actual on-the-wire AutoGen `node_name`.

Spike 10 caught it by pointing a real OneAPI Claude Opus 4.7 LLM at a
real `RoundRobinGroupChat(coder, executor)` with three tools
(`fetch_weather_api`, `read_file`, `query_db`) and asserting the effect
tags. Result: 0 tags before the fix, correct tags after.

### LangGraph was accidentally fine

LangGraph tool nodes carry `node.name` from the graph definition itself
(e.g. `graph.add_node("fetch_weather", ...)` → `node_name = "fetch_weather"`).
That's function-shaped by construction, so the classifier worked. LangGraph
adapter tests never had to reason about this — they were right by accident.

AutoGen, CrewAI, AG2, and any future message-based framework will all
face the same problem: the natural `node_name` they produce is
**message-class-shaped**, not function-shaped, and the classifier can't
see through it.

## Decision

**Adapter recorders MUST embed the tool function name in `node_name` for
every node with `kind=NodeKind.TOOL`, using the three-segment shape:**

```
{source_or_agent}:{Kind_or_ClassName}:{tool_name[+tool_name...]}
```

### Shape rules

1. **First segment** — agent / source identifier. For AutoGen, the
   `msg.source` field. For CrewAI, the agent role. For LangGraph, the
   graph-level node name (already single-segment, so rule is N/A —
   LangGraph continues to emit single-segment names).
2. **Second segment** — the kind / class / event-type label. For AutoGen
   this is the message class (`ToolCallRequestEvent`, etc.); for other
   frameworks use the framework-native kind label.
3. **Third segment** — the tool function name(s). If a single tool is
   invoked, use the bare name (`fetch_weather_api`). If N parallel tools
   are invoked in one event, join with `+`
   (`read_file+query_db`). De-duplicate while preserving order.
4. **Fallback when function name is unextractable** (malformed payload,
   duck-typed stub in tests, unknown framework shape): fall back to the
   legacy two-segment shape (`{source}:{Kind}`). Do NOT crash. Users
   still have the coarse `effects_map` override path.

### Graph-based adapters

Adapters whose `node_name` is already function-shaped (LangGraph is the
current example) are exempt from the three-segment convention. They may
continue emitting single-segment function names. The invariant ADR-020
protects is "the classifier's input contains the tool function name",
not the segment count.

### `effects_map` key contract

The `effects_map` kwarg accepts `dict[str, list[str]]`; keys are matched
by exact string equality against the final `node_name` the recorder
emits. Users who want per-tool overrides key on the full three-segment
string:

```python
recorder = AutoGenRecorder(store, effects_map={
    "coder:ToolCallExecutionEvent:fetch_weather_api": ["external"],
})
```

This key-space is **public API** (documented in the recorder docstring)
and is versioned with the adapter it attaches to.

## Consequences

### Positive

- Phase 3's effect classifier finally works on AutoGen (and by
  implication, on any future message-based adapter that follows the
  convention).
- `effects_map` overrides become per-tool × per-event-type × per-agent,
  which is the granularity real-world users need (different weather
  endpoints, different DB shards, etc. all get their own tags).
- The convention is cheap: every adapter needs ~15 lines to extract and
  splice the tool name.

### Negative / trade-offs

- **`node_name` strings are not a stable public API.** Users reading
  them out of a `Run` or displaying them in a custom UI will see the
  shape change between v0.4.0a1 (two segments) and v0.4.0a2
  (three segments) for AutoGen tool events. We judge this acceptable
  because (a) they were broken-effect-wise in a1 anyway, and (b) nobody
  has built on AutoGen `node_name` strings per the CHANGELOG.
- **`effects_map` keys targeting the old two-segment shape will silently
  become no-ops** after upgrade. This is a soft break: the override just
  stops matching any node. Discovery path: users notice effect tags
  aren't being overridden, inspect `nodes[i].node_name`, update the
  keys. CHANGELOG for v0.4.0a2 will call this out.

### Neutral

- The convention doesn't require any schema change. It lives entirely
  in adapter recorder code; `Node.node_name` is already `str`.
- Classifier code (`effects.py`) is unchanged. The fix is in the
  adapter's `node_name` synthesis only.

## Alternatives considered

### Alternative 1 — classifier reads `Node.metadata["tool_name"]`

Adapters would populate a structured field, classifier would read it
directly. Pros: no string surgery, no ambiguous separators. Cons:
requires every classifier consumer (CLI, Web UI, user extensions) to
know about the new field; requires schema-shaped docs for metadata;
breaks backward compat with any `effects_map` user targeting the old
single string key. Rejected — the metadata-field path is more invasive
than splicing a third segment.

### Alternative 2 — only fix AutoGen, don't codify a convention

Ship the recorder fix, skip ADR-020. Cons: when we write the CrewAI
adapter next, whoever does it will re-invent a different shape
(`agent_role/tool_name`, `agent[tool]`, whatever) and Phase 3's UX will
fragment per-adapter. Rejected — the convention is worth codifying now
while there's one adapter to get it right in.

### Alternative 3 — classifier gets smarter (scan nested metadata)

Classifier parses `node.metadata` for tool calls, not just `node_name`.
Cons: couples classifier to metadata schema, which varies per adapter.
Pushes the per-adapter knowledge into the wrong layer. Rejected —
responsibility belongs in the adapter: each adapter knows its own
framework's tool-call shape.

## References

- `docs/research/r48a-autogen-tool-effects.md` — empirical trigger,
  pre- and post-fix classifier output from spike 10.
- `tests/spikes/spike10_autogen_tool_effects.py` — reproducible spike.
- `tests/unit/test_adapter_autogen.py::test_tool_request_event_embeds_function_name`
  (and 3 sibling tests) — unit coverage of the new shape.
- ADR-019 — the "warn, don't sandbox" charter this ADR operationalizes
  for AutoGen.
- PH3-02 research note (`docs/research/ph3-02-effects-schema-decision.md`) —
  original Option A vs Option B choice that put us on the
  "metadata-only, no schema change" track.

## Three-trigger re-open rule (mirrors ADR-013 / ADR-019)

This ADR may be revisited only if **at least three** of the following
fire:

1. A future adapter (CrewAI, AG2, Swarm) has a native `node_name` shape
   that genuinely cannot accommodate a function-name segment without
   lossy mangling.
2. The `effects_map` public-API breakage from the shape change generates
   ≥3 distinct user issues on GitHub.
3. The classifier itself is being rewritten (e.g. moving from regex to
   a structured tag proposal) in a way that makes `node_name`
   parsing vestigial.
4. A new Phase (Phase 4+) introduces a fundamentally different
   contract for `Node` — e.g. per-node structured effect records
   attached at record time by the LLM itself.

Until then, the three-segment shape is the convention.
