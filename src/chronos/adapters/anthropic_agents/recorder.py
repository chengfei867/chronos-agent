"""Anthropic Agents SDK adapter — recorder (R70, ADR-026, Arc B slice 1).

Records ``claude-agent-sdk`` ``Message`` async iterator output into a
:class:`SqliteStore`. Conforms to ADR-016 :class:`RecorderProtocol` at
the signature level.

R70 ships **scaffold only**:

- ``record()`` consumes any object exposing an
  :class:`AnthropicMessageIterable` (anything async-iterating SDK
  ``Message`` subclasses): ``ClaudeSDKClient.receive_messages()``,
  ``query(...)`` (which is itself an async iterator), or a fake driving
  unit-tests. The iterator drives a sync recorder via ``asyncio.run``
  internally (mirrors the AutoGen sync-wrap precedent — ADR-017).
- ``fork()`` is a stub that raises
  ``NotImplementedError("R73: delegates to claude_agent_sdk.fork_session()")``.
  R73 swaps in the real ``fork_session()`` delegate per R69 spike #1.
- The Message → Node translator is intentionally permissive (duck-typed
  on attribute names like ``content``, ``model``, ``usage``,
  ``tool_use_id``, ``stop_reason``) so it works against either the real
  SDK or unit-test stub messages. Drift causes ``AdapterError`` (the
  one legal leak per ADR-016).

R70 explicitly out of scope (per ADR-026 §6 / CONTEXT §6 R70 non-goals):

- No live API call.
- No live MCP server.
- No CLI / HTTP / Web UI changes.
- No mutation of adapter-1-3 (langgraph / autogen / crewai).
- No tag / version bump (alpha at R72, GA at R74).

R69 → R70 invariants observed:

- Recorder seam = ``Message`` async iterator (R69 spike #2).
- Block taxonomy: ``UserMessage`` / ``AssistantMessage`` /
  ``SystemMessage`` / ``ResultMessage``; content blocks ``TextBlock`` /
  ``ToolUseBlock`` / ``ToolResultBlock`` / ``ThinkingBlock`` (R69
  spike #1.5).
- ADR-015 v2 extractor contract = additive fit, no amendment needed
  (R69 spike #1.5 confirmation).
"""

from __future__ import annotations

import asyncio
import threading
import uuid
from collections.abc import AsyncIterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from chronos.adapters.protocols import (
    AdapterError,
    ForkRef,
    RunRef,
)
from chronos.core.models import Fork, Node, NodeKind, Run, RunStatus, Usage

if TYPE_CHECKING:
    from chronos.store import SqliteStore


# ---------------------------------------------------------------------------
# Default Message-class-name → NodeKind map (ADR-026 §5 / R69 spike #1.5)
# ---------------------------------------------------------------------------

_DEFAULT_KIND_MAP: dict[str, NodeKind] = {
    # Top-level Message subclasses
    "UserMessage": NodeKind.LLM,  # prompt input — counts as an LLM-boundary node
    "AssistantMessage": NodeKind.LLM,  # model output
    "SystemMessage": NodeKind.FN,
    "ResultMessage": NodeKind.END,  # carries total_cost_usd, stop_reason
    # Inline-block dispatch — when an AssistantMessage carries a single
    # ToolUseBlock / ToolResultBlock we synthesise a TOOL node (ADR-026 §5).
    "ToolUseBlock": NodeKind.TOOL,
    "ToolResultBlock": NodeKind.TOOL,
    # ThinkingBlock — explicitly _not_ in the default map. Per R69 spike
    # #1.5, ThinkingBlock fits inside an AssistantMessage.content and
    # contributes to that node's state_after; it is not promoted to a
    # standalone node in slice 1. See ADR-026 §5.
}
"""Default Message → NodeKind mapping per R69 spike #1.5."""


# ---------------------------------------------------------------------------
# Buffered pending-node record (mirror of CrewAIRecorder._PendingNode)
# ---------------------------------------------------------------------------


@dataclass
class _PendingNode:
    """Per-message intermediate before SqliteStore commit.

    Filled by the recorder's translator; drained inside the ``record()``
    CM ``finally`` block in step-index order.
    """

    msg_cls: str
    node_name: str
    kind: NodeKind
    state_after: dict[str, Any] = field(default_factory=dict)
    model_name: str | None = None
    usage: dict[str, int] | None = None
    tool_name: str | None = None
    tool_input: dict[str, Any] | None = None
    tool_output: dict[str, Any] | None = None
    error_message: str | None = None


# ---------------------------------------------------------------------------
# Type alias for the recorder seam
# ---------------------------------------------------------------------------

#: Anything async-iterating SDK ``Message`` subclasses.
#:
#: Real-world incarnations:
#:
#: - ``ClaudeSDKClient.receive_messages()`` → ``AsyncIterator[Message]``
#: - ``ClaudeSDKClient.receive_response()`` → ``AsyncIterator[Message]``
#: - ``query(prompt, options) -> AsyncIterator[Message]``
#:
#: Unit tests pass an in-memory async generator yielding stub messages.
AnthropicMessageIterable = AsyncIterable[Any]


# ---------------------------------------------------------------------------
# Helpers: per-message extractors (duck-typed)
# ---------------------------------------------------------------------------


def _msg_cls_name(msg: Any) -> str:
    """Return the runtime class name of a Message — dispatch key."""
    return type(msg).__name__


def _extract_usage(msg: Any) -> dict[str, int] | None:
    """Best-effort usage extraction from AssistantMessage / ResultMessage.

    The SDK's ``Message.usage`` is a ``dict[str, int]`` (or ``None``)
    using Anthropic API field names: ``input_tokens``, ``output_tokens``,
    ``cache_creation_input_tokens``, ``cache_read_input_tokens``. We
    project these onto our canonical
    :class:`~chronos.core.models.Usage` schema (which uses
    ``prompt_tokens`` / ``completion_tokens`` / ``reasoning_tokens`` —
    ADR-013 / R20 finding #2):

    - ``input_tokens`` (+ cache_creation_input_tokens + cache_read_input_tokens)
      → ``prompt_tokens``
    - ``output_tokens`` → ``completion_tokens``
    - thinking / extended-thinking token counts (if surfaced) →
      ``reasoning_tokens``

    Cache token totals are summed into prompt_tokens to keep the value
    monotonic with what the user pays for, matching how the Linear and
    AutoGen adapters treat aggregate input.
    """
    raw = getattr(msg, "usage", None)
    if raw is None:
        return None
    if not isinstance(raw, dict):
        # SDK drift defence — surface an AdapterError instead of crashing
        # downstream Pydantic validation.
        raise AdapterError(
            f"AnthropicAgentsRecorder: expected dict for Message.usage, got "
            f"{type(raw).__name__} (Message class: {_msg_cls_name(msg)})"
        )

    def _ival(key: str) -> int:
        v = raw.get(key, 0)
        return int(v) if isinstance(v, int) else 0

    prompt = (
        _ival("input_tokens")
        + _ival("cache_creation_input_tokens")
        + _ival("cache_read_input_tokens")
    )
    # Fallback to chronos-native key if present (tests / stubs)
    if prompt == 0 and "prompt_tokens" in raw:
        prompt = _ival("prompt_tokens")
    completion = _ival("output_tokens")
    if completion == 0 and "completion_tokens" in raw:
        completion = _ival("completion_tokens")
    reasoning = _ival("reasoning_tokens") + _ival("thinking_tokens")

    out = {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "reasoning_tokens": reasoning,
    }
    # Drop the all-zero case so we don't manufacture spurious Usage rows
    # for non-LLM messages (UserMessage etc.).
    if not any(out.values()):
        return None
    return out


def _summarise_content(content: Any) -> dict[str, Any]:
    """Best-effort summary of Message.content for state_after.

    SDK ``Message.content`` is either a ``str`` or ``list[ContentBlock]``.
    ContentBlocks include ``TextBlock`` (``.text``), ``ToolUseBlock``
    (``.id``, ``.name``, ``.input``), ``ToolResultBlock``
    (``.tool_use_id``, ``.is_error``, ``.content``), ``ThinkingBlock``
    (``.thinking``, ``.signature``).
    """
    if content is None:
        return {}
    if isinstance(content, str):
        return {"text": content}
    if not isinstance(content, list):
        return {"raw": repr(content)[:500]}
    blocks: list[dict[str, Any]] = []
    for blk in content:
        cls = type(blk).__name__
        entry: dict[str, Any] = {"block": cls}
        for attr in ("text", "name", "input", "tool_use_id", "is_error", "thinking"):
            val = getattr(blk, attr, None)
            if val is not None:
                entry[attr] = val if isinstance(val, str | bool | dict | list) else repr(val)[:200]
        blocks.append(entry)
    return {"blocks": blocks}


def _node_name_for(msg: Any) -> str:
    """Synthesise a node_name for an SDK Message.

    Default scheme: ``"<MessageClass>"`` (e.g. ``"AssistantMessage"``,
    ``"UserMessage"``). For ``AssistantMessage`` carrying a single
    ToolUseBlock we postfix ``":<tool_name>"`` to make alignment across
    runs more legible.
    """
    cls = _msg_cls_name(msg)
    content = getattr(msg, "content", None)
    if cls == "AssistantMessage" and isinstance(content, list):
        for blk in content:
            if type(blk).__name__ == "ToolUseBlock":
                tool_name = getattr(blk, "name", None)
                if isinstance(tool_name, str) and tool_name:
                    return f"AssistantMessage:{tool_name}"
    return cls


# ---------------------------------------------------------------------------
# Recorder
# ---------------------------------------------------------------------------


class AnthropicAgentsRecorder:
    """Records Anthropic Agents SDK runs into a :class:`SqliteStore`.

    R70 scope: scaffold conformance (see module docstring). The recorder
    consumes any :data:`AnthropicMessageIterable`; in production this
    will be ``ClaudeSDKClient.receive_messages()`` or ``query(...)`` per
    R69 spike #2.3.

    The runtime parameter passed to ``record()`` is duck-typed: anything
    with an ``__aiter__`` / ``receive_messages()`` / ``receive_response()``
    method works. Real ``ClaudeSDKClient`` exposes ``receive_messages()``
    so a thin attribute-check wrapper covers both cases.

    Args:
        store: Persistence target.
        adapter_name: Written to ``Run.adapter``. Default
            ``"anthropic_agents"``.
        kind_map: Optional override merged over :data:`_DEFAULT_KIND_MAP`.
    """

    def __init__(
        self,
        store: SqliteStore,
        *,
        adapter_name: str = "anthropic_agents",
        kind_map: dict[str, NodeKind] | None = None,
    ) -> None:
        self._store = store
        self._adapter_name = adapter_name
        self._kind_map: dict[str, NodeKind] = {**_DEFAULT_KIND_MAP}
        if kind_map:
            self._kind_map.update(kind_map)
        self._lock = threading.Lock()
        self._buffer: list[_PendingNode] = []
        # ADR-026 §5.2 (R80, slice 3b): set inside `fork(...)` for the
        # duration of the child stream consumption so `_translate` can
        # stamp `state_after['tool_input']` on AssistantMessage Nodes
        # whose ToolUseBlock id appears as a key. None means no active
        # fork-with-substitution; `record()` always runs with this None.
        self._fork_overrides: dict[str, dict[str, Any]] | None = None

    # ------------------------------------------------------------------
    # Translator (Message → _PendingNode)
    # ------------------------------------------------------------------

    def _kind_for(self, msg: Any) -> NodeKind:
        cls = _msg_cls_name(msg)
        return self._kind_map.get(cls, NodeKind.FN)

    def _translate(self, msg: Any) -> _PendingNode:
        """Convert a single SDK Message into a _PendingNode.

        Pure: no IO, no mutation of recorder state. Tests exercise this
        directly without a store.
        """
        cls = _msg_cls_name(msg)
        kind = self._kind_for(msg)
        content = getattr(msg, "content", None)
        state = _summarise_content(content)

        # Add common metadata fields to state_after.
        # ADR-026 §5 (R75): `uuid` and `session_id` are the FORK CONTRACT —
        # `AnthropicAgentsRecorder.fork()` reads them off `parent_node.state_after`
        # to call `claude_agent_sdk.fork_session(session_id, up_to_message_id=uuid)`.
        # DO NOT remove these two keys without amending ADR-026 §5 first;
        # `test_record_state_after_carries_seed_coordinates_for_*` enforces this.
        # The remaining three (stop_reason / total_cost_usd / duration_ms) are
        # observability-only and may evolve without ADR amendment.
        for attr in ("uuid", "session_id", "stop_reason", "total_cost_usd", "duration_ms"):
            val = getattr(msg, attr, None)
            if val is not None:
                state[attr] = val

        usage = None
        model_name = None
        tool_name = None
        tool_input: dict[str, Any] | None = None
        tool_output: dict[str, Any] | None = None
        error_message: str | None = None

        if cls in ("AssistantMessage", "ResultMessage"):
            usage = _extract_usage(msg)
            model_name = getattr(msg, "model", None)

        # If AssistantMessage carries a single ToolUseBlock surface tool fields
        if cls == "AssistantMessage" and isinstance(content, list):
            tool_blocks = [b for b in content if type(b).__name__ == "ToolUseBlock"]
            if len(tool_blocks) == 1:
                blk = tool_blocks[0]
                tool_name = getattr(blk, "name", None)
                blk_input = getattr(blk, "input", None)
                if isinstance(blk_input, dict):
                    tool_input = dict(blk_input)
                # ADR-026 §5.1 (R76, slice 3a): surface ToolUseBlock.id as
                # `state_after["tool_use_id"]` so a downstream consumer can JOIN
                # the matching ToolResultBlock node (which carries the same
                # tool_use_id) without parsing the nested ``state_after.blocks``
                # list. This is the cross-Node linkage anchor for slice-3 tool
                # round-trip queries; it is NOT a schema change (state_after is
                # JSON-bag) but IS a public contract pin —
                # `test_record_tool_use_block_persists_id` enforces it.
                blk_id = getattr(blk, "id", None)
                if isinstance(blk_id, str) and blk_id:
                    state["tool_use_id"] = blk_id
                    # ADR-026 §5.2 (R80, slice 3b): if a fork-with-tool-
                    # substitution is in flight and this tool_use_id is
                    # one of the override keys, stamp the substituted
                    # input on the child Node's state_after. The original
                    # `tool_input` (column) and `state_after['tool_use_id']`
                    # (anchor) are left verbatim — only the new key
                    # `state_after['tool_input']` surfaces the rewrite.
                    overrides = self._fork_overrides
                    if overrides is not None and blk_id in overrides:
                        state["tool_input"] = overrides[blk_id]
            elif len(tool_blocks) > 1:
                # ADR-026 §5.1.1 (R77, slice 3a-P1): multi-block extension —
                # when an AssistantMessage carries >1 ToolUseBlock (batched
                # tool dispatch), surface the ordered ids list as
                # `state_after["tool_use_ids"]` (plural). The singular
                # `state_after["tool_use_id"]` is intentionally NOT set in
                # this case (R76 §5.1 binding contract: singular = 1:1 JOIN
                # anchor; plural = 1:N expansion via
                # `json_each(state_after->>'tool_use_ids')`). Order matches
                # block order in the source message so consumers can pair
                # against the matching ToolResultBlock list by index.
                # `test_record_multi_tool_use_block_persists_ids` enforces.
                ids = [
                    getattr(b, "id", None)
                    for b in tool_blocks
                    if isinstance(getattr(b, "id", None), str) and b.id
                ]
                if ids:
                    state["tool_use_ids"] = ids
                    # ADR-026 §5.2 (R80, slice 3b): multi-block
                    # substitution. `state_after['tool_input']` is a
                    # list aligned by index with `tool_use_ids`, with
                    # `None` entries for verbatim blocks. Only stamped
                    # when ≥1 override key matches; absent on Nodes
                    # whose tool_use_ids do not intersect the override
                    # mapping (so SQL `WHERE tool_input IS NOT NULL`
                    # still enumerates substituted Nodes only).
                    overrides = self._fork_overrides
                    if overrides is not None:
                        aligned: list[dict[str, Any] | None] = [
                            overrides.get(str(tid)) for tid in ids
                        ]
                        if any(v is not None for v in aligned):
                            state["tool_input"] = aligned
        # ToolResultBlock arrives inside UserMessage.content per R69 §1.5
        if cls == "UserMessage" and isinstance(content, list):
            result_blocks = [b for b in content if type(b).__name__ == "ToolResultBlock"]
            if len(result_blocks) == 1:
                blk = result_blocks[0]
                # ADR-026 §5.1 (R76, slice 3a): surface ToolResultBlock.tool_use_id
                # symmetric with the AssistantMessage(ToolUseBlock) case above.
                # `test_record_tool_result_block_links_to_use` enforces this.
                blk_tu_id = getattr(blk, "tool_use_id", None)
                if isinstance(blk_tu_id, str) and blk_tu_id:
                    state["tool_use_id"] = blk_tu_id
                if getattr(blk, "is_error", False):
                    error_message = repr(getattr(blk, "content", ""))[:500]
                else:
                    raw_out = getattr(blk, "content", None)
                    if isinstance(raw_out, dict):
                        tool_output = dict(raw_out)
                    elif raw_out is not None:
                        tool_output = {"text": repr(raw_out)[:500]}
            elif len(result_blocks) > 1:
                # ADR-026 §5.1.1 (R77, slice 3a-P1): multi-block extension,
                # symmetric to the AssistantMessage(>1 ToolUseBlock) case.
                # Order matches block order in the source message; the i-th
                # tool_use_ids entry of the result message JOINs to the i-th
                # tool_use_ids entry of the prior assistant message under
                # SDK contract. Singular `tool_use_id` not set; the singular
                # 1:1 anchor is reserved for the len==1 branch (R76 §5.1).
                # `test_record_multi_tool_result_block_persists_ids` enforces.
                ids = [
                    getattr(b, "tool_use_id", None)
                    for b in result_blocks
                    if isinstance(getattr(b, "tool_use_id", None), str) and b.tool_use_id
                ]
                if ids:
                    state["tool_use_ids"] = ids

        return _PendingNode(
            msg_cls=cls,
            node_name=_node_name_for(msg),
            kind=kind,
            state_after=state,
            model_name=model_name if isinstance(model_name, str) else None,
            usage=usage,
            tool_name=tool_name,
            tool_input=tool_input,
            tool_output=tool_output,
            error_message=error_message,
        )

    # ------------------------------------------------------------------
    # Async drainer
    # ------------------------------------------------------------------

    async def _consume(self, source: AnthropicMessageIterable) -> None:
        """Iterate the async source, translate, and append to buffer."""
        async for msg in source:
            pending = self._translate(msg)
            with self._lock:
                self._buffer.append(pending)

    def _resolve_iterator(self, runtime: Any) -> AnthropicMessageIterable:
        """Coerce a runtime to an async iterable of Messages.

        Accepts:
        - An object with ``receive_messages()`` (``ClaudeSDKClient``).
        - An object with ``receive_response()`` (also ``ClaudeSDKClient``).
        - An object that is itself async-iterable (``query()`` generator
          or unit-test stub).
        """
        if hasattr(runtime, "receive_messages"):
            return runtime.receive_messages()  # type: ignore[no-any-return]
        if hasattr(runtime, "receive_response"):
            return runtime.receive_response()  # type: ignore[no-any-return]
        if hasattr(runtime, "__aiter__"):
            return runtime  # type: ignore[no-any-return]
        raise AdapterError(
            "AnthropicAgentsRecorder: runtime is not a recognised SDK message "
            "source. Expected `ClaudeSDKClient` (receive_messages / "
            "receive_response) or an async iterable of Messages. Got: "
            f"{type(runtime).__name__}"
        )

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _drain_buffer_to_store(
        self,
        run: Run,
        node_ids: list[str],
    ) -> None:
        """Persist Run + accumulated _PendingNode buffer atomically."""
        with self._lock:
            pending = list(self._buffer)
            self._buffer.clear()
        with self._store.transaction():
            self._store.put_run(run)
            for idx, p in enumerate(pending):
                node_id = str(uuid.uuid4())
                usage_obj = None
                if p.usage is not None:
                    try:
                        usage_obj = Usage(**p.usage)
                    except Exception:
                        usage_obj = None
                node = Node(
                    id=node_id,
                    run_id=run.id,
                    step_index=idx,
                    node_name=p.node_name,
                    kind=p.kind,
                    state_after=p.state_after,
                    model_name=p.model_name,
                    usage=usage_obj,
                    tool_name=p.tool_name,
                    tool_input=p.tool_input,
                    tool_output=p.tool_output,
                    error_message=p.error_message,
                )
                self._store.put_node(node)
                node_ids.append(node_id)

    # ------------------------------------------------------------------
    # RecorderProtocol — record()
    # ------------------------------------------------------------------

    @contextmanager
    def record(
        self,
        runtime: Any,
        *,
        thread_id: str,
        task_description: str | None = None,
        tags: list[str] | None = None,
    ) -> Iterator[RunRef]:
        """Open a recording context.

        Yields a :class:`RunRef` (``run_id=None`` until exit). On exit:

        - Iterate the runtime's message stream (sync-wrap via
          ``asyncio.run`` per ADR-017 sync-first precedent).
        - Translate each Message to a ``_PendingNode``.
        - Persist Run + Nodes inside a single ``store.transaction()``
          (ADR-016 §P1.3 atomicity).

        On exception inside the with-block, the run is persisted with
        ``status=FAILED`` and the original exception re-raised.
        """
        ref = RunRef(thread_id=thread_id)
        run_id = str(uuid.uuid4())
        started = datetime.now(UTC)
        # Reset buffer for this run (recorder may be reused)
        with self._lock:
            self._buffer.clear()

        exc: BaseException | None = None
        try:
            yield ref
            # User block produced a runtime; consume the stream now.
            try:
                source = self._resolve_iterator(runtime)
                asyncio.run(self._consume(source))
            except AdapterError:
                raise
            except Exception as e:
                raise AdapterError(
                    f"AnthropicAgentsRecorder: failure consuming message stream: {e!r}"
                ) from e
        except BaseException as e:
            exc = e
            raise
        finally:
            ended = datetime.now(UTC)
            status = RunStatus.FAILED if exc is not None else RunStatus.COMPLETED
            run = Run(
                id=run_id,
                adapter=self._adapter_name,
                adapter_thread_id=thread_id,
                status=status,
                started_at=started,
                ended_at=ended,
                task_description=task_description,
                tags=list(tags) if tags else [],
            )
            try:
                self._drain_buffer_to_store(run, ref.node_ids)
                ref.run_id = run_id
            except Exception as drain_exc:
                # If we're already unwinding for another reason, attach context
                # but don't shadow the original.
                if exc is None:
                    raise
                # Best-effort: re-raise will happen via the original exc anyway.
                # Surface drain failure in metadata for debug.
                ref.node_ids.clear()
                _ = drain_exc

    # ------------------------------------------------------------------
    # RecorderProtocol — fork() (R73 stub)
    # ------------------------------------------------------------------

    @contextmanager
    def fork(
        self,
        runtime: Any,
        *,
        parent_run_id: str,
        at_node_id: str,
        overrides: dict[str, Any] | None = None,
        tool_input_overrides: dict[str, dict[str, Any]] | None = None,
        tool_result_overrides: dict[str, Any] | None = None,
        child_thread_id: str,
        reason: str | None = None,
        task_description: str | None = None,
        tags: list[str] | None = None,
    ) -> Iterator[ForkRef]:
        """Fork a recorded run at a given node, delegating to ``fork_session``.

        Algorithm (R74, ADR-026 Arc B slice 2):

        1. Validate ``parent_run_id`` / ``at_node_id`` exist + thread isolation.
        2. Recover the SDK ``session_id`` and ``message uuid`` captured in
           ``parent_node.state_after`` during :meth:`record` (lines 305-308).
        3. Call ``claude_agent_sdk.fork_session(session_id,
           up_to_message_id=uuid)`` to materialise a fresh child transcript.
           This is a pure JSONL rewrite — fresh UUIDs, ``forkedFrom`` stamp,
           no MCP-server impact (R69 spike, ADR-026 §3).
        4. Yield a :class:`ForkRef` carrying the *child SDK session id* on
           ``ref.metadata`` (via attribute set) so the user can spin up
           ``ClaudeSDKClient(options=ClaudeAgentOptions(resume=child_sid))``
           inside the ``with`` block.
        5. The user is expected to drive the resumed client and pass the
           resulting ``ClaudeSDKClient`` (or any async iterable of messages)
           to ``ref.submit_runtime(...)``. We then iterate exactly like
           :meth:`record` and translate to ``_PendingNode`` rows.
        6. On exit, persist the child Run + Nodes + a Fork row atomically.

        On failure inside the ``with`` block, the child Run is persisted
        with ``status=FAILED`` and the original exception re-raised. A
        Fork row is still written so the relation is queryable.

        Args:
            runtime: Unused at this layer — the SDK driver is supplied via
                ``ref.submit_runtime(client_or_iterable)`` inside the block.
                Accepted for ADR-016 signature parity.
            parent_run_id: Existing parent ``Run.id`` recorded by
                :meth:`record`.
            at_node_id: ``Node.id`` within ``parent_run_id`` whose
                ``state_after['session_id']`` and ``state_after['uuid']``
                will seed the SDK fork.
            overrides: Free-form key/value pairs persisted to ``Fork.edited_fields``
                for downstream replay-edit workflows. **Not** applied to
                the SDK transcript — the SDK fork is verbatim up to
                ``up_to_message_id``; user-side edits ride on the resumed
                prompt the user issues inside the ``with`` block.
            tool_input_overrides: ADR-026 §5.2 (R79 amendment, slice 3b)
                surface for fork-with-tool-substitution. Mapping
                ``tool_use_id → new_input_dict``; replaces the
                ``ToolUseBlock.input`` payload on the child branch
                while preserving the ``state_after['tool_use_id']``
                JOIN anchor (R76 §5.1) / ``state_after['tool_use_ids']``
                element (R77 §5.1.1) verbatim. ``None`` (default) and
                ``{}`` are identity — semantically equivalent to R74
                fork() with no §5.2 surface. **Implementation lands in
                R80**; R79 ships the kwarg as a no-op pass-through that
                raises ``NotImplementedError`` when non-empty so the
                R79 TDD-scaffold xfail tests fail with a precise error
                shape rather than ``TypeError``.
            tool_result_overrides: ADR-026 §5.3 (R81 amendment, slice 3c)
                surface for fork-with-tool-result-substitution — the
                symmetric mirror of ``tool_input_overrides`` on the
                output half of the tool round-trip. Mapping
                ``tool_use_id → new_result_content``; replaces the
                ``ToolResultBlock.content`` payload on the child branch
                while preserving the JOIN anchor stamps verbatim. The
                value is treated as opaque JSON-serialisable Python
                (typically ``str`` or list of content blocks). ``None``
                (default) and ``{}`` are identity — byte-equivalent to
                R74 / R80 fork() with no §5.3 surface. **Implementation
                lands in R82**; R81 ships the kwarg as a no-op
                pass-through that raises ``NotImplementedError`` when
                non-empty so the R81 TDD-scaffold xfail tests fail with
                a precise error shape rather than ``TypeError``.
            child_thread_id: User-supplied logical thread id for the child
                run. Must differ from the parent run's thread id.
            reason: Optional free-form fork reason (persisted to ``Fork.reason``).
            task_description: Optional free-form description for the child Run.
            tags: Optional list of string tags for the child Run.

        Yields:
            :class:`ForkRef` with ``parent_run_id`` / ``at_node_id`` /
            ``child_thread_id`` populated immediately, plus two extra
            attributes set after ``fork_session`` returns:

            - ``sdk_session_id``: child SDK session UUID (use as
              ``ClaudeAgentOptions.resume``).
            - ``submit_runtime(rt)``: callback the user MUST invoke with
              their resumed ``ClaudeSDKClient`` (or an async-iterable of
              SDK ``Message``) before the ``with`` block exits.

            On exit, ``ref.child_run_id`` / ``ref.fork_id`` / ``ref.node_ids``
            are populated.
        """
        del runtime  # signature parity only; child driver via ref.submit_runtime

        # --- R80 (ADR-026 §5.2 slice 3b implementation) ---------------------
        # Validate `tool_input_overrides` *before* delegating to fork_session.
        # The kwarg is normalised to a (possibly empty) dict so downstream
        # logic can treat None and {} uniformly. An empty mapping is identity
        # — falls through with `_fork_overrides=None` so `_translate` does
        # not stamp any `state_after['tool_input']` keys (R74 byte-identity
        # contract preserved, enforced by `test_fork_without_overrides_is_identity`).
        normalised_overrides: dict[str, dict[str, Any]] = (
            dict(tool_input_overrides) if tool_input_overrides else {}
        )

        # --- R81 (ADR-026 §5.3 slice 3c TDD-scaffold pass-through) ----------
        # `tool_result_overrides` is accepted on the signature so R81's
        # strict-xfail tests fail with a precise error shape, not
        # ``TypeError: unexpected keyword argument``. Empty (`None`/`{}`)
        # is identity — falls through to the R74/R80 path verbatim. Non-
        # empty raises ``NotImplementedError`` until R82 swaps this for
        # the validation + child-side stamp pipeline. Validation surface,
        # stamp shape, and SQL recipes are specified in ADR-026 §5.3.
        if tool_result_overrides:
            raise NotImplementedError(
                "R82: §5.3 slice 3c not yet implemented "
                "(tool_result_overrides is a draft contract — see ADR-026 §5.3)"
            )

        # --- Pre-flight: load parent artifacts and validate ---
        parent_run = self._store.get_run(parent_run_id)
        if parent_run is None:
            raise AdapterError(
                f"AnthropicAgentsRecorder.fork: parent_run_id={parent_run_id!r} not found in store"
            )
        parent_node = self._store.get_node(at_node_id)
        if parent_node is None:
            raise AdapterError(
                f"AnthropicAgentsRecorder.fork: at_node_id={at_node_id!r} not found in store"
            )
        if parent_node.run_id != parent_run_id:
            raise AdapterError(
                f"AnthropicAgentsRecorder.fork: at_node_id={at_node_id!r} does "
                f"not belong to parent_run_id={parent_run_id!r}"
            )
        if child_thread_id == parent_run.adapter_thread_id:
            raise AdapterError(
                f"AnthropicAgentsRecorder.fork: child_thread_id={child_thread_id!r} "
                f"must differ from parent thread_id={parent_run.adapter_thread_id!r} "
                "(would overwrite parent SDK transcript file)"
            )

        # --- ADR-026 §5.2 (R80, slice 3b) validation pipeline ---------------
        # When `tool_input_overrides` is non-empty, validate every key
        # against the parent run's use-side keyset BEFORE delegating to
        # `claude_agent_sdk.fork_session()`. Three checks per ADR §5.2
        # #### Validation:
        #   1. Key must be a `str`.
        #   2. Key must appear in the union of tool-use ids declared by
        #      any AssistantMessage* Node in `parent_run_id` (singular
        #      `state_after['tool_use_id']` per R76 §5.1, or any element
        #      of plural `state_after['tool_use_ids']` per R77 §5.1.1).
        #   3. Key must NOT appear in `unmatched_tool_uses(store,
        #      parent_run_id)` — fork past an orphan use-side is a
        #      slice-3a→3b coupling pre-condition violation.
        # Validations raise `AdapterError` synchronously so the SDK fork
        # never receives an illegal override. Empty / None override
        # mapping skips the entire pipeline (identity fork).
        if normalised_overrides:
            # Late import to keep `tool_linkage` private — internal API
            # mutability is preserved (R79 F3 / ADR §5.2 cites by name).
            from chronos.queries.tool_linkage import (
                _ids_from_state_after,
                _is_use_side,
                unmatched_tool_uses,
            )

            parent_nodes = self._store.get_nodes_for_run(parent_run_id)
            use_keyset: set[str] = set()
            for n in parent_nodes:
                if _is_use_side(n):
                    use_keyset.update(_ids_from_state_after(n))

            orphan_nodes = unmatched_tool_uses(self._store, parent_run_id)
            orphan_keyset: set[str] = set()
            for n in orphan_nodes:
                orphan_keyset.update(_ids_from_state_after(n))

            for tu_id, new_input in normalised_overrides.items():
                if not isinstance(tu_id, str):
                    raise AdapterError(
                        "AnthropicAgentsRecorder.fork: tool_input_overrides key "
                        f"must be a str, got {type(tu_id).__name__}={tu_id!r}"
                    )
                if not isinstance(new_input, dict):
                    raise AdapterError(
                        "AnthropicAgentsRecorder.fork: tool_input_overrides value "
                        f"for key {tu_id!r} must be a dict, got "
                        f"{type(new_input).__name__}"
                    )
                if tu_id not in use_keyset:
                    raise AdapterError(
                        "AnthropicAgentsRecorder.fork: tool_input_overrides key "
                        f"{tu_id!r} is not declared by any AssistantMessage Node "
                        f"in parent_run_id={parent_run_id!r} (use-side keyset "
                        f"size={len(use_keyset)}). ADR-026 §5.2 validation #2."
                    )
                if tu_id in orphan_keyset:
                    raise AdapterError(
                        "AnthropicAgentsRecorder.fork: tool_input_overrides key "
                        f"{tu_id!r} is an orphan use-side tool_use_id (no "
                        "matching ToolResultBlock yet) — slice-3a→3b coupling "
                        "pre-condition: round-trip must close in parent run. "
                        "ADR-026 §5.2 validation #3."
                    )

        # --- Recover SDK seed coordinates from parent_node.state_after ---
        # record() (line 305-308) stamps {'uuid', 'session_id'} into state_after
        # whenever the SDK Message exposes them. AssistantMessage / ResultMessage
        # always do; SystemMessage / UserMessage may not — fork from those is
        # rejected with a clear error.
        parent_state = parent_node.state_after or {}
        parent_session_id = parent_state.get("session_id")
        parent_uuid = parent_state.get("uuid")
        if not isinstance(parent_session_id, str) or not parent_session_id:
            raise AdapterError(
                f"AnthropicAgentsRecorder.fork: parent node {at_node_id!r} "
                "has no SDK session_id in state_after — fork only valid from "
                "AssistantMessage / ResultMessage anchor nodes"
            )
        if not isinstance(parent_uuid, str) or not parent_uuid:
            raise AdapterError(
                f"AnthropicAgentsRecorder.fork: parent node {at_node_id!r} "
                "has no SDK message uuid in state_after — fork anchor must be "
                "a node whose source Message exposed `uuid`"
            )

        # --- Late import: claude_agent_sdk.fork_session is the SDK primitive ---
        # Late so unit tests can monkey-patch via sys.modules without paying
        # the real SDK import cost. Real callers already imported the SDK
        # to drive record().
        try:
            from claude_agent_sdk import fork_session as _fork_session
        except Exception as imp_exc:  # pragma: no cover — optional-dep precedent
            raise AdapterError(
                "AnthropicAgentsRecorder.fork: claude_agent_sdk.fork_session "
                f"unavailable ({imp_exc!r}). Install the optional `anthropic_agents` "
                "extra (>= 0.1.80)."
            ) from imp_exc

        try:
            fork_result = _fork_session(
                parent_session_id,
                up_to_message_id=parent_uuid,
                title=task_description,
            )
        except Exception as fork_exc:
            raise AdapterError(
                "AnthropicAgentsRecorder.fork: fork_session() failed for "
                f"session_id={parent_session_id!r} up_to={parent_uuid!r}: {fork_exc!r}"
            ) from fork_exc
        child_sdk_session_id = getattr(fork_result, "session_id", None)
        if not isinstance(child_sdk_session_id, str) or not child_sdk_session_id:
            raise AdapterError(
                "AnthropicAgentsRecorder.fork: fork_session() returned no "
                f"child session_id (got {fork_result!r})"
            )

        # --- Build the ForkRef + user-callable hook for runtime submission ---
        ref = ForkRef(
            parent_run_id=parent_run_id,
            at_node_id=at_node_id,
            child_thread_id=child_thread_id,
        )
        # Attach SDK child id + submit_runtime hook (duck-typed extras, mirrors
        # AutoGen recorder's `submit_result` precedent).
        ref.sdk_session_id = child_sdk_session_id  # type: ignore[attr-defined]
        captured: dict[str, Any] = {"runtime": None}

        def submit_runtime(rt: Any) -> None:
            captured["runtime"] = rt

        ref.submit_runtime = submit_runtime  # type: ignore[attr-defined]

        # Reset buffer so the child run gets a clean slate.
        with self._lock:
            self._buffer.clear()

        # --- User block runs ClaudeSDKClient(resume=child_sdk_session_id) ---
        child_run_id = str(uuid.uuid4())
        started = datetime.now(UTC)
        exc: BaseException | None = None
        # ADR-026 §5.2 (R80): expose normalised overrides to `_translate`
        # for the duration of the child stream consumption. Set to None
        # (not the empty dict) when the mapping is empty so the stamping
        # branch is a single `is None` short-circuit and identity forks
        # incur zero per-Node cost. Cleared in `finally` to ensure a
        # subsequent `record()` on the same recorder runs unaffected.
        self._fork_overrides = normalised_overrides if normalised_overrides else None
        try:
            yield ref
            child_runtime = captured["runtime"]
            if child_runtime is not None:
                try:
                    source = self._resolve_iterator(child_runtime)
                    asyncio.run(self._consume(source))
                except AdapterError:
                    raise
                except Exception as e:
                    raise AdapterError(
                        f"AnthropicAgentsRecorder.fork: failure consuming "
                        f"child message stream: {e!r}"
                    ) from e
        except BaseException as e:
            exc = e
            raise
        finally:
            self._fork_overrides = None  # R80 §5.2: clear always, even on error
            ended = datetime.now(UTC)
            status = RunStatus.FAILED if exc is not None else RunStatus.COMPLETED
            child_run = Run(
                id=child_run_id,
                adapter=self._adapter_name,
                adapter_thread_id=child_thread_id,
                status=status,
                started_at=started,
                ended_at=ended,
                task_description=task_description,
                tags=list(tags) if tags else [],
            )
            fork_row = Fork(
                id=str(uuid.uuid4()),
                parent_run_id=parent_run_id,
                parent_node_id=at_node_id,
                child_run_id=child_run_id,
                edited_fields=dict(overrides) if overrides else {},
                reason=reason,
            )
            try:
                # Atomic write: child Run + Nodes + Fork row in one transaction.
                # We inline _drain_buffer_to_store's body here (rather than
                # call it) because store.transaction() does not support
                # nesting (raw BEGIN/COMMIT) and we need put_fork() inside
                # the same atomic boundary as the child nodes (LangGraph
                # precedent — _fork_from_history line 365).
                with self._lock:
                    pending = list(self._buffer)
                    self._buffer.clear()
                with self._store.transaction():
                    self._store.put_run(child_run)
                    for idx, p in enumerate(pending):
                        node_id = str(uuid.uuid4())
                        usage_obj: Usage | None = None
                        if p.usage is not None:
                            try:
                                usage_obj = Usage(**p.usage)
                            except Exception:
                                usage_obj = None
                        node = Node(
                            id=node_id,
                            run_id=child_run.id,
                            step_index=idx,
                            node_name=p.node_name,
                            kind=p.kind,
                            state_after=p.state_after,
                            model_name=p.model_name,
                            usage=usage_obj,
                            tool_name=p.tool_name,
                            tool_input=p.tool_input,
                            tool_output=p.tool_output,
                            error_message=p.error_message,
                        )
                        self._store.put_node(node)
                        ref.node_ids.append(node_id)
                    self._store.put_fork(fork_row)
                ref.child_run_id = child_run_id
                ref.fork_id = fork_row.id
            except Exception as drain_exc:  # pragma: no cover — defensive
                if exc is None:
                    raise
                ref.node_ids.clear()
                _ = drain_exc


__all__ = [
    "_DEFAULT_KIND_MAP",
    "AnthropicAgentsRecorder",
    "AnthropicMessageIterable",
    "_PendingNode",
]
