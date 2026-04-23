# ADR-011: State serialization boundary - recursive pydantic-to-dict coercion

Status: accepted
Date: 2026-04-23 (Round 17)
Consolidated into: ADR-015 (R25) — the `_jsonable` serialization boundary
is now Layer 3 of the framework-agnostic contract. This ADR remains the
historical record for the R17 decision.

## Context

`LangGraphRecorder._coerce_state` is the single chokepoint where LangGraph
state values become Chronos-owned data on their way to SQLite JSON storage
(per `store/sqlite.py` module docstring: "adapters own state coercion").

Before Round 17 this chokepoint was a shallow `dict(values)` — which worked
for plain state dicts but silently passed LangChain pydantic `BaseMessage`
instances through to the JSON encoder. During the first real-world dogfood
against `langgraph-supervisor-py` (multi-agent pattern, Anthropic
`ChatAnthropic` via OneAPI), this blew up:

```
TypeError: Object of type HumanMessage is not JSON serializable
  File "store/sqlite.py", line 195, in insert_nodes
    state_after_json=json.dumps(node.state_after),
```

The supervisor / react_agent pattern is extremely common — any graph built
with `langchain.agents.create_agent` or `langgraph.prebuilt.create_react_agent`
hits this path. Without the fix, Chronos simply does not record these graphs.

## Decision

The adapter's `_coerce_state` now delegates element coercion to a new private
helper `_jsonable(obj)` that recursively produces a JSON-serializable shape:

1. Primitives (None, str, int, float, bool) pass through.
2. Objects with `.model_dump()` (pydantic v1/v2 models, LangChain BaseMessage
   and subclasses) are dumped and then recursed.
3. Generic objects with `__dict__` fall back to `dict(__dict__)` + recurse.
4. `dict` / `list` / `tuple` / `set` / `frozenset` are recursed element-wise
   (tuples/sets become lists — JSON has no tuple/set type).
5. Exotic objects (datetime, UUID, Enum, bytes, ...) that survive steps 2-4
   fall back to `repr(obj)` instead of raising. This prioritizes recording
   completeness over type round-tripping: we would rather keep the trace and
   accept lossy values for rare types than lose the whole run.

Usage extractors (`aimessage_usage_extractor`, `anthropic_usage_extractor`,
`openai_usage_extractor`) now read message fields through a new
`_msg_field(msg, key)` helper that works on both pydantic objects and dicts.
Without this companion change, ADR-011 coercion would have silently broken
ADR-009 and ADR-010 (dict messages have no `getattr(msg, "usage_metadata")`).

## Trade-offs considered

**Alternative A**: teach `store.sqlite` to use a custom `json.JSONEncoder`
that knows about pydantic. Rejected: violates the ADR-003 "adapters own
coercion" boundary, moves LangChain knowledge into the storage layer, and
breaks invariance for alternative adapters (future AutoGen, CrewAI, ...).

**Alternative B**: require users to pre-serialize their state. Rejected:
hostile to LangGraph's stock `MessagesState`, and the whole selling point
of Chronos is that it wraps the graph without forcing state-shape changes.

**Alternative C**: keep shallow coercion and let errors bubble. Rejected
after dogfood: this is the default shape of most real-world multi-agent
graphs.

## Consequences

* `state_after_json` for Message-shaped state now contains dicts, not
  opaque object repr strings. Users can post-hoc introspect message
  content/tool_calls/response_metadata from the SQLite DB directly.
* `usage_extractor` authors must either (a) use the built-in extractors,
  which already dict-aware, or (b) handle dict shape in their own
  extractor. Documented on the extractor module docstring.
* One-way lossy coercion for exotic types (datetime -> ISO repr-string,
  UUID -> repr, bytes -> repr). If a future user needs round-trip fidelity
  we can add type tags, but no existing user has asked.
* New regression tests in `tests/unit/test_adapter_langgraph.py`
  (`_jsonable` edge cases) and `tests/unit/test_usage_extractor.py`
  (dict-coerced-message paths for all three extractors).

## Evidence

Discovered via real-world dogfood, not speculation:
- `/workspace/chronos-dogfood/supervisor/dogfood_baseline.py` —
  `create_supervisor()` over math + research react_agents, recorded run
  captures 3 nodes with per-node token accounting
  (supervisor 604+107, research_expert 1970+220, supervisor 1049+218).
- Pre-fix: crashed on JSON serialization.
- Post-fix (this ADR): clean 242/242 test suite, real multi-agent run
  recorded end-to-end.

## Related

- ADR-003 (SQLite schema) - defines the JSON storage contract.
- ADR-009 (usage-extractor hook) - the interface that ADR-011 had to stay
  compatible with.
- ADR-010 (native usage extractors) - ditto.
- `docs/case-studies/langgraph-supervisor.md` (Round 17) - the dogfood
  that exposed the bug.
