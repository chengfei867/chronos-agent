# Design — Fourth-Adapter Landscape (Arc B Slice 1)

**Round**: R68 (planning, md-only)
**Date**: 2026-05-13 (CST)
**Status**: Draft — feeds [ADR-026][ADR-026]
**Owner**: Hermes Agent
**Related**: [ADR-023][ADR-023] Phase 4 charter · [ADR-016][ADR-016] adapter interface · [ADR-026][ADR-026] Arc B scope · [r68-arc-b-scope][research] research survey

---

## 1. Feature statement

Add a **fourth framework adapter** to the Chronos adapter matrix, bringing the supported set to `{LangGraph, AutoGen, CrewAI, <new>}`. The new adapter must satisfy the [ADR-016][ADR-016] `RecorderProtocol` + `AdapterProtocol` contract unchanged — no adapter-interface ADR revisions are in scope for Arc B slice 1. The value proposition is breadth: Chronos's first external user should be reachable by picking the single framework with the strongest 2026-H2 tailwind.

Recommended target (per [research doc][research] §3): **Anthropic Agents SDK (`claude-agent-sdk`)**. Hot-backup: **OpenAI Agents SDK** (pre-authorised swap if R69 risks spike exposes an MCP fork-lifecycle blocker).

## 2. User stories

- **U1 (MCP-native shop)**: "I'm building a Claude-based agent with three MCP servers. It hallucinates a tool call once every twenty runs. I want to fork the trace at the moment-of-hallucination and try a different system prompt to see if the hallucination disappears, without re-running the twenty setup turns."
- **U2 (framework-switcher)**: "I migrated from LangGraph to Anthropic Agents SDK last month. My recording pipeline broke. I want a one-line adapter swap that gives me the same Chronos UI over my new agent."
- **U3 (diff-across-frameworks)**: "I'm A/B testing — is my LangGraph agent or my Anthropic Agents SDK agent better at the same task? I want to compare their traces side-by-side in the same Chronos UI." (This story is a pull for Arc A + Arc B synergy; no new code required, just validation that cross-framework diff works.)

## 3. Non-goals

- ❌ **New adapter-interface ADR.** [ADR-016][ADR-016] is the contract; any proposed revision would be a new ADR, out of scope for Arc B slice 1.
- ❌ **MCP protocol implementation.** We consume MCP via the Anthropic SDK's existing support; Chronos is not an MCP server or client.
- ❌ **Prompt-caching semantic changes.** The LangGraph extractor already handles Anthropic prompt caching (ADR-012 era). The new adapter reuses the same extractor layer.
- ❌ **Web UI framework-specific tabs.** The UI stays framework-agnostic (displays `Run`/`Node`/`Fork` rows). A future slice may add per-framework filters; not R69-R74.
- ❌ **TypeScript-native framework support.** Blocked by [ADR-001][ADR-001] until Python-or-TS revisited; Vercel AI SDK / Mastra deferred.
- ❌ **"All adapters in one release" bundle.** If Pydantic AI makes sense in Arc B slice 2, it ships as v0.8.0, not bundled into v0.7.0.

## 4. API shape sketch

The public surface users see:

```python
from chronos.adapters.anthropic_agents import AnthropicAgentsRecorder
from chronos.store import SqliteStore

store = SqliteStore.open(".chronos/store.db")
recorder = AnthropicAgentsRecorder(store=store)

from claude_agent_sdk import Agent
agent = Agent(system_prompt="You are a helpful assistant.", mcp_servers=[...])

with recorder.record(agent, thread_id="t1", task_description="answer Q") as run_ref:
    result = await agent.run("What's the capital of France?")
# run_ref.run_id now indexes into store.
```

Fork:

```python
with recorder.fork(
    agent,
    parent_run_id=run_ref.run_id,
    at_node_id="node_42",
    overrides={"system_prompt": "You are a terse assistant."},
    child_thread_id="t1-fork1",
    reason="system prompt A/B",
) as fork_ref:
    result = await agent.run("What's the capital of France?")
```

CLI (no new commands — all existing commands work uniformly):

```
$ chronos runs list
$ chronos tree <run_id>
$ chronos compare --auto-pivot <r1> <r2> <r3>
```

### 4.1 Recorder internals (preliminary)

Anthropic Agents SDK exposes an async generator event stream. The recorder:

1. Wraps `agent.run` (or `agent.stream`) at record start.
2. Iterates events: `MessageStartEvent` → open new `Node(kind=llm)`; `ToolUseEvent` → open `Node(kind=tool)`; `ToolResultEvent` → close tool node with output; `MessageStopEvent` → close llm node with usage.
3. Persists each node to the store via the same `SqliteStore` call sites LangGraph uses.
4. Returns `RunRef(run_id=...)` context-manager style on exit.

This is the LangGraph/CrewAI pattern, third verification. [ADR-016][ADR-016] remains unchanged.

### 4.2 Fork internals (preliminary — pending R69 risks spike)

Open question: **MCP server state rewind.** Two candidate policies:

- **Policy A (fresh server)**: At fork, teardown all MCP server connections; re-start fresh. Simple; loses any server-side state accumulated before the fork point.
- **Policy B (session re-seed)**: Use MCP session-id to re-connect to the same server session, seed the conversation history up to the fork point, and invoke. Requires Anthropic SDK to support session resume (ongoing unknown — R69 spike target).

[ADR-026][ADR-026] Draft will reserve both policies; R69 risks spike decides.

## 5. Node schema fit (ADR-003)

Existing [ADR-003][ADR-003] node schema (`kind` ∈ `{llm, tool, fn, router, fork, end}`) covers Anthropic Agents SDK cleanly:

| SDK event | Chronos `NodeKind` |
|---|---|
| `MessageStartEvent` / `MessageStopEvent` | `llm` |
| `ToolUseEvent` + matching `ToolResultEvent` | `tool` |
| Handoff / delegate to sub-agent | `router` (R48-B `EffectTag` classification) |
| End of conversation (max turns / stop) | `end` |
| User-initiated fork | `fork` |

No schema extensions required. This is the same finding as the CrewAI adapter rollout (R52) — three adapters worth of convergence validate ADR-003's node vocabulary.

## 6. Usage extraction fit (ADR-015)

Anthropic's `Usage` dataclass has `input_tokens`, `output_tokens`, `cache_creation_input_tokens`, `cache_read_input_tokens`. The LangGraph extractor already handles these for `ChatAnthropic` LLM calls (the prompt-caching semantics noted in CONTEXT.md long-term invariants). The new adapter reuses the same Layer-4 extractor; no extractor ADR changes.

## 7. Release strategy

Arc B slice 1 is a **two-minor-version runway** under the release pattern (R52→R55 CrewAI precedent, R58→R60 N-run compare precedent):

- **v0.7.0a1** (R72) — alpha pre-release: recorder scaffold + duck-typed tests + a dogfood script. No fork primitive yet.
- **v0.7.0** (R74) — GA: recorder + fork primitive + live-smoke test + full dogfood. Cut after R73 proves fork works end-to-end on a real Claude agent.

Bundle shape follows R60 invariant: core R70 + scaffold R71 + live-smoke R72 (alpha) + fork R73 + proof+release R74. Five-round slice, larger than Arc A slice 4 (R62-R64 three-round) because live-smoke gating adds two rounds.

### 7.1 Rollout checklist (R69-R74)

- [ ] **R69** — ADR-026 Draft → Accepted after risks spike. MCP fork-lifecycle policy chosen (A vs B). Pydantic dep pin chosen (`claude-agent-sdk>=X.Y,<Z.0`).
- [ ] **R70** — `src/chronos/adapters/anthropic_agents/recorder.py` + protocol conformance tests. Duck-typed fixture only. Adapter `LangGraph/AutoGen/CrewAI` matrix extends to four.
- [ ] **R71** — live-smoke test `tests/live/test_anthropic_agents_smoke.py` with `CHRONOS_LIVE=1 + ANTHROPIC_AUTH_TOKEN` triple-skipif. Record one multi-turn conversation with one MCP tool; verify node count, kinds, usage.
- [ ] **R72** — `scripts/dogfood_anthropic_agents.py` + v0.7.0a1 alpha tag.
- [ ] **R73** — fork primitive impl + tests + live-smoke fork.
- [ ] **R74** — v0.7.0 release cut per `chronos-release-pattern` skill (14th application).

## 8. Risks

Three open risks (triaged by [R27 risks doc][risks] for multi-framework issues, three new here):

| # | Risk | Severity | Mitigation |
|---|---|---|---|
| R1 | MCP server state cannot be rewound cleanly during fork | **High** | R69 risks spike; if Policy B infeasible, fall back to Policy A (fresh server) and document "fork loses pre-fork MCP state" as a known limitation. |
| R2 | Anthropic Agents SDK breaking change between R68 and R74 | Medium | Pin version in R69 (`>=X.Y,<Z.0`); re-run live-smoke on every cron round. Precedent: CrewAI pin bump ADR-022 after R53. |
| R3 | Claude model deprecations during R69-R74 (e.g., Claude 3.5 retired) | Low | Use `claude-sonnet-4.7` (latest stable as of 2026-05). If deprecated, bump to successor; no API shape change expected within major. |

## 9. Open questions

Resolved in this doc:

- ✅ Which of the six candidates? → Anthropic Agents SDK; OpenAI Agents SDK hot-backup.
- ✅ How does the adapter fit ADR-003/ADR-015/ADR-016? → Cleanly, no revisions needed.

Deferred to R69 risks spike:

- ❓ MCP server fork-lifecycle policy (A vs B).
- ❓ Whether `agent.iter` or `agent.stream` is the better recorder entry point.
- ❓ Exact `claude-agent-sdk` version pin.

Deferred to R74 retro:

- ❓ Arc B slice 2 target (Pydantic AI vs Letta).
- ❓ Whether to promote [ADR-023][ADR-023] Arc B candidate table to `docs/research/adapter-4-survey.md` (R27-style artifact) — currently superseded by this doc.

## 10. Acceptance criteria (for v0.7.0)

- [ ] `AnthropicAgentsRecorder` conforms to `RecorderProtocol` and `AdapterProtocol` (protocol conformance tests green).
- [ ] `with recorder.record(...)` records all LLM + tool + handoff events to the store.
- [ ] `with recorder.fork(...)` re-invokes the agent from a given `at_node_id` with `overrides` applied.
- [ ] Live-smoke test passes with real Claude model + real MCP server.
- [ ] Dogfood script exits 0 with runtime assertions on the recorded node structure (release-gate per R64 invariant).
- [ ] `chronos tree`, `chronos compare --auto-pivot`, `chronos compare --matrix` all work over Anthropic Agents SDK runs (no adapter-specific branches needed — uniform UI).
- [ ] Adapter does NOT regress LangGraph/AutoGen/CrewAI adapters (R52→R74 adapter streak candidate — 22 rounds zero code change).

## 11. Changelog (from v0.6.0 to v0.7.0)

**Added** — `AnthropicAgentsRecorder`, `claude-agent-sdk` integration, live-smoke for Anthropic Agents SDK.
**Unchanged** — Adapter interface (ADR-016), node schema (ADR-003), extractor contract (ADR-015), all three prior adapters. **Zero breaking changes** (Arc B slice 1 is pure-additive).

## 12. References

- [ADR-001][ADR-001] · [ADR-003][ADR-003] · [ADR-015][ADR-015] · [ADR-016][ADR-016] · [ADR-023][ADR-023] · [ADR-026][ADR-026]
- [research] — `docs/research/r68-arc-b-scope.md`
- [risks] — `docs/research/risks.md`
- [n-run-compare] — `docs/design/n-run-compare.md` (Arc A precedent)
- [fork-tree-viz] — `docs/design/fork-tree-viz.md` (Arc A precedent)

[ADR-001]: ../decisions/ADR-001-language.md
[ADR-003]: ../decisions/ADR-003-sqlite-schema.md
[ADR-015]: ../decisions/ADR-015-extractor-contract-v2.md
[ADR-016]: ../decisions/ADR-016-adapter-interface.md
[ADR-023]: ../decisions/ADR-023-phase-4-charter-skeleton.md
[ADR-026]: ../decisions/ADR-026-arc-b-scope.md
[research]: ../research/r68-arc-b-scope.md
[risks]: ../research/risks.md
[n-run-compare]: n-run-compare.md
[fork-tree-viz]: fork-tree-viz.md

---

*Authored R68 (2026-05-13 CST). Pure design — feeds ADR-026 Draft. No code lands this round.*
