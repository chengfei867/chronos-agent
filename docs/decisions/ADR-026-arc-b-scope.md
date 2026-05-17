# ADR-026: Arc B Scope — Fourth Adapter is Anthropic Agents SDK (Accepted)

**Status**: Accepted (R69, 2026-05-13 — promoted in-place from R68 Draft per R57 invariant; R75 amendment §5 codifies inter-method `state_after` contract)
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

### 5. Inter-method contract — `state_after` seed coordinates (R75 amendment)

The Anthropic Agents adapter's `record()` and `fork()` are joined by an
**implicit contract** on the shape of `Node.state_after`. R74 implemented
`fork()` against a contract that R70's `record()` happened to honour;
this amendment makes the contract **explicit** so future refactors of
either method cannot silently break the other.

#### Contract (binding from R75 onwards)

When `AnthropicAgentsRecorder.record()` consumes an `AssistantMessage`
or `ResultMessage` from the SDK message stream, it **MUST** stamp the
following keys onto the resulting `Node.state_after` dict whenever the
upstream message exposes them as non-None attributes:

| Key | Source | Used by |
|---|---|---|
| `uuid` | `msg.uuid` | `fork()` as `up_to_message_id` anchor |
| `session_id` | `msg.session_id` | `fork()` as parent SDK session anchor |
| `stop_reason` | `msg.stop_reason` | observability only (no fork dependency) |
| `total_cost_usd` | `msg.total_cost_usd` | observability only |
| `duration_ms` | `msg.duration_ms` | observability only |

Of these, **`uuid` and `session_id` are the fork-critical pair**. If
either is missing on the anchor node passed to `fork()`, the adapter
raises `AdapterError("no SDK session_id …")` / `("no SDK message uuid
…")`. `record()` MUST NOT silently drop them when the SDK exposes them.

#### Why "MUST" and not "SHOULD"

R74 P0 probe disproved an R71 assumption that `fork_session()` required
internal-API hooks; the actual integration was trivial because R70's
`record()` had already (incidentally) captured the right seed
coordinates. That was a happy accident. Codifying this now turns the
accident into a contract — the next round that touches `record()` will
see this section and not regress the field set.

#### Test enforcement

Two unit tests in `tests/unit/test_adapter_anthropic_agents.py` enforce
this contract independently of the fork tests:

- `test_record_state_after_carries_seed_coordinates_for_assistant` — an
  `AssistantMessage` with `uuid` + `session_id` populated on the SDK
  side must produce a `Node` with both keys in `state_after`.
- `test_record_state_after_carries_seed_coordinates_for_result` — same
  assertion for `ResultMessage`.

If a future refactor narrows the loop on lines 304-308 of `recorder.py`
(e.g., removes `session_id` from the metadata-stamping list), these
tests fail loudly **before** the fork integration tests do — preserving
the R74 invariant: "no release-gating contract left untested between
methods of the same module."

#### Out of scope for this contract

- `UserMessage` / `SystemMessage` are explicitly **NOT** required to
  carry `uuid` + `session_id` (the SDK does not stamp them on those
  message classes pre-`AssistantMessage`); `fork()` correctly rejects
  attempting to anchor on such nodes (`test_fork_rejects_anchor_without_session_id`).
- The remaining three observability-only keys (`stop_reason`,
  `total_cost_usd`, `duration_ms`) are not part of the fork contract;
  they MAY be removed without ADR amendment if a future SDK version
  drops them upstream.

### 5.1 Tool round-trip linkage — `state_after.tool_use_id` (R76 amendment, slice 3a)

Slice 3 of the Arc B v0.7.0 cut needs cross-Node SQL queries answering
"which assistant tool-use Node generated this tool-result Node?". The
underlying SDK already gives us the linkage: `ToolUseBlock.id` on the
`AssistantMessage` side, `ToolResultBlock.tool_use_id` on the matching
`UserMessage` side, byte-identical by SDK contract.

R76 surfaces that linkage onto `Node.state_after['tool_use_id']`
**symmetrically on both sides**. This is a public contract pin (not a
schema change — `state_after` is a JSON bag — but a binding promise the
recorder will not silently drop).

#### Contract (binding from R76 onwards)

For every `Node` recorded by `AnthropicAgentsRecorder`:

- If the `Node` is an `AssistantMessage` whose `content` carries
  **exactly one** `ToolUseBlock`, then `state_after['tool_use_id']` MUST
  equal that `ToolUseBlock.id` (a non-empty string), provided the SDK
  populates `id` (defended with `isinstance(..., str) and id`).
- If the `Node` is a `UserMessage` whose `content` carries **exactly
  one** `ToolResultBlock`, then `state_after['tool_use_id']` MUST equal
  that `ToolResultBlock.tool_use_id` under the same guard.
- A pair of linked Nodes (one tool-use, one tool-result) MUST yield
  byte-identical values for `state_after['tool_use_id']` — this is the
  JOIN key for slice-3 queries.
- A `UserMessage` carrying an **orphan** `ToolResultBlock` (no preceding
  `AssistantMessage(ToolUseBlock)` with matching id, e.g. a resumed /
  forked session entry) MUST NOT cause `record()` to fail; the result
  Node still surfaces `state_after['tool_use_id']` and downstream
  consumers detect the orphan via empty JOIN result. Asymmetric
  tolerance: missing anchor is observability loss, not a record()
  failure.

#### Test enforcement

Three unit tests in `tests/unit/test_adapter_anthropic_agents.py` §6.2
pin this contract:

- `test_record_tool_use_block_persists_id` — use side
- `test_record_tool_result_block_links_to_use` — both sides + JOIN equality
- `test_unmatched_tool_result_does_not_break_record` — orphan tolerance

Any future change to the `state_after` stamping logic that breaks these
tests is an ADR-026 §5.1 contract violation and requires either a new
amendment or an explicit ADR superseding §5.1.

#### Out of scope for §5.1

- Multi-block messages (>1 `ToolUseBlock` or >1 `ToolResultBlock` in a
  single message) do NOT receive a top-level singular `tool_use_id` —
  resolved by §5.1.1 below (R77, slice 3a-P1) which surfaces an ordered
  `tool_use_ids` (plural) list instead. Singular and plural fields are
  mutually exclusive per Node.
- No new column / no sidecar / no Node graph edge — the JSON-bag
  approach is sufficient for slice-3 SQL queries
  (`state_after->>'tool_use_id'`).

### 5.1.1 Multi-block tool linkage — `state_after.tool_use_ids` (R77 amendment, slice 3a-P1)

§5.1 covers the 1:1 single-block case. R77 extends the contract to
multi-block messages — an `AssistantMessage` carrying >1 `ToolUseBlock`
(batched parallel tool dispatch) or a `UserMessage` carrying >1
`ToolResultBlock` (paired results). The SDK preserves block order, so
the linkage is unambiguous: `use[i] ↔ result[i]` by index across the
two messages.

#### Contract (binding from R77 onwards)

For every `Node` recorded by `AnthropicAgentsRecorder`:

- If the `Node` is an `AssistantMessage` whose `content` carries
  **more than one** `ToolUseBlock`, then `state_after['tool_use_ids']`
  MUST be a list of `ToolUseBlock.id` values **in source block order**
  (NOT sorted, NOT deduplicated), filtered by the same defensive guard
  (`isinstance(..., str) and id`) used in §5.1. If all ids are filtered
  out, the key is omitted (parallels §5.1's missing-anchor tolerance).
- If the `Node` is a `UserMessage` whose `content` carries **more than
  one** `ToolResultBlock`, then `state_after['tool_use_ids']` MUST be a
  list of `ToolResultBlock.tool_use_id` values in source block order
  under the same guard.
- A pair of linked Nodes (one multi-tool-use, one multi-tool-result)
  MUST yield byte-identical `state_after['tool_use_ids']` lists — this
  is the JOIN keyset for slice-3 queries expanding 1:N via
  `json_each(state_after->>'tool_use_ids')`.
- **Mutual exclusivity (binding):** singular `state_after['tool_use_id']`
  (§5.1) and plural `state_after['tool_use_ids']` (§5.1.1) MUST NEVER
  coexist on the same Node. `len == 1 → singular only`;
  `len > 1 → plural only`. This guarantees consumers can branch
  unambiguously and SQL `COALESCE` patterns work without de-dup.

#### Test enforcement

Three unit tests in `tests/unit/test_adapter_anthropic_agents.py`
§6.2.1 pin this contract:

- `test_record_multi_tool_use_block_persists_ids` — use side, plural
  set, singular absent
- `test_record_multi_tool_result_block_persists_ids` — both sides plural
  + byte-identical JOIN keyset
- `test_record_mixed_count_keeps_singular_and_plural_separate` — stream
  mixing single-block and multi-block messages keeps the two contracts
  cleanly separate per Node (regression guard against future collapse)

#### Consumer pattern (slice 3 SQL)

Linked-Node JOIN expands cleanly with `json_each` regardless of
block-count cardinality:

```sql
-- Pair single-block use with single-block result
SELECT u.id AS use_node, r.id AS result_node
FROM nodes u JOIN nodes r
  ON u.state_after->>'tool_use_id' = r.state_after->>'tool_use_id'
WHERE u.state_after->>'tool_use_id' IS NOT NULL;

-- Pair multi-block use[i] with multi-block result[i]
SELECT u.id AS use_node, r.id AS result_node, ju.value AS tu_id
FROM nodes u, json_each(u.state_after->>'tool_use_ids') ju
JOIN nodes r, json_each(r.state_after->>'tool_use_ids') jr
  ON ju.value = jr.value AND ju.key = jr.key  -- index-aligned pair
WHERE u.node_name LIKE 'AssistantMessage%' AND r.node_name = 'UserMessage';
```

#### Out of scope for §5.1.1

- Asymmetric block counts (e.g. 3 ToolUseBlocks but 2 ToolResultBlocks
  in the next UserMessage) — the per-Node contract still holds (each
  side carries its own ordered list); cross-message asymmetry is
  surfaced as a JOIN gap, same as the §5.1 orphan case. No special
  handling at recorder level.
- Cross-turn batching (one Assistant batched-use spanning multiple
  subsequent UserMessage results) — not observed in current SDK
  traffic; reserved for a future slice if it materialises.

### 5.2 Fork-with-tool-substitution contract (R79 amendment, slice 3b)

**Status: Implemented (R80).** Sibling §5.3 (R81 amendment, slice 3c) extends this contract to result-side substitution.

Slice 3a (R76 §5.1 + R77 §5.1.1) gave us *anchors* for the tool-use ↔
tool-result round-trip. Slice 3b is what those anchors are *for*:
fork a recorded run at a specific node and **rewrite the tool input**
that the child branch will see, before the agent reasons again.

This is the load-bearing user story for "agent time-travel debugger" —
the user spotted a bad tool call mid-run, wants to rewind, change the
input, and watch how downstream reasoning diverges. Without §5.2 the
fork primitive can only re-issue an *unedited* transcript (R74).

#### Contract

`AnthropicAgentsRecorder.fork()` gains one optional keyword argument:

```python
def fork(
    self,
    runtime: Any,
    *,
    parent_run_id: str,
    at_node_id: str,
    overrides: dict[str, Any] | None = None,
    tool_input_overrides: dict[str, dict[str, Any]] | None = None,  # NEW
    child_thread_id: str,
    reason: str | None = None,
    task_description: str | None = None,
    tags: list[str] | None = None,
) -> Iterator[ForkRef]:
```

`tool_input_overrides` is a mapping `tool_use_id → new_input_dict`:

- **Key**: a `tool_use_id` string. MUST already exist in the parent run's
  use-side keyset (i.e. some `AssistantMessage*` Node in `parent_run_id`
  declares it via `state_after['tool_use_id']` (R76 §5.1) or as an
  element of `state_after['tool_use_ids']` (R77 §5.1.1)).
- **Value**: a JSON-serialisable dict to substitute as the
  `ToolUseBlock.input` payload in the child branch when that block is
  re-emitted.

Both singular (1:1) and plural (1:N) §5.1 / §5.1.1 anchors are valid
keys — slice 3b is per-id granular, NOT per-Node. Replacing a single
element of a multi-block `tool_use_ids` list while leaving siblings
verbatim is supported and is the primary debugging workflow.

`tool_input_overrides=None` (default) and `tool_input_overrides={}`
(empty mapping) are both **identity** forks — semantically equivalent
to R74 fork() with no §5.2 surface. This keeps R74 callers source-stable.

#### Stamp on child Nodes

When the child branch's first AssistantMessage Node carrying an
overridden `ToolUseBlock` is recorded:

- `state_after['tool_use_id']` (or matching list element of
  `state_after['tool_use_ids']`) — **unchanged** from parent. The
  binding contract for the JOIN anchor is preserved across the fork.
- `state_after['tool_input']` — **new**, set to the substituted input
  dict. Absent on Nodes that did NOT have their input rewritten (so
  consumers can `WHERE state_after->>'tool_input' IS NOT NULL` to
  enumerate substituted calls in a child run).

For multi-block messages where only some `tool_use_ids` were
overridden, `state_after['tool_input']` is a list aligned by index
with `tool_use_ids`, with `null` entries for verbatim blocks.

#### Validation (fail-fast, no silent drop)

`fork()` MUST raise `AdapterError` *before* delegating to
`claude_agent_sdk.fork_session()` if any key in `tool_input_overrides`:

1. Is not a string, or
2. Does not appear in the union of tool-use ids declared by any
   `AssistantMessage*` Node in `parent_run_id`'s use-side keyset
   (`_ids_from_state_after` over `_is_use_side` Nodes — same shape as
   `chronos.queries.tool_linkage._ids_from_state_after`), or
3. Refers to a `tool_use_id` that is *orphan on the use side* (i.e.
   appears in `chronos.queries.tool_linkage.unmatched_tool_uses(store,
   parent_run_id)` — the use side has no matching result yet so
   replaying past it is a category error). Slice 3b pre-condition:
   the use→result round-trip must have *closed* in the parent run.

Validation 3 is the load-bearing slice-3a→slice-3b coupling: R78's
`unmatched_tool_uses` helper exists *for this check*. Consumers who
want to fork mid-tool-call must wait for the result Node first or use
a different primitive.

The substituted `value` payload is validated for JSON-serialisability
only (no schema match against the original tool's input shape — that
is the agent's / tool server's responsibility).

#### Test enforcement

R79 lands four `pytest.mark.xfail(strict=True, reason="slice 3b — R80")`
tests in `tests/unit/test_anthropic_agents_fork_tool_override.py`:

1. `test_fork_without_overrides_is_identity` — `tool_input_overrides=
   None` and `={}` produce a child run byte-identical to R74 fork().
2. `test_fork_with_override_changes_downstream_input` — given a
   recorded parent with one `ToolUseBlock` keyed by `tool_use_id="t1"`,
   `fork(..., tool_input_overrides={"t1": {"x": 99}})` produces a
   child run whose first AssistantMessage Node has
   `state_after['tool_input'] == {"x": 99}` and unchanged
   `state_after['tool_use_id'] == "t1"`.
3. `test_fork_with_override_of_unknown_id_raises` — overriding a
   `tool_use_id` absent from the parent's use-side keyset raises
   `AdapterError` *before* the SDK call.
4. `test_fork_with_override_of_orphan_use_id_raises` — overriding a
   `tool_use_id` returned by `unmatched_tool_uses(store, parent_run_id)`
   raises `AdapterError` (slice-3a→3b coupling pre-condition).

Strict-xfail makes R80 implementation a forcing function: when the
implementation lands, every test flips to passing → strict-xfail
fires → R80 round agent removes the markers as part of the same
commit.

R79 may optionally land a no-op pass-through in `recorder.py` — accept
the kwarg, raise `NotImplementedError("R80: §5.2 slice 3b not yet
implemented")` when non-empty — so the tests fail with
`NotImplementedError` rather than `TypeError: unexpected keyword
argument`, narrowing R80's diff to a single function body.

#### Consumer SQL pattern

Once R80 ships, a consumer (dashboard / CLI / dogfood script) can
enumerate substituted tool calls in a child run with:

```sql
SELECT n.id, n.step_index, json_extract(n.state_after, '$.tool_use_id') AS tu_id,
       json_extract(n.state_after, '$.tool_input')  AS new_input
FROM nodes n
WHERE n.run_id = :child_run_id
  AND json_extract(n.state_after, '$.tool_input') IS NOT NULL
ORDER BY n.step_index;
```

Plural form for multi-block child Nodes:

```sql
SELECT n.id, n.step_index, je.value AS tu_id, ji.value AS new_input
FROM nodes n,
     json_each(n.state_after, '$.tool_use_ids') je,
     json_each(n.state_after, '$.tool_input')   ji
WHERE n.run_id = :child_run_id
  AND je.key = ji.key             -- index-aligned per §5.1.1
  AND ji.value IS NOT NULL
ORDER BY n.step_index, je.key;
```

#### Out of scope for §5.2

- Substituting `ToolResultBlock.content` (i.e. faking a tool's
  *output* without invoking the real tool). Reserved for slice 3c +
  ADR-026 §5.3 (MCP passthrough scoping). §5.2 only edits *inputs*;
  the agent and tool server still execute normally.
- Multi-step substitutions across more than one Node in the same fork
  call — supported (the mapping is keyset-wide), but consumers should
  prefer one fork-per-edit for cleaner debugging trees.
- HTTP / CLI surface — `tool_input_overrides` lands on the recorder
  Python API only in R80. CLI wiring is a separate slice (3d?).
- `chronos.queries.tool_linkage` promotion to a public API. Slice 3b
  uses it internally for validation; the package stays internal until
  a dedicated ADR formalises consumer-facing query helpers.

### 5.3 Fork-with-tool-result-substitution contract (R81 amendment, slice 3c)

**Status: Implemented (R82).**

Slice 3b (R80 §5.2) gave the user time-travel power on the **input** half
of the tool round-trip: rewrite what the agent *asks* the tool. Slice 3c
is the symmetric mirror on the **output** half: rewrite what the agent
*gets back* from the tool, without re-invoking the real tool. This is
the second load-bearing user story for the time-travel debugger — "the
real tool is non-deterministic / expensive / no longer reachable; replay
the agent's reasoning under a hypothetical tool result."

§5.2 and §5.3 are sibling-extensions, not supersessions: a single
`fork()` call MAY carry both `tool_input_overrides` and
`tool_result_overrides` simultaneously (orthogonal keyspaces — use-side
vs result-side). The two override mappings touch disjoint Node sides and
disjoint `state_after` keys.

#### Contract

`AnthropicAgentsRecorder.fork()` gains one further optional keyword:

```python
def fork(
    self,
    runtime: Any,
    *,
    parent_run_id: str,
    at_node_id: str,
    child_thread_id: str,
    task_description: str,
    tool_input_overrides: dict[str, dict[str, Any]] | None = None,  # §5.2
    tool_result_overrides: dict[str, Any] | None = None,            # §5.3 NEW
) -> Iterator[ForkRef]: ...
```

- **Key**: `tool_use_id` (the same JOIN anchor §5.1 / §5.1.1 stamp on
  both sides). The mapping selects *which* tool round-trip to rewrite
  the result for; the value supplies the substitute payload.
- **Value**: an arbitrary JSON-serialisable Python object — typically
  a `str` (Anthropic's most common `ToolResultBlock.content` shape) or
  a list of content blocks (`[{"type": "text", "text": "..."}]`). The
  recorder does not interpret the value beyond persistence; downstream
  the SDK / agent code surfaces it verbatim.
- **Identity semantics**: `None` and `{}` are both pure no-ops —
  byte-identical to a §5.2-only / R74-only fork. Empty mapping does
  *not* trigger any new code path; it short-circuits at the same `is
  None`-style guard the R80 §5.2 implementation uses for its own
  overrides (see `recorder.py:867`, `self._fork_overrides = ... or
  None`).

#### Validation (mirrors §5.2; runs *before* the SDK call)

When `tool_result_overrides` is non-empty, the recorder validates each
key fail-fast. Errors are raised synchronously as `AdapterError`
(consistent with §5.2 #1-#3) and the SDK fork is never invoked.

1. **Key-type**: key must be `str`. Non-`str` → `AdapterError` quoting
   `type(key).__name__`.
2. **Result-side keyset membership**: key must appear in the union of
   tool-use ids declared by *result-side* Nodes in `parent_run_id` —
   i.e. `_is_result_side(n)` Nodes (UserMessage carrying ToolResultBlock
   per §5.1 singular form, or any element of §5.1.1 plural
   `state_after['tool_use_ids']`). An id present *only* on use-side
   (orphan use, no matching result yet) is rejected here as "not in
   result-side keyset" — slice-3a→3c coupling pre-condition (round-trip
   must close in parent run).
3. **No double-substitution**: a key MUST NOT also appear in
   `tool_input_overrides` — overriding both the input and the result
   for the same `tool_use_id` is contradictory (rewriting the input
   implies the agent re-asks the tool with new input, but rewriting the
   result implies the tool was never re-invoked). `AdapterError` quoting
   the conflicting id.

Note the asymmetry vs §5.2: §5.2 validates against the *use-side*
keyset (where `ToolUseBlock.id` was declared) and rejects orphan use-ids
that haven't received a matching result; §5.3 validates against the
*result-side* keyset (where `ToolResultBlock.tool_use_id` was declared).
A round-trip that closed in the parent passes both; a half-open
round-trip is rejected on whichever side the user tried to rewrite.

#### Child-side stamp

When a child run's translated Node carries a `ToolResultBlock` whose
`tool_use_id` matches an override key, the recorder writes the
substitute content into `state_after`:

```python
state_after = {
    "tool_use_id": "<unchanged JOIN anchor>",  # §5.1 — preserved verbatim
    "tool_result_content": <override value>,   # §5.3 NEW
    # ... any other §5 keys (tool_use_ids plural form per §5.1.1) ...
}
```

For multi-block result Nodes (§5.1.1 plural form), the stamp follows
§5.2's index-aligned shape: `state_after['tool_result_contents']` is
an ordered list whose `i`-th entry is either the original
`ToolResultBlock.content` (no override matched id `i`) or the override
value (override matched). Mutually exclusive with the singular form,
same `len==1 → singular only / len>1 → plural only` rule as §5.1.1.

JOIN anchors `tool_use_id` (singular) and `tool_use_ids` (plural) are
preserved byte-for-byte — slice-3 SQL recipes still work; only the
*payload* fields are overridden.

#### Out of scope (slice 3c)

- HTTP / CLI surface — `tool_result_overrides` lands on the recorder
  Python API only in R82. CLI wiring is a later slice.
- Multi-step result substitutions across nested forks (overriding a
  tool result whose effect propagates through *another* fork). Each
  fork in a chain carries its own independent `tool_result_overrides`;
  no transitive bookkeeping.
- MCP passthrough scoping — `tool_result_overrides` applies uniformly
  regardless of whether the originating tool was a built-in or an MCP
  server tool. MCP-aware filtering is reserved for a future slice if
  it surfaces a real need.
- Streaming / partial substitution — the override value replaces the
  *entire* `ToolResultBlock.content` payload at translation time; we do
  not rewrite individual content blocks within a multi-block result.

#### SQL recipe (consumer-side enumeration)

To list every result-substituted call in a child run:

```sql
SELECT id, kind,
       json_extract(state_after, '$.tool_use_id') AS tu_id,
       json_extract(state_after, '$.tool_result_content') AS new_content
FROM nodes
WHERE run_id = ?
  AND json_extract(state_after, '$.tool_result_content') IS NOT NULL;
```

Multi-block (§5.1.1 plural) consumers swap to `json_each` over
`tool_result_contents`. Both forms are documented alongside §5.1.1's
existing recipe.

#### Test enforcement

R81 ships a four-test scaffold (`tests/unit/test_anthropic_agents_fork_tool_result_override.py`):

1. `test_fork_without_result_overrides_is_identity` — `None` and `{}`
   produce a child run byte-identical to R74 / R80 fork(). **EXPECTED
   PASS** on R81 (no-op pass-through).
2. `test_fork_with_result_override_changes_downstream_result` —
   overriding a single `tool_use_id` rewrites
   `state_after['tool_result_content']` on the child Node while
   preserving `state_after['tool_use_id']`. **xfail strict (R82)**.
3. `test_fork_with_result_override_of_unknown_id_raises` — overriding
   an id absent from the parent's *result-side* keyset raises
   `AdapterError` *before* the SDK call (validation #2). **xfail strict
   (R82)**.
4. `test_fork_with_result_override_collides_with_input_override_raises`
   — same id in both `tool_input_overrides` and `tool_result_overrides`
   raises `AdapterError` (validation #3). **xfail strict (R82)**.

Strict-xfail makes R82 a forcing function: when the implementation
lands, all three xfail tests flip to passing → strict-xfail trips →
R82 commit removes the markers in the same diff. Same forcing-function
discipline as R76→R77 §5.1.1, R79→R80 §5.2.

### 6. What Arc B slice 2+ looks like

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
