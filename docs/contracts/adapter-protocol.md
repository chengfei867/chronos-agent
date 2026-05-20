# AdapterProtocol — recorder + adapter contract

> **Status**: stable as of v0.7.0 (Phase 4 Arc B slice 1 GA, R87/R88).
> **Source of truth**: [`src/chronos/adapters/protocols.py`](../../src/chronos/adapters/protocols.py) — runtime-checkable
> `Protocol` definitions. This doc is the *narrative* companion to the runtime
> classes; when wording disagrees, the runtime classes win.
> **Author**: Hermes Agent (R89 cron, 2026-05-20). Created to reconcile the R85
> contract finding (envelope-determines-kind) into a permanent contract doc.

This page documents the framework-agnostic contract every Chronos adapter
must satisfy. As of v0.7.0 we ship four first-class adapters that all
conform: `langgraph`, `linear`, `autogen`, `crewai`, `anthropic_agents`.

The full surface is small on purpose — adapters are thin shims, not
plugins. Most behaviour lives in `chronos.core` and `chronos.store`; the
adapter only translates a framework's runtime stream into Chronos `Node`
records.

## Public surface (3 protocols + 2 dataclasses + 1 exception)

### Protocols

- `RecorderProtocol` — the core record/fork contract. Two context managers:
  `record(runtime, *, thread_id) -> RunRef` and `fork(parent_run, anchor,
  *, child_thread_id, ...) -> ForkRef`. Both yield mutable handles that
  populate-on-exit.
- `AdapterProtocol` — the plugin / constructor shape (ADR-016).
  Module-level instance per adapter (e.g. `anthropic_agents_adapter`)
  satisfies this structurally. Exposes `name`, `build_recorder(store, ...)`,
  and the `RunRef`/`ForkRef`/`AdapterError` re-exports.
- `NodeIdentityResolver` — pluggable framework → `(name, kind)` hook for
  recorders that need bespoke per-event labelling (e.g. LangGraph's
  super-step → node-name resolver).

### Dataclasses (mutable handles)

- `RunRef(thread_id, run_id=None, node_ids=[])` — yielded by `record()`.
  `run_id` populated on context-manager exit; `node_ids` appended in step
  order.
- `ForkRef(parent_run_id, at_node_id, child_run_id=None, child_thread_id=None,
  fork_id=None, node_ids=[])` — yielded by `fork()`.

### Exception

- `AdapterError` — the **only** legal framework-leak exception per the
  ADR-016 lifecycle contract. Anything else (`KeyError` from a missing
  snapshot field, `AttributeError` from SDK drift, etc.) must be caught
  and re-wrapped.

## Lifecycle invariants

1. **`record()` is exclusive of `fork()`** — a recorder cannot yield both
   handles concurrently; one CM must exit before the next opens.
2. **Persistence happens on CM exit, in step order** — partial node
   persistence on exception is allowed (run is marked `FAILED`); but
   inside the `with` block the handle's `node_ids` is only ever
   *append-only*.
3. **Thread/session identity is opaque to Chronos** — the framework's
   `thread_id` is passed through verbatim. Chronos does not parse it.
4. **Fork child `thread_id` MUST differ from parent's** — enforced by
   `AdapterError` at fork-CM open. (Same-thread forks would conflate run
   storage.)
5. **`Node.kind` dispatch is per-envelope, not per-block** — see the
   "Envelope-determines-kind" subsection below.

## Envelope-determines-kind (R85 contract finding, codified at R89)

When a framework's runtime stream surfaces *messages* that contain a
list of *content blocks* — for example `claude-agent-sdk`'s
`AssistantMessage(content=[TextBlock(...), ToolUseBlock(...)])` or
`UserMessage(content=[ToolResultBlock(...)])` — Chronos records **one
`Node` per message**, with `Node.kind` dispatched on the **envelope**
type (i.e. the message subclass), **not** the per-block content type.

### What this means in practice

For the `anthropic_agents` adapter:

| SDK envelope | Inner blocks | `Node.kind` | Why |
|---|---|---|---|
| `AssistantMessage` | `[TextBlock]` | `LLM` | Message-type dispatch: `AssistantMessage` → `LLM`. |
| `AssistantMessage` | `[TextBlock, ToolUseBlock]` | `LLM` | Same. The `ToolUseBlock` does **not** promote the node to `TOOL`. |
| `AssistantMessage` | `[ToolUseBlock]` | `LLM` | Same. The whole assistant turn is one `LLM` node. |
| `UserMessage` | `[ToolResultBlock]` | `LLM` | Same. The tool-result reply is one `LLM` node carrying the result inside `state_after.blocks`. |
| `SystemMessage` | (any) | `FN` | Map entry. |
| `ResultMessage` | — | `END` | Carries `total_cost_usd`, `stop_reason`. |

The recorder dispatch implementation lives at
`src/chronos/adapters/anthropic_agents/recorder.py:_kind_for()` (line
≈303, R89): it reads `type(msg).__name__` and looks up the result in
`_DEFAULT_KIND_MAP` (line ≈69). Block types are *never* the dispatch key.

### Where the block-level distinction lives

Block content is preserved per-block inside `state_after`:

```python
node.state_after == {
    "blocks": [
        {"block": "TextBlock", "text": "..."},
        {"block": "ToolUseBlock", "id": "toolu_...", "name": "add", "input": {...}},
    ]
}
```

The `state_after.blocks[i].block` key carries the *block class name* —
this is what readers should filter on when they care about block kind
(e.g. graph-query helpers in `chronos.queries.tool_linkage`, dogfood
invariant inspectors). Do **not** filter on `node.kind == TOOL`
expecting to find tool-use *blocks*; you'll find none.

### What about the recorder block-dispatch table?

`_DEFAULT_KIND_MAP` (recorder.py:77) historically contained two block
entries:

```python
"ToolUseBlock": NodeKind.TOOL,    # DEAD — see below
"ToolResultBlock": NodeKind.TOOL, # DEAD — see below
```

These entries are **dead code** in the current architecture. The
dispatch key (`type(msg).__name__`) only ever produces *envelope*
class names because the recorder iterates the SDK's top-level
`Message` async iterator — block instances never reach `_kind_for()`
directly.

The entries are kept (rather than deleted) for two reasons:

1. **Forward compatibility** — if a future SDK release surfaces blocks
   as top-level stream items (e.g. a future `claude-agent-sdk` stream
   mode that emits per-block events), these entries activate without
   code change.
2. **Defensive fallback** — if a recorder caller injects a custom
   `kind_map` that overrides `AssistantMessage → LLM` to defer to
   per-block dispatch via a wrapper, the entries provide a sensible
   default.

Per R85 we document this rather than remove the entries.

### Rationale

Per-message dispatch was chosen over per-block dispatch because:

- **One Node per SDK message keeps `tu_id` linkage one-to-one** — the
  R76 / ADR-026 §5.1 contract `state_after.tool_use_id` (single-block
  case) and §5.1.1 `state_after.tool_use_ids` (multi-block case) both
  rely on each `AssistantMessage` carrying one `Node`. Per-block split
  would require either re-stamping linkage across N split nodes or
  giving up the one-tu_id-per-message-side guarantee.
- **It matches the canonical SDK contract surface** — the SDK's public
  iterator yields `Message` instances, not blocks. Chronos' `Node`
  granularity should match the SDK's emission granularity unless a
  framework gives us a stronger reason to split.
- **It bounds node count** — per-block split would explode node counts
  on long assistant turns (a single 5-tool-use turn would become 6 nodes
  instead of 1), which would inflate replay storage, complicate diff
  tooling, and break the "one Node = one observable agent step" mental
  model that anchors the rest of the project.

The cross-adapter rule generalises to *all* Chronos adapters:

> **`Node.kind` is dispatched on the envelope type that the framework's
> top-level event stream emits.** If the framework emits messages, kind
> is per-message; if it emits supersteps, kind is per-superstep; if it
> emits raw events, kind is per-event. Block-level / sub-event-level
> distinctions are preserved inside `state_after`, never as separate
> nodes.

### See also

- ADR-026 §6 AC-2 closing note — first inline mention.
- `progress/2026-05-18-round-85.md` — the round where the contract
  finding was discovered live (run_id `27f836eb…`).
- `progress/2026-05-19-round-86.md` — pre-finding documented in `_degradation.py`-adjacent commentary.
- `progress/2026-05-19-round-87.md` — promoted from pre-finding to finding.
- `progress/2026-05-20-round-89.md` — this doc landed.
- `docs/adapters/anthropic_agents.md` — adapter-specific message → node mapping table.

## What an adapter MUST do

(Mostly cross-references; details live in ADR-016 and the per-adapter docs.)

1. Implement `RecorderProtocol`'s two CMs against the framework's runtime
   stream. Treat the framework's iterator as the single source of truth;
   never inject synthetic events.
2. Translate each framework event into a `Node` with stable `kind`,
   `name`, `state_after`, and (when applicable) `tool_name` /
   `tool_input` / `tool_output` / `error_message`.
3. Persist on CM exit via the injected `SqliteStore`. Never write
   directly mid-stream — partial persistence breaks the all-or-failed
   atomicity guarantee.
4. Re-wrap framework exceptions as `AdapterError`. Document any
   exception that is *intentionally* allowed to escape (none are, today).
5. Expose a module-level `AdapterProtocol` instance (e.g.
   `from chronos.adapters.anthropic_agents import anthropic_agents_adapter`)
   so plugin discovery (ADR-016 P2) finds the adapter without import
   gymnastics.

## What an adapter MUST NOT do

1. Inject synthetic nodes / events that did not exist in the framework's
   runtime stream.
2. Mutate `state_after` after node persistence.
3. Leak framework-specific exception types beyond the `AdapterError`
   wrapper.
4. Assume `thread_id` has any structure beyond opaque `str`.
5. Block on network IO during translate — translate is a pure function
   from framework event to `_PendingNode`. Network IO belongs in the
   framework's runtime, not the recorder.

## Version + stability

- The protocol surface (3 protocols + 2 dataclasses + `AdapterError`)
  is **stable** as of v0.5.0 (R59) and re-confirmed each minor release.
- The "envelope-determines-kind" rule is **stable** as of v0.7.0 (R89)
  and applies to every adapter past, present, and future.
- New protocols / new fields go through ADR. The most recent contract
  amendments are ADR-026 §5 (Anthropic-specific seed coordinates),
  §5.1/§5.1.1 (`tool_use_id` linkage), §5.2 (tool-input override fork),
  §5.3 (tool-result override fork). All five amendments respect the
  envelope-determines-kind rule.

[adr-016]: ../decisions/ADR-016-adapter-interface.md
[adr-026]: ../decisions/ADR-026-arc-b-scope.md
