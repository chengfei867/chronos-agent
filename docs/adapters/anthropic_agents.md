# `anthropic_agents` adapter

> **Adapter status (R71, 2026-05-14):** scaffold + recorder shipped (R70),
> live smoke gated on upstream session-protocol authorisation.
> `fork()` lands in R73, GA in v0.7.0 (target R74). See [ADR-026][adr-026]
> and [`docs/research/r69-mcp-fork-lifecycle.md`][r69-mcp].

The `anthropic_agents` adapter wraps Anthropic's official
[`claude-agent-sdk`][cas-pypi] (Python) so Chronos can record, replay,
fork, and diff agent traces produced by `ClaudeSDKClient` /
`query(prompt, options)` sessions.

## Installation

```bash
uv sync --extra anthropic_agents
```

Pulls in `claude-agent-sdk>=0.1.80,<1.0` and its transitive dependencies.
Pin rationale (ADR-026 §7): the 0.1.x line is explicitly alpha (Anthropic
ships weekly additive-only patches; see PyPI Development Status). The
upper bound is the next major (`<1.0`) rather than the next minor — this
is **library-maturity-aware** pinning per the R69 refinement of ADR-022,
which is unchanged for stable 1.x SemVer dependencies.

The SDK bundles a Node.js [`claude-code` CLI][cas-cli] as a subprocess.
Node.js v20+ is required on `PATH`. `which claude` should resolve once
the extra is installed.

## Authentication

The SDK speaks Anthropic's *session* subprotocol — not the public
`messages` API. This means:

- Direct API access via `ANTHROPIC_API_KEY` against
  `https://api.anthropic.com` works out of the box.
- `Bedrock` / `Vertex` upstreams configured via `ANTHROPIC_BASE_URL`
  work if they implement session-protocol pass-through.
- **OneAPI / messages-only relays do not work.** The SDK falls back
  to `model='<synthetic>'` and emits an `AssistantMessage` with
  `error='authentication_failed'`. The dogfood probe at
  `scripts/dogfood/arc_b_slice_1_smoke.py` detects this exact
  signature and exits with code 2 + a structured blocker report.

Verify your environment with:

```bash
uv run python scripts/dogfood/arc_b_slice_1_smoke.py
```

Exit 0 = release-gate green; exit 2 = upstream not session-protocol-aware
(see the script docstring for the unblock checklist).

## Recording a run

```python
from claude_agent_sdk import ClaudeAgentOptions, query
from chronos.adapters.anthropic_agents import AnthropicAgentsRecorder
from chronos.store.sqlite import SqliteStore

store = SqliteStore.open("chronos.db")
recorder = AnthropicAgentsRecorder(store=store)

runtime = query(
    prompt="Summarise the latest news on the H-1B visa lottery.",
    options=ClaudeAgentOptions(max_turns=4),
)

with recorder.record(runtime, thread_id="news-summary-2026-05-14") as ref:
    pass  # the recorder consumes the async stream on context exit

print(f"Recorded run: {ref.run_id}")
```

The recorder's seam is the `Message` async iterator returned by either
the top-level `query(...)` (stateless) or the
`ClaudeSDKClient.receive_response()` method (stateful client). Both work
without modification — `_resolve_iterator()` duck-types both shapes.

## Message → Node mapping

`Node.kind` is dispatched on the **message envelope class**, not on the
inner content blocks. See
[`docs/contracts/adapter-protocol.md`](../contracts/adapter-protocol.md#envelope-determines-kind-r85-contract-finding-codified-at-r89)
for the cross-adapter rule and rationale (R85 contract finding,
codified at R89).

| SDK class           | Chronos `kind` | `Node.name`                              |
| ------------------- | -------------- | ---------------------------------------- |
| `UserMessage`       | `llm`          | `UserMessage`                            |
| `AssistantMessage`  | `llm`          | `AssistantMessage` or `AssistantMessage:<tool>` |
| `SystemMessage`     | `fn`           | `SystemMessage`                          |
| `ResultMessage`     | `end`          | `ResultMessage`                          |

The dispatch table lives in
[`recorder.py`](../../src/chronos/adapters/anthropic_agents/recorder.py)
as `_DEFAULT_KIND_MAP` (≈line 69) and the lookup happens in
`_kind_for(msg)` via `type(msg).__name__`.

Tool surfacing happens **inside** these envelopes — it does not change
`Node.kind`:

- `AssistantMessage` with a single `ToolUseBlock` → still `kind=llm`,
  but `tool_name` / `tool_input` are populated on the `Node`, and
  `Node.name` is suffixed with `:<tool_name>` for cross-run alignment
  legibility (e.g. `AssistantMessage:add`).
- `AssistantMessage` with multiple `ToolUseBlock`s (R77 multi-block
  case, ADR-026 §5.1.1) → still `kind=llm`; per-block tool ids are
  surfaced as `state_after.tool_use_ids` (list).
- `UserMessage` with one or more `ToolResultBlock`s → still `kind=llm`;
  `tool_output` populated (single-block case) and matching tool ids
  are surfaced as `state_after.tool_use_ids` (multi-block case);
  `is_error=True` propagates as `error_message`.

Per-block content (`TextBlock`, `ToolUseBlock`, `ToolResultBlock`,
`ThinkingBlock`) is preserved inside `state_after.blocks[i].block` —
filter on that key when you need block-level granularity. Do not
filter on `node.kind == TOOL` looking for tool-use *blocks*; you'll
find none, because `kind` is dispatched per-envelope.

The recorder's `_DEFAULT_KIND_MAP` carries two block-class entries
(`ToolUseBlock → TOOL`, `ToolResultBlock → TOOL`) that are **dead code
under the current SDK contract** — block instances never reach
`_kind_for()` because the SDK iterator yields top-level `Message`
instances. The entries are kept for forward compatibility and as a
defensive default; see the
[adapter-protocol contract doc](../contracts/adapter-protocol.md#what-about-the-recorder-block-dispatch-table)
for the full rationale.

The four block types `{TextBlock, ToolUseBlock, ToolResultBlock,
ThinkingBlock}` enumerated in [R69 spike #2][r69-mcp] are handled
explicitly inside the message-envelope summariser; unknown block
classes fall through with a `class-name` tag so they fail loudly
rather than silently lossy. (R71→R87 has not yet surfaced any fifth
type in real traces.)

## Forking

`fork()` is **not yet implemented** in the R70 scaffold:

```python
recorder.fork(...)  # raises NotImplementedError("R73: delegate to claude_agent_sdk.fork_session()")
```

The R69 source-inspection spike confirmed the SDK ships a native
`fork_session(session_id, up_to_message_id=...)` primitive in
`claude_agent_sdk._internal.session_mutations`. R73 will swap the
`NotImplementedError` for a thin delegate to that primitive — no
custom re-seed / Policy A / Policy B logic needed. See
[`docs/research/r69-mcp-fork-lifecycle.md`][r69-mcp] §3.

## Live smoke + CI

The opt-in live smoke harness lives at
[`tests/live/test_anthropic_agents_smoke.py`](../../tests/live/test_anthropic_agents_smoke.py).
Run with:

```bash
set -a && . /workspace/.hermes/.env && set +a
CHRONOS_LIVE=1 \
  uv run pytest tests/live/test_anthropic_agents_smoke.py -m live -v
```

The harness skips cleanly with a clear reason when the upstream is not
session-protocol-aware (e.g. baidu-int OneAPI relay), so it is safe to
leave in `CHRONOS_LIVE=1` CI even before R72 alpha cuts.

## Roadmap

| Round | Milestone                                                    |
| ----- | ------------------------------------------------------------ |
| R70 ✅ | Core scaffold + 34 unit tests (no SDK install required)      |
| R71 🚧 | Live smoke + dogfood probe (gated on session upstream)       |
| R72   | Alpha tag `v0.7.0a1`                                         |
| R73   | `fork()` via `fork_session()` delegate                       |
| R74   | GA `v0.7.0` (record + fork + dogfood + adapter doc complete) |

[adr-026]: ../decisions/ADR-026-arc-b-scope.md
[r69-mcp]: ../research/r69-mcp-fork-lifecycle.md
[cas-pypi]: https://pypi.org/project/claude-agent-sdk/
[cas-cli]: https://www.npmjs.com/package/@anthropic-ai/claude-code
