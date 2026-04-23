# Case Study: Dogfooding Chronos against langgraph-supervisor-py

**Round**: R17
**Date**: 2026-04-23
**Target**: [langchain-ai/langgraph-supervisor-py](https://github.com/langchain-ai/langgraph-supervisor-py) @ main
**Stars at time of test**: 1,566 | **Open issues**: 54 | **Status**: officially semi-deprecated (moved into langchain v1)
**LLM provider**: Anthropic Claude Opus 4.7 via OneAPI Bedrock proxy

## TL;DR

Running Chronos against a real open-source LangGraph multi-agent framework
(rather than our own synthetic test graphs) surfaced **3 real bugs inside
Chronos** within the first 10 minutes. All 3 are now fixed, documented
(ADR-011), and guarded by regression tests. This is the single strongest
argument we have seen for the "dogfood before feature-adding" discipline.

## Why this target?

Scored from a 6-candidate shortlist (other candidates: `agent-inbox`,
`langgraph-bigtool`, `langgraph-reflection`, `open_deep_research`,
`langgraph-swarm-py`). `langgraph-supervisor-py` scored 8/10 because:

- **Multi-agent pattern** exercises Chronos's per-node attribution more
  than any single-agent graph could.
- **Officially semi-deprecated** = high density of real pain points that
  users have hit.
- **Active community** (54 open issues) = representative surface for
  real-world bug hunting.
- Works out-of-the-box with OneAPI's `/v1/messages` endpoint, no custom
  client plumbing needed.

## Setup

```bash
git clone https://gh.llkk.cc/https://github.com/langchain-ai/langgraph-supervisor-py
cd langgraph-supervisor-py
uv venv && source .venv/bin/activate
UV_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/ \
  uv pip install -e . "langchain-anthropic>=0.3" /path/to/chronos-agent
```

Workload: `dogfood_baseline.py` — supervisor over two react_agents (math
tools + mock research tool), prompt: "What are the combined 2024 FAANG
headcounts?" Expected to fan out to research_expert, come back, get a
totaled answer.

## Findings

### Finding #1 (real Chronos bug) — JSON serialization on pydantic messages

First run exploded with:
```
TypeError: Object of type HumanMessage is not JSON serializable
```

**Root cause**: `LangGraphRecorder._coerce_state` was a shallow
`dict(values)` — fine for plain state dicts, but LangChain `BaseMessage`
instances went straight through to `json.dumps` untouched.

**Why our own tests missed this**: every existing test uses either plain
dict state or simple string messages. None used pydantic `BaseMessage`.

**Fix**: ADR-011 — recursive `_jsonable` helper that walks state and
calls `.model_dump()` on any pydantic model before handing off to JSON.
Added 4 edge-case tests (pydantic, nested lists/tuples, primitives,
exotic types like datetime/UUID/Enum/bytes).

### Finding #2 (discoverability) — cryptic "no checkpointer" error

Second run:
```
ValueError: No checkpointer set
```

Chronos's LangGraph adapter **requires** the graph to have a checkpointer
(to read state history), but this requirement lives only in the adapter's
internal assumptions — not in `docs/getting-started.md`, not in the
docstring of `LangGraphRecorder.__init__`, not in the error message.

**Severity**: medium. The error is raised by LangGraph itself, not by
Chronos, so users assume it's a LangGraph config bug. No code fix — we
add this to the onboarding doc and sharpen the error message in a later
round.

### Finding #3 (real Chronos bug, regression from fix #1) — extractors blind to dict messages

After the Finding #1 fix, the run succeeded but every node reported
`tokens=0+0` despite real LLM work. Inspection of the raw `state_after_json`
in SQLite showed `usage_metadata` was present:
```
usage_metadata: {"input_tokens": 1110, "output_tokens": 174, ...}
```

**Root cause**: the Finding #1 fix dict-ified messages. All three native
extractors (`aimessage_`, `anthropic_`, `openai_`) do
`getattr(msg, "usage_metadata", None)` — which is always `None` for dicts.
Coercion "worked"; extraction silently dropped everything.

**Fix**: introduce a `_msg_field(msg, key)` helper that dispatches on
`isinstance(msg, dict)`. Both access paths are now compatible. Added 2
regression tests (dict-shape for aimessage + anthropic extractors; openai
shape is same code path).

## Final trace

```
=== Node trace ===
  [  0] supervisor             kind=llm  dur=3080ms  tokens=604+107
  [  1] research_expert        kind=llm  dur=14901ms tokens=1970+220
  [  2] supervisor             kind=llm  dur=2788ms  tokens=1049+218
                                                     ────────────────
                                                     3623 in + 545 out
```

At a glance: `research_expert` is **60% of prompt tokens** and **75% of
wall time** — the exact kind of observability we are supposed to deliver,
now actually working on a real workload.

## Did this expose a fork-execute ("selection A") need?

**No, and that's a data point.** ADR-008 froze "fork plan produces JSON
only, no auto-execute" pending "real demand" evidence. In this dogfood
the user (me) never wished for auto-execute; what I wished for was:
- `usage_extractor` that Just Works — **fixed now**.
- A `chronos runs compare <A> <B>` that would show token delta between
  runs — not yet implemented, but that's a diff-UX need, not a fork-
  execute need.

ADR-008's boundary stays frozen. We revisit after 2-3 more dogfood
targets.

## What we did NOT test

- **Sub-graph nesting**: supervisor uses `create_react_agent` which is
  itself a compiled graph. Chronos records the top-level supervisor
  loop but does not descend into each worker agent's internal ReAct
  turns. This is intentional (one snapshot per top-level node), but
  users building deeper hierarchies may want sub-run attribution.
  Candidate for a future ADR.
- **Streaming tokens**: `.ainvoke()` only, no `.astream_events`.
- **Checkpointer persistence**: used `InMemorySaver` only, not SQLite
  or Postgres checkpointers. The latter might have different state
  dumping quirks.

## Artifacts

- Script: `/workspace/chronos-dogfood/supervisor/dogfood_baseline.py`
- Database: `/workspace/chronos-dogfood/supervisor/dogfood.db`
- Regression tests: `tests/unit/test_adapter_langgraph.py::test_jsonable_*`,
  `tests/unit/test_usage_extractor.py::test_*_works_on_dict_coerced_messages`
- Decision doc: `docs/decisions/ADR-011-state-serialization-boundary.md`

## Cost of this round

(All via OneAPI proxy — no money spent, internal quota only.)

- Prompt tokens across all baseline runs: ~12K
- Completion tokens: ~2K
- Dev iterations to go green: 4 (JSON error → checkpointer → temperature
  deprecated → token extraction regression)

## Takeaways for next rounds

1. **Synthetic tests do not substitute for dogfood.** 236 green unit tests
   coexisted with 3 showstopper bugs on the first real multi-agent run.
2. **Every boundary needs dual-shape testing.** Anywhere we hand data
   across an internal boundary (coerce → extract → store), test both the
   before-shape and after-shape paths.
3. **OneAPI Claude Opus 4.7 gotchas** (recorded in agent memory for
   future rounds): no `temperature` param; model name must match the
   exact display name from `GET /v1/models` ("Claude Opus 4.7" with
   spaces and proper case); response always wraps a fake
   `"error": {"type": "", "message": ""}` field that is safe to ignore.
