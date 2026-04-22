"""LangGraph recorder adapter.

This module converts a completed LangGraph run into Chronos's canonical
:class:`Run` + :class:`Node` records, with no manual reshape from the user.

See :doc:`docs/decisions/ADR-004-langgraph-snapshot-mapping` for the exact
mapping algorithm and empirical evidence it's based on.

Public API
----------

    >>> from chronos.adapters.langgraph import LangGraphRecorder
    >>> from chronos.store import SqliteStore
    >>>
    >>> with SqliteStore.open("chronos.db") as store:
    ...     recorder = LangGraphRecorder(store)
    ...     with recorder.record(graph, thread_id="t1") as run_ref:
    ...         graph.invoke(initial_state, {"configurable": {"thread_id": "t1"}})
    ...     # on context exit, the adapter walks the state history and
    ...     # persists a Run + one Node per executed graph step.
    >>> run_ref.run_id  # UUID str of the recorded Run
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from chronos.core.models import Node, NodeKind, Run, RunStatus

if TYPE_CHECKING:
    from chronos.store import SqliteStore


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class AdapterError(RuntimeError):
    """Raised when the LangGraph snapshot structure doesn't match expectations.

    Usually indicates a LangGraph version drift — the spike 4 shape we
    depend on may have changed. Re-run spike 4 and update ADR-004 if so.
    """


# ---------------------------------------------------------------------------
# Reference returned to the ``with recorder.record(...)`` block
# ---------------------------------------------------------------------------


@dataclass
class RunRef:
    """Mutable handle users can read after the ``record`` block exits.

    Before ``__exit__``, ``run_id`` is None (we can't commit until the user
    actually invokes the graph). After exit it holds the persisted Run's id
    so callers can query the store.
    """

    thread_id: str
    run_id: str | None = None
    node_ids: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# The adapter itself
# ---------------------------------------------------------------------------


class LangGraphRecorder:
    """Recorder: translates LangGraph checkpoints → Chronos records.

    Instantiate once per process; reuse across many runs. The adapter is
    stateless between ``record()`` calls.

    Args:
        store: A :class:`SqliteStore` to persist into.
        kind_map: Optional dict mapping ``node_name -> NodeKind``. Nodes not
            in the map default to :attr:`NodeKind.FN`. Pass
            ``{"plan": NodeKind.LLM, "search_tool": NodeKind.TOOL, ...}`` to
            record richer semantics.
    """

    def __init__(
        self,
        store: SqliteStore,
        *,
        kind_map: dict[str, NodeKind] | None = None,
    ) -> None:
        self._store = store
        self._kind_map: dict[str, NodeKind] = dict(kind_map or {})

    # ------------------------------------------------------------------
    # Public context manager
    # ------------------------------------------------------------------

    @contextmanager
    def record(
        self,
        graph: Any,
        *,
        thread_id: str,
        task_description: str | None = None,
        tags: list[str] | None = None,
    ) -> Iterator[RunRef]:
        """Capture a LangGraph execution for the given ``thread_id``.

        The user is responsible for actually invoking ``graph`` with a
        matching config inside the ``with`` block. We reconstruct the run
        from ``graph.get_state_history()`` on exit.

        Args:
            graph: A compiled LangGraph ``StateGraph``.
            thread_id: Must match ``config["configurable"]["thread_id"]``
                passed to ``graph.invoke()`` inside the block.
            task_description: Optional human-readable label for the run.
            tags: Optional list of tags to store on the Run.

        Yields:
            A :class:`RunRef` that will have its ``run_id`` populated on exit.

        Raises:
            AdapterError: If no snapshots are found for ``thread_id`` (the
                user forgot to invoke) or if the snapshot structure is
                unexpected.
        """
        ref = RunRef(thread_id=thread_id)
        try:
            yield ref
        except Exception:
            # User's graph.invoke() raised. We still try to record whatever
            # snapshots exist, marking the run as FAILED. Re-raise after.
            self._persist_from_history(
                graph,
                ref,
                status=RunStatus.FAILED,
                task_description=task_description,
                tags=tags or [],
            )
            raise
        else:
            self._persist_from_history(
                graph,
                ref,
                status=RunStatus.COMPLETED,
                task_description=task_description,
                tags=tags or [],
            )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _persist_from_history(
        self,
        graph: Any,
        ref: RunRef,
        *,
        status: RunStatus,
        task_description: str | None,
        tags: list[str],
    ) -> None:
        """Walk graph.get_state_history() and write Run + Nodes to the store.

        Implements the algorithm from ADR-004 §"Decision — The Mapping
        Algorithm". Any structural deviation → :class:`AdapterError`.
        """
        cfg: Any = {"configurable": {"thread_id": ref.thread_id}}

        # newest-first → oldest-first (the natural reading order)
        snapshots = list(reversed(list(graph.get_state_history(cfg))))

        if not snapshots:
            # User didn't actually invoke anything; nothing to record.
            # (Alternatively: create an empty Run. We choose to no-op
            #  so scripts that fail before invoke don't pollute the DB.)
            return

        # --- Sanity: the first snapshot should be the `source=input` placeholder.
        first = snapshots[0]
        first_source = _meta_source(first)
        if first_source != "input":
            raise AdapterError(
                f"expected first snapshot source='input', got {first_source!r}. "
                "LangGraph version may have changed — re-run spike4 and "
                "update ADR-004."
            )

        # Build a provisional Run. We'll fill in final_state after the loop.
        run_id = str(uuid.uuid4())
        started_at = _parse_created_at(first)
        last_snapshot = snapshots[-1]
        ended_at = _parse_created_at(last_snapshot)

        # initial_state: the values on the very first executed-node snapshot.
        # That's snapshots[1] (index 0 is the input placeholder). If the user
        # didn't actually invoke, we already returned above.
        initial_state = dict(snapshots[1].values) if len(snapshots) >= 2 else {}

        run = Run(
            id=run_id,
            adapter="langgraph",
            adapter_thread_id=ref.thread_id,
            status=status,
            started_at=started_at,
            ended_at=ended_at,
            task_description=task_description,
            initial_state=initial_state,
            final_state=_coerce_state(last_snapshot.values),
            tags=list(tags),
            metadata={
                "checkpoint_ns": _ckpt_ns(first),
                "num_snapshots": len(snapshots),
            },
        )

        # --- Build nodes by pairing pre/post snapshots ---
        node_rows: list[Node] = []
        prev_node_id: str | None = None

        # Iterate over pairs (pre, post) where pre is a checkpoint whose
        # `tasks[0]` tells us which node is about to run, and `post.values`
        # is the state after it ran.
        for i in range(1, len(snapshots) - 1):
            pre = snapshots[i]
            post = snapshots[i + 1]

            if not pre.tasks:
                # Shouldn't happen for well-formed runs; skip defensively.
                continue

            task = pre.tasks[0]
            node_name = getattr(task, "name", None)
            if not node_name:
                raise AdapterError(f"snapshot[{i}].tasks[0] has no .name — LangGraph API changed?")

            step_idx = _meta_step(pre)
            if step_idx is None or step_idx < 0:
                # step=-1 is the input placeholder — should have been at i=0.
                continue

            kind = self._kind_map.get(node_name, NodeKind.FN)

            node = Node(
                id=str(uuid.uuid4()),
                run_id=run_id,
                step_index=step_idx,
                node_name=node_name,
                kind=kind,
                parent_node_id=prev_node_id,
                started_at=_parse_created_at(pre),
                ended_at=_parse_created_at(post),
                state_after=_coerce_state(post.values),
                metadata={
                    "checkpoint_id": _ckpt_id(post),
                    "parent_checkpoint_id": _ckpt_id(pre),
                    "langgraph_task_id": getattr(task, "id", None),
                },
            )
            node_rows.append(node)
            prev_node_id = node.id

        # --- Persist atomically ---
        with self._store.transaction():
            self._store.put_run(run)
            for node in node_rows:
                self._store.put_node(node)

        ref.run_id = run_id
        ref.node_ids = [n.id for n in node_rows]


# ---------------------------------------------------------------------------
# Snapshot field accessors (centralised so API drift is a one-place fix)
# ---------------------------------------------------------------------------


def _meta_source(snap: Any) -> str | None:
    md = getattr(snap, "metadata", None)
    if isinstance(md, dict):
        return md.get("source")
    return None


def _meta_step(snap: Any) -> int | None:
    md = getattr(snap, "metadata", None)
    if isinstance(md, dict):
        val = md.get("step")
        if isinstance(val, int):
            return val
    return None


def _parse_created_at(snap: Any) -> datetime:
    raw = getattr(snap, "created_at", None)
    if isinstance(raw, str):
        return datetime.fromisoformat(raw)
    if isinstance(raw, datetime):
        return raw if raw.tzinfo else raw.replace(tzinfo=UTC)
    # Fallback: unknown shape — use now() so we don't blow up the whole run.
    return datetime.now(UTC)


def _ckpt_id(snap: Any) -> str | None:
    cfg = getattr(snap, "config", None) or {}
    return (cfg.get("configurable") or {}).get("checkpoint_id")


def _ckpt_ns(snap: Any) -> str:
    cfg = getattr(snap, "config", None) or {}
    ns = (cfg.get("configurable") or {}).get("checkpoint_ns", "")
    return str(ns) if ns is not None else ""


def _coerce_state(values: Any) -> dict[str, Any]:
    """LangGraph usually gives us a dict; be defensive for edge types."""
    if isinstance(values, dict):
        return dict(values)
    return {"__non_dict__": repr(values)}


__all__ = ["AdapterError", "LangGraphRecorder", "RunRef"]
