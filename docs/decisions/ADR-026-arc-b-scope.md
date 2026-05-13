# ADR-026: Arc B Scope — Fourth Adapter is Anthropic Agents SDK (Accepted)

**Status**: Accepted (R69, 2026-05-13 — promoted in-place from R68 Draft per R57 invariant)
**Date**: 2026-05-13 (Drafted R68; Accepted R69)
**Deciders**: chengfei867, Hermes Agent
**Supersedes**: the preliminary Arc B candidate table in [ADR-023][ADR-023] §Arc B (R56 snapshot, superseded by R68 research)
**Depends on**: [ADR-016][ADR-016] (adapter interface), [ADR-023][ADR-023] (Phase 4 charter, Arc B deferred until Arc A ships), [ADR-001][ADR-001] (Python 3.11+ pin)
**Related**: [ADR-017][ADR-017] (AutoGen sync-wrap), [ADR-021][ADR-021] (CrewAI adapter), [ADR-022][ADR-022] (CrewAI version pin bump)
**Feeds**: [docs/design/fourth-adapter-landscape.md][design], [docs/research/r68-arc-b-scope.md][research], [docs/research/r69-mcp-fork-lifecycle.md][r69]

---

## Context

Arc A of Phase 4 shipped fully through v0.6.0 (slice 1-5 + item 2 fork-tree viz; see CONTEXT.md §5 R58-R67 history). Per [ADR-023][ADR-023] §Decision, Arc B (Ecosystem — fourth adapter + export surfaces) was explicitly deferred until Arc A shipped. That gate has now opened.

R68 is a planning round (md-only, single-slot). Its job is to convert the ADR-023 Arc B charter sketch ("a fourth framework adapter, candidate table TBD") into a committable scope. The R68 research survey ([docs/research/r68-arc-b-scope.md][research]) evaluated six candidates along nine axes; this ADR commits to a primary target and pre-authorises one fallback.

### Why commit now (R68) rather than defer

1. Arc A is closed, Arc B is the ADR-023-blessed next active arc. Deferring means either idle cycles or bleeding into Arc C (plumbing, which has zero demand signal). ADR-023 §"Why Arc A over Arc B / Arc C" explicitly marks Arc C as demand-driven — it cannot be the next arc without external users showing up, and as of R68 there are zero.
2. The R56→R57 lesson (charter skeleton → scope commit) applies here: a deferred decision is cheaper than a wrong one, but an **over**-deferred decision is a drift magnet. R68 is analogous to R57 (the moment Arc A was formally committed after R56's three-arcs framing).
3. [R68 research][research] §2.1 finds **Anthropic Agents SDK** uniquely well-matched to Chronos's positioning (MCP-native shops, underserved by existing observability tools). The 2026-Q2 tailwind (MCP standardisation + Claude 3.7 Sonnet + MCP server ecosystem growth) is time-sensitive — delaying by a full quarter cedes ground to Langfuse/Phoenix.

### What's different from the ADR-023 snapshot

ADR-023 §Arc B table listed six candidates with "TBD" on event hooks and ADR-016 mapping difficulty. R68 research resolved:

- **OpenAI Swarm** — declining relevance (OpenAI pivoted to Agents SDK). Reject.
- **OpenAI Assistants v2** — proprietary, API-only, no real adapter surface. Reject.
- **Anthropic Agents SDK** — rising fast, MCP-native, low-medium ADR-016 mapping difficulty. **Promote to primary.**
- **Letta** — ambitious but risky (server/client opacity). Defer to Arc B slice 2+.
- **LiveKit Agents** — real-time voice niche. Defer indefinitely.
- **Generic OTel receiver** — schema mismatch. Defer to Arc B slice 3+ as catch-all.

Plus two newly-evaluated candidates not in ADR-023's original table:

- **OpenAI Agents SDK** (Swarm successor, post-R56) — **hot-backup** if MCP fork-lifecycle turns out infeasible.
- **Pydantic AI** — low-risk, narrow-scope. Candidate for Arc B slice 2.

---

## Decision

**Arc B slice 1 target: Anthropic Agents SDK (`claude-agent-sdk`).** Five-round rollout R70-R74, bundled as v0.7.0. **Pre-authorised fallback: OpenAI Agents SDK** if the R69 risks spike exposes a blocker in MCP server fork-lifecycle (see §Fallback clause below).

### 1. Primary binding

- **Framework**: Anthropic Agents SDK (`claude-agent-sdk-python`).
- **Adapter module**: `src/chronos/adapters/anthropic_agents/` (sibling to `langgraph.py`, `autogen/`, `crewai/`).
- **Version pin**: `claude-agent-sdk>=0.1.80,<1.0` (optional-dep in `pyproject.toml::[project.optional-dependencies].anthropic_agents`). R69 crystallised; floor chosen because `fork_session()` + `SessionStore` shipped well before 0.1.80; ceiling at next-major per [ADR-022][ADR-022] precedent. See [r69][r69] §3.
- **Event-capture pattern**: Async iteration over the SDK's `Message` stream — either `query()` (stateless generator) or `ClaudeSDKClient.receive_response()` / `receive_messages()` (stateful client context-manager). No monkeypatch. Third verification of the "stream → log" pattern after LangGraph callbacks and CrewAI event bus. No ADR-016 revisions required.
- **Fork primitive**: SDK-native `fork_session(session_id, up_to_message_id=...)` — a **first-class transcript-level fork already shipped in 0.1.x**. The adapter wraps it; no custom re-seed logic. MCP servers are per-CLI-subprocess (not per-session) so fork does not touch MCP state. See [r69][r69] §1.

### 2. Interface fit

[ADR-016][ADR-016] `RecorderProtocol` and `AdapterProtocol` are unchanged. The new adapter implements:

```python
class AnthropicAgentsRecorder:
    def __init__(self, store: SqliteStore): ...
    def record(self, agent, *, thread_id, task_description=None, tags=None) -> ContextManager[RunRef]: ...
    def fork(self, agent, *, parent_run_id, at_node_id, overrides=None, child_thread_id, reason=None, task_description=None, tags=None) -> ContextManager[ForkRef]: ...
```

Module-level `anthropic_agents_adapter: AdapterProtocol` per R32-B pattern (LangGraph and Linear precedent).

Node schema ([ADR-003][ADR-003]) and extractor contract ([ADR-015][ADR-015]) require **zero** revisions — see [design][design] §5-§6. This is a pure-additive adapter; the "adapter-interface stability" claim post-ADR-016 holds for the fourth adapter, strengthening the R27 multi-framework risks doc's "the contract survives a fourth framework" empirical hypothesis.

### 3. Release strategy

Five-round rollout (R70-R74), bundled as v0.7.0. Mirrors the CrewAI v0.4.0 cadence (R49-R55) but compressed:

- **R70** — recorder core + duck-typed conformance tests.
- **R71** — live-smoke (`tests/live/test_anthropic_agents_smoke.py`) with triple-skipif (`CHRONOS_LIVE` + `ANTHROPIC_AUTH_TOKEN` + SDK import guard).
- **R72** — dogfood script + v0.7.0a1 alpha tag.
- **R73** — fork primitive + fork live-smoke.
- **R74** — v0.7.0 release cut per `chronos-release-pattern` skill (14th application).

### 4. Fallback clause (pre-authorised swap)

If R69 risks spike concludes that MCP server state cannot be rewound cleanly during fork (Risk R1 in [design][design] §8), the R70-R74 rollout substitutes **OpenAI Agents SDK** for Anthropic Agents SDK with **no additional ADR required**. The rollout phases are identical, just swap framework name + SDK package + event-stream shape. This pre-authorisation prevents a round-level re-planning detour if the blocker materialises.

Criteria for invoking the fallback (must meet ALL):

1. R69 risks spike confirms no feasible Policy B (session re-seed) for MCP server lifecycle during fork.
2. Policy A (fresh server on fork) is judged by R69 agent to materially degrade the Chronos value prop for MCP-heavy agents (e.g., forks lose >30% of useful state).
3. OpenAI Agents SDK `TracingProcessor` API is still stable at R69 (`openai-agents>=X.Y` is shippable).

If any criterion fails, stick with primary (Anthropic Agents SDK) and document the MCP limitation in the v0.7.0 release notes.

### 5. What Arc B slice 2+ looks like

After v0.7.0 ships:

- **Arc B slice 2 (v0.8.0)**: One of Pydantic AI or Letta. Decision at R74 retro.
- **Arc B slice 3+ (TBD)**: Generic OTel receiver, Jupyter integration, Parquet export. Demand-driven; may slip into Arc C cohort.

None of these bind this ADR. ADR-026 only commits Arc B slice 1.

---

## Acceptance criteria (for ADR-026 Accepted promotion)

Per [ADR-016][ADR-016] R1-R4 gates (applied here for the fourth adapter):

- [ ] **AC-1** — Adapter implements `RecorderProtocol` and `AdapterProtocol`; conformance tests green.
- [ ] **AC-2** — Live-smoke records one multi-turn conversation with ≥1 MCP tool; verify node kinds + usage extraction.
- [ ] **AC-3** — Fork primitive re-invokes agent from `at_node_id` with `overrides`; live-smoke green.
- [ ] **AC-4** — Dogfood script exits 0 with runtime assertions on recorded structure (per R64 dogfood-as-release-gate invariant).
- [ ] **AC-5** — Existing adapter matrix (LangGraph/AutoGen/CrewAI) does not regress: all tests green, zero code change to `langgraph.py`/`autogen/`/`crewai/`.

ADR-026 promotes Draft → Accepted in R74 **after** AC-1..AC-5 all tick.

### In-place promotion marker

Per the R57 "in-place ADR promotion" invariant, this ADR's Draft→Accepted flip happens by editing the status field of this same file (no new file, no branching). **Scope flip happened in R69** — i.e. the Arc B scope selection (Anthropic Agents SDK as slice 1) is now settled. AC-1..AC-5 are **release-time gates** tracked separately; the R74 release commit will note "ADR-026 acceptance gates AC-1..AC-5 closed" rather than flipping status again.

---

## Open questions (resolved by R69 risks spike)

All three blocker-class questions resolved by source-inspection spike of `anthropics/claude-agent-sdk-python` (commit at v0.1.81 on PyPI, R69). Full notes: [docs/research/r69-mcp-fork-lifecycle.md][r69].

1. **MCP server fork-lifecycle policy** (was: A fresh-server vs B session-reseed).
   **Resolved**: *neither*. The SDK ships `fork_session(session_id, up_to_message_id=...)` in `_internal/session_mutations.py` — a pure transcript-JSONL rewrite that assigns new UUIDs and truncates history at the requested message. **MCP servers have zero coupling to fork** (grep `"mcp"` in `session_mutations.py` → 0 hits); MCP servers are per-CLI-subprocess and reconnect stateless on session resume. The chronos-agent adapter therefore **delegates to the SDK primitive** — no custom Policy A / Policy B / re-seed logic needed. §4 fallback clause remains dormant but unactivated.

2. **Recorder entry point** (was: `agent.iter(...)` vs `agent.stream(...)`).
   **Resolved**: both names were speculative and **do not exist** in the SDK. Actual primitives:
   - `query(prompt, options) -> AsyncIterator[Message]` — stateless fire-and-forget.
   - `ClaudeSDKClient` (stateful async context manager) + `await client.query(prompt)` + `async for msg in client.receive_response(): ...` — multi-turn pattern used for both recording and fork-resume.
   - Message union: `UserMessage | AssistantMessage | SystemMessage | ResultMessage`; content blocks: `TextBlock | ToolUseBlock | ToolResultBlock | ThinkingBlock`.
   Recorder seam = wrap the `receive_response()` async iterator (parallel to the CrewAI event bus and LangGraph callback patterns). See [r69][r69] §2.

3. **Version pin** (was: `claude-agent-sdk>=X.Y,<Z.0`).
   **Resolved**: `claude-agent-sdk>=0.1.80,<1.0` declared as extra in `pyproject.toml::[project.optional-dependencies].anthropic_agents`. PyPI latest = 0.1.81 (83 releases in the 0.1.x line; still alpha/pre-1.0). Python requirement `>=3.10` (compatible with our 3.11+ floor per [ADR-001][ADR-001]); MIT licensed. Ceiling at next-major rather than next-minor because the SDK is still rapidly iterating and 0.x minor bumps have been additive in practice (e.g. `fork_session` shipped mid-0.1.x). Revisit ceiling at R74 retro if 0.2 releases before then. See [r69][r69] §3.

**R71 live-smoke prerequisite** (new finding, not a blocker): the SDK spawns a bundled Node.js `claude-code` CLI as subprocess (see `README.md:10-20`). Live-smoke tests need Node available on the runner; override path via `ClaudeAgentOptions(cli_path=...)`. R71's skipif matrix mirrors the existing `HAS_CREWAI` pattern.

Deferred to R74 retro (no block on v0.7.0):

4. Arc B slice 2 target (Pydantic AI vs Letta).
5. Whether to promote [ADR-023][ADR-023] Arc B candidate table into a dedicated `docs/research/adapter-4-survey.md` artifact (currently superseded by R68 research doc).

---

## Consequences

### Positive

- Fourth adapter broadens user cohort to MCP-native Claude shops (the 2026-H2 fastest-growing segment per the research doc).
- Validates ADR-016 contract across a fourth framework (strong "interface-stability" evidence).
- Enables U3 cross-framework diff story (LangGraph run vs Anthropic Agents run in the same compare view) — no new code, just dogfood confirmation.
- Pre-authorised fallback clause prevents round-level detour if primary blocks.

### Negative

- Commits five rounds (R70-R74) to one framework. If Anthropic Agents SDK loses momentum mid-Arc, we've already shipped by R74 — sunk cost is manageable (one minor release cycle).
- Adds `claude-agent-sdk` as a new optional dependency; expands the optional-dep live-test skipif matrix.
- Delays Arc B slice 2 (Pydantic AI / Letta) by ~5-6 weeks at current cron cadence.

### Neutral

- No changes to Web UI, node schema, extractor contract, CLI, or HTTP API surface. Pure-additive adapter.
- No changes to existing three adapters — they remain zero-regression through R74 (adapter streak R52→R74 target = 22 rounds zero code change; current at R67 = 16 rounds).

---

## References

- [ADR-023][ADR-023] — Phase 4 charter (supersedes Arc B candidate table)
- [ADR-016][ADR-016] — Adapter interface
- [ADR-017][ADR-017] — AutoGen sync-wrap (adapter pattern precedent)
- [ADR-021][ADR-021] — CrewAI adapter (adapter pattern precedent)
- [ADR-022][ADR-022] — CrewAI version pin bump (pin policy precedent)
- [research] — `docs/research/r68-arc-b-scope.md`
- [r69] — `docs/research/r69-mcp-fork-lifecycle.md`
- [design] — `docs/design/fourth-adapter-landscape.md`

[ADR-001]: ADR-001-language.md
[ADR-003]: ADR-003-sqlite-schema.md
[ADR-015]: ADR-015-extractor-contract-v2.md
[ADR-016]: ADR-016-adapter-interface.md
[ADR-017]: ADR-017-autogen-adapter-sync-wrap.md
[ADR-021]: ADR-021-crewai-adapter.md
[ADR-022]: ADR-022-crewai-version-pin-bump.md
[ADR-023]: ADR-023-phase-4-charter-skeleton.md
[research]: ../research/r68-arc-b-scope.md
[r69]: ../research/r69-mcp-fork-lifecycle.md
[design]: ../design/fourth-adapter-landscape.md

---

*Authored R68 (2026-05-13 CST, planning round); promoted to Accepted in R69 after source-inspection spike closed all 3 blocker-class open questions. Arc B slice 1 scope now frozen: Anthropic Agents SDK + SDK-native `fork_session` + `ClaudeSDKClient.receive_response()` recorder seam + `claude-agent-sdk>=0.1.80,<1.0` pin. Release gates AC-1..AC-5 tick in R70-R74. Fallback clause (§4) remains dormant — no trigger activated.*
