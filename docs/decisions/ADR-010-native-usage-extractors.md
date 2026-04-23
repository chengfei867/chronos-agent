# ADR-010: Native Usage Extractors for Anthropic & OpenAI

**Status**: Accepted
**Date**: 2026-04-23 (Round 15)
**Supersedes**: —
**Superseded by**: —
**Consolidated into**: ADR-015 (R25) — provider-specific field mappings
are absorbed into Layer 5 of the v2 contract. This ADR remains the
historical record for the R15 decision.
**Related**: ADR-009 (usage extractor hook)

---

## Context

ADR-009 (Round 12) shipped the `usage_extractor` hook and one convenience
extractor, `aimessage_usage_extractor`, which reads LangChain 0.3+'s
standardised `AIMessage.usage_metadata`. That covers the newest LangChain
code path but explicitly **not** two others that ADR-009 §Context flagged:

- `AIMessage.response_metadata["token_usage"]` — populated by
  `langchain_openai.ChatOpenAI` and anything that round-trips through OpenAI
  SDK `ChatCompletion.usage`.
- `AIMessage.response_metadata["usage"]` — populated by
  `langchain_anthropic.ChatAnthropic` and anything that round-trips through
  Anthropic SDK `Message.usage`.

Both are widely-deployed LangChain configurations today. A user running
either has to hand-write an extractor. Worse, naïve hand-written versions
miss **cache tokens** (Anthropic prompt caching, OpenAI cached prompt
discount) and **reasoning tokens** (o1/o3), leading to cost under-reporting.

The downstream use-case — "which A/B fork variant was cheaper?" from
`chronos fork plan` + `chronos diff --show-usage` — is only useful if the
numbers are right.

## Decision

Ship two more convenience extractors in `chronos.adapters.langgraph_usage`:

```python
def anthropic_usage_extractor(ctx: UsageContext) -> UsageResult | None: ...
def openai_usage_extractor(ctx: UsageContext) -> UsageResult | None: ...
```

Both implement the existing `UsageExtractor` Protocol from ADR-009. **No
schema change, no protocol change, no breaking change.** They are siblings
to `aimessage_usage_extractor`.

### Field mapping

**Anthropic** (`response_metadata["usage"]`, shape per
`anthropic.types.Usage`):

| Source field                      | Maps to                | Notes |
|-----------------------------------|------------------------|-------|
| `input_tokens`                    | `prompt_tokens` (+=)   | base |
| `output_tokens`                   | `completion_tokens`    | — |
| `cache_creation_input_tokens`     | `prompt_tokens` (+=)   | 25% surcharge is a *cost* concern, handled by user pricing table — we only account the token count |
| `cache_read_input_tokens`         | `prompt_tokens` (+=)   | 90% discount ditto |

`reasoning_tokens = 0` — Anthropic models don't expose a separate reasoning
count on the current API (extended thinking surfaces differently and is
not in the basic `usage` block).

Model name comes from `response_metadata["model"]` or `["model_name"]`.

**OpenAI** (`response_metadata["token_usage"]`, shape per
`openai.types.CompletionUsage`):

| Source field                                          | Maps to                | Notes |
|-------------------------------------------------------|------------------------|-------|
| `prompt_tokens`                                       | `prompt_tokens`        | already includes cached |
| `completion_tokens`                                   | `completion_tokens`    | already includes reasoning |
| `completion_tokens_details.reasoning_tokens`          | `reasoning_tokens`     | o1/o3 |

We do **not** subtract reasoning from `completion_tokens` — the OpenAI API
already includes reasoning in the completion count, and keeping the total
consistent means `prompt + completion` still equals `total_tokens`.
`reasoning_tokens` is reported alongside as sub-detail.

`prompt_tokens_details.cached_tokens` is **not** double-added because
OpenAI already folds it into `prompt_tokens`. (Anthropic is the opposite —
cache tokens come out separately. Hence the divergent handling.)

Model name comes from `response_metadata["model_name"]` or `["model"]`.

### Semantics (all three extractors)

1. Walk `ctx.post_values["messages"]` from the tail, take the **newest**
   message whose `response_metadata` has the expected key.
2. Return `None` if no match — this is the expected case for non-LLM nodes
   and gets silently skipped by the recorder (ADR-009 §Decision #4).
3. Raise nothing on malformed data — coerce with `int(... or 0)` and skip
   the field.
4. `cost_usd_cents` is always `None`. Pricing is user turf.
5. Duck typing throughout — we do **not** import `anthropic` or `openai`.
   Users without those packages installed can still use the extractors.

## Consequences

### Positive

- Covers the two biggest LangChain LLM families out of the box.
- Cache-token accounting is right by construction — the #1 hand-written
  pitfall disappears.
- Existing `aimessage_usage_extractor` is untouched.
- Symmetric API — each provider has a clearly-named extractor.
- ADR-009 Protocol survives intact; future AutoGen/CrewAI adapters can
  drop their own `*_usage_extractor` next to ours.

### Negative

- More public surface (2 new names). Mitigated: all re-exported from
  `chronos.adapters.langgraph_usage` alongside the existing one.
- Users with **mixed** providers need a composed extractor. We document
  (and test) the one-liner: `lambda ctx: anthropic_usage_extractor(ctx)
  or openai_usage_extractor(ctx) or aimessage_usage_extractor(ctx)`.
- Tiny code duplication between the three extractors (message-walking
  loop). Acceptable — each path has its own shape and explicit is better
  than a clever generic.

### Neutral

- No CLI changes — existing `runs list --usage`, `runs show`, `diff
  --show-usage` just start showing numbers for previously-silent users.

## Alternatives Considered

### (A) Extend `aimessage_usage_extractor` to also read `response_metadata`

Rejected: mixing three distinct shapes into one function makes precedence
rules implicit and the function hard to name. Separate functions let users
pick exactly the path they expect.

### (B) Make it automatic — try all three in order in `record()`

Rejected: magic. Users should opt in to exactly the accounting path that
matches their setup; a fallback cascade can quietly double-count if a
message somehow carries both `usage_metadata` *and* `response_metadata`.
If users want the cascade, they compose it themselves (see ADR-009
philosophy: Chronos stays adapter/provider neutral).

### (C) Take a hard `anthropic.types.Usage` / `openai.types.CompletionUsage`
dependency

Rejected: adds two heavy optional deps to core just for type hints. Duck
typing reads the same field names with no install cost.

## Implementation Notes

- Both functions live in `chronos/adapters/langgraph_usage.py`.
- Added to `__all__`.
- Tests extend `tests/unit/test_usage_extractor.py` with:
  - Anthropic happy-path + cache-creation + cache-read
  - OpenAI happy-path + reasoning tokens (o1-style)
  - Both: no messages, no response_metadata, malformed types
  - Composed fallback chain (doc test)

## Verification Gates

- Unit: each extractor returns correct `UsageResult` on its native shape,
  `None` on mismatched shape, doesn't raise on malformed input.
- Regression: all existing 216 tests stay green; `aimessage_usage_extractor`
  behaviour unchanged.
- Dogfood: no CLI surface change, 18/18 stay green.
