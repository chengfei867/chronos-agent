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
from chronos.core.models import Node, NodeKind, Run, RunStatus, Usage

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

        # Add common metadata fields to state_after
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
        # ToolResultBlock arrives inside UserMessage.content per R69 §1.5
        if cls == "UserMessage" and isinstance(content, list):
            result_blocks = [b for b in content if type(b).__name__ == "ToolResultBlock"]
            if len(result_blocks) == 1:
                blk = result_blocks[0]
                if getattr(blk, "is_error", False):
                    error_message = repr(getattr(blk, "content", ""))[:500]
                else:
                    raw_out = getattr(blk, "content", None)
                    if isinstance(raw_out, dict):
                        tool_output = dict(raw_out)
                    elif raw_out is not None:
                        tool_output = {"text": repr(raw_out)[:500]}

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
        child_thread_id: str,
        reason: str | None = None,
        task_description: str | None = None,
        tags: list[str] | None = None,
    ) -> Iterator[ForkRef]:
        """R73 stub — delegates to ``claude_agent_sdk.fork_session()``.

        Per R69 spike #1: the SDK ships ``fork_session(session_id,
        up_to_message_id=...)`` as a transcript-JSONL rewrite primitive.
        R73 will: (a) call ``fork_session`` to materialise the child
        transcript; (b) attach the recorder to the resulting session;
        (c) emit a synthetic FORK ``NodeKind`` node and ``Fork`` row;
        (d) replay forward via ``ClaudeSDKClient`` against the forked
        session-id.

        R70 deliberately leaves this unimplemented to avoid silently
        partial fork semantics.
        """
        del runtime, parent_run_id, at_node_id, overrides, child_thread_id
        del reason, task_description, tags
        raise NotImplementedError(
            "AnthropicAgentsRecorder.fork(): scheduled for R73. Per ADR-026 §6 "
            "rollout plan, fork delegates to "
            "`claude_agent_sdk._internal.session_mutations.fork_session()` "
            "(R69 spike #1 finding). Slice 1 (R70-R74) lands record-only at "
            "v0.7.0a1 (R72), full record + fork at v0.7.0 (R74)."
        )
        yield  # pragma: no cover — keeps mypy happy on Iterator return type


__all__ = [
    "_DEFAULT_KIND_MAP",
    "AnthropicAgentsRecorder",
    "AnthropicMessageIterable",
    "_PendingNode",
]
