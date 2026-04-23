# ADR-012 — Multi-LLM-per-Node Usage Accumulation

- **Status:** Accepted
- **Date:** 2026-04-23
- **Round:** R18 (langgraph-swarm-py dogfood)
- **Supersedes:** extends ADR-009 (usage extractor contract)
- **Related:** ADR-011 (UsageContext)

## Context

Until R18 the LangGraph usage extractors (`aimessage_usage_extractor`,
`anthropic_usage_extractor`, `openai_usage_extractor`) walked
`ctx.post_values["messages"]` and returned the usage of the **last** (or
"newest with metadata") `AIMessage`. This worked for every graph we had
dogfooded in R10–R17, where each LangGraph node issued **exactly one** LLM
call before yielding.

R18's dogfood target — `langgraph-swarm-py` — broke that assumption. In a
swarm, each "agent node" is itself a `create_react_agent` sub-graph that
runs to completion (possibly multiple LLM calls + tool rounds) **inside a
single super-step** of the parent swarm graph. From Chronos's vantage point
(the parent graph's `astream("values")` stream) the node appears to execute
once, but between the "before" and "after" state-snapshots several
`AIMessage` objects may have been appended.

### Concrete evidence (R18 Finding #1)

In the swarm dogfood trace, the `Bob` node appended **two** new `AIMessage`
objects between `pre_values` and `post_values`:

| Call           | input_tokens | output_tokens |
|----------------|--------------|---------------|
| Bob → research | 1053         | 112           |
| Bob → handoff  | 1222         | 99            |
| **True total** | **2275**     | **211**       |

Old extractor returned **`(1222, 99)`** — undercounting by `(1053, 112)`
(~46% of prompt tokens and ~53% of completion tokens lost). This is not a
graph-author error; it is a Chronos observation bug.

The same latent bug existed in the R17 supervisor dogfood but was not
triggered there because each `create_react_agent` sub-graph happened to make
exactly one LLM call per turn for that particular workload. R18 exposed it.

## Decision

**The LangGraph usage extractors MUST sum `usage_metadata` (or equivalent
SDK-specific usage fields) across *all new `AIMessage` objects* appended
between `UsageContext.pre_values` and `UsageContext.post_values`.**

Formally, for each extractor:

1. Compute `delta_msgs = post_values["messages"][len(pre_values["messages"]):]`
   (treating a missing `pre_values["messages"]` as empty — covers the first
   super-step of any graph).
2. Iterate over `delta_msgs`, accumulating usage only from `AIMessage`
   objects that carry SDK-specific usage metadata.
3. Return `None` if no new messages carry usage (non-LLM node).
4. The returned `UsageRecord.model_name` is taken from the **last** new
   message that carries a model identifier (best-effort; mixed-model nodes
   are rare and not blocked by this ADR).

This is a **duck-typed** operation — we detect usage shape, not SDK class.
Cache tokens continue to fold into `prompt_tokens` (ADR-009);
`reasoning_tokens` remains a sub-field of `completion_tokens` (ADR-009).

## Rationale

- **No data-model change.** `UsageContext.pre_values` has existed since
  R15 (ADR-011) but was unused. This ADR simply activates it.
- **No public API change.** The three extractor functions keep the same
  signature and return type; only internals change.
- **Preserves non-LLM-node `None` semantic.** Nodes that only mutate state
  (no new `AIMessage`) still return `None`, so they continue to be
  classified `kind="tool"` / `kind="state"` downstream.
- **Dogfood-driven.** The fix was discovered by using Chronos on a real
  public library (1472★ `langgraph-swarm-py`), not synthesized in a lab.
  R18 progress log records the full investigation.

## Alternatives Considered

### A. Change the data model — split each inner LLM call into its own `Node`

Rejected. This would require the adapter to *subscribe* to the inner
sub-graph's own stream (not just the parent's) which is both invasive
(Chronos would have to know which nodes *contain* sub-graphs) and fragile
(new LangGraph composition primitives would break it). It also changes
replay semantics — users who wrote `replay --node Bob` would suddenly find
three nodes named `Bob.*` in the trace.

### B. Only document as "known limitation" — don't fix extractors

Rejected. The bug is silent and produces numbers that look valid. Users
building cost dashboards on `usage_total_prompt_tokens` would
systematically under-report by anywhere from 30% to 70% on swarm-style
graphs. Not acceptable for a tool whose selling point is trace fidelity.

### C. Require graph authors to emit one `AIMessage` per node

Rejected. Chronos is an observer, not a linter. We must work with existing
LangGraph ecosystem code as-is.

## Consequences

**Positive**

- Token counts now accurate on any graph where a single super-step makes
  N≥1 LLM calls (swarm, complex react_agent compositions, evaluator-loop
  patterns).
- `UsageContext.pre_values` finally has a documented use.

**Negative**

- Extractors are slightly slower (O(delta_msgs) per node instead of
  O(1) — still negligible, <1ms in practice).
- Custom user-written extractors (none known in the wild yet) that relied
  on the old "last message wins" semantics would need updating. The
  extractor docstring now calls this out explicitly.

**Neutral**

- `model_name` field still best-effort (last-hit wins across mixed-model
  nodes). No user ever complained about the old semantics here so we don't
  gold-plate.

## Verification

Five regression tests added in `tests/unit/test_usage_extractor.py`:

| Test                                              | What it pins                                          |
|---------------------------------------------------|-------------------------------------------------------|
| `test_adr012_aimessage_only_new_messages_counted` | Pre-history is never double-counted                   |
| `test_adr012_anthropic_multi_llm_per_node`        | Exact Bob-node swarm scenario (2 calls → sum)         |
| `test_adr012_anthropic_empty_new_returns_none`    | Non-LLM node still returns `None`                     |
| `test_adr012_openai_sums_multi_new_messages`      | OpenAI path accumulates + reasoning_tokens summed     |
| `test_adr012_missing_pre_values_treats_all_as_new`| Initial super-step (no `pre_values["messages"]`) OK   |

Dogfood verification: swarm `Bob` node records **`2291+213`** (was
`1222+99`); R17 supervisor dogfood re-run shows no regression —
`research_expert` now `1957+283` (was `1755+271`, very mild undercount we
had never noticed).
