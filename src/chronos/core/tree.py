"""Neutral reasoning-tree assembly — pure functions over a :class:`SqliteStore`.

Extracted from :mod:`chronos.api.server` in R67 (Arc A item 2 CLI closeout) so
both the HTTP surface and the new ``chronos tree`` CLI can call the same
assembler without the CLI depending on FastAPI.

The functions here are a **pure view** over store state — they never mutate
anything, they do all reads through the passed-in store handle, and their
output shape is the v0.6.0 frozen public contract pinned by
`docs/decisions/ADR-025-fork-tree-viz-scope.md`.

Shape (HTTP + CLI ``--json`` mode are byte-for-byte identical):

.. code-block:: python

   # include_descendants=False (default)
   {
       "run_id": str,
       "nodes": [<node dict with run_id>, ...],
       "edges": [{"from", "to", "kind": "sequential" | "fork", ...}, ...],
       "child_runs": [<fork dict>, ...],
   }

   # include_descendants=True — additive superset
   {
       ...,                     # all of the above, extended across the subtree
       "descendant_run_ids": [<root>, <child>, ..., ordered BFS],
       "run_summaries": {
           <run_id>: {"task_description", "status", "started_at", "adapter"},
           ...
       },
   }

See ADR-025 §Interface for the freeze.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from chronos.core.models import Fork, Node

if TYPE_CHECKING:
    from chronos.store import SqliteStore


__all__ = ["assemble_tree", "assemble_tree_with_descendants"]


def _node_to_dict(node: Node) -> dict[str, Any]:
    return node.model_dump(mode="json")


def _fork_to_dict(fork: Fork) -> dict[str, Any]:
    return fork.model_dump(mode="json")


def assemble_tree(
    store: SqliteStore, run_id: str, nodes: list[Node], forks: list[Fork]
) -> dict[str, Any]:
    """Build the neutral reasoning-tree shape for one run.

    Edge kinds:

    * ``sequential`` — same-run ``parent_node_id`` chain.
    * ``fork`` — cross-run link from the parent's ``parent_node_id`` to the
      first node of the child run. If the child run has no nodes yet
      (e.g. still running), the edge's ``to`` is ``None`` and the frontend
      shows the fork as an unresolved branch.

    This shape is a strict superset of what ReactFlow needs (frontend adds
    ``position`` / ``type`` locally) and is framework-neutral — it doesn't
    bake any single viewer into the API contract.
    """
    edges: list[dict[str, Any]] = []

    # Sequential edges within this run — one per node with parent_node_id set.
    for node in nodes:
        if node.parent_node_id is not None:
            edges.append(
                {
                    "from": node.parent_node_id,
                    "to": node.id,
                    "kind": "sequential",
                }
            )

    # Fork edges out of this run (cross-run). For each fork, look up the
    # first node of the child run so the edge has a concrete target; if the
    # child has no nodes, target is None.
    for fork in forks:
        child_nodes = store.get_nodes_for_run(fork.child_run_id)
        child_first_id: str | None = child_nodes[0].id if child_nodes else None
        edges.append(
            {
                "from": fork.parent_node_id,
                "to": child_first_id,
                "kind": "fork",
                "fork_id": fork.id,
                "child_run_id": fork.child_run_id,
                "edited_fields": fork.edited_fields,
            }
        )

    # Tag every node dict with its run_id so frontend can group by run
    # (for descendant trees this is essential; for single-run it's a no-op
    # but keeping the tag unconditional simplifies the client).
    node_dicts: list[dict[str, Any]] = []
    for n in nodes:
        d = _node_to_dict(n)
        d["run_id"] = run_id
        node_dicts.append(d)

    return {
        "run_id": run_id,
        "nodes": node_dicts,
        "edges": edges,
        "child_runs": [_fork_to_dict(f) for f in forks],
    }


def assemble_tree_with_descendants(store: SqliteStore, root_run_id: str) -> dict[str, Any]:
    """DFS-merge the root run with every descendant via fork edges.

    Returns the same shape as :func:`assemble_tree`, but ``nodes`` covers
    every run in the fork subtree and ``edges`` includes both the
    sequential links inside each run AND the cross-run fork edges that
    stitch them together.

    The response grows two extra top-level fields:

    * ``descendant_run_ids`` — ordered list of distinct run_ids included
      (root first, then by DFS discovery order).
    * ``run_summaries`` — ``{run_id: {task_description, status,
      started_at, adapter}}`` so the frontend can render lane labels
      without a second round-trip per run.

    Cycle protection: a ``visited: set[str]`` guards against pathological
    fork graphs (currently impossible by schema — fork.parent != child —
    but defensive against future bulk imports / bad data).

    Missing runs (``store.get_run`` returns ``None`` — e.g. orphaned fork
    child) are silently skipped; the subtree under them just doesn't
    appear. Never 500s on dangling pointers.
    """
    visited: set[str] = set()
    merged_nodes: list[dict[str, Any]] = []
    merged_edges: list[dict[str, Any]] = []
    merged_forks: list[dict[str, Any]] = []
    descendant_ids: list[str] = []
    run_summaries: dict[str, dict[str, Any]] = {}

    stack: list[str] = [root_run_id]

    while stack:
        rid = stack.pop(0)  # BFS-ish; ordering is stable + deterministic
        if rid in visited:
            continue
        visited.add(rid)

        run = store.get_run(rid)
        if run is None:
            # Skip gracefully — a fork referencing a vanished run shouldn't
            # 500 the viewer. Frontend just won't see its nodes.
            continue

        nodes = store.get_nodes_for_run(rid)
        forks = store.get_forks_for_parent(rid)

        subtree = assemble_tree(store, rid, nodes, forks)
        merged_nodes.extend(subtree["nodes"])
        merged_edges.extend(subtree["edges"])
        merged_forks.extend(subtree["child_runs"])

        descendant_ids.append(rid)
        run_summaries[rid] = {
            "task_description": run.task_description,
            "status": run.status.value if hasattr(run.status, "value") else run.status,
            "started_at": run.started_at.isoformat() if run.started_at else None,
            "adapter": run.adapter,
        }

        for fork in forks:
            if fork.child_run_id not in visited:
                stack.append(fork.child_run_id)

    return {
        "run_id": root_run_id,
        "nodes": merged_nodes,
        "edges": merged_edges,
        "child_runs": merged_forks,
        "descendant_run_ids": descendant_ids,
        "run_summaries": run_summaries,
    }
