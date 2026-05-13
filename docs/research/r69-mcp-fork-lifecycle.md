# R69 — Anthropic Agents SDK risks spike: MCP fork-lifecycle, recorder entry point, version pin

**Round**: 69 (2026-05-13 CST, planning/research slot inside 0–11 window)
**Type**: Research, md-only, single-slot
**Depends on**: [ADR-026][ADR-026] (Draft, Arc B slice 1 scope), [r68-arc-b-scope][r68] (6-candidate survey)
**Feeds**: ADR-026 Draft → Accepted (this round, in-place per R57 invariant)

---

## 0. Purpose

ADR-026 §5 (Open questions) deferred three questions to the R69 risks spike before Draft → Accepted promotion:

1. **MCP server fork-lifecycle policy** — Policy A (fresh MCP server on fork) vs Policy B (session re-seed).
2. **Recorder entry point** — `agent.iter()` vs `agent.stream()` (names speculative in ADR-026).
3. **Version pin** — lower/upper bounds for `claude-agent-sdk`.

R69 resolves all three by reading the public `anthropics/claude-agent-sdk-python` source (clone via `gh-proxy.com`, no install, no live API). No production dependency added; no code changes to `chronos-agent` this round.

The headline finding is: **the SDK already ships a first-class `fork_session()` primitive** (stable since 0.1.x). This collapses the MCP fork-lifecycle question from "design a new mechanism" to "wire the existing mechanism". The three questions are answerable in one round.

---

## 1. Spike #1 — MCP fork-lifecycle policy

### 1.1 Finding: `fork_session()` is first-class in the SDK

Source: `src/claude_agent_sdk/_internal/session_mutations.py:240-345` in `anthropics/claude-agent-sdk-python@0.1.81`.

Signature:

```python
def fork_session(
    session_id: str,
    directory: str | None = None,
    up_to_message_id: str | None = None,
    title: str | None = None,
) -> ForkSessionResult:
    """Fork a session into a new branch with fresh UUIDs."""
```

Key behaviour (paraphrased from the docstring + implementation):

- Copies transcript JSONL entries from the source session, **remapping every message UUID** and preserving the `parentUuid` chain.
- `up_to_message_id` slices the transcript inclusively at a specific message — this is the "at_node_id" semantics we need for `ForkProtocol.fork(at_node_id=...)`.
- Sidechains (subagent sessions) are filtered out of the copy; the main chain carries through. Progress messages (UI-only chain links) are mapped for parent-chain resolution but not written to the fork output.
- Creates the new `.jsonl` file atomically (`O_WRONLY | O_CREAT | O_EXCL`, mode 0600) — no partial-fork state on disk.
- Returns `ForkSessionResult(session_id=<new_uuid>)`. The caller is expected to resume from that session_id on the next `query()` / `ClaudeSDKClient` connect.

Async variant: `fork_session_via_store()` (line 885) is available for `SessionStore`-backed setups (0.1.71 introduced the `SessionStore` protocol + `InMemorySessionStore` reference implementation — see CHANGELOG:184).

### 1.2 What does the MCP server actually do during fork?

**It doesn't do anything, because fork never touches it.** `session_mutations.py` has **zero** references to MCP. Fork is a pure filesystem transform on the transcript JSONL. When you next `query()` or `ClaudeSDKClient().connect()` resuming the forked session_id, the CLI (and therefore the MCP server subprocesses it manages) starts fresh with the forked transcript as context.

This collapses ADR-026 §4's "Policy A vs Policy B" dichotomy entirely:

- There is no **stateful MCP session** attached to a `session_id` at the SDK layer. MCP servers are per-CLI-process, not per-session. Each `ClaudeSDKClient` connection spawns a fresh CLI subprocess (`subprocess_cli.py`), and the MCP servers it manages are bound to that subprocess lifetime.
- Fork creates a new `session_id`. When the parent Chronos adapter resumes that new session, the CLI and its MCP servers are **either** re-used (if the same `ClaudeSDKClient` is still alive — the resume attaches the forked transcript as the new active session) **or** fresh (if a new client is created). Both are acceptable.

### 1.3 Decision — Policy A (implicit fresh server) wins by default

The dichotomy dissolves. **The adapter uses the SDK's native `fork_session()`**; whichever policy the SDK/CLI uses for MCP is the policy Chronos uses. That's effectively Policy A ("MCP servers start fresh after fork") from ADR-026's framing, but there's no additional code or configuration on the Chronos side.

Consequences:

- ✅ **Fallback clause not triggered.** ADR-026 §4 §Fallback requires all three criteria; #1 (Policy B infeasible) and #2 (Policy A degrades value prop) both fail to hold because Policy A is the SDK-native path and there's no value-prop degradation we can measure at this layer. The R68 pre-authorisation stays dormant; the scope-commit ADR gets cleanly Accepted.
- ✅ **Arc B slice 1 ships on primary target.** No swap to OpenAI Agents SDK needed. OpenAI Agents SDK stays reserved for Arc B slice 2+ (or slice 1 rollback if R70+ surprises us).
- ⚠️ **Documentation note**: if the user's MCP server holds meaningful out-of-band state (e.g., a database write, a GitHub issue created via an MCP GitHub tool), **that state is real-world-side-effect** and fork cannot unring it. This is a generic Chronos invariant, not an MCP-specific one — forks replay prompts + tool *results*; real side effects at tool execution time are not reversible. Document in the R70 adapter README + the fourth-adapter design doc.

### 1.4 What about `update_state(as_node=...)` equivalent?

LangGraph's fork primitive (ADR-017 era, LangGraphAdapter) uses `update_state(as_node=...) + invoke(None)` to inject state mutations at a specific node. The Anthropic SDK analogue is:

- **Slice at node**: `fork_session(..., up_to_message_id=<target_msg_uuid>)` — cut the transcript at the fork point.
- **Mutate at node**: the Chronos adapter can edit the last `UserMessage` or `AssistantMessage` *before* writing the fork file (the SDK's `_build_fork_lines()` is internal; we'd either submit a PR upstream or implement our own JSONL rewrite). **Preference**: extend the SDK via PR if needed; otherwise wrap `fork_session()` with a post-step that rewrites the last message in the forked JSONL file before resume.

For R70 slice 1 (record-only, no fork primitive), this question is deferred. Fork primitive lands in **R73**. R73 will decide PR-upstream vs local JSONL rewrite. Annotate in ADR-026 Consequences.

### 1.5 Mapping to ADR-003 `NodeKind`

Unchanged from [fourth-adapter-landscape][fourth-adapter] §5. Reconfirmed by R69 source inspection:

| SDK `Message` subclass | ADR-003 `NodeKind` | Notes |
|---|---|---|
| `UserMessage` | `llm` (prompt input) | `content` is `str` or `list[ContentBlock]`; `uuid` and `parent_tool_use_id` available |
| `AssistantMessage` | `llm` (model output) | Contains `content: list[ContentBlock]`; `usage` dict populated; `model` + `session_id` + `uuid` available for recorder dedup |
| `ToolUseBlock` (inside `AssistantMessage.content`) | `tool` (invocation) | `id`, `name`, `input: dict` — clean tool-call shape |
| `ToolResultBlock` (inside `UserMessage.content`) | `tool` (return) | `tool_use_id` threads to the invocation; `is_error` surfaces error classification |
| `SystemMessage`, `ResultMessage` | `end` or discarded | `ResultMessage` has `total_cost_usd`, `usage`, `duration_ms` — surface usage extraction |
| Handoffs (subagent invocation via sidechain) | `router` | Out of slice 1 scope; Arc B slice 2+ |
| Explicit fork via `fork_session` | `fork` | Chronos adapter emits this synthetically on `ForkProtocol.fork()` call |
| Stop (end of conversation) | `end` | From `ResultMessage` with `stop_reason` |

All six `NodeKind` values covered. **Zero ADR-003 / ADR-015 / ADR-016 revisions required** — this matches the R68 design doc claim.

---

## 2. Spike #2 — Recorder entry point

ADR-026 §5 Q2 speculated two names: `agent.iter()` vs `agent.stream()`. **Neither exists.** The SDK does not have an "Agent" object with `.iter()` or `.stream()` methods. The actual public API has two entry points:

### 2.1 `query(*, prompt, options, transport) -> AsyncIterator[Message]`

Source: `src/claude_agent_sdk/query.py:11-80`.

- Fire-and-forget async generator yielding `Message` subclasses.
- Stateless: each `query()` is an independent session.
- Ideal for CI/automation, code generation, single-turn tasks.
- **Chronos mapping**: perfect for `record(...)` on short-lived tasks. Simple async-for loop gives us every `Message` in order with `session_id`, `uuid`, `parent_tool_use_id` on the dataclasses. No monkeypatching required.

### 2.2 `ClaudeSDKClient` — stateful multi-turn

Source: `src/claude_agent_sdk/client.py:83-628`. Key methods:

- `async with ClaudeSDKClient(options=...) as client: ...` — context manager owns the CLI subprocess lifecycle.
- `await client.query(prompt)` — send a user message.
- `async for msg in client.receive_response()` — async-iterate messages for the *current* turn (ends at the next `ResultMessage`).
- `async for msg in client.receive_messages()` — open-ended stream (use for multi-turn observation).
- `await client.interrupt()` — abort the current task.
- `await client.rewind_files(user_message_id=...)` — file-undo for edit sessions (not our concern in slice 1).

**Chronos mapping**: the `Recorder` wraps the client's `receive_response()` (or `receive_messages()`) iterator and logs each `Message` to the store. Shape mirrors the CrewAI event-bus recorder (ADR-021) and the LangGraph callback recorder: "observe the stream, write nodes to SqliteStore, exit when the stream ends."

### 2.3 Decision — use **both**, gated by caller

ADR-026's original question was a false binary. The adapter provides **two record modes**:

1. **`AnthropicAgentsRecorder.record_query(prompt, options, ...)`** — wraps `query()`. Context-manager yields `RunRef`; internally iterates the generator. Use case: scripted single-turn tasks.
2. **`AnthropicAgentsRecorder.record_client(client, *, thread_id, ...)`** — takes an already-connected `ClaudeSDKClient`, attaches to its `receive_messages()` stream for the lifetime of the context-manager. Use case: interactive / multi-turn applications.

Both modes share the same `Message → Node` translator (internal), and both use the same `SqliteStore` write path.

**Simpler alternative** (deferred to R70 implementation): ship **only `record_client`** in slice 1 and document `query()` as "wrap it in a `ClaudeSDKClient`-like shim if you need single-turn recording" — or provide a thin helper `record_query` in R72+ if user demand surfaces. R70 decides based on implementation ergonomics. This is a rollout-ordering choice, not a design-shape choice.

Either way, the recorder entry point is **the `Message` async iterator**, not a speculative `agent.iter/stream`. ADR-026 §Decision §1 Event-capture pattern line ("Async event stream iteration (no monkeypatch)") stays correct verbatim; §5 Q2 is resolved.

---

## 3. Spike #3 — Version pin

### 3.1 PyPI snapshot (2026-05-13)

```
curl -s https://pypi.org/pypi/claude-agent-sdk/json | jq '.info.version, (.releases|keys|length)'
# latest: 0.1.81
# total_releases: 83
```

All 83 releases are in the 0.1.x line. Most recent ten (as of R69): 0.1.72 → 0.1.81 (shipped within weeks per CHANGELOG cadence — roughly one release per week, mostly bundled-CLI bumps).

`pyproject.toml` in upstream repo declares `Development Status :: 3 - Alpha`, `requires-python = ">=3.10"`, deps: `anyio>=4.0.0`, `sniffio>=1.0.0`, `mcp>=1.19.0`. Chronos targets Python 3.11+ (ADR-001) so the dep is compatible.

### 3.2 Pin strategy

Options (per ADR-022 CrewAI pin precedent):

- **(a)** Narrow floor, narrow ceiling: `>=0.1.81,<0.2.0`. Pros: tight reproducibility. Cons: 0.1.x cadence is weekly; users on `0.1.83` released tomorrow would hit our ceiling, forcing Chronos to re-pin reactively.
- **(b)** Current-minor floor, next-major ceiling: `>=0.1.80,<1.0`. Pros: absorbs the weekly 0.1.x patch stream; only breaks on 1.0.0 (semver major). Cons: 0.1.x being an **alpha** line means breaking changes are technically allowed mid-minor; but ADR-022 already accepted this trade-off for CrewAI (`>=0.80,<2.0` when CrewAI was also in rapid-iteration mode).
- **(c)** Wide: `>=0.1.70`. Pros: maximum compat. Cons: `fork_session()` shipped per CHANGELOG in "Session management" commit (line 306) somewhere around 0.1.40-0.1.50 era; pinning too low lets users hit `AttributeError: no attribute 'fork_session'`.

### 3.3 Decision — Option (b), `claude-agent-sdk>=0.1.80,<1.0`

Rationale:

- `0.1.80` and `0.1.81` both contain `fork_session()` + `fork_session_via_store()` + `SessionStore` protocol (required for R73). `0.1.80` is chosen over `0.1.81` as the floor so users with one-week-old installs aren't forced to upgrade to pick up Chronos.
- `<1.0` ceiling matches ADR-022 pattern: we expect 1.0.0 to carry breaking-change semantics (project is explicitly pre-1.0), at which point Chronos re-evaluates.
- Optional dep per ADR-016 convention: goes in `pyproject.toml::[project.optional-dependencies].anthropic_agents`, not core deps. Live-smoke test guards with triple-skipif per the R59/R60 pattern (`CHRONOS_LIVE` + `ANTHROPIC_API_KEY` / auth equivalent + SDK import guard).

### 3.4 Secondary dep: Node.js CLI bundled

The SDK bundles a Node.js-based Claude Code CLI (`src/claude_agent_sdk/_bundled/`). Live-smoke tests will fail in CI without Node installed. This is an **R71 live-smoke concern**, not a pin concern. Document in the R70 README + add a `docs/adapters/anthropic_agents.md` note + the R71 live-smoke skipif checks `shutil.which("node")` alongside the SDK import.

---

## 4. Updated Open-Questions table (for ADR-026 §5 rewrite)

| ID | Original question | R69 resolution |
|---|---|---|
| Q1 | MCP fork-lifecycle Policy A vs B | Dissolved — SDK's `fork_session()` handles transcript-level fork; MCP servers are per-CLI-process, not per-session; effective Policy A with zero Chronos-side code. Fallback clause stays dormant (criteria not met). |
| Q2 | Recorder entry `agent.iter` vs `agent.stream` | False binary — both names speculative. Real API: `query()` async generator + `ClaudeSDKClient.receive_response()/receive_messages()`. Adapter wraps the async iterator pattern (same as LangGraph callbacks, same as CrewAI event bus). R70 picks `record_client` first; `record_query` helper deferred to R72+ if demand. |
| Q3 | Version pin | `claude-agent-sdk>=0.1.80,<1.0`, optional dep, live-smoke skipif `shutil.which("node")` + SDK import + `CHRONOS_LIVE`. |

All three questions answered. ADR-026 can flip Draft → Accepted this round.

---

## 5. Side findings (not in original questions)

### 5.1 SDK `SessionStore` protocol aligns with Chronos adapter injection pattern

The SDK 0.1.71 `SessionStore` protocol (5 methods: `append`, `load`, `list_sessions`, `delete`, `list_subkeys`) is orthogonal to Chronos's `SqliteStore`. R70 will **not** wrap `SqliteStore` as a `SessionStore` — that's a cross-layer confusion (SDK sessions hold raw JSONL transcripts; Chronos nodes are an abstraction layer above that). Instead: adapter writes SDK messages → Chronos node translator → `SqliteStore` (same pattern as LangGraph recorder). Flagging here so R70 doesn't go down the wrong path.

### 5.2 `fork_session` message-UUID remapping is lossy for Chronos diff

`fork_session()` assigns fresh UUIDs on every transcript entry in the fork. This is **correct** for the SDK (forks must have unique IDs) but is **lossy** for Chronos diff: we want to recognise "this assistant message in the fork is derived from that assistant message in the parent". Mitigation: the Chronos adapter records a `(original_uuid → forked_uuid)` mapping at fork time (available via `_build_fork_lines()` internal, or re-derived by diffing source and fork transcripts) and persists it as fork metadata. R73 concern; note for future ADR.

### 5.3 `StreamEvent` (partial-message streaming) optional

The SDK has `StreamEvent` for partial-message delta streaming (enabled by `ClaudeAgentOptions.include_partial_messages=True`). Default is off. Chronos adapter slice 1 **opts out** — we only record complete messages (`AssistantMessage`, `UserMessage`, `ResultMessage`). Partial-event streaming is a future Arc B slice 3+ feature if demand surfaces.

### 5.4 `McpServerConnectionStatus` and `get_mcp_status()` exist

`client.get_mcp_status()` returns `McpStatusResponse` with per-server connection status. Useful for adapter diagnostics but not a slice-1 blocker. Surface as "advanced debugging" in the README, not in the core recorder API.

---

## 6. Verdict

**Anthropic Agents SDK is clear for primary binding.** All three R69 risks resolve to "the SDK already solved it; wire it in". ADR-026 promotes Draft → Accepted in-place this round. Fallback clause (§4) stays on paper as insurance; no trigger.

R70 (next round) begins core adapter scaffold: `src/chronos/adapters/anthropic_agents/` module path, `AnthropicAgentsRecorder.record_client(...)` as primary entry, duck-typed conformance tests. `claude-agent-sdk` enters `pyproject.toml::[project.optional-dependencies].anthropic_agents` as `claude-agent-sdk>=0.1.80,<1.0`. No live LLM calls in R70; R71 for live-smoke.

Adapter streak: R52→R69 = **18 rounds** of zero adapter code change (LangGraph + AutoGen + CrewAI all untouched). R70 breaks the streak by adding a new adapter module — not a regression, an additive fourth adapter.

---

## 7. Artefact manifest

- `docs/research/r69-mcp-fork-lifecycle.md` — this doc (~9 KB).
- `docs/decisions/ADR-026-arc-b-scope.md` — Status `Draft` → `Accepted` in-place; §5 Open-questions rewritten with R69 resolutions; §Decision §4 Fallback marked "dormant — criteria not met R69"; §1 version pin crystallised to `>=0.1.80,<1.0`; footer R68→R69 with evidence pointer.
- `docs/roadmap.md` — header `Last updated` R68 → R69; §4.2 Arc B slice 1 line ADR-026 `(R68 Draft)` → `(R69 Accepted)`.

No code changes. No `pyproject.toml` edits (R70 adds the optional dep). No `CHANGELOG.md` edits (only user-visible changes go there; ADR promotion is internal).

---

[ADR-026]: ../decisions/ADR-026-arc-b-scope.md
[r68]: r68-arc-b-scope.md
[fourth-adapter]: ../design/fourth-adapter-landscape.md

*Authored R69 (2026-05-13 CST, single-slot planning/research round). Feeds ADR-026 Draft → Accepted this round. No live LLM call; findings derived from source inspection of `anthropics/claude-agent-sdk-python@0.1.81` cloned via gh-proxy.com.*
