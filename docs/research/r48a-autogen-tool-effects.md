# R48-A AutoGen tool-call effects tagging gap + fix

**Round:** R48-A (2026-04-26)
**Status:** Fixed — embedded function name in tool event node_name
**Depends on:** PH3-02 (`docs/research/ph3-02-effects-schema-decision.md`),
ADR-019 (no sandbox), `src/chronos/adapters/effects.py` R44-A classifier
**Informs:** ADR-020 (node_name shape rule for tool events),
`docs/guides/forking-safely.md` §"Per-tool effects"
**Spike:** `tests/spikes/spike10_autogen_tool_effects.py`

---

## Question

After v0.4.0a1 shipped the "fork-safety bundle" (ADR-019 + effects
classifier + Web UI badge + `forking-safely.md` guide), does the
classifier *actually work* on a real AutoGen GroupChat that invokes
tools via real LLM function-calling? Or was Phase 3's effects pipeline
only validated on synthetic LangGraph traces?

## TL;DR

- Before this round: **every tool node on AutoGen got `effects=[]`**,
  because the recorder built `node_name` as `"{source}:{ClassName}"`
  (e.g. `"coder:ToolCallExecutionEvent"`) and the classifier's regexes
  (`\bfetch_\w+\b`, `\bread_file\b`, …) only match function-name-shaped
  strings. The fork-safety warning badge was silently broken for the
  most common tool-calling scenario.
- After this round: tool event `node_name`s now include the function
  name as a third segment
  (`"coder:ToolCallExecutionEvent:fetch_weather_api"`), classifier
  regexes fire, `effects=["network"]` etc. are produced correctly,
  and `effects_map` overrides become per-tool × per-event-type ×
  per-agent instead of the previous coarse per-event-type-per-agent.

## Spike

`tests/spikes/spike10_autogen_tool_effects.py` builds a
`RoundRobinGroupChat(coder, executor)` where `coder` has three tools:
`fetch_weather_api`, `read_file`, `query_db`. It runs against
OneAPI/GLM-5 with real function-calling (confirmed working by a
standalone curl probe that returned a `tool_calls` response with
`name="add"` for a test prompt).

### Pre-fix run

```
step=1  kind=tool  node_name='coder:ToolCallRequestEvent'    effects=[]
step=2  kind=tool  node_name='coder:ToolCallExecutionEvent'  effects=[]
```

Classifier saw `"coder:ToolCallRequestEvent"`, tried to match
`\bfetch_\w+\b` / `\bread_\w+\b` / etc. — nothing matches
`ToolCallRequestEvent`. Output: `[]`.

### Post-fix run

```
step=1  kind=tool  node_name='coder:ToolCallRequestEvent:fetch_weather_api'    effects=['network']
step=2  kind=tool  node_name='coder:ToolCallExecutionEvent:fetch_weather_api'  effects=['network']
```

## Why this broke silently for 4 rounds

R44-A introduced the classifier and wrote comprehensive tests against
function-shaped names (`"call_weather_api"`, `"read_file"`, etc.).
R46-A wired it into the AutoGen adapter and the Web UI badge. Neither
round had a test that fed the classifier an *actual AutoGen node_name*
— the unit tests used duck-typed messages where the author chose
`node_name` directly. So the stack was green end-to-end without ever
proving that the `{source}:{ClassName}` shape the AutoGen recorder
actually produces would feed the classifier anything useful.

The LangGraph adapter uses `node.name` from the graph-definition layer
(e.g. `"fetch_weather"`), which is *already* function-shaped — so the
LangGraph side of Phase 3 worked. AutoGen, being message-based, has
no natural per-node function name and the recorder had to synthesize
one. The synthesis skipped the function name buried in
`ToolCallRequestEvent.content[*].name`, which is the only actually-useful
signal for effect classification.

Spike 10 caught this in the first round where we pointed a real LLM
at a real multi-agent tool-calling team. **Lesson:** every classifier
test must use a realistic `node_name` string from the adapter it will
run against, not a hand-chosen one.

## Fix

`src/chronos/adapters/autogen/recorder.py`:

1. Add `_TOOL_EVENT_CLASSES = {"ToolCallRequestEvent",
   "ToolCallExecutionEvent", "ToolCallSummaryMessage"}`.
2. Add `_extract_tool_names(msg)` — pulls `name` from each dict/object
   in `msg.content` when it's a list; returns de-duplicated names in
   order. Defensive against string-typed content (used in the existing
   unit tests) and against missing `name` fields.
3. When building `node_name` for tool events, use
   `"{source}:{ClassName}:{name1[+name2...]}"`. Non-tool events keep
   the legacy two-segment shape.
4. When the list is empty (malformed or duck-typed stub), fall back
   to the legacy two-segment shape so no crash path opens up.

Tests added to `tests/unit/test_adapter_autogen.py`:

- `test_tool_request_event_embeds_function_name` — single tool call,
  both request + execution events, asserts `node_name` includes the
  function name and `metadata["effects"] == ["network"]`.
- `test_tool_event_multiple_calls_concatenates_names` — parallel
  `read_file + query_db`, asserts `"read_file+query_db"` joiner and
  both `"fs"` + `"db"` tags appear.
- `test_tool_event_falls_back_when_name_missing` — string-content
  message keeps the legacy shape.
- `test_effects_map_still_overrides_new_shape` — user-supplied
  override keyed on the new full shape wins.

## Backward compatibility

- **`node_name` strings are not a stable public API.** They are shown
  in the Web UI and CLI `chronos runs show` but are adapter-specific;
  no consumer looks them up by value. Changing the shape is safe.
- **`effects_map` keys ARE a public API** (documented in the recorder
  docstring). The contract was *"pass the node_name the recorder
  emits as the key"* — which is what users still do, just with the
  new shape. Existing user code would either: (a) use keys like
  `"coder:ToolCallExecutionEvent"` → now matches zero nodes, silently.
  Discovery path: users notice their overrides aren't taking effect,
  inspect the actual node_names, update the keys. (b) use empty or
  LangGraph-style keys — unaffected.
- ADR-020 will document the contract so future adapters converge on
  a shape: `"{agent_or_source}:{Kind}:{tool_name[+tool_name...]}"`.

## Lessons

1. **Classifier tests must use real adapter output.** Synthetic
   `node_name` strings hid this for 4 rounds. Now every classifier
   test with `NodeKind.TOOL` should either: (a) use a name we've
   empirically confirmed the adapter produces, or (b) feed through
   the real recorder path.
2. **"Live smoke green" ≠ "feature works end-to-end".** R37.5 added
   a live-LLM smoke test for AutoGen agent_id capture. It didn't
   cover tool-calling because the smoke prompt was
   "`Reply in 5 words`" — no tool use. We now have spike10 as a
   companion that exercises the tool path specifically. Consider
   promoting it to a `@pytest.mark.live` test after two rounds of
   stability.
3. **Message-based frameworks need synthesized node_names — design
   them carefully.** AutoGen, CrewAI, and AG2 all have the same
   shape. Future adapters should follow the 3-segment convention
   from day one.

## Follow-ups

- [ ] ADR-020 codifying `{source}:{Kind}:{tool_name}` convention
      (this round).
- [ ] Update `docs/guides/forking-safely.md` to mention per-tool
      overrides (this round).
- [ ] Next alpha (`v0.4.0a2`) ships this fix; CHANGELOG notes the
      shape change.
- [ ] Consider promoting spike10 to a `@pytest.mark.live` test next
      round if OneAPI/GLM-5 remains stable.
- [ ] (Future) LangGraph and CrewAI adapters' tool-node naming should
      be reviewed for consistency with ADR-020.
