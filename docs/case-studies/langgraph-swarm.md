# Case Study — Dogfooding Chronos on `langgraph-swarm-py`

- **Round:** R18
- **Date:** 2026-04-23
- **Target:** [`langchain-ai/langgraph-swarm-py`](https://github.com/langchain-ai/langgraph-swarm-py) (1472★, active, 22 open issues at time of writing)
- **Why this target:** contrasts R17's `langgraph-supervisor` (centralized supervisor calls workers) — `langgraph-swarm-py` is **decentralized handoff** (agents hand control peer-to-peer via `create_handoff_tool`). Different topology, same Chronos instrumentation.
- **Outcome:** 1 real bug found & fixed (ADR-012), 1 UX friction documented, 0 data-model changes.

## Scenario

Two-agent swarm answering `"What is 15% of the US federal government's total spending in fiscal year 2024?"`:

- **Alice** — math expert, tools: `percent_of(pct, whole)`
- **Bob** — researcher, tools: `research_fact(topic)` (returns a hard-coded "$6.75T" fact to stay deterministic)

Expected flow: Alice realises she needs a fact → handoff to Bob → Bob looks up the fact → handoff back to Alice → Alice computes `15% × $6.75T = $1.0125T`.

Model: Claude Opus 4.7 via OneAPI proxy (`model="Claude Opus 4.7"`, no temperature, R17 recipe).

Instrumentation: 4 lines — same as every prior dogfood round.

```python
from chronos.adapters.langgraph import LangGraphRecorder
from chronos.store.sqlite import SqliteStore

store = SqliteStore(db_path)
recorder = LangGraphRecorder(store=store)
async for event in recorder.record(app, inputs=..., thread_id=...):
    pass
```

## What we observed

```
[  0] Alice           kind=llm  dur=1890ms  tokens=1118+96
[  1] Bob             kind=llm  dur=14924ms tokens=2291+213
[  2] Alice           kind=llm  dur=15301ms tokens=3193+235
```

Run completed cleanly. Answer correct. Node graph matches the semantic flow.

But the raw trace on disk told a deeper story. The `Bob` super-step had appended **4** new messages to the state, not 1:

| idx | type | name  | what                                            |
|-----|------|-------|-------------------------------------------------|
| 0   | ai   | Bob   | reasoning + `research_fact(...)` tool_call      |
| 1   | tool | Bob   | tool result: "$6.75 trillion ..."               |
| 2   | ai   | Bob   | reasoning + `transfer_to_alice()` tool_call     |
| 3   | tool | Bob   | handoff confirmation                            |

That's **two** separate LLM calls inside what the parent swarm graph sees as a single `Bob` step.

## Finding #1 — Multi-LLM-per-node token undercount (fixed)

### The bug

Chronos's three LangGraph usage extractors (`aimessage_usage_extractor`, `anthropic_usage_extractor`, `openai_usage_extractor`) all followed the pattern "walk the messages list, return the last `AIMessage` with usage metadata". For Bob above, that returned `(1222, 99)` — Bob's *final* LLM call, the handoff one — **missing** the research LLM call's `(1053, 112)`.

Undercount: **46% of prompt tokens, 53% of completion tokens silently dropped**.

### Why R17 never caught this

R17's supervisor dogfood also used `create_react_agent` worker nodes, which in principle could make multiple LLM calls per super-step. But the R17 workload (3-research-fact problem, no handoffs-within-worker) resulted in each worker making exactly one LLM call per invocation. Pure coincidence. The bug was latent.

### The fix (ADR-012)

Extractors now diff `ctx.post_values["messages"]` against `ctx.pre_values["messages"]` and sum usage across **all** new `AIMessage` objects — not just the last one.

```python
def _new_messages(ctx: UsageContext) -> list[Any]:
    pre = (ctx.pre_values or {}).get("messages") or []
    post = (ctx.post_values or {}).get("messages") or []
    if len(post) < len(pre):
        return post  # unusual: state replaced, treat all as new
    return list(post[len(pre):])
```

`UsageContext.pre_values` had existed since R15 (ADR-011) — exposed against future need, unused until now. R18 made it earn its keep.

### Verification

After the fix:

```
[  1] Bob             kind=llm  dur=14924ms tokens=2291+213   ← was 1222+99
```

R17 supervisor dogfood re-run: `research_expert` now `1957+283` (was `1755+271` — a previously-unnoticed ~10% undercount that the pre-R18 code was also guilty of when `create_react_agent` happened to emit an extra `AIMessage`). No regressions elsewhere.

Five regression tests added. See [ADR-012](../decisions/ADR-012-multi-llm-per-node-usage.md).

## Finding #2 — `create_handoff_tool` handoff shows as normal tool_call

Purely informational. When Alice hands off to Bob, the trace shows:

```
[  0] Alice  last AIMessage has tool_call: transfer_to_bob({})
              followed by tool message: "Successfully transferred to Bob"
[  1] Bob    active_agent transitioned Alice → Bob in state_after
```

There's no special "handoff" event type — it's encoded as a regular tool call with a specific name pattern (`transfer_to_*`) and a state-level `active_agent` update. This is **by design** in langgraph-swarm-py (handoffs are implemented as tools so the ReAct agent loop handles them naturally), and Chronos captures everything the framework emits. No action needed; documenting for users who might try `chronos diff` across nodes and wonder why the "handoff" looks like any other tool call.

## Finding #3 — `Node` has `state_after` only, no `state_before` (cognitive friction)

When writing the `inspect_trace.py` debugging script, the natural question is "what did this node add?" The API today:

```python
run.initial_state                  # whole run's starting state
run.final_state                    # whole run's ending state
node.state_after                   # the post-super-step state
# ↑ no node.state_before
```

To reconstruct "what Bob appended" you must read `nodes[i-1].state_after` (or `run.initial_state` for the first node) and diff. This is 3 lines of code; not broken, just annoying enough that I wrote the helper twice before realising I was recomputing.

**Decision: not a bug.** Adding `state_before` would duplicate storage (each state snapshot can be 10-50KB for message lists) without adding information. The CLI `chronos diff NODE_A NODE_B` already does this diff internally. We'll add a note to the Recipes doc showing the `state_after` chain pattern.

## What didn't come up

Still no demand for the "auto-execute forked plan" feature that ADR-008 preemptively blocked. Two rounds of real dogfood (R17 + R18), zero users have wanted to re-run a modified fork and produce new observations — the value is in reading the fork + inspecting what *would* have happened. ADR-008's boundary remains frozen.

## Takeaway

R18's bug was **only findable by dogfood**. No unit test would have generated a multi-LLM-per-node graph by accident; no code review would have noticed that `pre_values` was unused (it was exposed "for the future"). A real 1472★ library stressed an assumption that had survived eight prior rounds of development, and one 3-hour dogfood session surfaced it.

This is why dogfood is the project's primary quality mechanism.
