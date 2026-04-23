# Case Study: `langgraph-bigtool` (R20, dogfood #3)

**Target**: [`langchain-ai/langgraph-bigtool`](https://github.com/langchain-ai/langgraph-bigtool) v0.0.3 — 529★, LangGraph agents with **semantic tool retrieval** across large (hundreds/thousands) tool registries.

**Why this target**: completes the dogfood triptych. R17 supervisor = centralized routing; R18 swarm = decentralized handoff; R20 bigtool = **single agent + meta-tool (retrieve_tools) + dynamic tool injection**. Topology is orthogonal to the previous two — exercises Chronos on a multi-turn single-agent loop rather than a multi-agent dance.

## Setup

```
pip install langgraph-bigtool langchain-anthropic
# + Chronos 0.1.4 in editable mode
```

Query: *"Use available tools to calculate the arc cosine of 0.5."*
Registry: all 51 callable functions from Python's `math` stdlib.
LLM: Claude Opus 4.7 via baidu-int OneAPI.
Retrieval: **custom keyword matcher, no embeddings** — OneAPI embedding support is untested, and the dogfood is about Chronos, not embedding quality.

## Result

**Answer (correct)**: *"The arc cosine of 0.5 is approximately 1.0472 radians (which equals π/3, or 60°)."*

**Captured trace** (5 nodes, 1 invocation):

```
[0] agent          kind=llm  dur=1691ms  tokens=795+99     model=claude-opus-4-7
[1] select_tools   kind=tool dur=1ms     tokens=0+0        model=-
[2] agent          kind=llm  dur=14022ms tokens=1333+64    model=claude-opus-4-7
[3] tools          kind=tool dur=1ms     tokens=0+0        model=-
[4] agent          kind=llm  dur=2177ms  tokens=1417+42    model=claude-opus-4-7
```

The LLM's three turns are correctly booked as three separate `agent` nodes (not one collapsed node) — this is because `bigtool`'s top-level graph uses the LangGraph-native node name `agent`, and Chronos faithfully records one node per step per snapshot (ADR-004). Per-turn token counts are **independent** (795/1333/1417 prompt-tokens show the conversation growing turn-over-turn), which is the correct accounting; no R18-style under-count regression.

## Findings

### F1. Upstream blocker: `langgraph-bigtool 0.0.3` × `langgraph 1.1.9` ABI break

```python
# langgraph_bigtool/graph.py:140
tool_call = tool_node.inject_tool_args(call, state, store)
# AttributeError: 'ToolNode' object has no attribute 'inject_tool_args'.
# Did you mean: '_inject_tool_args'?
```

LangGraph 1.x made `ToolNode.inject_tool_args` private. `bigtool 0.0.3` was pinned to the pre-1.x public API.

**Workaround (this dogfood)**: in-place rename in site-packages (`inject_tool_args` → `_inject_tool_args`). A durable fix belongs upstream (PR to `langchain-ai/langgraph-bigtool`, or bigtool bumping its langgraph ceiling). **Not a Chronos bug**, but documented here so anyone dogfooding bigtool + a recent langgraph hits the same wall we did.

### F2. Cognitive-friction: `model_name` lives on `Node`, not `Node.usage`

The R17 supervisor dogfood, the R18 swarm dogfood, and our first R20 bigtool script **all** contained the same bug:

```python
u = n.usage
model = getattr(u, "model_name", None) or "-"   # ← always "-"
```

because `Usage` has **only** token fields (`prompt_tokens`, `completion_tokens`, `reasoning_tokens`) — `model_name` is a top-level attribute on `Node`:

```python
# chronos/core/models.py
class Node(BaseModel):
    ...
    # LLM-specific (nullable unless kind == LLM)
    model_name: str | None = None
    usage: Usage | None = None
    cost_usd_cents: int | None = None
```

The extractor layer **correctly** propagates `UsageResult.model_name` to `Node.model_name` (not `Node.usage.model_name`), and inspecting the raw DB shows `n.model_name == 'claude-opus-4-7'` as expected. The bug is in user expectation.

**Three independent authors hit the same mistake** (same agent, three separate sessions, writing from scratch each time). That's strong signal. The cognitive model is: *"tokens and model go together, both are LLM-specific, group them"*. The actual model factors cost/model/usage as **three parallel LLM-specific fields on Node**.

**Verdict**: not a bug, but a real DX wart. Possible mitigations (all ADR territory, none executed this round):
- Add a convenience accessor `Node.model` that forwards (less typing, same location).
- Move `model_name` onto `Usage` (schema break, rejected).
- Document it on `Node.usage`'s docstring as a "see also: Node.model_name" note (cheapest; recommended first step).

### F3. Chronos captures the meta-tool pattern correctly

`select_tools` (bigtool's built-in "retrieve the tools I should consider" node) is recorded as a distinct `tool`-kind node between the first and second `agent` turns. This is the topology-level thing we wanted to stress-test, and it works without any adapter-level change: the default `kind_map = {"agent": LLM, "select_tools": TOOL, "tools": TOOL}` is enough.

No new extractor was needed. No usage under-count was observed (unlike R18's swarm where the react-agent inner loop hid LLM calls — here the outer graph exposes each turn).

## Invariants exercised

- **ADR-004** (1 step = 1 node): ✓ five nodes for five steps.
- **ADR-009** (usage extractor contract): ✓ Anthropic extractor populates tokens + model; no extractor mutations needed.
- **ADR-012** (multi-LLM-per-node accumulation): ✓ not triggered here (each agent turn is its own node, so there's nothing to accumulate), but the loop harmless.
- **ADR-008** (fork=JSON-only): not exercised this round. Three dogfood rounds now complete without generating a single "I need to auto-execute a fork" user demand. The ADR-008 "freeze until evidence" posture is confirmed by three independent topologies.

## Conclusions

1. **Chronos 0.1.4 handles single-agent-multi-turn topology with zero changes.** Not surprising — bigtool's outer graph is the easiest of the three dogfood shapes — but it's good to confirm the React-agent flattening trick from R18 isn't needed here.
2. **F2 is the actionable takeaway.** After three rounds of our own tool confusing us, a trivial doc/accessor fix is cheap and earns back hours of user frustration.
3. **ADR-008 lift-or-stay decision is now ripe.** Three dogfood rounds × zero execute-fork demand = sufficient weak-consistent evidence to formalize the decision in ADR-013.

Collected against Chronos v0.1.4 on 2026-04-23.
