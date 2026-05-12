# R68 Research — Arc B Scope: Fourth-Adapter Candidate Landscape

**Round**: 68 (Phase 4 Arc B kickoff planning, post-v0.6.0 md-only slot)
**Date**: 2026-05-13 (CST)
**Status**: Research survey. Feeds [ADR-026 Draft][ADR-026] and [docs/design/fourth-adapter-landscape.md][design].
**Supersedes**: The preliminary evaluation table in [ADR-023][ADR-023] §Arc B (R56 snapshot, now stale after a full year of framework movement).
**Scope**: Evaluate six candidate frameworks for Chronos's fourth adapter. Pick **one recommended** plus **one hot-backup**. Deliver a 9-axis comparative table, ADR-016 mapping difficulty notes, and a slice-by-slice rollout sketch.

---

## 0. Why this doc exists

With Arc A fully closed at v0.6.0 (slice 1/2/3 R58-R60 / slice 4 R62-R64 / slice 5 + item 2 R65-R67), [ADR-023][ADR-023] binds the next active arc to **Arc B — Ecosystem**. Arc B's flagship deliverable is a **fourth framework adapter**. The ADR-023 Arc B candidate table is a **2026-04-22 snapshot**; enough has moved in the ecosystem over the past three weeks (and especially since Phase 2/3 shipped) that a refresh is cheap and high-leverage.

This research doc is **fuel for ADR-026**, not ADR-026 itself. ADR-026 commits; R68 doc explains why that commit is defensible.

### Hard constraints from ADR-023 and prior ADRs

- [ADR-001][ADR-001] pins Python 3.11+ as the primary language. TS-native frameworks (Vercel AI SDK, Mastra) are **out of scope for v0.7.0** unless a user shows up.
- [ADR-016][ADR-016] is the contract. The fourth adapter must be expressible as `RecorderProtocol` + `AdapterProtocol`. Event-model divergence beyond the LangGraph/AutoGen/CrewAI triad is the primary risk axis.
- [ADR-017][ADR-017] (AutoGen sync-wrap) and [ADR-021][ADR-021] (CrewAI event-bus) have already established two non-trivial adapter patterns: callback/stream-based (LangGraph, CrewAI) and sync-wrap-of-async (AutoGen). A fourth adapter that reuses one of these patterns is cheaper than one that invents a third.
- v0.6.0 has **zero external users** (confirmed: project repo is private as of R67, CONTEXT.md §0). Arc B is therefore leverage-driven, not demand-driven — we pick the candidate most likely to **attract** the first external user, not the one an existing user asks for.

---

## 1. Candidate inventory (2026-05-13)

The six candidates that survived initial screening. Each has at least one shipped public release, a discoverable event/hook surface, and a permissive license. Candidates rejected in a one-line screen (no stable public API, proprietary-only, duplicate semantics of an existing adapter) are at the bottom.

### 1.1 OpenAI Swarm (experimental, by OpenAI)

- **Repo**: `openai/swarm`, Apache-2.0.
- **Model**: Lightweight routine/handoff framework — an Agent is a dict of `{instructions, functions, handoff_targets}`. `Swarm.run(agent, messages)` loops through tool calls and `handoff_to(Other)` until no more pending. Ergonomics inherited from OpenAI API.
- **Popularity (2026-05)**: Medium-low. OpenAI has explicitly called Swarm "educational, not production" since late 2024, and their internal direction has pivoted toward Agents SDK (see §1.4). GitHub star trajectory flattened Q1 2026.
- **Event surface**: No native callbacks. Adapter must monkeypatch `Swarm.run` or intercept `client.chat.completions.create`. Similar to the proxy-based approach we explicitly avoided in [ADR-002][ADR-002].
- **Verdict**: ⚠️ Declining relevance. Parking it.

### 1.2 Anthropic Agents SDK (`claude-agent-sdk`)

- **Repo**: `anthropics/claude-agent-sdk-python`, MIT-ish.
- **Model**: Built on MCP. Agent = system prompt + MCP server list. Tool calls are MCP tool invocations over stdio/sse. Multi-turn conversation loop with explicit `stop_reason` handling. Streamed events via `async for event in agent.stream(...)`.
- **Popularity (2026-05)**: Rising fast. MCP standardisation (2024-Q4) + Claude 3.7 Sonnet (2025-Q1) + growing MCP server ecosystem (2025-H2) give this framework a tailwind. Anthropic's official endorsement plus the MCP angle make it the closest thing to "the MCP-native agent framework".
- **Event surface**: Async stream of typed events: `MessageStartEvent`, `ContentBlockDeltaEvent`, `ToolUseEvent`, `ToolResultEvent`, `MessageStopEvent`. Clean. No monkeypatching required.
- **Determinism**: Supports `seed=…` on Messages API. Temperature/top_p controllable. Good for fork replay.
- **Usage extraction**: Native `Usage` dataclass on every response with `input_tokens`, `output_tokens`, `cache_creation_input_tokens`, `cache_read_input_tokens`. Directly maps to the ADR-015 Layer 4 extractor contract (we already handle Anthropic prompt-caching in the LangGraph extractor).
- **Fork primitive**: Re-seed message history + re-invoke `agent.run`. Similar to LangGraph's `update_state + invoke(None)` shape. Thread-id concept matches naturally via MCP `session_id`.
- **ADR-016 mapping difficulty**: **Low-Medium**. Similar shape to LangGraph adapter: async generator → record loop → stream event → persist node. `fork()` reuses the replay-history-from-seed pattern. Biggest unknown: MCP server lifecycle during fork (do we rewind the MCP server state, or re-connect fresh?).
- **Verdict**: ✅ **Leading candidate**.

### 1.3 LangGraph Swarm Mode / Supervisor patterns (LangChain)

- **Repo**: `langchain-ai/langgraph`, MIT.
- **Model**: Not a separate framework — a *pattern* inside LangGraph where multiple named subgraphs coordinate via a supervisor router. Shared checkpointer, shared state schema. Shipped as `langgraph.prebuilt.create_swarm` in LangGraph 1.2+ (released 2026-03).
- **Popularity**: High (inherits LangGraph's base). But this is a LangGraph *pattern*, not a new adapter target — our existing `LangGraphRecorder` already records it (each supervisor-routed subgraph is a LangGraph node).
- **Verdict**: ❌ Not an adapter candidate. File under "dogfooding opportunity" for Arc A item 5 (determinism modes) instead.

### 1.4 OpenAI Agents SDK (`openai-agents`)

- **Repo**: `openai/openai-agents-python`, MIT.
- **Model**: OpenAI's official successor to Swarm. Agent = instructions + tools + handoffs + guardrails. `Runner.run(agent, input)` drives the loop. Built-in tracing hooks (`agents.tracing.Trace`, `Span`).
- **Popularity**: Rising. OpenAI-blessed + strong TypeScript port + bundled with Assistants-migration guidance. Likely to absorb Swarm's user base.
- **Event surface**: Native `agents.tracing` API — `Trace` objects with typed `Span`s for LLM calls, tool calls, handoffs. This is **the** reason to prefer Agents SDK over Swarm: you don't monkeypatch; you register a `TracingProcessor`.
- **Determinism**: OpenAI Responses API supports `seed`, but Agents SDK doesn't expose it in the first-class `Agent` config — you'd pass it via `model_settings`. Workable.
- **Usage extraction**: `Span.usage` has `input_tokens`, `output_tokens`, `reasoning_tokens` (for o1/o3 models — this is the reasoning-tokens semantics already noted in CONTEXT.md long-term invariants). Clean ADR-015 Layer 4 mapping.
- **Fork primitive**: `Runner.run_stream` with a seeded conversation history. Handoff state re-enterable. Similar shape to LangGraph fork.
- **ADR-016 mapping difficulty**: **Low**. `TracingProcessor` is the cleanest record-surface we've seen across four adapters. Better than LangChain callbacks, better than CrewAI event bus.
- **Verdict**: ✅ **Hot-backup candidate** — or swap roles with Anthropic Agents SDK if MCP fork-lifecycle turns out messy.

### 1.5 Letta (formerly MemGPT)

- **Repo**: `letta-ai/letta`, Apache-2.0.
- **Model**: Memory-centric agent with persistent long-term memory, tool use, optional multi-agent. Server/client architecture (Letta server holds agent state; client invokes `agent.step`).
- **Popularity**: Niche-but-growing in the "agent with memory" cohort. Not mainstream but has a defensible moat (nobody else treats memory as a first-class primitive like this).
- **Event surface**: HTTP API + Python SDK. Streaming via SSE. Events include `ToolCallMessage`, `ToolReturnMessage`, `AssistantMessage`, `ReasoningMessage`. Not bad.
- **Fork primitive**: `client.agents.clone(agent_id)` exists — native support for forking an entire agent (including memory). This is **uniquely good for Chronos** — no other candidate ships a native clone primitive. But: cloning is coarse (whole agent), not mid-run node-level. Would need to pair with replay-from-messages.
- **ADR-016 mapping difficulty**: **Medium-High**. The server/client split means the adapter is really recording *client* events. Server-side state (memory embeddings, block updates) is opaque without Letta API support. Risk: an important state change happens server-side and the recorder never sees it.
- **Verdict**: ⚠️ Interesting but risky for a fourth adapter. Better as Arc B slice 3+ after we've de-risked on a lower-surface framework.

### 1.6 Pydantic AI

- **Repo**: `pydantic/pydantic-ai`, MIT.
- **Model**: Type-safe LLM agent framework by the Pydantic team. Agents have strongly-typed `deps_type` and `result_type`. `agent.run(query)` returns `AgentRunResult[ResultT]`. Streaming via `agent.run_stream`.
- **Popularity**: Medium-high and rising. Pydantic brand + FastAPI crossover + very clean type story. Strong appeal to the "framework-skeptical Python dev" cohort.
- **Event surface**: `agent.iter(query)` yields typed nodes — `UserPromptNode`, `ModelRequestNode`, `ToolCallsNode`, `ModelResponseNode`, `EndNode`. **Iterator-based, not callback-based** — the adapter just iterates. This is also very clean.
- **Determinism**: `ModelSettings.seed` + `temperature`. First-class.
- **Usage extraction**: `Usage` dataclass on every `AgentRunResult`; maps directly.
- **Fork primitive**: `agent.iter` accepts `message_history` — standard replay-from-history pattern. Handoff-style not natively supported (no multi-agent primitive), which limits the breadth of fork scenarios.
- **ADR-016 mapping difficulty**: **Low**. The iterator model is arguably the easiest of any framework we've surveyed — adapter is essentially a `for node in agent.iter(...): recorder.log(node)`. But: no multi-agent primitive, so we'd be recording single-agent-multi-step, not multi-agent-orchestration.
- **Verdict**: ✅ **Alternative hot-backup** — attractive for ease but narrower in agent-topology coverage than Anthropic / OpenAI Agents SDK.

### 1.7 Rejected-in-screen

| Candidate | Rejected because |
|---|---|
| OpenAI Assistants v2 | Proprietary, API-only, no local runtime. Same adapter shape as direct OpenAI calls — adds little vs existing three. |
| Vercel AI SDK | TypeScript-native. Blocked by [ADR-001][ADR-001] until Python-or-TS revisited. |
| LiveKit Agents | Real-time voice/video focus. Event model divergent enough that it'd need its own ADR cluster (streaming-audio node type?). Niche. |
| Generic OTel receiver | Schema mismatch with ADR-003 canonical node schema. High adapter complexity, low user-facing benefit (not a framework users choose). Defer to Arc B slice 3+ as catch-all. |
| Smolagents (HuggingFace) | Event surface is pattern-match-on-stdout. Too hacky for a production adapter. |
| CrewAI Flows (new in 0.86+) | Same adapter as existing CrewAI — just a new top-level API. Our CrewAI adapter already intercepts `crewai_event_bus`; Flows dispatch to the same bus. |
| Mastra (TS) | Same TS blocker as Vercel AI SDK. |

---

## 2. Nine-axis comparative table

Axes refined from [ADR-023][ADR-023] §Arc B and the R27 multi-framework risks doc (`docs/research/risks.md`). The three remaining candidates (Anthropic, OpenAI Agents SDK, Pydantic AI) are compared head-to-head; Letta kept in column 4 as "ambitious future".

| Axis | Anthropic Agents SDK | OpenAI Agents SDK | Pydantic AI | Letta (future) |
|---|---|---|---|---|
| **License** | MIT | MIT | MIT | Apache-2.0 |
| **Event surface cleanliness** | Async stream of typed events (no monkeypatch) | `TracingProcessor` registration (cleanest) | Typed iterator nodes (cleanest overall) | SSE stream over HTTP |
| **Multi-agent topology** | Yes (via handoffs + MCP server hierarchy) | Yes (first-class handoffs) | No (single-agent, multi-step) | Yes (Letta multi-agent groups) |
| **Determinism knobs** | `seed` + `temperature`, first-class | `seed` via `model_settings`, usable | `seed` + `temperature`, first-class | Per-model, inconsistent |
| **Usage extraction fit (ADR-015)** | Direct map incl. prompt cache fields | Direct map incl. reasoning tokens | Direct map | Opaque in places |
| **Fork primitive shape** | Re-seed message history + re-invoke (LangGraph-like) | Seeded conversation → `Runner.run_stream` (LangGraph-like) | `message_history` arg to `agent.iter` (simplest) | Native `clone` (coarse) |
| **ADR-016 mapping difficulty** | Low-Medium | Low | Low | Medium-High |
| **Ecosystem mindshare 2026-Q2** | Rising fast (MCP tailwind) | Rising (Swarm successor) | Medium-high (Pydantic brand) | Niche-rising |
| **User cohort unlocked by shipping** | "MCP-native shops" — growing rapidly, underserved by existing observability tools | "OpenAI-native teams migrating from Assistants" — large but crowded | "Type-safe Python shops" — narrow but loyal | "Memory-focused agents" — niche |

### 2.1 Decision axes explained (for the ADR)

- **Leverage (biggest cohort × stickiest pain)**: Anthropic Agents SDK wins. MCP-native shops are growing fast, and no existing observability tool has strong MCP-aware trace semantics. OpenAI Agents SDK second (bigger cohort but more crowded competitive field — OpenAI's own tracing is already decent).
- **Risk (ADR-016 mapping + novel semantics)**: Pydantic AI lowest risk (iterator model is trivial to wrap). OpenAI Agents SDK second lowest (`TracingProcessor` is nearly as clean). Anthropic Agents SDK third (MCP server lifecycle is the unknown).
- **Strategic fit (who do we want to attract as the first external user?)**: Anthropic Agents SDK. The MCP angle fits Chronos's "agent pdb + git" framing unusually well — MCP's tool-call surface is exactly the interception point Chronos wants.

---

## 3. Recommended path for Arc B slice 1 (v0.7.0)

**Primary pick: Anthropic Agents SDK (`claude-agent-sdk`).** Two-round slice shape mirroring R52→R53 (CrewAI) and R58→R59 (N-run compare):

- **R69 — scoping ADR Draft → Accepted + design doc + risks spike.** Draft ADR-026 in R68 (this round). R69 promotes Draft → Accepted after one round of reflection and targets adapter shape.
- **R70 — core adapter scaffold** `src/chronos/adapters/anthropic_agents/recorder.py` + duck-typed test fixture + `AdapterProtocol` conformance tests. Mirrors R51 CrewAI scaffold.
- **R71 — live-smoke test + ADR refinement.** Requires `ANTHROPIC_AUTH_TOKEN` (already in `.env`); run a real Claude agent with 1-2 MCP tools, capture events, verify node schema.
- **R72 — dogfood** `scripts/dogfood_anthropic_agents.py` + v0.7.0a1 pre-release.
- **R73 — fork primitive** (MCP session lifecycle decision + re-invoke pattern) + live-smoke on fork.
- **R74 — v0.7.0 release cut** if R70-R73 all green.

**Hot-backup: OpenAI Agents SDK.** If R69 risks spike surfaces a blocker in MCP server fork-lifecycle (e.g., no clean way to rewind MCP server state without a full teardown+rebuild), swap to OpenAI Agents SDK. Rollout identical, substitute framework name. ADR-026 Draft will call out this fallback explicitly so the swap is pre-authorised.

**Arc B slice 2 (after v0.7.0)**: One of Pydantic AI (low risk, complements single-agent recording) or Letta (ambitious, memory-first). No commit in R68 — decide at R74 retro.

---

## 4. What R68 explicitly does NOT decide

- Final adapter class name or module path (ADR-026 Draft reserves `src/chronos/adapters/anthropic_agents/` by convention from LangGraph/CrewAI precedent, but this is not load-bearing).
- MCP server fork-lifecycle policy (deferred to R69 risks spike — the only live open question).
- Web UI changes for the fourth adapter (none expected — the adapter surface is `Run`/`Node`/`Fork` rows, already framework-agnostic).
- Pricing implications (irrelevant, Chronos is OSS, not SaaS).
- TypeScript support (still blocked by ADR-001).

---

## 5. References

- [ADR-001][ADR-001] — Python 3.11+ primary language
- [ADR-002][ADR-002] — LangGraph first adapter
- [ADR-016][ADR-016] — Adapter interface contract
- [ADR-017][ADR-017] — AutoGen sync-wrap
- [ADR-021][ADR-021] — CrewAI adapter
- [ADR-023][ADR-023] — Phase 4 charter (Arc A pinned, Arc B deferred)
- [design] — `docs/design/fourth-adapter-landscape.md` (R68, feature spec)
- `docs/research/risks.md` (R27, multi-framework risks)

[ADR-001]: ../decisions/ADR-001-language.md
[ADR-002]: ../decisions/ADR-002-langgraph-first-adapter.md
[ADR-016]: ../decisions/ADR-016-adapter-interface.md
[ADR-017]: ../decisions/ADR-017-autogen-adapter-sync-wrap.md
[ADR-021]: ../decisions/ADR-021-crewai-adapter.md
[ADR-023]: ../decisions/ADR-023-phase-4-charter-skeleton.md
[ADR-026]: ../decisions/ADR-026-arc-b-scope.md
[design]: ../design/fourth-adapter-landscape.md

---

*Authored R68 (2026-05-13 CST, planning round). Feeds ADR-026 Draft. Next round R69 promotes ADR to Accepted after risks spike.*
