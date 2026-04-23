# ADR-009: Usage & Cost Capture via Extractor Hook

**Status**: Accepted
**Date**: 2026-04-23 (Round 12)
**Supersedes**: —
**Superseded by**: —
**Related**: ADR-003 (schema), ADR-004 (langgraph mapping), ADR-006 (diff alignment)

---

## Context

`Node` already has fields `usage: Usage | None` and `cost_usd_cents: int | None`
(see ADR-003), intended for token accounting. However, since M1.1 landed, the
LangGraph adapter has **never populated them** — `grep -n "usage\|cost_usd"
src/chronos/adapters/langgraph.py` returns zero hits.

This is a latent capability. Users doing A/B prompt experiments (the natural
companion to `chronos fork plan`, M1.10) currently can't answer
"which variant spent fewer tokens?" from Chronos alone; they must re-instrument
at the application layer.

LangGraph exposes usage data in several places with no single canonical path:

- `AIMessage.usage_metadata` (LangChain standard, since 0.3.x)
- `AIMessage.response_metadata["token_usage"]` (OpenAI)
- `AIMessage.response_metadata["usage"]` (Anthropic)
- State-level accumulators users define themselves
- Callback-based trackers (`get_openai_callback`)

A single hard-coded path would break half our users.

## Decision

Add an **optional** `usage_extractor` kwarg to `LangGraphRecorder.__init__` with
the signature:

```python
UsageExtractor = Callable[[UsageContext], UsageResult | None]

@dataclass(frozen=True)
class UsageContext:
    node_name: str
    pre_snapshot: Any        # LangGraph StateSnapshot (pre-node)
    post_snapshot: Any       # LangGraph StateSnapshot (post-node)
    pre_values: dict[str, Any]
    post_values: dict[str, Any]
    task: Any                # pre_snapshot.tasks[0]

@dataclass(frozen=True)
class UsageResult:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    reasoning_tokens: int = 0
    cost_usd_cents: int | None = None
    model_name: str | None = None
```

Semantics:

1. If `usage_extractor` is `None` (default), Chronos records nodes exactly as
   before — `usage=None`, `cost_usd_cents=None`. **Fully backwards compatible.**
2. If set, it is called once per recorded node. The return value maps to
   `Node.model_name`, `Node.usage` (as `Usage(prompt_tokens, completion_tokens,
   reasoning_tokens)`), and `Node.cost_usd_cents`.
3. If the extractor **raises**, Chronos logs a warning (via stdlib `logging`,
   logger name `chronos.adapters.langgraph.usage`) and continues with
   `usage=None`. **A buggy extractor must never abort a recording.**
4. If the extractor **returns `None`**, the node simply has no usage — this is
   the normal case for non-LLM nodes (routers, tools, fallbacks).
5. The extractor is called **after** `post_values` is materialised but **before**
   the `Node` is appended; it has read-only access.

## Consequences

### Positive
- **Zero schema change**: leverages fields shipped in M1.1.
- **Fully backwards compatible**: existing users see identical behaviour.
- **Adapter-neutral signature**: when AutoGen/CrewAI adapters land, they can
  accept the same `UsageExtractor` protocol — just with adapter-specific
  `UsageContext` payloads (likely a Protocol or adapter-typed dataclass per
  adapter). The shape stays the same.
- **User owns pricing**: Chronos stays out of the model-pricing business. Users
  plug in their own cost table or use `langchain_community`'s callback.
- **Testable**: the hook boundary is pure — a synthetic `UsageContext` in tests
  exercises the full pipeline without a real LLM.

### Negative
- One more constructor kwarg on `LangGraphRecorder`.
- Cost calculation correctness is user-delegated; we don't validate.
- Exceptions-are-silent may hide bugs. Mitigated by `logging.WARNING` and a
  test that asserts the warning fires.

### Neutral
- CLI surface grows: `runs list` gets a "tokens" column, `runs show` shows
  `usage: N+M` per node, `diff` gains a `--show-usage` flag (ADR-009b / follow-up).

## Alternatives Considered

### (A) Hard-code LangChain's `AIMessage.usage_metadata` path
Rejected: covers only newest LC versions and breaks for Anthropic/local-LLM
users who ship their own accumulator.

### (B) Accept the extractor only at `record()` call time (not `__init__`)
Rejected: users typically have one pricing setup per codebase; per-call kwarg
leads to copy-paste. We *do* allow `record(... usage_extractor=override)` as a
follow-up if user demand appears.

### (C) Let users post-process after `record()` returns
Rejected: forces every user to write re-opening logic and write back through a
non-existent update API. The extractor during recording is the low-friction
path.

### (D) Populate from state_after automatically if keys `_usage` / `_tokens`
exist
Rejected: magic keys in user state are invasive. Opt-in explicit hook is
clearer.

## Implementation Notes

- Default extractor provided as a convenience:
  `chronos.adapters.langgraph_usage.aimessage_usage_extractor` — reads
  `AIMessage.usage_metadata` from `post_values` top-level messages list. Users
  without LangChain messages simply don't import it.
- `UsageContext` / `UsageResult` exported from
  `chronos.adapters.langgraph_usage` to keep the core adapter file focused.
- `logging.getLogger("chronos.adapters.langgraph.usage").warning(...)` on
  extractor exception, with the exception info.

## Verification Gates

- Unit: extractor called once per node, `None` returns leave fields unset,
  raised exceptions log + continue.
- Integration: synthetic graph with a fake node returning a fake usage dict
  — recorded Node has populated `usage` + `cost_usd_cents`.
- CliRunner: `chronos runs show <id>` includes usage line iff any node has
  usage; `chronos runs list` sums tokens across run.
- Zero regressions: all 195 existing tests still green with no extractor
  configured.
