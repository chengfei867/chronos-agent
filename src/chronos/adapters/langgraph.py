"""LangGraph recorder adapter.

This module converts a completed LangGraph run into Chronos's canonical
:class:`Run` + :class:`Node` records, with no manual reshape from the user.

See :doc:`docs/decisions/ADR-004-langgraph-snapshot-mapping` for the mapping
algorithm on *original* threads and :doc:`docs/decisions/ADR-005-fork-semantics`
for the fork mapping on *forked* threads.

Public API
----------

Record an original run::

    >>> with recorder.record(graph, thread_id="t1") as run_ref:
    ...     graph.invoke(initial_state, {"configurable": {"thread_id": "t1"}})
    >>> run_ref.run_id

Fork an existing run::

    >>> with recorder.fork(
    ...     parent_run_id=run_ref.run_id,
    ...     at_node_id=some_node_id,
    ...     overrides={"research": "alternative"},
    ...     child_thread_id="t1-fork",
    ... ) as fork_ref:
    ...     graph.invoke(None, {"configurable": {"thread_id": "t1-fork"}})
    >>> fork_ref.child_run_id, fork_ref.fork_id
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from chronos.core.models import Fork, Node, NodeKind, Run, RunStatus

if TYPE_CHECKING:
    from chronos.store import SqliteStore


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class AdapterError(RuntimeError):
    """Raised when the LangGraph snapshot structure doesn't match expectations.

    Usually indicates a LangGraph version drift — the spike 4 / spike 5 shape
    we depend on may have changed. Re-run the spikes and update the ADRs if so.
    """


# ---------------------------------------------------------------------------
# References returned to user code
# ---------------------------------------------------------------------------


@dataclass
class RunRef:
    """Mutable handle returned from :meth:`LangGraphRecorder.record`.

    Populated on context-manager exit: ``run_id`` becomes the UUID of the
    persisted Run, ``node_ids`` lists the persisted Nodes in step order.
    """

    thread_id: str
    run_id: str | None = None
    node_ids: list[str] = field(default_factory=list)


@dataclass
class ForkRef:
    """Mutable handle returned from :meth:`LangGraphRecorder.fork`.

    Populated on context-manager exit with the child Run's id, the Fork
    record id, and the persisted child-side Node ids.
    """

    parent_run_id: str
    at_node_id: str
    child_thread_id: str
    child_run_id: str | None = None
    fork_id: str | None = None
    node_ids: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# The adapter itself
# ---------------------------------------------------------------------------


class LangGraphRecorder:
    """Translates LangGraph checkpoints → Chronos records (record + fork).

    Instantiate once per process; reuse across many runs. The adapter is
    stateless between ``record()`` / ``fork()`` calls — all state lives in
    the injected :class:`SqliteStore`.

    Args:
        store: A :class:`SqliteStore` to persist into.
        kind_map: Optional dict mapping ``node_name -> NodeKind``. Nodes not
            in the map default to :attr:`NodeKind.FN`.
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
    # record() — original runs (ADR-004)
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

        The user is responsible for invoking ``graph`` inside the
        ``with`` block with a matching config. We reconstruct the run
        from ``graph.get_state_history()`` on exit.
        """
        ref = RunRef(thread_id=thread_id)
        try:
            yield ref
        except Exception:
            self._record_from_history(
                graph,
                ref,
                status=RunStatus.FAILED,
                task_description=task_description,
                tags=tags or [],
            )
            raise
        else:
            self._record_from_history(
                graph,
                ref,
                status=RunStatus.COMPLETED,
                task_description=task_description,
                tags=tags or [],
            )

    # ------------------------------------------------------------------
    # fork() — forked runs (ADR-005)
    # ------------------------------------------------------------------

    @contextmanager
    def fork(
        self,
        graph: Any,
        *,
        parent_run_id: str,
        at_node_id: str,
        overrides: dict[str, Any] | None = None,
        child_thread_id: str,
        reason: str | None = None,
        task_description: str | None = None,
        tags: list[str] | None = None,
    ) -> Iterator[ForkRef]:
        """Fork a prior recorded run at a given node, with state overrides.

        On enter, we seed ``child_thread_id`` with the parent node's
        ``state_after`` merged with ``overrides``, using
        ``graph.update_state(as_node=<parent_node_name>)``. The user is
        then expected to call ``graph.invoke(None, cfg_child)`` to let
        the graph continue from the seed.

        On exit, we walk ``graph.get_state_history(cfg_child)``, persist
        a child :class:`Run` + :class:`Node` rows + a :class:`Fork`
        linkage record. See ADR-005 for the full algorithm.
        """
        overrides = dict(overrides or {})

        # --- Pre-flight: load parent artifacts and validate ---
        parent_run = self._store.get_run(parent_run_id)
        if parent_run is None:
            raise AdapterError(f"parent_run_id={parent_run_id!r} not found in store")

        parent_node = self._store.get_node(at_node_id)
        if parent_node is None:
            raise AdapterError(f"at_node_id={at_node_id!r} not found in store")
        if parent_node.run_id != parent_run_id:
            raise AdapterError(
                f"at_node_id={at_node_id!r} does not belong to parent_run_id={parent_run_id!r}"
            )

        if child_thread_id == parent_run.adapter_thread_id:
            raise AdapterError(
                f"child_thread_id={child_thread_id!r} must differ from parent "
                f"thread_id={parent_run.adapter_thread_id!r} (would overwrite parent checkpoints)"
            )

        # --- Build seed state: parent node's state_after + overrides ---
        seeded_state = dict(parent_node.state_after or {})
        seeded_state.update(overrides)

        cfg_child: Any = {"configurable": {"thread_id": child_thread_id}}

        # Seed the new thread: pretend <parent_node.node_name> just produced this state.
        graph.update_state(cfg_child, seeded_state, as_node=parent_node.node_name)

        ref = ForkRef(
            parent_run_id=parent_run_id,
            at_node_id=at_node_id,
            child_thread_id=child_thread_id,
        )

        # --- User runs graph.invoke(None, cfg_child) inside the block ---
        status = RunStatus.COMPLETED
        failure: BaseException | None = None
        try:
            yield ref
        except BaseException as exc:
            status = RunStatus.FAILED
            failure = exc

        # --- Teardown: persist child Run + Nodes + Fork record ---
        self._fork_from_history(
            graph,
            ref,
            parent_run=parent_run,
            parent_node=parent_node,
            overrides=overrides,
            reason=reason,
            status=status,
            task_description=task_description,
            tags=tags or [],
        )

        if failure is not None:
            raise failure

    # ------------------------------------------------------------------
    # Internal: record() pipeline
    # ------------------------------------------------------------------

    def _record_from_history(
        self,
        graph: Any,
        ref: RunRef,
        *,
        status: RunStatus,
        task_description: str | None,
        tags: list[str],
    ) -> None:
        cfg: Any = {"configurable": {"thread_id": ref.thread_id}}
        snapshots = list(reversed(list(graph.get_state_history(cfg))))

        if not snapshots:
            return  # nothing to record (user never invoked)

        first_source = _meta_source(snapshots[0])
        if first_source != "input":
            raise AdapterError(
                f"expected first snapshot source='input', got {first_source!r}. "
                "LangGraph version may have changed — re-run spike4 and update ADR-004."
            )

        # For an original run, the input placeholder (idx 0) is NOT a Node;
        # we start real nodes at idx 1. initial_state lives on idx 1's values.
        initial_state = (
            dict(snapshots[1].values)
            if len(snapshots) >= 2 and isinstance(snapshots[1].values, dict)
            else {}
        )
        run_id = str(uuid.uuid4())
        run, nodes = self._build_run_and_nodes(
            snapshots=snapshots,
            run_id=run_id,
            thread_id=ref.thread_id,
            status=status,
            task_description=task_description,
            tags=tags,
            initial_state=initial_state,
            loop_start=1,  # skip the input placeholder
            first_step_index=0,  # child of nothing; start at 0
            first_parent_node_id=None,
            extra_metadata={},
        )

        with self._store.transaction():
            self._store.put_run(run)
            for n in nodes:
                self._store.put_node(n)

        ref.run_id = run_id
        ref.node_ids = [n.id for n in nodes]

    # ------------------------------------------------------------------
    # Internal: fork() pipeline
    # ------------------------------------------------------------------

    def _fork_from_history(
        self,
        graph: Any,
        ref: ForkRef,
        *,
        parent_run: Run,
        parent_node: Node,
        overrides: dict[str, Any],
        reason: str | None,
        status: RunStatus,
        task_description: str | None,
        tags: list[str],
    ) -> None:
        cfg_child: Any = {"configurable": {"thread_id": ref.child_thread_id}}
        snapshots = list(reversed(list(graph.get_state_history(cfg_child))))

        if not snapshots:
            raise AdapterError(
                f"no snapshots on forked thread_id={ref.child_thread_id!r}. "
                "Did update_state run? This is likely a bug in the adapter."
            )

        first_source = _meta_source(snapshots[0])
        if first_source != "update":
            raise AdapterError(
                f"expected forked thread's first snapshot source='update', got {first_source!r}. "
                "LangGraph version may have changed — re-run spike5 and update ADR-005."
            )

        # For a forked thread: snapshots[0] is the seed and also plays the
        # role of "pre-first-downstream-node". initial_state = seed values.
        initial_state = dict(snapshots[0].values) if isinstance(snapshots[0].values, dict) else {}

        child_run_id = str(uuid.uuid4())
        run, nodes = self._build_run_and_nodes(
            snapshots=snapshots,
            run_id=child_run_id,
            thread_id=ref.child_thread_id,
            status=status,
            task_description=task_description,
            tags=[*tags, "fork"],
            initial_state=initial_state,
            loop_start=0,  # forked thread has no input placeholder
            first_step_index=parent_node.step_index + 1,
            first_parent_node_id=parent_node.id,  # first child node points to parent node cross-Run
            extra_metadata={
                "forked_from_run": parent_run.id,
                "forked_at_node": parent_node.id,
                "forked_at_node_name": parent_node.node_name,
                "overrides_keys": sorted(overrides.keys()),
            },
        )

        fork_record = Fork(
            id=str(uuid.uuid4()),
            parent_run_id=parent_run.id,
            parent_node_id=parent_node.id,
            child_run_id=child_run_id,
            edited_fields=dict(overrides),
            reason=reason,
        )

        with self._store.transaction():
            self._store.put_run(run)
            for n in nodes:
                self._store.put_node(n)
            self._store.put_fork(fork_record)

        ref.child_run_id = child_run_id
        ref.fork_id = fork_record.id
        ref.node_ids = [n.id for n in nodes]

    # ------------------------------------------------------------------
    # Shared core: snapshot list → (Run, list[Node])
    # ------------------------------------------------------------------

    def _build_run_and_nodes(
        self,
        *,
        snapshots: list[Any],
        run_id: str,
        thread_id: str,
        status: RunStatus,
        task_description: str | None,
        tags: list[str],
        initial_state: dict[str, Any],
        loop_start: int,
        first_step_index: int,
        first_parent_node_id: str | None,
        extra_metadata: dict[str, Any],
    ) -> tuple[Run, list[Node]]:
        """Walk snapshots and build canonical Run + Nodes.

        Unified helper for :meth:`_record_from_history` (original runs,
        ``loop_start=1``, ``first_step_index=0``) and
        :meth:`_fork_from_history` (forked threads, ``loop_start=0``,
        ``first_step_index=parent.step_index + 1``).
        """
        first = snapshots[0]
        last = snapshots[-1]
        started_at = _parse_created_at(first)
        ended_at = _parse_created_at(last)

        run = Run(
            id=run_id,
            adapter="langgraph",
            adapter_thread_id=thread_id,
            status=status,
            started_at=started_at,
            ended_at=ended_at,
            task_description=task_description,
            initial_state=initial_state,
            final_state=_coerce_state(last.values),
            tags=list(tags),
            metadata={
                "checkpoint_ns": _ckpt_ns(first),
                "num_snapshots": len(snapshots),
                **extra_metadata,
            },
        )

        nodes: list[Node] = []
        prev_node_id: str | None = first_parent_node_id
        step_cursor = first_step_index

        for i in range(loop_start, len(snapshots) - 1):
            pre = snapshots[i]
            post = snapshots[i + 1]
            if not pre.tasks:
                continue

            task = pre.tasks[0]
            node_name = getattr(task, "name", None)
            if not node_name:
                raise AdapterError(f"snapshot[{i}].tasks[0] has no .name — LangGraph API changed?")

            kind = self._kind_map.get(node_name, NodeKind.FN)
            lg_step = _meta_step(pre)

            node = Node(
                id=str(uuid.uuid4()),
                run_id=run_id,
                step_index=step_cursor,
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
                    "langgraph_step": lg_step,
                },
            )
            nodes.append(node)
            prev_node_id = node.id
            step_cursor += 1

        return run, nodes


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
    return datetime.now(UTC)


def _ckpt_id(snap: Any) -> str | None:
    cfg = getattr(snap, "config", None) or {}
    return (cfg.get("configurable") or {}).get("checkpoint_id")


def _ckpt_ns(snap: Any) -> str:
    cfg = getattr(snap, "config", None) or {}
    ns = (cfg.get("configurable") or {}).get("checkpoint_ns", "")
    return str(ns) if ns is not None else ""


def _coerce_state(values: Any) -> dict[str, Any]:
    if isinstance(values, dict):
        return dict(values)
    return {"__non_dict__": repr(values)}


__all__ = ["AdapterError", "ForkRef", "LangGraphRecorder", "RunRef"]
