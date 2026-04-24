"""AutoGen adapter recorder — ADR-017 sync-wrap strategy.

See :mod:`chronos.adapters.autogen` package docstring and ADR-017 for the
architectural rationale. This module implements the record half of
:class:`~chronos.adapters.protocols.RecorderProtocol`; fork raises
:class:`AdapterError` (Phase 3 candidate).

Message → Node mapping
======================

Each ``BaseChatMessage`` in ``TaskResult.messages`` produces one Node.
Mapping rules (can be overridden per-adapter via ``kind_map``):

+-----------------------------------+-------------------+
| AutoGen message class             | Default NodeKind  |
+===================================+===================+
| ``TextMessage`` (source=user)     | ``FN``            |
+-----------------------------------+-------------------+
| ``TextMessage`` (source=agent)    | ``LLM``           |
+-----------------------------------+-------------------+
| ``ToolCallRequestEvent``          | ``TOOL``          |
+-----------------------------------+-------------------+
| ``ToolCallExecutionEvent``        | ``TOOL``          |
+-----------------------------------+-------------------+
| ``ToolCallSummaryMessage``        | ``TOOL``          |
+-----------------------------------+-------------------+
| ``HandoffMessage``                | ``ROUTER``        |
+-----------------------------------+-------------------+
| anything else                     | ``FN``            |
+-----------------------------------+-------------------+

Usage
=====

``BaseChatMessage.models_usage`` (when set) carries ``prompt_tokens`` and
``completion_tokens`` as a :class:`autogen_core.models.RequestUsage`. The
recorder copies these verbatim into :class:`~chronos.core.models.Usage`.
AutoGen does not currently report reasoning-token usage, so
``usage.reasoning_tokens`` stays at 0.

State snapshots
===============

For a message-based framework there is no "state dict" equivalent to
LangGraph's ``StateSnapshot.values``. We synthesize ``state_after`` as
``{"messages": [...serialized messages up to and including this one...]}``
so downstream consumers (diff, fork, UI) see a cumulative transcript —
this mirrors AutoGen's own execution model (message history is the state).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from chronos.adapters.protocols import AdapterError, ForkRef, RunRef
from chronos.core.models import Node, NodeKind, Run, RunStatus, Usage
from chronos.store import SqliteStore

if TYPE_CHECKING:
    pass


# ---------------------------------------------------------------------------
# Default message-class → NodeKind mapping (see module docstring)
# ---------------------------------------------------------------------------

_DEFAULT_KIND_MAP: dict[str, NodeKind] = {
    "TextMessage": NodeKind.LLM,  # will downgrade to FN for source=user below
    "ToolCallRequestEvent": NodeKind.TOOL,
    "ToolCallExecutionEvent": NodeKind.TOOL,
    "ToolCallSummaryMessage": NodeKind.TOOL,
    "HandoffMessage": NodeKind.ROUTER,
    "MultiModalMessage": NodeKind.LLM,
    "StopMessage": NodeKind.END,
}


def _message_cls_name(msg: Any) -> str:
    """Return the class name of an AutoGen message, defensively.

    Uses ``type(msg).__name__`` rather than ``msg.type`` (an instance attr
    on some AutoGen versions) to avoid coupling to a shape that shifted
    between 0.4 and 0.7.
    """
    return type(msg).__name__


def _serialize_message(msg: Any) -> dict[str, Any]:
    """Best-effort JSON-safe representation of a ``BaseChatMessage``.

    AutoGen 0.7 messages are pydantic models with a ``dump()`` / ``model_dump()``
    method. We prefer ``model_dump(mode='python')`` but degrade gracefully
    for duck-typed stubs (used in tests).
    """
    if hasattr(msg, "model_dump"):
        try:
            return dict(msg.model_dump(mode="python"))
        except Exception:
            pass
    # Duck-typed fallback — pull the usual fields.
    out: dict[str, Any] = {
        "cls": _message_cls_name(msg),
    }
    for attr in ("source", "content", "type"):
        if hasattr(msg, attr):
            out[attr] = getattr(msg, attr)
    return out


def _extract_usage(msg: Any) -> Usage | None:
    """Read ``msg.models_usage`` and coerce to :class:`Usage`, or ``None``."""
    raw = getattr(msg, "models_usage", None)
    if raw is None:
        return None
    prompt = getattr(raw, "prompt_tokens", None)
    completion = getattr(raw, "completion_tokens", None)
    if prompt is None and completion is None:
        return None
    return Usage(
        prompt_tokens=int(prompt or 0),
        completion_tokens=int(completion or 0),
        reasoning_tokens=0,
    )


# ---------------------------------------------------------------------------
# Recorder
# ---------------------------------------------------------------------------


class AutoGenRecorder:
    """Records AutoGen ``Team.run()`` executions into a :class:`SqliteStore`.

    Conforms to ADR-016 ``RecorderProtocol`` at the signature level.
    Execution does **not** run inside the CM — AutoGen's async API forces
    the user to call ``asyncio.run(team.run(...))`` themselves. The
    recorder observes the returned ``TaskResult`` via either:

    1. ``ref.submit_result(result)`` inside the ``with`` block (preferred).
    2. ``runtime.messages`` (AutoGen's own history buffer) as a fallback
       on exit if ``submit_result`` was not called.

    If both are absent (e.g. the user code errored before producing a
    result), the recorder persists a Run with ``status=FAILED`` and no
    Node rows.

    Args:
        store: Persistence target.
        adapter_name: Written to ``Run.adapter``. Default ``"autogen"``.
        kind_map: Optional per-message-class override. Merged over
            :data:`_DEFAULT_KIND_MAP`.
    """

    def __init__(
        self,
        store: SqliteStore,
        *,
        adapter_name: str = "autogen",
        kind_map: dict[str, NodeKind] | None = None,
    ) -> None:
        self._store = store
        self._adapter_name = adapter_name
        self._kind_map: dict[str, NodeKind] = {**_DEFAULT_KIND_MAP}
        if kind_map:
            self._kind_map.update(kind_map)

    # ------------------------------------------------------------------
    # kind resolution
    # ------------------------------------------------------------------

    def _kind_for(self, msg: Any) -> NodeKind:
        cls = _message_cls_name(msg)
        default = self._kind_map.get(cls, NodeKind.FN)
        # Special case: a TextMessage from source='user' is really a
        # human input, not an LLM output. Demote to FN.
        if cls == "TextMessage" and getattr(msg, "source", None) == "user":
            return NodeKind.FN
        return default

    # ------------------------------------------------------------------
    # record() — sync CM (ADR-017)
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
        """Record an AutoGen ``Team.run()`` execution.

        The user is expected to call ``asyncio.run(team.run(...))`` inside
        the ``with`` block and pass the returned ``TaskResult`` via
        :meth:`RunRef.submit_result` (attached below). If they don't, we
        fall back to reading ``runtime.messages`` (AutoGen teams keep the
        history buffer as an instance attr after run() completes).

        Args:
            runtime: The AutoGen ``Team`` (or any object exposing
                ``.messages``/``.model_dump`` for testing).
            thread_id: User-supplied identifier. Persisted as
                ``Run.adapter_thread_id``.
            task_description: Optional free-form description.
            tags: Optional list of string tags.

        Yields:
            A :class:`RunRef` extended with :meth:`submit_result`. On
            successful exit ``ref.run_id`` and ``ref.node_ids`` are
            populated. On exception inside the ``with`` block a failed
            Run is persisted and the exception re-raised.
        """
        ref = RunRef(thread_id=thread_id)

        # Stash for post-exit reading; a light hack that avoids subclassing
        # RunRef in the public API.
        captured: dict[str, Any] = {"result": None}

        def submit_result(result: Any) -> None:
            captured["result"] = result

        # Attach as a method-like attribute. mypy: users pass a duck-typed
        # object anyway; recorder.py doesn't rely on static typing here.
        ref.submit_result = submit_result  # type: ignore[attr-defined]

        try:
            yield ref
        except AdapterError:
            self._persist_failed_shell(
                ref=ref,
                task_description=task_description,
                tags=tags or [],
                error="adapter error inside with-block",
            )
            raise
        except Exception as exc:
            self._persist_failed_shell(
                ref=ref,
                task_description=task_description,
                tags=tags or [],
                error=str(exc),
            )
            raise

        # Success path — resolve messages via submitted result, else runtime.
        messages = _resolve_messages(captured["result"], runtime)
        self._persist_run_and_nodes(
            ref=ref,
            messages=messages,
            task_description=task_description,
            tags=tags or [],
            status=RunStatus.COMPLETED,
        )

    # ------------------------------------------------------------------
    # fork() — not implemented in v0.2.0 (ADR-017 §Decision)
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
        """Not implemented — see ADR-017 §Decision.

        AutoGen fork requires re-seeding agent message history and
        re-invoking the team, which in turn requires deterministic
        tool/agent seeding that the recorder cannot transparently
        provide. Tracked as a Phase 3 candidate ADR (roadmap §Phase 3).
        """
        raise AdapterError(
            "AutoGenRecorder.fork() is not implemented in v0.2.x — "
            "tracked in roadmap Phase 3. See ADR-017 §Decision."
        )
        # Unreachable but makes mypy happy about the generator contract.
        yield ForkRef(  # pragma: no cover
            parent_run_id=parent_run_id,
            at_node_id=at_node_id,
            child_thread_id=child_thread_id,
        )

    # ------------------------------------------------------------------
    # persistence helpers
    # ------------------------------------------------------------------

    def _persist_run_and_nodes(
        self,
        *,
        ref: RunRef,
        messages: list[Any],
        task_description: str | None,
        tags: list[str],
        status: RunStatus,
    ) -> None:
        run_id = str(uuid.uuid4())
        now = datetime.now(UTC)

        # Build the cumulative message list once so we can write the Run
        # as COMPLETED on first insert and never re-put_run(). The sqlite
        # store uses INSERT OR REPLACE on runs, and nodes.run_id carries
        # ON DELETE CASCADE — a second put_run(run) would silently drop
        # every node row we just inserted. See R33 autogen adapter debug
        # for the full story.
        serialized: list[dict[str, Any]] = [_serialize_message(m) for m in messages]
        final_state = {"messages": list(serialized)}

        run = Run(
            id=run_id,
            adapter=self._adapter_name,
            adapter_thread_id=ref.thread_id,
            status=status,
            started_at=now,
            ended_at=now,
            task_description=task_description,
            initial_state={},
            final_state=final_state,
            tags=list(tags),
        )
        node_ids: list[str] = []
        with self._store.transaction():
            self._store.put_run(run)

            prev_node_id: str | None = None
            for step_index, msg in enumerate(messages):
                node_id = str(uuid.uuid4())
                usage = _extract_usage(msg)
                source = getattr(msg, "source", None) or "unknown"
                cls_name = _message_cls_name(msg)
                cumulative = serialized[: step_index + 1]
                node = Node(
                    id=node_id,
                    run_id=run_id,
                    step_index=step_index,
                    node_name=f"{source}:{cls_name}",
                    kind=self._kind_for(msg),
                    parent_node_id=prev_node_id,
                    started_at=now,
                    ended_at=now,
                    state_after={"messages": list(cumulative)},
                    model_name=(getattr(msg, "model_name", None) if usage is not None else None),
                    usage=usage,
                )
                self._store.put_node(node)
                node_ids.append(node_id)
                prev_node_id = node_id

        ref.run_id = run_id
        ref.node_ids = node_ids

    def _persist_failed_shell(
        self,
        *,
        ref: RunRef,
        task_description: str | None,
        tags: list[str],
        error: str,
    ) -> None:
        run_id = str(uuid.uuid4())
        now = datetime.now(UTC)
        run = Run(
            id=run_id,
            adapter=self._adapter_name,
            adapter_thread_id=ref.thread_id,
            status=RunStatus.FAILED,
            started_at=now,
            ended_at=now,
            task_description=task_description,
            initial_state={},
            final_state=None,
            tags=list(tags),
            metadata={"error": error},
        )
        with self._store.transaction():
            self._store.put_run(run)
        ref.run_id = run_id
        ref.node_ids = []


# ---------------------------------------------------------------------------
# helpers used from record() — at module scope for testability
# ---------------------------------------------------------------------------


def _resolve_messages(submitted: Any, runtime: Any) -> list[Any]:
    """Resolve the message list to record.

    Priority: explicit ``submit_result`` wins; fallback to ``runtime.messages``
    (AutoGen ``Team`` keeps the history buffer after ``run()`` completes);
    else empty list (recorded Run will have zero Nodes but still a Run row
    for visibility).
    """
    if submitted is not None:
        msgs = getattr(submitted, "messages", None)
        if msgs is not None:
            return list(msgs)
    # Fallback: try the runtime's own message buffer.
    msgs = getattr(runtime, "messages", None)
    if msgs is not None:
        return list(msgs)
    return []
